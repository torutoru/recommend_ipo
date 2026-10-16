from fastapi import APIRouter

from ..config import ScoringConfig, get_scoring_config

router = APIRouter()


@router.get("/scoring-config", response_model=ScoringConfig)
def read_scoring_config() -> ScoringConfig:
    """현재 적용 중인 하드 필터·점수·등급·증거금 기준값.

    frontend 의 "판정 기준" 안내 화면에서 사용한다.
    구조 변경은 api-contract 협상 후 pm 이 반영한다.
    """
    return get_scoring_config()
