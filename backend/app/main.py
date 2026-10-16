from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import store
from .config import get_settings
from .routers import collect, health, ipos, scoring_config


def create_app() -> FastAPI:
    settings = get_settings()
    # 테이블 생성 보장 — 라우터 핸들러가 store.last_collected_at() 등을 안전히 호출
    store.init_db()
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
    app.include_router(collect.router, prefix="/api")
    return app


app = create_app()
