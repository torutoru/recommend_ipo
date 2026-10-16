"""OpenDART 호출 래퍼.

- 키는 Settings.dart_cert_key 에서만 읽는다(응답·로그에 노출 금지).
- 호출 간격을 두어 과도한 트래픽 방지.
- 캐시는 collect.py 가 책임, 여기선 단순 호출.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from .config import get_settings


DART_API = "https://opendart.fss.or.kr/api"
_DEFAULT_TIMEOUT = 20.0
_MIN_INTERVAL_SEC = 0.4         # 호출 간 최소 간격

_last_called_at: float = 0.0


def _throttle() -> None:
    global _last_called_at
    now = time.monotonic()
    wait = (_last_called_at + _MIN_INTERVAL_SEC) - now
    if wait > 0:
        time.sleep(wait)
    _last_called_at = time.monotonic()


def _key() -> str:
    key = get_settings().dart_cert_key
    if not key:
        raise RuntimeError(
            "DART_CERT_KEY 가 설정되지 않았습니다. backend/.env.local 에 변수를 넣으세요."
        )
    return key


def list_disclosures(
    *,
    bgn_de: str,
    end_de: str,
    pblntf_detail_ty: str = "C001",
    last_reprt_at: str = "N",
    page_count: int = 100,
    page_no: int = 1,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict:
    """공시 검색. 기본은 C001(지분증권 증권신고서)."""
    _throttle()
    params = {
        "crtfc_key": _key(),
        "bgn_de": bgn_de,
        "end_de": end_de,
        "pblntf_detail_ty": pblntf_detail_ty,
        "last_reprt_at": last_reprt_at,
        "page_count": page_count,
        "page_no": page_no,
    }
    r = httpx.get(f"{DART_API}/list.json", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def download_document_zip(
    *,
    rcept_no: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> bytes:
    """원문 ZIP 다운로드. ZIP 바이트 그대로 반환."""
    _throttle()
    r = httpx.get(
        f"{DART_API}/document.xml",
        params={"crtfc_key": _key(), "rcept_no": rcept_no},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.content
