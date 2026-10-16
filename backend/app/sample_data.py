"""샘플 데이터 — v0.4 (달력 개발용).

목표:
- 상태: PENDING / PASS-S / PASS-A / PASS-B / REJECT 각 1건 이상
- 체크리스트: MET / NOT_MET / UNKNOWN / INFO 조합 다양
- 달력 UX: 청약 기간/상장일이 **여러 달에 걸치게** 배치
- market: KOSPI / KOSDAQ / KONEX / null 섞음
- listing_date: 있는 종목·없는 종목 섞음
"""
from __future__ import annotations

from datetime import datetime

from .config import get_scoring_config
from .schemas import (
    Indicators,
    IpoDetail,
    SourceDoc,
)
from .time_utils import now_iso_kst
from .scoring import (
    build_checklist,
    build_verdict,
    calc_min_deposit,
    evaluate,
)


_DART_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


def _dart(rcept_no: str) -> str:
    return f"{_DART_URL}{rcept_no}"


def _build(
    *,
    corp_code: str,
    corp_name: str,
    market: str | None,
    subscription_start: str | None,
    subscription_end: str | None,
    listing_date: str | None,
    band_low: int | None,
    band_high: int | None,
    final_price: int | None,
    indicators: Indicators,
    sources: list[SourceDoc],
    shares: int = 10,
) -> IpoDetail:
    cfg = get_scoring_config()
    result = evaluate(indicators, cfg)
    deposit = calc_min_deposit(final_price, shares, cfg)
    checklist = build_checklist(indicators, deposit, cfg, listing_date=listing_date)
    now = now_iso_kst()

    return IpoDetail(
        id=corp_code,
        corp_name=corp_name,
        market=market,  # type: ignore[arg-type]
        subscription_start=subscription_start,
        subscription_end=subscription_end,
        listing_date=listing_date,
        band_low=band_low,
        band_high=band_high,
        final_price=final_price,
        verdict=build_verdict(result),
        indicators=indicators,
        scores=result.scores,
        reasons=result.reasons,
        reject_reasons=result.reject_reasons,
        min_deposit=deposit,
        sources=sources,
        updated_at=now,
        checklist=checklist,
    )


# ---------- 샘플 (10월 ~ 12월 + 월 경계) ----------

def _s_pending_oct() -> IpoDetail:
    """PENDING + 10월 청약, 상장일 미공시, market=KOSDAQ."""
    return _build(
        corp_code="00990001",
        corp_name="(샘플) 나라AI",
        market="KOSDAQ",
        subscription_start="2026-10-28",
        subscription_end="2026-10-29",
        listing_date=None,                          # 미공시
        band_low=18000,
        band_high=22000,
        final_price=None,
        indicators=Indicators(report_rcept_no="20261020000001"),
        sources=[
            SourceDoc(doc_type="PROSPECTUS", rcept_no="20261020000001",
                      rcept_dt="2026-10-20", url=_dart("20261020000001")),
        ],
    )


def _s_pass_s_cross_month() -> IpoDetail:
    """PASS-S + 청약 10월 말, 상장 11월 — 달력에서 월 경계 걸침, market=KOSPI."""
    return _build(
        corp_code="00990002",
        corp_name="(샘플) 세종바이오",
        market="KOSPI",
        subscription_start="2026-10-30",
        subscription_end="2026-10-31",
        listing_date="2026-11-11",                  # 다른 달
        band_low=42000,
        band_high=48000,
        final_price=52000,                          # ABOVE_BAND
        indicators=Indicators(
            competition_rate=2214.3,
            competition_rate_type="weighted",
            demand_amount_krw=6_200_000_000_000,    # +5 가산
            price_position="ABOVE_BAND",
            lockup_ratio=38.5,
            lockup_ratio_basis="allocated",
            tradable_ratio=22.0,
            old_share_ratio=0.0,
            new_share_count=8_000_000,
            old_share_count=0,
            total_offering_count=8_000_000,
            offering_amount_krw=8_000_000 * 52_000,     # 4,160억 → 가산 조건 충족
            report_rcept_no="20261024000022",
        ),
        sources=[
            SourceDoc(doc_type="PROSPECTUS", rcept_no="20261010000011",
                      rcept_dt="2026-10-10", url=_dart("20261010000011")),
            SourceDoc(doc_type="REGISTRATION_AMENDED", rcept_no="20261024000022",
                      rcept_dt="2026-10-24", url=_dart("20261024000022")),
        ],
    )


def _s_reject_nov() -> IpoDetail:
    """REJECT(점수 보유) + 11월 초, 상장일 11월 중순, market=KOSDAQ."""
    return _build(
        corp_code="00990003",
        corp_name="(샘플) 한강에너지",
        market="KOSDAQ",
        subscription_start="2026-11-03",
        subscription_end="2026-11-04",
        listing_date="2026-11-13",
        band_low=11000,
        band_high=13000,
        final_price=9500,                           # BELOW_BAND
        indicators=Indicators(
            competition_rate=612.4,
            competition_rate_type="simple",
            demand_amount_krw=180_000_000_000,
            price_position="BELOW_BAND",
            lockup_ratio=4.2,
            lockup_ratio_basis="allocated",
            tradable_ratio=55.0,
            old_share_ratio=42.0,
            new_share_count=2_320_000,
            old_share_count=1_680_000,
            total_offering_count=4_000_000,
            offering_amount_krw=4_000_000 * 9_500,      # 380억 — 가산 미달
            report_rcept_no="20261019000033",
        ),
        sources=[
            SourceDoc(doc_type="REGISTRATION_AMENDED", rcept_no="20261019000033",
                      rcept_dt="2026-10-19", url=_dart("20261019000033")),
        ],
    )


def _s_pass_b_cross_month() -> IpoDetail:
    """PASS-B + 11월 말 ~ 12월 상장 (월 경계), market=KOSPI, 체크리스트 혼재."""
    return _build(
        corp_code="00990004",
        corp_name="(샘플) 대륙중공업",
        market="KOSPI",
        subscription_start="2026-11-27",
        subscription_end="2026-11-28",
        listing_date="2026-12-05",
        band_low=55000,
        band_high=62000,
        final_price=58000,                          # WITHIN_BAND
        indicators=Indicators(
            competition_rate=1620.0,
            competition_rate_type="simple",
            demand_amount_krw=2_200_000_000_000,
            price_position="WITHIN_BAND",
            lockup_ratio=12.0,
            lockup_ratio_basis="allocated",
            tradable_ratio=38.0,                    # NOT_MET
            old_share_ratio=10.0,
            new_share_count=10_800_000,
            old_share_count=1_200_000,
            total_offering_count=12_000_000,
            offering_amount_krw=12_000_000 * 58_000,    # 6,960억 → 1000억 이상 + 1620:1 ≥ 800 → 가산 +5
            report_rcept_no="20261105000044",
        ),
        sources=[
            SourceDoc(doc_type="REGISTRATION_AMENDED", rcept_no="20261105000044",
                      rcept_dt="2026-11-05", url=_dart("20261105000044")),
        ],
    )


def _s_pass_a_lockup_unknown() -> IpoDetail:
    """PASS-A + lockup=UNKNOWN(파싱 실패), 상장일 미공시, market=null."""
    return _build(
        corp_code="00990005",
        corp_name="(샘플) 북극로보틱스",
        market=None,                                # 시장 구분 파싱 실패 가정
        subscription_start="2026-11-17",
        subscription_end="2026-11-18",
        listing_date=None,
        band_low=24000,
        band_high=28000,
        final_price=28000,                          # TOP_OF_BAND
        indicators=Indicators(
            competition_rate=1850.0,
            competition_rate_type="weighted",
            demand_amount_krw=1_500_000_000_000,
            price_position="TOP_OF_BAND",
            lockup_ratio=None,
            lockup_ratio_basis=None,
            tradable_ratio=24.0,
            old_share_ratio=0.0,
            new_share_count=6_000_000,
            old_share_count=0,
            total_offering_count=6_000_000,
            offering_amount_krw=6_000_000 * 28_000,     # 1,680억 → 가산 조건 충족 (1850 ≥ 800)
            report_rcept_no="20261112000055",
        ),
        sources=[
            SourceDoc(doc_type="PROSPECTUS", rcept_no="20261101000050",
                      rcept_dt="2026-11-01", url=_dart("20261101000050")),
            SourceDoc(doc_type="PROSPECTUS_AMENDED", rcept_no="20261112000055",
                      rcept_dt="2026-11-12", url=_dart("20261112000055")),
        ],
    )


def _s_pass_b_konex_dec() -> IpoDetail:
    """PASS-B + 12월 청약·상장, market=KONEX (코넥스), 체크리스트 flow MET."""
    return _build(
        corp_code="00990006",
        corp_name="(샘플) 가야반도체",
        market="KONEX",
        subscription_start="2026-12-15",
        subscription_end="2026-12-16",
        listing_date="2026-12-23",
        band_low=8000,
        band_high=10000,
        final_price=10000,                          # TOP_OF_BAND
        indicators=Indicators(
            competition_rate=820.0,                 # 500~1000 → comp 15
            competition_rate_type="simple",
            demand_amount_krw=120_000_000_000,
            price_position="TOP_OF_BAND",           # 20
            lockup_ratio=11.0,                      # 10~20 → 15
            lockup_ratio_basis="allocated",
            tradable_ratio=28.0,                    # 25~35, flow otherwise → 12
            old_share_ratio=0.0,
            new_share_count=1_500_000,
            old_share_count=0,
            total_offering_count=1_500_000,
            offering_amount_krw=1_500_000 * 10_000,     # 150억 — 1000억 미달 → 가산 없음
            report_rcept_no="20261210000077",
        ),
        sources=[
            SourceDoc(doc_type="REGISTRATION_AMENDED", rcept_no="20261210000077",
                      rcept_dt="2026-12-10", url=_dart("20261210000077")),
        ],
    )


_SAMPLES: dict[str, IpoDetail] = {
    d.id: d
    for d in [
        _s_pending_oct(),
        _s_pass_s_cross_month(),
        _s_reject_nov(),
        _s_pass_b_cross_month(),
        _s_pass_a_lockup_unknown(),
        _s_pass_b_konex_dec(),
    ]
}


def all_details() -> list[IpoDetail]:
    return sorted(
        _SAMPLES.values(),
        key=lambda d: (d.subscription_start or "9999-99-99"),
    )


def get_detail(corp_code: str, shares: int) -> IpoDetail | None:
    base = _SAMPLES.get(corp_code)
    if base is None:
        return None
    cfg = get_scoring_config()
    deposit = calc_min_deposit(base.final_price, shares, cfg)
    checklist = build_checklist(base.indicators, deposit, cfg, listing_date=base.listing_date)
    return base.model_copy(update={"min_deposit": deposit, "checklist": checklist})


def last_collected_at() -> str:
    return now_iso_kst()
