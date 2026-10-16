"""Turso HTTP 어댑터 유닛 테스트 — httpx 를 MockTransport 로 교체 (실 Turso 연결 없이).

지시 #14 — libsql_experimental 이 Render 에서 영속성 실패해 Hrana over HTTP (`/v2/pipeline`) 로 전환.
이 테스트는 다음을 보장:
- URL 변환(libsql://→https://), 토큰·URL 로그 미노출
- SQL params typed value 매핑, 응답 rows 역직렬화
- Cursor iter 가 fetchall 기반 (지시 #13 재발 방지)
- `cols` 없을 때 _wrap 이 RuntimeError
- store.connect() 가 Turso 경로로 라우팅
- 쓰기 → 다른 커넥션에서 읽기 영속성(fake 공유 저장소)
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Callable

import httpx
import pytest

from app.config import get_settings
from app.turso_adapter import (
    TursoConnectError,
    TursoConnection,
    _from_value,
    _mask,
    _Row,
    _split_sql,
    _to_arg,
    _to_http_url,
)


# ---------- 유닛 ----------

def test_row_dict_access():
    r = _Row({"a": 1, "b": "x"})
    assert r["a"] == 1
    assert r[0] == 1
    assert list(r.keys()) == ["a", "b"]


def test_split_sql_handles_multiple():
    stmts = _split_sql("CREATE TABLE t(x INT); INSERT INTO t VALUES (1);  ")
    assert len(stmts) == 2
    assert stmts[0].startswith("CREATE") and stmts[1].startswith("INSERT")


def test_to_arg_type_mapping():
    assert _to_arg(None) == {"type": "null"}
    assert _to_arg(42) == {"type": "integer", "value": "42"}
    assert _to_arg(1.5) == {"type": "float", "value": "1.5"}
    assert _to_arg("hi") == {"type": "text", "value": "hi"}
    assert _to_arg(True) == {"type": "integer", "value": "1"}


def test_from_value_type_mapping():
    assert _from_value({"type": "null"}) is None
    assert _from_value({"type": "integer", "value": "7"}) == 7
    assert _from_value({"type": "float", "value": "2.5"}) == 2.5
    assert _from_value({"type": "text", "value": "ok"}) == "ok"


def test_to_http_url_scheme_conversions():
    assert _to_http_url("libsql://foo.turso.io") == "https://foo.turso.io"
    assert _to_http_url("https://x") == "https://x"
    assert _to_http_url("wss://x") == "https://x"


def test_mask_hides_value():
    assert _mask("") == "<empty>"
    assert _mask("abcd") == "***"
    assert _mask("abcdefghij") == "abcd***ij"


# ---------- Fake Turso 서버 (httpx MockTransport + 커넥션 간 공유 저장소) ----------

class _FakeTursoBackend:
    """매우 단순한 in-memory 테이블 — INSERT/SELECT/CREATE/DELETE 를 상태로 보존.

    핵심 사용 패턴만 처리 (store.py 가 쓰는 SQL 커버):
    - CREATE TABLE IF NOT EXISTS ... ;
    - INSERT INTO <t> (cols) VALUES (?,?,...) ON CONFLICT(...) DO UPDATE SET ... — upsert
    - UPDATE / DELETE / PRAGMA foreign_keys 는 no-op 성공
    - SELECT * FROM <t> [WHERE col = ?] — 평면 매칭
    - SELECT ... FROM <t> ORDER BY ... — ORDER BY 무시
    """

    def __init__(self):
        # table_name -> list[dict]
        self.tables: dict[str, list[dict]] = defaultdict(list)
        # table_name -> list[column]
        self.schemas: dict[str, list[str]] = {}
        # 자동 증가 id (collect_runs)
        self.autoinc: dict[str, int] = defaultdict(int)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        results: list[dict] = []
        for req in body["requests"]:
            if req["type"] == "close":
                continue
            stmt = req["stmt"]
            sql = stmt["sql"].strip().rstrip(";").strip()
            args = [self._from_arg(a) for a in stmt.get("args", [])]
            try:
                results.append({"type": "ok", "response": {"type": "execute",
                                                            "result": self._run(sql, args)}})
            except Exception as e:
                results.append({"type": "error", "error": {"message": str(e)}})
        return httpx.Response(200, json={"baton": None, "results": results})

    def _from_arg(self, a):
        t = a.get("type")
        if t == "null":
            return None
        if t == "integer":
            return int(a["value"])
        if t == "float":
            return float(a["value"])
        return a.get("value")

    def _run(self, sql: str, args: list) -> dict:
        up = sql.upper()
        if up.startswith("PRAGMA FOREIGN_KEYS"):
            return {"cols": [], "rows": [], "affected_row_count": 0, "last_insert_rowid": None}
        if up.startswith("CREATE TABLE"):
            # 매우 단순 — 테이블명과 컬럼명만 추출
            import re
            m = re.search(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)\s*\((.*)\)", sql, re.IGNORECASE | re.DOTALL)
            if m:
                name = m.group(1)
                cols_raw = m.group(2)
                cols = [c.strip().split()[0] for c in cols_raw.split(",") if c.strip() and not c.strip().upper().startswith(("PRIMARY", "FOREIGN"))]
                self.schemas[name] = cols
                self.tables.setdefault(name, [])
            return {"cols": [], "rows": [], "affected_row_count": 0, "last_insert_rowid": None}
        if up.startswith("CREATE INDEX"):
            return {"cols": [], "rows": [], "affected_row_count": 0, "last_insert_rowid": None}
        if up.startswith("INSERT INTO"):
            import re
            m = re.match(r"INSERT INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES\s*\(([^)]+)\)(.*)", sql, re.IGNORECASE | re.DOTALL)
            if not m:
                return {"cols": [], "rows": [], "affected_row_count": 0, "last_insert_rowid": None}
            table = m.group(1)
            cols = [c.strip() for c in m.group(2).split(",")]
            tail = m.group(4) or ""
            row = dict(zip(cols, args))
            # ON CONFLICT DO UPDATE 처리 (upsert) — PRIMARY KEY 로 corp_code 사용 가정
            if "ON CONFLICT" in tail.upper():
                pk = cols[0]
                existing = [r for r in self.tables[table] if r.get(pk) == row.get(pk)]
                if existing:
                    existing[0].update(row)
                    return {"cols": [], "rows": [], "affected_row_count": 1, "last_insert_rowid": None}
            self.tables[table].append(row)
            self.autoinc[table] += 1
            return {"cols": [], "rows": [], "affected_row_count": 1,
                    "last_insert_rowid": str(self.autoinc[table])}
        if up.startswith("DELETE FROM"):
            import re
            m = re.match(r"DELETE FROM\s+(\w+)(?:\s+WHERE\s+(\w+)\s*=\s*\?)?", sql, re.IGNORECASE)
            if m:
                table = m.group(1)
                col = m.group(2)
                if col and args:
                    before = len(self.tables[table])
                    self.tables[table] = [r for r in self.tables[table] if r.get(col) != args[0]]
                    affected = before - len(self.tables[table])
                else:
                    affected = len(self.tables[table])
                    self.tables[table] = []
                return {"cols": [], "rows": [], "affected_row_count": affected, "last_insert_rowid": None}
        if up.startswith("UPDATE"):
            # 단순 매치만 — 테스트에선 collect_runs UPDATE 뿐
            import re
            m = re.match(r"UPDATE\s+(\w+)\s+SET\s+(.*?)\s+WHERE\s+(\w+)\s*=\s*\?", sql, re.IGNORECASE | re.DOTALL)
            if m:
                table = m.group(1)
                set_clause = m.group(2)
                where_col = m.group(3)
                where_val = args[-1]
                set_cols = [c.strip().split("=")[0].strip() for c in set_clause.split(",")]
                for r in self.tables[table]:
                    if r.get(where_col) == where_val:
                        for i, c in enumerate(set_cols):
                            r[c] = args[i]
                        break
                return {"cols": [], "rows": [], "affected_row_count": 1, "last_insert_rowid": None}
        if up.startswith("SELECT"):
            return self._select(sql, args)
        return {"cols": [], "rows": [], "affected_row_count": 0, "last_insert_rowid": None}

    def _select(self, sql: str, args: list) -> dict:
        import re
        # SELECT <cols> FROM <table> [WHERE <col> = ?] [ORDER BY ...]
        m = re.match(
            r"SELECT\s+(.+?)\s+FROM\s+(\w+)(?:\s+WHERE\s+(.*?))?(?:\s+ORDER\s+BY.*)?(?:\s+LIMIT.*)?$",
            sql, re.IGNORECASE | re.DOTALL,
        )
        if not m:
            return {"cols": [], "rows": [], "affected_row_count": 0, "last_insert_rowid": None}
        cols_part = m.group(1).strip()
        table = m.group(2)
        where = (m.group(3) or "").strip()
        rows_src = list(self.tables.get(table, []))

        # 단순 WHERE 지원: `col = ?`, `col IS NOT NULL`, `col IS NULL`, `AND` 조합
        if where:
            cond = where
            for part in [p.strip() for p in cond.split("AND")]:
                mm = re.match(r"(\w+)\s*=\s*\?", part, re.IGNORECASE)
                if mm:
                    col = mm.group(1)
                    val = args.pop(0) if args else None
                    rows_src = [r for r in rows_src if r.get(col) == val]
                    continue
                mm = re.match(r"(\w+)\s+IS\s+NULL", part, re.IGNORECASE)
                if mm:
                    rows_src = [r for r in rows_src if r.get(mm.group(1)) is None]
                    continue
                mm = re.match(r"(\w+)\s+IS\s+NOT\s+NULL", part, re.IGNORECASE)
                if mm:
                    rows_src = [r for r in rows_src if r.get(mm.group(1)) is not None]
                    continue

        # COUNT(*) 처리 — 지시 #14 쓰기 검증용
        import re as _re
        m_count = _re.match(r"COUNT\(\*\)\s+AS\s+(\w+)", cols_part, _re.IGNORECASE)
        if m_count:
            alias = m_count.group(1)
            return {"cols": [{"name": alias}], "rows": [[self._pack(len(rows_src))]],
                    "affected_row_count": 0, "last_insert_rowid": None}

        # cols 결정
        if cols_part == "*":
            cols = self.schemas.get(table) or (list(rows_src[0].keys()) if rows_src else [])
        else:
            cols = [c.strip() for c in cols_part.split(",")]
        out_rows = [[self._pack(r.get(c)) for c in cols] for r in rows_src]
        return {"cols": [{"name": c} for c in cols], "rows": out_rows,
                "affected_row_count": 0, "last_insert_rowid": None}

    def _pack(self, v):
        if v is None:
            return {"type": "null"}
        if isinstance(v, int):
            return {"type": "integer", "value": str(v)}
        if isinstance(v, float):
            return {"type": "float", "value": str(v)}
        return {"type": "text", "value": str(v)}


@pytest.fixture
def fake_turso(monkeypatch):
    """httpx.Client 를 MockTransport 로 교체 + Settings 에 fake URL/토큰 주입."""
    backend = _FakeTursoBackend()
    transport = httpx.MockTransport(backend.handle)

    original_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("transport", transport)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)

    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"
    return backend


# ---------- 핵심 기능 ----------

def test_connect_turso_raises_when_env_empty():
    from app.turso_adapter import connect_turso
    s = get_settings()
    s.turso_database_url = ""
    s.turso_auth_token = ""
    with pytest.raises(TursoConnectError):
        with connect_turso():
            pass


def test_execute_select_returns_row(fake_turso):
    from app.turso_adapter import connect_turso
    # 사전 데이터 삽입
    fake_turso.schemas["ipos"] = ["corp_code", "corp_name"]
    fake_turso.tables["ipos"].append({"corp_code": "00534729", "corp_name": "디티에스"})
    with connect_turso() as conn:
        cur = conn.execute("SELECT corp_code, corp_name FROM ipos WHERE corp_code = ?", ("00534729",))
        row = cur.fetchone()
        assert row["corp_code"] == "00534729"
        assert row["corp_name"] == "디티에스"


def test_cursor_iter_via_fetchall(fake_turso):
    """회귀 (#13): __iter__ 는 fetchall 기반."""
    from app.turso_adapter import connect_turso
    fake_turso.schemas["ipos"] = ["corp_code"]
    fake_turso.tables["ipos"].extend([{"corp_code": "a"}, {"corp_code": "b"}])
    with connect_turso() as conn:
        rows = list(conn.execute("SELECT corp_code FROM ipos"))
        assert [r["corp_code"] for r in rows] == ["a", "b"]


def test_wrap_raises_when_no_cols(fake_turso):
    """`cols` 가 비어 있으면 _wrap 이 명시 RuntimeError (raw tuple 금지)."""
    from app.turso_adapter import _CursorAdapter
    # cols 없이 rows 가 있는 비정상 응답을 수동 조립
    cur = _CursorAdapter({"cols": [], "rows": [[{"type": "text", "value": "x"}]]})
    with pytest.raises(RuntimeError, match="cols"):
        cur.fetchone()


# ---------- 영속성 (지시 #14 핵심) ----------

def test_write_persists_across_connections(fake_turso):
    """회귀 (#14): 쓰기 → 새 커넥션에서 읽기로 영속성 확인."""
    from app.turso_adapter import connect_turso
    # 커넥션 A — 테이블 생성 + INSERT
    with connect_turso() as a:
        a.executescript(
            "CREATE TABLE IF NOT EXISTS ipos (corp_code TEXT PRIMARY KEY, corp_name TEXT);"
        )
        a.execute(
            "INSERT INTO ipos (corp_code, corp_name) VALUES (?, ?)",
            ("00534729", "디티에스"),
        )
    # 커넥션 B — 읽기 (fake backend 는 공유 상태 보존)
    with connect_turso() as b:
        row = b.execute("SELECT corp_code, corp_name FROM ipos WHERE corp_code = ?", ("00534729",)).fetchone()
        assert row is not None
        assert row["corp_name"] == "디티에스"


def test_affected_row_count_available(fake_turso):
    from app.turso_adapter import connect_turso
    with connect_turso() as a:
        a.executescript("CREATE TABLE IF NOT EXISTS t (x INTEGER);")
        cur = a.execute("INSERT INTO t (x) VALUES (?)", (1,))
        # last_insert_rowid 는 fake 가 autoinc 로 생성
        assert cur.lastrowid == 1


def test_store_connect_uses_turso(fake_turso):
    from app import store
    with store.connect() as conn:
        assert isinstance(conn, TursoConnection)


def test_store_connect_no_fallback_on_turso_failure(monkeypatch):
    """Turso 호출 자체가 깨지면 fallback 없이 TursoConnectError."""
    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"

    def failing_transport(req):
        raise httpx.ConnectError("network down")

    transport = httpx.MockTransport(failing_transport)
    original_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("transport", transport)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", patched_init)

    from app import store
    with pytest.raises(TursoConnectError):
        with store.connect() as conn:
            conn.execute("SELECT 1")


def test_token_not_leaked_in_error(monkeypatch):
    s = get_settings()
    s.turso_database_url = "libsql://top-secret-prod.turso.io"
    s.turso_auth_token = "SUPERSECRETTOKEN"

    def http_500(req):
        return httpx.Response(500, text="server exploded " + "SUPERSECRETTOKEN")

    transport = httpx.MockTransport(http_500)
    original_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.setdefault("transport", transport)
        original_init(self, *args, **kwargs)
    monkeypatch.setattr(httpx.Client, "__init__", patched_init)

    from app.turso_adapter import connect_turso
    with pytest.raises(TursoConnectError) as exc:
        with connect_turso() as c:
            c.execute("SELECT 1")
    msg = str(exc.value)
    assert "SUPERSECRETTOKEN" not in msg
    assert "top-secret-prod" not in msg
