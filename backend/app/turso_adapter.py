"""Turso 어댑터 — Hrana over HTTP (`/v2/pipeline`) 를 httpx 로 직접 호출.

지시 #14: libsql_experimental 은 Render 에서 영속성 실패(수집 SUCCEEDED 지만 /api/ipos 0건) →
Turso HTTP API 로 전환. 각 요청이 명확히 서버에 도달하고, 응답에 `affected_row_count` 가 포함돼
쓰기 성공 여부를 즉시 검증할 수 있다. 네이티브 의존성 없음, Windows·Linux 모두 동작.

sqlite3-호환 인터페이스:
- `TursoConnection.execute(sql, params=())` → `_CursorAdapter`
- `executemany(sql, seq)` → 단일 pipeline 요청으로 묶어 전송
- `executescript(sql)` → `;` 로 분리해 pipeline 다중 statement
- `commit()` / `close()` 는 **no-op** (각 요청 autocommit)
- 결과 row 는 컬럼명 dict-like `_Row`

로그·에러 금지:
- `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` 전체 값을 에러·로그에 노출하지 않는다.
"""
from __future__ import annotations

import base64
import re
from contextlib import contextmanager
from typing import Any, Iterator, Optional

import httpx

from .config import get_settings


class TursoConnectError(RuntimeError):
    """Turso 연결·요청 실패 — fallback 없이 호출자에게 전파."""


# ---------- URL ----------

def _to_http_url(url: str) -> str:
    """`libsql://host.turso.io` → `https://host.turso.io`.

    `wss:` / `ws:` 도 http(s) 로 매핑. 이미 http(s) 이면 그대로.
    """
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):]
    if url.startswith("wss://"):
        return "https://" + url[len("wss://"):]
    if url.startswith("ws://"):
        return "http://" + url[len("ws://"):]
    return url


def _mask(s: str) -> str:
    if not s:
        return "<empty>"
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}***{s[-2:]}"


# ---------- 값 ↔ Turso typed value ----------

def _to_arg(v: Any) -> dict:
    """Python 값 → Hrana typed value (지시 #23 확정 포맷):
    - integer: value 는 **문자열** (JS 안전 정수 범위 때문)
    - float:   value 는 **JSON 숫자** (지시 #23 수정 — 문자열이면 Turso 가 "expected f64" 400)
    - text:    value 는 문자열
    - null / blob: 전용 타입
    """
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        # Turso 는 boolean 전용 타입 없음 — 0/1 integer 로
        return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode("ascii")}
    # str 또는 그 외 → text
    return {"type": "text", "value": str(v)}


def _from_value(v: dict) -> Any:
    """Turso 응답의 typed value → Python 원시값.

    integer 는 문자열로, float 는 숫자(또는 문자열 호환) 로 올 수 있음을 둘 다 수용.
    """
    t = v.get("type")
    if t == "null":
        return None
    val = v.get("value")
    if t == "integer":
        return int(val)
    if t == "float":
        return float(val)   # JSON 숫자 또는 문자열 둘 다 float() 수용
    if t == "text":
        return val
    if t == "blob":
        return base64.b64decode(v.get("base64", ""))
    return val


# ---------- Row (sqlite3.Row 호환) ----------

class _Row:
    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def keys(self):
        return self._data.keys()


# ---------- HTTP 호출 ----------

def _post_pipeline(client: httpx.Client, base_url: str, token: str, statements: list[dict]) -> list[dict]:
    """pipeline 요청 → results 리스트 반환.

    statements: `[{"sql": "...", "args": [...]}, ...]`
    results[i]: `{"cols": [...], "rows": [[...]], "affected_row_count": N, "last_insert_rowid": X}`
    """
    requests = [{"type": "execute", "stmt": s} for s in statements]
    requests.append({"type": "close"})
    body = {"requests": requests}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        r = client.post(f"{base_url}/v2/pipeline", headers=headers, json=body, timeout=30.0)
    except httpx.HTTPError as e:
        raise TursoConnectError(
            f"Turso HTTP 요청 실패 (url={_mask(base_url)}) — {type(e).__name__}"
        ) from None
    if r.status_code != 200:
        # 지시 #23: 400 등 에러에 서버 응답 본문(SQL 에러 문구)을 포함해 원인 파악 가능하게.
        # URL/토큰은 치환, 본문 자체에 token 이 포함될 가능성은 낮지만 mask 한 번 더 적용.
        body_text = _redact(r.text, token)[:600]
        # 400 요청에서 어떤 statement 가 문제인지 보조 정보(첫 SQL)
        hint = ""
        if statements:
            first_sql = (statements[0].get("sql") or "")[:140]
            hint = f" first_sql={first_sql!r}"
        raise TursoConnectError(
            f"Turso HTTP {r.status_code} (url={_mask(base_url)}){hint} body={body_text}"
        )
    payload = r.json()
    results = payload.get("results", [])
    out: list[dict] = []
    for i, item in enumerate(results[: len(statements)]):
        if item.get("type") == "error":
            err = item.get("error", {})
            msg = _redact(err.get("message", "unknown"), token)[:400]
            sql_hint = ""
            if i < len(statements):
                sql_hint = f" sql={(statements[i].get('sql') or '')[:140]!r}"
            raise TursoConnectError(f"Turso SQL 에러 (stmt #{i}): {msg}{sql_hint}")
        resp = item.get("response", {})
        out.append(resp.get("result", {}))
    return out


def _redact(text: str, token: str) -> str:
    if token and token in text:
        text = text.replace(token, "<token>")
    return text


# ---------- Cursor / Connection ----------

class _CursorAdapter:
    """Turso HTTP 결과 1건을 sqlite3-cursor 처럼 노출."""

    def __init__(self, result: dict):
        self._result = result or {}
        self._rows_raw = self._result.get("rows", []) or []
        self._cols = [c.get("name") for c in self._result.get("cols", [])]
        self._pos = 0
        self.lastrowid = _parse_lastrowid(self._result)

    def fetchone(self) -> Optional[_Row]:
        if self._pos >= len(self._rows_raw):
            return None
        row = self._rows_raw[self._pos]
        self._pos += 1
        return self._wrap(row)

    def fetchall(self) -> list[_Row]:
        out = [self._wrap(r) for r in self._rows_raw[self._pos:]]
        self._pos = len(self._rows_raw)
        return out

    def __iter__(self):
        return iter(self.fetchall())

    def _wrap(self, row_values: list[dict]) -> _Row:
        if not self._cols:
            raise RuntimeError(
                "Turso 응답에 cols 가 비어 있어 row 를 dict 로 감쌀 수 없습니다 "
                "(non-SELECT 결과를 fetch 하려는 호출 패턴일 수 있음)."
            )
        parsed = [_from_value(v) if isinstance(v, dict) else v for v in row_values]
        return _Row(dict(zip(self._cols, parsed)))


def _parse_lastrowid(result: dict) -> Optional[int]:
    v = result.get("last_insert_rowid")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class TursoConnection:
    """HTTP 기반 커넥션 — context 안에서 사용. autocommit 전제.

    트랜잭션(지시 보강 #정확도-C):
      ``with conn.transaction(): ...`` 안에서 호출되는 쓰기 execute 는 **버퍼링** 되고,
      context 종료 시 ``BEGIN + 쿼리들 + COMMIT`` 를 **한 pipeline** 으로 전송 — Hrana 원자성 보장.
      예외 발생 시 아무 것도 전송하지 않음(기존 데이터 유지).
      트랜잭션 내 SELECT 는 지원하지 않음(쓰기 전용 묶음).
    """

    def __init__(self, client: httpx.Client, base_url: str, token: str):
        self._client = client
        self._base_url = base_url
        self._token = token
        self._tx_pending: Optional[list[dict]] = None

    # ---- 공개 API ----
    def execute(self, sql: str, params: Optional[tuple | list] = None) -> _CursorAdapter:
        stmt = {"sql": sql}
        if params is not None:
            stmt["args"] = [_to_arg(p) for p in params]
        if self._tx_pending is not None:
            self._tx_pending.append(stmt)
            return _CursorAdapter({})
        results = _post_pipeline(self._client, self._base_url, self._token, [stmt])
        return _CursorAdapter(results[0] if results else {})

    def executemany(self, sql: str, seq_of_params) -> _CursorAdapter:
        stmts = [{"sql": sql, "args": [_to_arg(p) for p in params]} for params in seq_of_params]
        if not stmts:
            return _CursorAdapter({})
        if self._tx_pending is not None:
            self._tx_pending.extend(stmts)
            return _CursorAdapter({})
        results = _post_pipeline(self._client, self._base_url, self._token, stmts)
        return _CursorAdapter(results[-1])

    @contextmanager
    def transaction(self) -> Iterator["TursoConnection"]:
        """지시 보강: BEGIN + 쓰기 쿼리들 + COMMIT 를 한 pipeline 으로.
        예외 시 아무것도 전송하지 않음(ROLLBACK 불필요 — 전송 자체 안 함)."""
        if self._tx_pending is not None:
            raise RuntimeError("TursoConnection.transaction 중첩 미지원")
        self._tx_pending = []
        try:
            yield self
        except Exception:
            self._tx_pending = None
            raise
        else:
            stmts = self._tx_pending
            self._tx_pending = None
            if stmts:
                all_stmts = [{"sql": "BEGIN"}] + stmts + [{"sql": "COMMIT"}]
                _post_pipeline(self._client, self._base_url, self._token, all_stmts)

    def executescript(self, script: str) -> None:
        stmts = [{"sql": s} for s in _split_sql(script) if s]
        if not stmts:
            return
        _post_pipeline(self._client, self._base_url, self._token, stmts)

    def commit(self) -> None:
        # Turso HTTP 는 각 요청 autocommit — 명시 commit 불필요
        pass

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    # ---- context ----
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _split_sql(script: str) -> list[str]:
    """세미콜론 기준 분리 (단순 — 현재 SCHEMA 는 문자열·주석 안에 ; 없음)."""
    parts = [p.strip().rstrip(";").strip() for p in script.split(";")]
    return [p + ";" for p in parts if p]


@contextmanager
def connect_turso() -> Iterator[TursoConnection]:
    """Turso HTTP 커넥션 (autocommit). 실패 시 TursoConnectError, fallback 없음."""
    s = get_settings()
    url = s.turso_database_url
    token = s.turso_auth_token
    if not url or not token:
        raise TursoConnectError(
            "TURSO_DATABASE_URL/TURSO_AUTH_TOKEN 가 비어 있습니다 — connect_turso() 호출 전 use_turso() 확인."
        )
    base = _to_http_url(url)
    client = httpx.Client()
    conn = TursoConnection(client, base, token)
    try:
        yield conn
    finally:
        conn.close()
