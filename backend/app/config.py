from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    dart_cert_key: str = Field(default="", description="DART OpenAPI 인증키. 로그·응답 출력 금지.")
    # CORS 환경변수 `CORS_ORIGINS` 에 CSV 로. 예: "http://localhost:5173,https://my-netlify.app"
    cors_origins: str = Field(default="http://localhost:5173")

    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]
    scoring_config_path: Path = BACKEND_DIR / "app" / "config_files" / "scoring.yaml"
    sqlite_path: Path = BACKEND_DIR / "data" / "recommend_ipo.sqlite"
    use_sample_data: bool = False   # 기본: DB(수집기 결과). 테스트는 conftest 에서 True 로 강제.
    market_dominance_ratio: float = 3.0   # extract_market fallback: 1위가 2위의 N배 이상이어야 채택

    # 증분 수집 (requirements 11장)
    incremental_overlap_days: int = 7     # 마지막 수집 시각 - N일부터 조회(정정 누락 방지)
    initial_days: int = 90                # 최초 실행 시 조회 범위

    # IPO 식별 — 회사명에 아래 키워드가 포함되면 스팩으로 간주해 제외 (지시 #15, CSV).
    # 사용자 결정으로 "기업인수목적" 외에 "스팩" 도 추가.
    spac_exclusion_keywords: str = "기업인수목적,스팩"

    def spac_keywords(self) -> list[str]:
        return [k.strip() for k in self.spac_exclusion_keywords.split(",") if k.strip()]

    # 공모 금액 타당성 검사 (pm 지시 — 다비오 사례: 12,300원 오탐).
    # 원문 "모집(매출)총액" 매치값이 아래 두 하한 중 어느 하나라도 미달이면 null + warning
    # → fallback(total_offering_count × final_price) 로 다시 산출. 둘 다 없으면 null.
    offering_amount_min_absolute_krw: int = 100_000_000           # 1억 원 (업계 최소 IPO 규모 기준)
    offering_amount_min_ratio_vs_band_low: float = 0.10           # total_offering_count × band_low 의 10%

    # 수집 보호 (requirements 12장, api-contract v0.7). 비어 있으면 보호 없음.
    collect_key: str = ""

    # Turso (requirements 12장, 운영 DB).
    # 두 변수가 모두 있으면 Turso, 없으면 로컬 SQLite. 테스트는 conftest 에서 둘 다 ""로 강제.
    turso_database_url: str = ""
    turso_auth_token: str = ""


# ---------- scoring.yaml 모델 (api-contract v0.3) ----------

PricePositionKey = Literal["ABOVE_BAND", "TOP_OF_BAND", "WITHIN_BAND", "BELOW_BAND"]


class ScoreTier(BaseModel):
    gte: float
    points: int


class LargeCapBonus(BaseModel):
    """v0.6: 공모 금액 >= min_offering_amount_krw AND 경쟁률 >= min_competition_rate 일 때 +points."""
    min_offering_amount_krw: int
    min_competition_rate: float
    points: int


class CompScoreConfig(BaseModel):
    max: int
    tiers: list[ScoreTier]
    default: int
    large_cap_bonus: LargeCapBonus


class PriceScoreConfig(BaseModel):
    max: int
    points: dict[PricePositionKey, int]


class LockupScoreConfig(BaseModel):
    max: int
    tiers: list[ScoreTier]
    default: int


class FlowZeroIf(BaseModel):
    tradable_gt: float
    old_share_gte: float


class FlowTopIf(BaseModel):
    tradable_lt: float
    old_share_eq: float
    points: int


class FlowScoreConfig(BaseModel):
    max: int
    zero_if: FlowZeroIf
    top_if: FlowTopIf
    otherwise: int


class ScoreConfig(BaseModel):
    comp: CompScoreConfig
    price: PriceScoreConfig
    lockup: LockupScoreConfig
    flow: FlowScoreConfig


class GradeConfig(BaseModel):
    pass_min: int
    s_min: int
    a_min: int


class DepositConfig(BaseModel):
    default_shares: int
    margin_rate: float
    fee_krw: int


class ChecklistConfig(BaseModel):
    competition_min: float
    price_positions_met: list[PricePositionKey]
    lockup_min: float
    flow_tradable_max: float
    flow_old_share_lt: float


class ScoringConfig(BaseModel):
    score: ScoreConfig
    grade: GradeConfig
    deposit: DepositConfig
    checklist: ChecklistConfig


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def use_turso(settings: Optional[Settings] = None) -> bool:
    """Turso 사용 여부 — 환경변수(설정 객체) 둘 다 있어야 True."""
    s = settings or get_settings()
    return bool(s.turso_database_url) and bool(s.turso_auth_token)


@lru_cache(maxsize=1)
def get_scoring_config() -> ScoringConfig:
    path = get_settings().scoring_config_path
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ScoringConfig.model_validate(raw)
