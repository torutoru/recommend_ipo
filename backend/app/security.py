"""보안 유틸 — 에러·로그에서 비밀값(DART 키·Turso 토큰·내부 경로) 제거.

지시 #45 ①: DART 키가 httpx.HTTPStatusError 메시지(크rtfc_key=... URL)에서 흘러나와
parse_warnings 테이블(Turso) 과 CLI stdout 에 저장될 수 있음. 모든 외부 노출 경로를
이 모듈로 통일한다.
"""
from __future__ import annotations

import re

from .config import get_settings


_RE_CRTFC_KEY = re.compile(r"crtfc_key=[A-Za-z0-9]+")


_RE_URL = re.compile(r"https?://[^\s'\"]+")


def mask_secrets(msg: str) -> str:
    """문자열에서 알려진 비밀값과 내부 경로를 치환해 반환.

    - DART `crtfc_key` 쿼리 파라미터 (URL·httpx 예외 메시지에서 흘러나옴) → `crtfc_key=***`
    - 설정에 로드된 실제 키 값 → `***`
    - Turso DB URL/토큰 → placeholder
    - 로컬 파일 경로 → `<path>`
    - 길이 상한 300자
    """
    s = get_settings()
    # 1) crtfc_key 쿼리 파라미터는 설정 유무와 무관하게 패턴으로 마스킹 (가장 먼저)
    msg = _RE_CRTFC_KEY.sub("crtfc_key=***", msg)
    # 2) 설정 값이 직접 노출된 경우도 치환
    if s.dart_cert_key:
        msg = msg.replace(s.dart_cert_key, "***")
    if s.collect_key:
        msg = msg.replace(s.collect_key, "***")
    if s.turso_database_url:
        msg = msg.replace(s.turso_database_url, "<turso-url>")
    if s.turso_auth_token:
        msg = msg.replace(s.turso_auth_token, "<turso-token>")
    # 3) 로컬 파일 경로 — URL(http://...) 과 충돌하지 않도록 URL 을 임시 placeholder 로 보호
    placeholders: list[str] = []

    def _save_url(m: "re.Match") -> str:
        placeholders.append(m.group(0))
        return f"\x00URL{len(placeholders) - 1}\x00"

    msg = _RE_URL.sub(_save_url, msg)
    msg = re.sub(r"[A-Za-z]:[\\/][^\s'\"]+", "<path>", msg)
    msg = re.sub(r"/[^\s'\"]*/[^\s'\"]+", "<path>", msg)
    for i, u in enumerate(placeholders):
        msg = msg.replace(f"\x00URL{i}\x00", u)
    return msg[:300]


def mask_exception(e: BaseException) -> str:
    """예외를 "Type: message" 포맷으로 변환 후 mask_secrets 적용."""
    return mask_secrets(f"{type(e).__name__}: {e}")
