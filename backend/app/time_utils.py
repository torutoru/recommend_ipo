"""시간 유틸 — 응답에 나가는 모든 시각은 KST(+09:00) ISO 8601 로.

Render 는 UTC 로 돌기 때문에 서버 로컬시간(`datetime.now().astimezone()`)에 의존하면 "+00:00" 이 섞인다.
계약 공통 규칙(ISO 8601 +09:00) 준수를 위해 **중앙 유틸로 강제**.
"오늘 날짜"(수집 조회 범위 등)도 KST 기준으로 계산한다.

Windows 는 `tzdata` 패키지가 설치되어 있어야 `ZoneInfo("Asia/Seoul")` 가 동작한다.
"""
from __future__ import annotations

from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """현재 시각(KST 타임존 포함)."""
    return datetime.now(tz=KST)


def now_iso_kst() -> str:
    """YYYY-MM-DDTHH:MM:SS+09:00 포맷."""
    return now_kst().isoformat(timespec="seconds")


def today_kst() -> date:
    """KST 기준 '오늘'."""
    return now_kst().date()


def kst_days_ago(days: int) -> datetime:
    """KST 기준 N일 전(해당 시각)."""
    return now_kst() - timedelta(days=days)
