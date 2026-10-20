"""저장소 ↔ 응답 모델 어댑터.

- `use_sample_data=True` 면 sample_data 모듈로, 아니면 store(SQLite)로 조회.
- store 의 row dict → IpoDetail(scores 재계산, 체크리스트 재생성)로 변환.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .config import get_scoring_config, get_settings
from .time_utils import now_iso_kst
from .schemas import (
    CorrectionInfo,
    Indicators,
    IpoDetail,
    IpoSummary,
    SourceDoc,
)
from .scoring import (
    build_checklist,
    build_verdict,
    evaluate,
    summary_from_detail,
)
from . import sample_data, store


# ---------- row → 모델 ----------

def _indicators_from_row(row: dict) -> Indicators:
    return Indicators(
        competition_rate=row.get("competition_rate"),
        competition_rate_type=row.get("competition_rate_type"),
        demand_amount_krw=row.get("demand_amount_krw"),
        price_position=row.get("price_position"),
        lockup_ratio=row.get("lockup_ratio"),
        lockup_ratio_basis=row.get("lockup_ratio_basis"),
        tradable_ratio=row.get("tradable_ratio"),
        old_share_ratio=row.get("old_share_ratio"),
        new_share_count=row.get("new_share_count"),
        old_share_count=row.get("old_share_count"),
        total_offering_count=row.get("total_offering_count"),
        offering_amount_krw=row.get("offering_amount_krw"),
        report_rcept_no=row.get("report_rcept_no"),
    )


def _sources_from_row(row: dict) -> list[SourceDoc]:
    return [SourceDoc.model_validate(s) for s in row.get("sources", [])]


def _correction_from_row(row: dict) -> Optional[CorrectionInfo]:
    """v0.8 (지시 #17): row.correction_requested_at 이 있으면 CorrectionInfo. 없으면 None."""
    requested = row.get("correction_requested_at")
    if not requested:
        return None
    return CorrectionInfo(requested_at=requested, amended_at=row.get("correction_amended_at"))


def _underwriters_from_row(row: dict) -> list[str]:
    """v1.2 (지시 #21): underwriters_json 컬럼(JSON 문자열) → list[str]."""
    raw = row.get("underwriters_json")
    if not raw:
        return []
    try:
        import json as _json
        data = _json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except Exception:
        return []


def _detail_from_row(row: dict) -> IpoDetail:
    cfg = get_scoring_config()
    ind = _indicators_from_row(row)
    correction = _correction_from_row(row)
    result = evaluate(ind, cfg, correction=correction)
    checklist = build_checklist(ind, cfg)   # v1.5 (지시 #33): 4항목
    return IpoDetail(
        id=row["corp_code"],
        corp_name=row["corp_name"],
        market=row.get("market"),                     # v0.4 — 원문 파싱 결과(없으면 null)
        subscription_start=row.get("subscription_start"),
        subscription_end=row.get("subscription_end"),
        listing_date=row.get("listing_date"),         # v0.4
        # v1.1 (지시 #20): 공모 일정 — IpoSummary 레벨 필드
        price_confirm_date=row.get("price_confirm_date"),
        demand_forecast_start=row.get("demand_forecast_start"),
        demand_forecast_end=row.get("demand_forecast_end"),
        band_low=row.get("band_low"),
        band_high=row.get("band_high"),
        final_price=row.get("final_price"),
        verdict=build_verdict(result),
        updated_at=row.get("updated_at") or now_iso_kst(),
        indicators=ind,
        scores=result.scores,
        reasons=result.reasons,
        reject_reasons=result.reject_reasons,
        # v1.6 (지시 #34): min_deposit 필드 제거
        sources=_sources_from_row(row),
        checklist=checklist,
        underwriters=_underwriters_from_row(row),   # v1.2 (지시 #21)
    )


# ---------- 공개 API ----------

def all_details() -> list[IpoDetail]:
    """v1.6 (지시 #34): shares 파라미터 제거."""
    if get_settings().use_sample_data:
        return sample_data.all_details()
    rows = store.list_ipos()
    return [_detail_from_row(r) for r in rows]


def get_detail(corp_code: str) -> Optional[IpoDetail]:
    """v1.6 (지시 #34): shares 파라미터 제거."""
    if get_settings().use_sample_data:
        return sample_data.get_detail(corp_code)
    row = store.get_ipo(corp_code)
    if row is None:
        return None
    return _detail_from_row(row)


def last_collected_at() -> Optional[str]:
    if get_settings().use_sample_data:
        return sample_data.last_collected_at()
    return store.last_collected_at()


def all_summaries() -> list[IpoSummary]:
    return [summary_from_detail(d) for d in all_details()]
