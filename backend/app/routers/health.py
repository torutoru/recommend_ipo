from fastapi import APIRouter

from .. import repository
from ..schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", last_collected_at=repository.last_collected_at())
