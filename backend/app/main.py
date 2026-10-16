from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import health, ipos, scoring_config


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="recommend_ipo backend",
        version="0.1.0",
        description="DART 공시 기반 공모주 청약 추천 API (MVP).",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(ipos.router, prefix="/api")
    app.include_router(scoring_config.router, prefix="/api")
    return app


app = create_app()
