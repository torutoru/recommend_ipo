from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import maintenance, store
from .config import get_settings
from .routers import collect, health, holdings, ipos, scoring_config


def create_app() -> FastAPI:
    settings = get_settings()
    # 테이블 생성 보장 — 라우터 핸들러가 store.last_collected_at() 등을 안전히 호출.
    # 지시 #45 ①: parse_warnings 의 crtfc_key 노출 마스킹까지 한 번에 수행.
    # Turso 접속 실패 등은 서비스 기동을 막지 않도록 try/except 로 흡수(요청 처리 시 재시도됨).
    try:
        store.init_db()
        masked = store.mask_crtfc_key_in_warnings()
        if masked > 0:
            import logging
            logging.getLogger(__name__).warning(
                "parse_warnings 에서 crtfc_key 포함 행 %d건을 마스킹했습니다 (값은 로그에 출력하지 않음).",
                masked,
            )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("init_db / parse_warnings 마스킹 중 예외 발생 — 요청 시 재시도")
    # 지시 #54: 일회성 비IPO 45개 정리 (다음 릴리스에서 삭제 예정)
    maintenance.run_startup_cleanup()
    app = FastAPI(
        title="recommend_ipo backend",
        version="0.1.0",
        description="DART 공시 기반 공모주 청약 추천 API (MVP).",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],   # 지시 #51 holdings — PUT·DELETE 필요
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    app.include_router(ipos.router, prefix="/api")
    app.include_router(scoring_config.router, prefix="/api")
    app.include_router(collect.router, prefix="/api")
    app.include_router(holdings.router, prefix="/api")
    return app


app = create_app()
