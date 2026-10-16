"""Turso(libSQL) 어댑터 — Render(Linux) 운영 전용. 로컬(Windows) 에서는 사용 안 됨.

지연 import (`libsql_experimental`) 로 Windows 에서는 임포트 자체가 일어나지 않는다.
`store.connect()` 가 `use_turso()` True 일 때만 이 모듈을 불러온다.

sqlite3 호환성 보완:
- `libsql_experimental.connect()` 는 sqlite3-호환 Connection 반환.
- row_factory 는 지원 안 될 수 있어 커서 결과를 dict-like 로 감싸는 `_RowAdapter` 를 둔다.
- `PRAGMA foreign_keys = ON` 등은 지원된다(libSQL 가 SQLite 호환).

**로그 금지**: TURSO_DATABASE_URL / TURSO_AUTH_TOKEN 값은 어디에도 출력하지 않는다.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from .config import get_settings


class TursoConnectError(RuntimeError):
    """Turso 연결 실패 — fallback 없이 호출자에게 전파."""


def _import_libsql():
    try:
        import libsql_experimental as libsql
    except ImportError as e:
        raise TursoConnectError(
            "libsql-experimental 패키지가 설치되지 않았습니다 "
            "(Windows 에서는 설치되지 않습니다). 운영 환경에서 Turso 를 쓰려면 Linux(Render)에서 돌리세요."
        ) from e
    return libsql


def _mask(s: str) -> str:
    """로그·에러 메시지 안에서 토큰·URL 끝을 가린다 (완전 노출 방지)."""
    if not s:
        return "<empty>"
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}***{s[-2:]}"


class _Row:
    """sqlite3.Row 모양을 흉내 — 컬럼명으로 접근 + keys()."""
    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def keys(self):
        return self._data.keys()


class TursoConnection:
    """`sqlite3.Connection` 과 유사한 인터페이스를 노출하는 얇은 래퍼.

    store.py 가 사용하는 기능만 지원:
      - execute(sql, params=()) → cursor
      - executemany(sql, seq_of_params)
      - executescript(sql_script)  — SQL 을 ';' 기준으로 분리해 순차 실행
      - commit() / close()
      - 컨텍스트 매니저
      - 결과 row → dict-like (_Row)
    """

    def __init__(self, inner):
        self._conn = inner

    # ---- cursor ----
    def execute(self, sql: str, params: tuple | list | None = None):
        cur = self._conn.cursor()
        cur.execute(sql, params or ())
        return _CursorAdapter(cur)

    def executemany(self, sql: str, seq):
        cur = self._conn.cursor()
        cur.executemany(sql, list(seq))
        return _CursorAdapter(cur)

    def executescript(self, script: str):
        # libsql_experimental 은 multi-statement 를 한 execute 로 못 받을 수 있어 분리 실행.
        for stmt in _split_sql(script):
            if stmt:
                self._conn.cursor().execute(stmt)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    # ---- context ----
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        self.close()
        return False


class _CursorAdapter:
    """libsql cursor → sqlite3-style(Row 반환).

    주의 (지시 #13 fix):
    - libsql_experimental 커서는 Python 이터레이터 프로토콜(__iter__/__next__) 지원이 **보장되지 않는다**.
      → `__iter__` 를 `self.fetchall()` 로 구현(한 번에 모두 가져온 뒤 순회).
    - description 이 None 이면 컬럼명 없이 dict 로 감쌀 수 없다. raw tuple 반환은 금지(pm 지시).
      → 명시 RuntimeError. non-SELECT 쿼리는 fetchone/fetchall 호출 자체를 피하는 패턴이어야 함.
    """

    def __init__(self, cursor):
        self._cur = cursor

    def fetchone(self):
        row = self._cur.fetchone()
        return self._wrap(row)

    def fetchall(self):
        return [self._wrap(r) for r in self._cur.fetchall()]

    def __iter__(self):
        # libsql cursor 가 iterable 아닐 수 있으니 fetchall 기반.
        return iter(self.fetchall())

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    def _wrap(self, row):
        if row is None:
            return None
        desc = getattr(self._cur, "description", None) or []
        cols = [d[0] for d in desc]
        if not cols:
            raise RuntimeError(
                "Turso 커서에 description 이 없어 row 를 dict 로 감쌀 수 없습니다 "
                "(non-SELECT 결과를 fetch 하려는 호출 패턴일 수 있음)."
            )
        return _Row(dict(zip(cols, row)))


def _split_sql(script: str) -> list[str]:
    """세미콜론 기준 statement 분리 (주석·문자열 안의 ; 는 단순 처리로는 오탐 가능하지만,
    현재 schema 는 그런 케이스 없음)."""
    out = []
    buf = []
    for ch in script:
        buf.append(ch)
        if ch == ";":
            s = "".join(buf).strip()
            if s:
                out.append(s)
            buf = []
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


@contextmanager
def connect_turso() -> Iterator[TursoConnection]:
    """TURSO_DATABASE_URL / TURSO_AUTH_TOKEN 설정 상태를 전제로 Turso 커넥션을 연다.

    실패 시 **fallback 없이** `TursoConnectError` 를 던진다 (pm 요구).
    """
    s = get_settings()
    url = s.turso_database_url
    token = s.turso_auth_token
    if not url or not token:
        raise TursoConnectError(
            "TURSO_DATABASE_URL/TURSO_AUTH_TOKEN 가 비어 있습니다 — connect_turso() 호출 전 use_turso() 로 확인하세요."
        )
    libsql = _import_libsql()
    try:
        inner = libsql.connect(url, auth_token=token)
    except Exception as e:
        # 메시지 안에 전체 토큰·URL 가 들어가지 않도록 마스킹
        raise TursoConnectError(
            f"Turso 연결 실패 (url={_mask(url)}) — 원인: {type(e).__name__}"
        ) from None
    # FK 활성화 (SQLite 호환)
    try:
        inner.cursor().execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    conn = TursoConnection(inner)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
