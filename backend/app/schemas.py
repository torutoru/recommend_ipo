from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


Status = Literal["PENDING", "PASS", "REJECT"]
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


class Verdict(BaseModel):
    status: Status
    grade: Optional[Grade] = None
    score: Optional[int] = Field(default=None, ge=0, le=100)


class IpoSummary(BaseModel):
    id: str
    corp_name: str
    market: Optional[Market] = None                             # MVP: 항상 null
    subscription_start: Optional[str] = None
    subscription_end: Optional[str] = None
    listing_date: Optional[str] = None                          # MVP: 항상 null
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


class IpoDetail(IpoSummary):
    indicators: Indicators
    scores: Scores
    reasons: list[str] = Field(default_factory=list)
    reject_reasons: list[str] = Field(default_factory=list)
    min_deposit: Optional[MinDeposit] = None
    sources: list[SourceDoc] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)   # v0.3 — 항상 6개


class IpoList(BaseModel):
    items: list[IpoSummary]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    last_collected_at: Optional[str] = None
