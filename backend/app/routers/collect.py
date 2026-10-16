from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Response, status

from .. import collect_service
from ..config import get_settings
from ..schemas import CollectStatus

router = APIRouter(prefix="/collect")


def _enforce_collect_key(x_collect_key: Optional[str]) -> None:
    """v0.7 — 서버 수집 키가 설정돼 있으면 헤더 일치 요구. 미설정이면 보호 없음.

    상수 시간 비교(`secrets.compare_digest`)로 타이밍 공격 방지.
    """
    required = get_settings().collect_key
    if not required:
        return
    provided = x_collect_key or ""
    if not secrets.compare_digest(provided.encode("utf-8"), required.encode("utf-8")):
        raise HTTPException(status_code=401, detail="수집 키가 올바르지 않습니다.")


@router.post("", response_model=CollectStatus)
def start_collect(
    response: Response,
    x_collect_key: Optional[str] = Header(default=None, alias="X-Collect-Key"),
) -> CollectStatus:
    _enforce_collect_key(x_collect_key)
    # 샘플 모드에선 수집 불가(접근 자체를 막음)
    if get_settings().use_sample_data:
        raise HTTPException(status_code=409, detail="샘플 모드 상태에서는 수집을 실행할 수 없습니다.")

    started, state = collect_service.try_start()
    if not started:
        response.status_code = status.HTTP_409_CONFLICT
        return state
    response.status_code = status.HTTP_202_ACCEPTED
    return state


@router.get("/status", response_model=CollectStatus)
def get_status() -> CollectStatus:
    return collect_service.current_status()
