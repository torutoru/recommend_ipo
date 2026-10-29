import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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


@router.get("/wake")
def wake() -> JSONResponse:
    """지시 #59 (api-contract v1.9): Render Free 슬립 깨우기 전용 — DB/외부 호출 없이 즉시 응답.

    `Cache-Control: no-store` 로 Netlify/브라우저 캐시 금지(매번 Render 를 깨워야 함).
    """
    return JSONResponse(
        content={"status": "ok"},
        headers={"Cache-Control": "no-store"},
    )
