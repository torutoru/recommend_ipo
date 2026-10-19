from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


Status = Literal[
    "PENDING",
    "INCOMPLETE",       # v1.0
    "CORRECTION",       # v0.8 (지시 #17) — 금감원 정정신고서 제출요구 있음 + 발행조건확정 없음
    "PASS",
    "REJECT",
]
Grade = Literal["S", "A", "B"]                                 # v0.3: C 삭제
PricePosition = Literal[
    "ABOVE_BAND",
    "TOP_OF_BAND",
    "WITHIN_BAND",                                              # v0.3
    "BELOW_BAND",                                               # v0.3
]
Market = Literal["KOSPI", "KOSDAQ", "KONEX"]
DocType = Literal[
    "PROSPECTUS",
    "PROSPECTUS_AMENDED",
    "REGISTRATION_AMENDED",
    "ISSUANCE_REPORT",
    "CORRECTION_REQUEST",   # v0.8 (지시 #17) — 금감원 "정정신고서 제출요구" 공시
]
CompetitionRateType = Literal["simple", "weighted"]
LockupBasis = Literal["allocated", "applied"]

ChecklistKey = Literal[
    "competition",
    "price_position",
    "lockup",
    "flow",
    "min_deposit",
    "sell_timing",
]
ChecklistResult = Literal["MET", "NOT_MET", "UNKNOWN", "INFO"]
# v0.9 (지시 #18): competition 전용 — "좋음"/"아주 좋음" 2단계 표시
ChecklistLevel = Literal["GOOD", "VERY_GOOD"]


class ScoreRange(BaseModel):
    """v1.4 (지시 #27): 미확인 지표가 있지만 범위로 PASS/REJECT 가 확정된 경우 노출.

    `score`·`scores.total` 은 null, 이 필드에 가능 점수 범위가 들어간다.
    PASS 등급은 `min` 기준(최소 보장 등급).
    """
    min: int = Field(ge=0, le=100)
    max: int = Field(ge=0, le=100)


class CorrectionInfo(BaseModel):
    """v0.8 (지시 #17): 금감원 정정신고서 제출요구 정보.

    `requested_at`: 정정신고서 제출요구일 (YYYY-MM-DD)
    `amended_at`: 그 이후 발행사가 제출한 정정신고서 접수일 (아직 없으면 null)
    """
    requested_at: str
    amended_at: Optional[str] = None


class Verdict(BaseModel):
    status: Status
    grade: Optional[Grade] = None
    score: Optional[int] = Field(default=None, ge=0, le=100)
    score_range: Optional[ScoreRange] = None   # v1.4 (지시 #27)
    correction: Optional[CorrectionInfo] = None   # v0.8 (지시 #17)


class IpoSummary(BaseModel):
    id: str
    corp_name: str
    market: Optional[Market] = None                             # MVP: 항상 null
    subscription_start: Optional[str] = None
    subscription_end: Optional[str] = None
    listing_date: Optional[str] = None                          # MVP: 항상 null
    # v1.1 (지시 #20): 공모 일정 — PENDING/CORRECTION 종목 안내용
    price_confirm_date: Optional[str] = None                    # 공모가 확정공고일 = [발행조건확정] 공시 공개일
    demand_forecast_start: Optional[str] = None                 # 수요예측 시작일
    demand_forecast_end: Optional[str] = None                   # 수요예측 종료일
    band_low: Optional[int] = None
    band_high: Optional[int] = None
    final_price: Optional[int] = None
    verdict: Verdict
    updated_at: str


class Indicators(BaseModel):
    competition_rate: Optional[float] = None
    competition_rate_type: Optional[CompetitionRateType] = None
    demand_amount_krw: Optional[int] = None
    price_position: Optional[PricePosition] = None
    lockup_ratio: Optional[float] = None
    lockup_ratio_basis: Optional[LockupBasis] = None
    tradable_ratio: Optional[float] = None
    old_share_ratio: Optional[float] = None
    new_share_count: Optional[int] = None
    old_share_count: Optional[int] = None
    total_offering_count: Optional[int] = None
    offering_amount_krw: Optional[int] = None            # v0.6
    report_rcept_no: Optional[str] = None


class Scores(BaseModel):
    comp: Optional[int] = None    # 0~35 (가산 포함, 최대 35)
    price: Optional[int] = None   # 0~25
    lockup: Optional[int] = None  # 0~20
    flow: Optional[int] = None    # 0~20
    total: Optional[int] = None   # 0~100


class SourceDoc(BaseModel):
    doc_type: DocType
    rcept_no: str
    rcept_dt: str
    url: str


class MinDeposit(BaseModel):
    shares: int
    deposit_krw: int        # shares × final_price × margin_rate
    fee_krw: int            # v0.3
    total_krw: int          # v0.3 = deposit_krw + fee_krw


class ChecklistItem(BaseModel):
    key: ChecklistKey
    label: str
    indicator: str
    criterion: str
    actual: Optional[str] = None
    result: ChecklistResult
    level: Optional[ChecklistLevel] = None   # v0.9 (지시 #18): competition 만 설정


class IpoDetail(IpoSummary):
    indicators: Indicators
    scores: Scores
    reasons: list[str] = Field(default_factory=list)
    reject_reasons: list[str] = Field(default_factory=list)
    min_deposit: Optional[MinDeposit] = None
    sources: list[SourceDoc] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)   # v0.3 — 항상 6개
    # v1.2 (지시 #21): 주관사·인수회사 이름(대표→공동→인수 순, 중복 제거). 상세 화면에만 노출.
    underwriters: list[str] = Field(default_factory=list)


class IpoList(BaseModel):
    items: list[IpoSummary]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    last_collected_at: Optional[str] = None


# ---------- 수집 API (v0.5 + v0.7) ----------

CollectRunStatus = Literal["IDLE", "RUNNING", "SUCCEEDED", "FAILED"]


class CollectProgress(BaseModel):
    done: int
    total: Optional[int] = None   # 모르면 null


class CollectSummary(BaseModel):
    new_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    failed_count: int = 0
    withdrawn_count: int = 0


class CollectFailure(BaseModel):
    """v1.3 (지시 #22): 종목 단위 실패 사유 — 키·URL 미노출."""
    corp_code: str
    corp_name: str
    reason: str


class CollectStatus(BaseModel):
    status: CollectRunStatus
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    progress: Optional[CollectProgress] = None
    summary: Optional[CollectSummary] = None
    failures: list[CollectFailure] = Field(default_factory=list)  # v1.3 (지시 #22)
    error: Optional[str] = None
    last_collected_at: Optional[str] = None
