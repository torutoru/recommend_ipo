"""내 공모주 holdings API (지시 #51 dd93b259, requirements 24장, api-contract v1.7).

- GET  /api/holdings           → `{ items: Holding[] }` (정렬은 frontend)
- PUT  /api/holdings/{corp_code}  body `{shares, price, memo}` → 200 Holding (upsert)
- DELETE /api/holdings/{corp_code} → 204 (없어도 204)

인증 없음(사용자 결정). 응답에 비밀값 없음.
수집(collect)·재파싱은 이 테이블을 건드리지 않는다 — 테스트로 고정.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Response

from .. import store
from ..schemas import Holding, HoldingList, HoldingUpsertRequest
from ..time_utils import now_iso_kst


router = APIRouter(prefix="/holdings")


def _hydrate(conn, row) -> Holding:
    """저장 행 + ipos(corp_name, listing_date) 결합 + amount_krw 파생."""
    corp_name: Optional[str] = None
    listing_date: Optional[str] = None
    ipo = conn.execute(
        "SELECT corp_name, listing_date FROM ipos WHERE corp_code = ?",
        (row["corp_code"],),
    ).fetchone()
    if ipo is not None:
        corp_name = ipo["corp_name"]
        listing_date = ipo["listing_date"]
    return Holding(
        corp_code=row["corp_code"],
        shares=row["shares"],
        price=row["price"],
        memo=row["memo"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        corp_name=corp_name,
        listing_date=listing_date,
        amount_krw=row["shares"] * row["price"],
    )


@router.get("", response_model=HoldingList)
def list_holdings() -> HoldingList:
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT corp_code, shares, price, memo, created_at, updated_at "
            "FROM holdings ORDER BY created_at"
        ).fetchall()
        return HoldingList(items=[_hydrate(conn, r) for r in rows])


@router.put("/{corp_code}", response_model=Holding)
def upsert_holding(corp_code: str, body: HoldingUpsertRequest) -> Holding:
    with store.connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM ipos WHERE corp_code = ?", (corp_code,)
        ).fetchone()
        if exists is None:
            raise HTTPException(status_code=404, detail="corp_code 가 ipos 에 없음")
        now = now_iso_kst()
        existing = conn.execute(
            "SELECT created_at FROM holdings WHERE corp_code = ?", (corp_code,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO holdings (corp_code, shares, price, memo, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (corp_code, body.shares, body.price, body.memo, now, now),
            )
        else:
            conn.execute(
                "UPDATE holdings SET shares=?, price=?, memo=?, updated_at=? "
                "WHERE corp_code = ?",
                (body.shares, body.price, body.memo, now, corp_code),
            )
        row = conn.execute(
            "SELECT corp_code, shares, price, memo, created_at, updated_at "
            "FROM holdings WHERE corp_code = ?",
            (corp_code,),
        ).fetchone()
        return _hydrate(conn, row)


@router.delete("/{corp_code}")
def delete_holding(corp_code: str) -> Response:
    with store.connect() as conn:
        conn.execute("DELETE FROM holdings WHERE corp_code = ?", (corp_code,))
    return Response(status_code=204)
