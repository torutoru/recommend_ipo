import os

from fastapi import APIRouter

from .. import repository
from ..collect import PARSER_VERSION
from ..schemas import HealthResponse

router = APIRouter()


def _resolve_commit() -> str | None:
    """지시 #31: Render(`RENDER_GIT_COMMIT`) / 범용(`GIT_COMMIT`·`COMMIT_SHA`) 환경변수 중 하나.
    없으면 null — 로컬 개발 환경 등."""
    for key in ("RENDER_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA"):
        v = os.environ.get(key)
        if v:
            return v[:7]
    return None


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        last_collected_at=repository.last_collected_at(),
        parser_version=PARSER_VERSION,
        commit=_resolve_commit(),
    )
