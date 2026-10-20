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
    pblntf_detail_ty: Optional[str] = "C001",
    last_reprt_at: str = "N",
    page_count: int = 100,
    page_no: int = 1,
    corp_code: Optional[str] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict:
    """공시 검색. 기본은 C001(지분증권 증권신고서).

    corp_code 가 주어지면 해당 종목만 조회(지시 #24).
    pblntf_detail_ty 가 None 이면 유형 필터 없이 조회(지시 #17 수정: 금감원 "정정신고서제출요구" 공지 포함).
    """
    _throttle()
    params: dict = {
        "crtfc_key": _key(),
        "bgn_de": bgn_de,
        "end_de": end_de,
        "last_reprt_at": last_reprt_at,
        "page_count": page_count,
        "page_no": page_no,
    }
    if pblntf_detail_ty:
        params["pblntf_detail_ty"] = pblntf_detail_ty
    if corp_code:
        params["corp_code"] = corp_code
    r = httpx.get(f"{DART_API}/list.json", params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get_estk_rs(
    *,
    corp_code: str,
    bgn_de: str,
    end_de: str,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict:
    """OpenDART estkRs.json — 지분증권 증권신고서 주요정보.

    응답 구조: {"status","message","group":[{"title":"모집매출총괄"|"인수인정보"|...,"list":[...]}]}
    """
    _throttle()
    r = httpx.get(
        f"{DART_API}/estkRs.json",
        params={
            "crtfc_key": _key(),
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


_ZIP_MAGIC = b"PK\x03\x04"


def download_document_zip(
    *,
    rcept_no: str,
    timeout: float = _DEFAULT_TIMEOUT,
    retries: int = 3,
    retry_backoff_sec: float = 1.5,
) -> bytes:
    """원문 ZIP 다운로드. 지시 #22: 일시 오류(014 "파일이 존재하지 않습니다"·네트워크 timeout)에 재시도.

    - OpenDART 가 간혹 ZIP 대신 XML `<result><status>014</status>…</result>` 를 돌려주는 경우가 있음.
      ZIP 매직(`PK\\x03\\x04`) 로 시작하지 않으면 "실패" 로 간주해 재시도.
    - 재시도 간격: retry_backoff_sec × 시도번호 (1.5·3·4.5 초 정도).
    - 모든 시도 실패 시 RuntimeError 전파 → 호출자(process_corp)가 "download_failed" 분기로 처리.
    """
    last_err: Optional[str] = None
    for attempt in range(1, retries + 1):
        _throttle()
        try:
            r = httpx.get(
                f"{DART_API}/document.xml",
                params={"crtfc_key": _key(), "rcept_no": rcept_no},
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.content
            if data.startswith(_ZIP_MAGIC):
                return data
            # ZIP 아님 — status 014 등 JSON/XML 응답. 재시도.
            last_err = f"응답이 ZIP 아님(attempt {attempt}, 크기 {len(data)}B)"
        except httpx.HTTPError as e:
            last_err = f"HTTP {type(e).__name__}(attempt {attempt})"
        if attempt < retries:
            import time as _time
            _time.sleep(retry_backoff_sec * attempt)
    raise RuntimeError(f"원문 다운로드 {retries}회 실패 — {last_err}")
