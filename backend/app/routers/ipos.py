from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .. import repository
from ..schemas import IpoDetail, IpoList, IpoSummary, Status
from ..scoring import summary_from_detail

router = APIRouter(prefix="/ipos")


def _overlaps_range(
    summary_start: Optional[str],
    summary_end: Optional[str],
    listing_date: Optional[str],
    rng_from: Optional[str],
    rng_to: Optional[str],
) -> bool:
    """v0.4 — 청약기간(start~end) 또는 listing_date 중 하나라도 [rng_from, rng_to] 와 겹치면 True.

    - 두 날짜 모두 YYYY-MM-DD (일자 기반 포함 경계).
    - from/to 가 둘 다 None 이면 True(필터 없음).
    - 청약기간 end 가 null 이면 start==end 로 간주. start 도 null 이면 청약기간은 '없는 것'.
    - 범위 오버랩: not (A.end < B.from or A.start > B.to)
    """
    if rng_from is None and rng_to is None:
        return True

    hits = []
    # 청약기간
    if summary_start is not None:
        s = summary_start
        e = summary_end or summary_start
        hits.append((s, e))
    # 상장일
    if listing_date is not None:
        hits.append((listing_date, listing_date))

    if not hits:
        return False

    for s, e in hits:
        a_end_before_b_from = rng_from is not None and e < rng_from
        a_start_after_b_to = rng_to is not None and s > rng_to
        if not (a_end_before_b_from or a_start_after_b_to):
            return True
    return False


@router.get("", response_model=IpoList)
def list_ipos(
    status: Optional[Status] = Query(default=None),
    from_date: Optional[str] = Query(default=None, alias="from",
                                     description="YYYY-MM-DD. v0.4: 청약기간 또는 상장일이 [from,to] 와 겹치는 종목"),
    to_date: Optional[str] = Query(default=None, alias="to"),
) -> IpoList:
    items: list[IpoSummary] = []
    for d in repository.all_details():
        if status is not None and d.verdict.status != status:
            continue
        if not _overlaps_range(
            d.subscription_start, d.subscription_end, d.listing_date, from_date, to_date
        ):
            continue
        items.append(summary_from_detail(d))
    items.sort(key=lambda it: (it.subscription_start or "9999-99-99"))
    return IpoList(items=items)


@router.get("/{corp_code}", response_model=IpoDetail)
def get_ipo(
    corp_code: str,
    # v1.6 (지시 #34): shares 쿼리는 들어와도 **무시**(422 반환 안 함, 하위 호환).
    shares: Optional[int] = Query(default=None),
) -> IpoDetail:
    _ = shares   # 받고 버림
    d = repository.get_detail(corp_code)
    if d is None:
        raise HTTPException(status_code=404, detail="해당 종목을 찾을 수 없습니다.")
    return d
