"""SQLite 저장소 — 수집·조회.

- 표준 라이브러리 sqlite3 사용(의존성 추가 없음).
- 스키마는 **파싱 결과(parser.ParsedIpo + 식별 메타)**를 보존하고, 응답은 매번 점수 재계산 전제.
  (설정 변경 시 재수집 없이 점수가 갱신되도록.)
- 외부 수집기(collect.py)만 쓰기, 라우터는 읽기만.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from .time_utils import now_iso_kst
from pathlib import Path
from typing import Iterator, Optional

from .config import get_settings, use_turso


SCHEMA = """
CREATE TABLE IF NOT EXISTS ipos (
    corp_code                TEXT PRIMARY KEY,
    corp_name                TEXT NOT NULL,
    market                   TEXT,              -- v0.4
    subscription_start       TEXT,
    subscription_end         TEXT,
    listing_date             TEXT,              -- v0.4
    band_low                 INTEGER,
    band_high                INTEGER,
    final_price              INTEGER,
    price_position           TEXT,
    competition_rate         REAL,
    competition_rate_type    TEXT,
    demand_quantity          INTEGER,
    demand_amount_krw        INTEGER,
    lockup_ratio             REAL,
    lockup_ratio_basis       TEXT,
    tradable_ratio           REAL,
    old_share_ratio          REAL,
    new_share_count          INTEGER,
    old_share_count          INTEGER,
    total_offering_count     INTEGER,
    offering_amount_krw      INTEGER,            -- v0.6
    report_rcept_no          TEXT,
    withdrawn_rcept_no       TEXT,               -- v0.5 — 철회 신고서 접수번호 (NOT NULL → 제외 종목)
    updated_at               TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    corp_code  TEXT NOT NULL,
    doc_type   TEXT NOT NULL,
    rcept_no   TEXT NOT NULL,
    rcept_dt   TEXT NOT NULL,
    url        TEXT NOT NULL,
    PRIMARY KEY (corp_code, rcept_no),
    FOREIGN KEY (corp_code) REFERENCES ipos(corp_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS parse_warnings (
    corp_code  TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    message    TEXT NOT NULL,
    PRIMARY KEY (corp_code, seq),
    FOREIGN KEY (corp_code) REFERENCES ipos(corp_code) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS collect_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    days          INTEGER,
    collected     INTEGER DEFAULT 0,
    errors        INTEGER DEFAULT 0,
    note          TEXT
);

CREATE INDEX IF NOT EXISTS idx_ipos_subscription_start ON ipos(subscription_start);
CREATE INDEX IF NOT EXISTS idx_ipos_listing_date ON ipos(listing_date);
"""


# ---------- 연결 ----------

def _resolve_path(path: Optional[Path]) -> Path:
    p = path or get_settings().sqlite_path
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    """매 호출마다 짧게 쓰고 닫는 커넥션. FK 활성화.

    v0.7 (requirements 12장): `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` 둘 다 설정되면 Turso 로 연결.
    **연결 실패는 조용히 SQLite 로 fallback 하지 않는다** — pm 지시 #12.
    `TursoConnectError` 그대로 전파 → 서버 기동 실패 또는 수집 실패로 명시.
    """
    if use_turso():
        from .turso_adapter import connect_turso  # 지연 import (Windows 에서 전혀 안 불러감)
        with connect_turso() as tconn:
            yield tconn  # TursoConnection — sqlite3.Connection 와 유사 인터페이스
        return

    conn = sqlite3.connect(str(_resolve_path(path)))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# 운영 DB(Turso·배포된 SQLite) 에 안전한 컬럼 추가용 마이그레이션.
# SQLite 는 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 를 지원하지 않으므로 PRAGMA 로 체크.
# **DROP·DELETE 금지** — 추가만. 이 함수는 init_db() 가 자동 호출한다.
_MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, DDL — "ALTER TABLE {table} ADD COLUMN {column} ..." 뒷부분)
    # 예: 미래에 ipos 에 withdrawn_rcept_no 를 ipos 에 추가해야 할 때
    #   ("ipos", "some_new_col", "some_new_col TEXT"),
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    """존재하지 않는 컬럼만 ADD COLUMN. DROP 금지."""
    for table, column, ddl in _MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def init_db(path: Optional[Path] = None) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        _run_migrations(conn)


# ---------- 쓰기 ----------

def upsert_ipo(
    conn: sqlite3.Connection,
    *,
    corp_code: str,
    corp_name: str,
    market: Optional[str],
    subscription_start: Optional[str],
    subscription_end: Optional[str],
    listing_date: Optional[str],
    band_low: Optional[int],
    band_high: Optional[int],
    final_price: Optional[int],
    price_position: Optional[str],
    competition_rate: Optional[float],
    competition_rate_type: Optional[str],
    demand_quantity: Optional[int],
    demand_amount_krw: Optional[int],
    lockup_ratio: Optional[float],
    lockup_ratio_basis: Optional[str],
    tradable_ratio: Optional[float],
    old_share_ratio: Optional[float],
    new_share_count: Optional[int],
    old_share_count: Optional[int],
    total_offering_count: Optional[int],
    offering_amount_krw: Optional[int],
    report_rcept_no: Optional[str],
) -> None:
    now = now_iso_kst()
    conn.execute(
        """
        INSERT INTO ipos (
            corp_code, corp_name, market, subscription_start, subscription_end, listing_date,
            band_low, band_high, final_price, price_position,
            competition_rate, competition_rate_type, demand_quantity, demand_amount_krw,
            lockup_ratio, lockup_ratio_basis, tradable_ratio, old_share_ratio,
            new_share_count, old_share_count, total_offering_count, offering_amount_krw, report_rcept_no,
            updated_at
        ) VALUES (?,?,?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?, ?,?,?,?,?, ?)
        ON CONFLICT(corp_code) DO UPDATE SET
            corp_name=excluded.corp_name,
            market=excluded.market,
            subscription_start=excluded.subscription_start,
            subscription_end=excluded.subscription_end,
            listing_date=excluded.listing_date,
            band_low=excluded.band_low,
            band_high=excluded.band_high,
            final_price=excluded.final_price,
            price_position=excluded.price_position,
            competition_rate=excluded.competition_rate,
            competition_rate_type=excluded.competition_rate_type,
            demand_quantity=excluded.demand_quantity,
            demand_amount_krw=excluded.demand_amount_krw,
            lockup_ratio=excluded.lockup_ratio,
            lockup_ratio_basis=excluded.lockup_ratio_basis,
            tradable_ratio=excluded.tradable_ratio,
            old_share_ratio=excluded.old_share_ratio,
            new_share_count=excluded.new_share_count,
            old_share_count=excluded.old_share_count,
            total_offering_count=excluded.total_offering_count,
            offering_amount_krw=excluded.offering_amount_krw,
            report_rcept_no=excluded.report_rcept_no,
            updated_at=excluded.updated_at
        """,
        (
            corp_code, corp_name, market, subscription_start, subscription_end, listing_date,
            band_low, band_high, final_price, price_position,
            competition_rate, competition_rate_type, demand_quantity, demand_amount_krw,
            lockup_ratio, lockup_ratio_basis, tradable_ratio, old_share_ratio,
            new_share_count, old_share_count, total_offering_count, offering_amount_krw, report_rcept_no,
            now,
        ),
    )


def replace_sources(
    conn: sqlite3.Connection,
    corp_code: str,
    sources: list[dict],
) -> None:
    conn.execute("DELETE FROM sources WHERE corp_code = ?", (corp_code,))
    conn.executemany(
        "INSERT INTO sources (corp_code, doc_type, rcept_no, rcept_dt, url) VALUES (?,?,?,?,?)",
        [
            (corp_code, s["doc_type"], s["rcept_no"], s["rcept_dt"], s["url"])
            for s in sources
        ],
    )


def replace_warnings(
    conn: sqlite3.Connection,
    corp_code: str,
    warnings: list[str],
) -> None:
    conn.execute("DELETE FROM parse_warnings WHERE corp_code = ?", (corp_code,))
    conn.executemany(
        "INSERT INTO parse_warnings (corp_code, seq, message) VALUES (?,?,?)",
        [(corp_code, i, w) for i, w in enumerate(warnings)],
    )


def known_rcept_nos(conn: sqlite3.Connection) -> set[str]:
    """DB(sources + ipos.withdrawn_rcept_no + ipos.report_rcept_no)에 이미 들어와 있는 접수번호 집합.

    증분 수집: 이 집합에 없는 접수번호만 새로 처리한다.
    """
    out: set[str] = set()
    for r in conn.execute("SELECT rcept_no FROM sources"):
        out.add(r["rcept_no"])
    for r in conn.execute("SELECT withdrawn_rcept_no FROM ipos WHERE withdrawn_rcept_no IS NOT NULL"):
        out.add(r["withdrawn_rcept_no"])
    return out


def mark_withdrawn(conn: sqlite3.Connection, corp_code: str, rcept_no: str, now: Optional[str] = None) -> None:
    """철회 신고서 발견 → 종목에 withdrawn 플래그. ipos 레코드가 없으면 최소 메타만 생성."""
    now = now or now_iso_kst()
    conn.execute(
        """
        INSERT INTO ipos (corp_code, corp_name, withdrawn_rcept_no, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(corp_code) DO UPDATE SET
            withdrawn_rcept_no=excluded.withdrawn_rcept_no,
            updated_at=excluded.updated_at
        """,
        (corp_code, corp_code, rcept_no, now),
    )


def start_collect_run(conn: sqlite3.Connection, days: int) -> int:
    cur = conn.execute(
        "INSERT INTO collect_runs (started_at, days) VALUES (?, ?)",
        (now_iso_kst(), days),
    )
    return cur.lastrowid


def finish_collect_run(
    conn: sqlite3.Connection, run_id: int, *, collected: int, errors: int, note: str = ""
) -> None:
    conn.execute(
        "UPDATE collect_runs SET finished_at = ?, collected = ?, errors = ?, note = ? WHERE id = ?",
        (now_iso_kst(), collected, errors, note, run_id),
    )


# ---------- 읽기 ----------

def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def list_ipos(path: Optional[Path] = None) -> list[dict]:
    """모든 종목 + 각 종목의 sources·warnings 를 포함한 dict. 철회 종목은 제외."""
    with connect(path) as conn:
        ipos = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM ipos WHERE withdrawn_rcept_no IS NULL "
            "ORDER BY COALESCE(subscription_start, '9999-99-99')"
        )]
        srcs: dict[str, list[dict]] = {}
        for r in conn.execute("SELECT * FROM sources ORDER BY rcept_dt"):
            srcs.setdefault(r["corp_code"], []).append({
                "doc_type": r["doc_type"],
                "rcept_no": r["rcept_no"],
                "rcept_dt": r["rcept_dt"],
                "url": r["url"],
            })
        warns: dict[str, list[str]] = {}
        for r in conn.execute("SELECT * FROM parse_warnings ORDER BY seq"):
            warns.setdefault(r["corp_code"], []).append(r["message"])
        for i in ipos:
            i["sources"] = srcs.get(i["corp_code"], [])
            i["warnings"] = warns.get(i["corp_code"], [])
    return ipos


def get_ipo(corp_code: str, path: Optional[Path] = None) -> Optional[dict]:
    """철회 종목은 조회 불가(None 반환)."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM ipos WHERE corp_code = ? AND withdrawn_rcept_no IS NULL",
            (corp_code,),
        ).fetchone()
        if row is None:
            return None
        out = _row_to_dict(row)
        out["sources"] = [
            {"doc_type": r["doc_type"], "rcept_no": r["rcept_no"],
             "rcept_dt": r["rcept_dt"], "url": r["url"]}
            for r in conn.execute(
                "SELECT * FROM sources WHERE corp_code = ? ORDER BY rcept_dt", (corp_code,)
            )
        ]
        out["warnings"] = [
            r["message"]
            for r in conn.execute(
                "SELECT message FROM parse_warnings WHERE corp_code = ? ORDER BY seq", (corp_code,)
            )
        ]
        return out


def last_collected_at(path: Optional[Path] = None) -> Optional[str]:
    with connect(path) as conn:
        row = conn.execute(
            "SELECT finished_at FROM collect_runs WHERE finished_at IS NOT NULL "
            "ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
        return row["finished_at"] if row else None
