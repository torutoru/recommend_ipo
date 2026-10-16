"""Turso 어댑터 유닛 테스트 (Windows·Linux 공통, libsql_experimental 설치 불요).

- `libsql_experimental` 모듈을 fake 로 주입 → `connect_turso()` 가 TursoConnection 반환
- `_Row`, `_CursorAdapter`, `TursoConnection.executescript` 분기 동작 확인
- 미설치 환경 재현 (`sys.modules["libsql_experimental"] = None`) → TursoConnectError
- 토큰·URL 이 에러 메시지에 **그대로 노출되지 않음** 확인
"""
from __future__ import annotations

import sys
import types

import pytest

from app.config import get_settings
from app.turso_adapter import (
    TursoConnectError,
    TursoConnection,
    _Row,
    _split_sql,
    connect_turso,
)


# ---------- 유닛 ----------

def test_row_dict_access_and_keys():
    r = _Row({"a": 1, "b": "x"})
    assert r["a"] == 1
    assert r["b"] == "x"
    assert r[0] == 1
    assert list(r.keys()) == ["a", "b"]


def test_split_sql_handles_multi_statements():
    stmts = _split_sql("CREATE TABLE t (x INT); INSERT INTO t VALUES (1);  ")
    assert stmts == ["CREATE TABLE t (x INT);", "INSERT INTO t VALUES (1);"]


# ---------- fake libsql_experimental ----------

class _FakeCursor:
    """실 libsql_experimental 커서를 **엄격하게** 흉내 (지시 #13):
    - `__iter__` 는 **지원하지 않음** → 호출자가 iter 하면 TypeError
    - 비-SELECT 쿼리의 description 은 **None**
    - lastrowid 는 INSERT 시만 의미 있음
    """

    def __init__(self):
        self.description = None     # 기본 None, SELECT 쿼리에서만 세팅
        self._rows: list[tuple] = []
        self._pos = 0
        self.lastrowid = 42
        self.executed_sql: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.executed_sql.append((sql, tuple(params) if params else ()))
        s = sql.lstrip().upper()
        if s.startswith("SELECT"):
            if "FROM IPOS" in s and ("WHERE CORP_CODE" in s and "?" in sql):
                self.description = [("corp_code",), ("corp_name",)]
                self._rows = [("00534729", "디티에스")]
            elif "FROM IPOS" in s:  # list_ipos 전체 조회
                self.description = [("corp_code",), ("corp_name",)]
                self._rows = [("00534729", "디티에스")]
            elif "FROM SOURCES" in s:
                self.description = [("corp_code",), ("doc_type",), ("rcept_no",), ("rcept_dt",), ("url",)]
                self._rows = []
            else:
                self.description = [("x",)]
                self._rows = []
        else:
            self.description = None   # INSERT/ALTER/PRAGMA 등
            self._rows = []
        return self

    def executemany(self, sql, seq):
        for p in seq:
            self.execute(sql, p)
        return self

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        r = self._rows[self._pos]
        self._pos += 1
        return r

    def fetchall(self):
        out = self._rows[self._pos:]
        self._pos = len(self._rows)
        return out

    # ⚠ __iter__ 를 **정의하지 않는다** — 실 libsql 과 동일. 호출자가 iter 하면 TypeError.


class _FakeInner:
    def __init__(self, closed=None):
        self._cursors: list[_FakeCursor] = []
        self.committed = 0
        self.closed = False

    def cursor(self):
        c = _FakeCursor()
        self._cursors.append(c)
        return c

    def commit(self):
        self.committed += 1

    def close(self):
        self.closed = True


@pytest.fixture
def fake_libsql(monkeypatch):
    """libsql_experimental 모듈을 fake 로 주입."""
    mod = types.ModuleType("libsql_experimental")

    def fake_connect(url, auth_token=None):
        return _FakeInner()

    mod.connect = fake_connect
    monkeypatch.setitem(sys.modules, "libsql_experimental", mod)
    return mod


# ---------- Turso 연결 ----------

def test_connect_turso_raises_when_env_empty():
    s = get_settings()
    # conftest 에서 이미 "" 로 세팅되어 있지만 명시
    s.turso_database_url = ""
    s.turso_auth_token = ""
    with pytest.raises(TursoConnectError):
        with connect_turso():
            pass


def test_connect_turso_raises_when_libsql_missing(monkeypatch):
    """libsql_experimental 를 import 할 수 없는 환경 재현."""
    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"
    # import 실패를 강제
    monkeypatch.setitem(sys.modules, "libsql_experimental", None)
    with pytest.raises(TursoConnectError) as exc:
        with connect_turso():
            pass
    # 토큰이 메시지에 노출되지 않아야 함
    assert "faketoken" not in str(exc.value)


def test_connect_turso_returns_wrapper(fake_libsql):
    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"
    with connect_turso() as conn:
        assert isinstance(conn, TursoConnection)
        cur = conn.execute("SELECT corp_code, corp_name FROM ipos WHERE corp_code = ?", ("00534729",))
        row = cur.fetchone()
        assert row["corp_code"] == "00534729"
        assert row["corp_name"] == "디티에스"


def test_executescript_splits_statements(fake_libsql):
    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"
    with connect_turso() as conn:
        conn.executescript("CREATE TABLE a(x INT); CREATE TABLE b(y INT);")
    # fake 는 executescript 를 execute 2회로 분리해 받음 — Fake Inner 확인은 생략, 예외 없음만 확인


def test_token_not_leaked_in_connect_error(monkeypatch):
    """libsql.connect 자체가 예외 발생 → 메시지에 token 미노출."""
    mod = types.ModuleType("libsql_experimental")

    def failing_connect(url, auth_token=None):
        raise RuntimeError(f"nope url={url} token={auth_token}")

    mod.connect = failing_connect
    monkeypatch.setitem(sys.modules, "libsql_experimental", mod)

    s = get_settings()
    s.turso_database_url = "libsql://top-secret-prod.turso.io"
    s.turso_auth_token = "SUPERSECRETTOKEN"
    with pytest.raises(TursoConnectError) as exc:
        with connect_turso():
            pass
    msg = str(exc.value)
    assert "SUPERSECRETTOKEN" not in msg
    assert "top-secret-prod" not in msg


# ---------- store.connect() 가 Turso 를 경유 ----------

def test_store_connect_uses_turso_when_env_set(fake_libsql):
    from app import store
    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"
    with store.connect() as conn:
        assert isinstance(conn, TursoConnection)


def test_cursor_adapter_iter_uses_fetchall_not_native_iter(fake_libsql):
    """회귀 (#13): libsql 커서가 __iter__ 를 지원하지 않아도 TursoConnection 이 iter 가능해야 함.
    실제 Render 500 원인 — `for r in conn.execute(...)` 가 깨졌음.
    """
    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"
    with connect_turso() as conn:
        cur = conn.execute("SELECT corp_code, corp_name FROM ipos")
        # iter 는 fetchall 기반이므로 libsql 네이티브 iter 가 없어도 돌아감
        rows = list(cur)
        assert len(rows) == 1
        assert rows[0]["corp_code"] == "00534729"


def test_store_list_ipos_works_via_turso(fake_libsql, tmp_path):
    """회귀 (#13): store.list_ipos() 가 Turso 커서 순회에서 터지지 않아야 함."""
    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"
    from app import store
    rows = store.list_ipos()
    assert isinstance(rows, list)
    # fake 는 ipos 1건·sources 0건·warnings 0건 — 예외 없이 응답
    assert len(rows) == 1
    assert rows[0]["corp_code"] == "00534729"


def test_wrap_raises_when_description_is_none(fake_libsql):
    """회귀 (#13): description 이 None 인 커서에서 fetchone 하면 raw tuple 반환 금지."""
    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"
    with connect_turso() as conn:
        # INSERT (description None) → fetchone 호출 시도. 결과 자체는 None 이므로 wrap 통과.
        cur = conn.execute("INSERT INTO ipos (corp_code) VALUES (?)", ("test",))
        assert cur.fetchone() is None   # 실제 INSERT 는 결과 없음 → None 안전

        # 하지만 description None 인데 row 가 있는 비정상 상황을 흉내:
        # fake 커서를 수동 조작해 row 를 넣어둠
        cur._cur._rows = [("x",)]
        cur._cur._pos = 0
        cur._cur.description = None
        import pytest
        with pytest.raises(RuntimeError, match="description"):
            cur.fetchone()


def test_store_connect_does_not_fallback_on_turso_failure(monkeypatch):
    """Turso 연결 실패 시 조용히 SQLite 로 가지 않고 예외 전파."""
    mod = types.ModuleType("libsql_experimental")

    def failing_connect(url, auth_token=None):
        raise RuntimeError("network down")

    mod.connect = failing_connect
    monkeypatch.setitem(sys.modules, "libsql_experimental", mod)

    s = get_settings()
    s.turso_database_url = "libsql://fake.turso.io"
    s.turso_auth_token = "faketoken"
    from app import store
    with pytest.raises(TursoConnectError):
        with store.connect() as _:
            pass
