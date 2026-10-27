"""일회성 정리 코드 — 지시 #54 (requirements 26장).

v33 (10/27 10:13 운영 수집) 에서 증분 조회 유형 필터가 풀려 유입된 **비IPO 45개 종목**을
삭제한다. pm 이 10/26 스냅샷에 없던 종목 중 청약일·밴드가 모두 null 인 종목을 전수 확인한
목록(`.claude/co-work/daily-check/junk45.json`) 을 **corp_code 고정 리스트** 로 하드코딩.

운영 보장:
- 서버 기동 시(`app/main.py:create_app()`) 1회 호출. 멱등 — 이미 없으면 0건.
- 영향 테이블: `ipos`, `sources`, `parse_warnings`. **holdings 는 절대 건드리지 않음**.
- v34 로직은 신규 corp 를 **C001 공시** 로만 발견 → 이 corp 들이 C001 공시 없으면 재유입 없음.

다음 릴리스에서 이 모듈과 호출을 삭제한다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from . import store


_JUNK45_CORP_CODES: tuple[str, ...] = (
    # 지시 #54 pm 확정 — `.claude/co-work/daily-check/junk45.json` 10/27 스냅샷
    "00251400", "00260514", "00120191", "00324548", "00326272",
    "00405463", "01196881", "00453804", "00516468", "00695394",
    "00241412", "00267331", "00260453", "00188380", "00380942",
    "00796471", "00222295", "00382001", "00113465", "00684918",
    "00844936", "00160144", "00243553", "02053398", "00241388",
    "00275251", "00148665", "01396612", "01105825", "00908261",
    "02053389", "00631475", "00393636", "01511521", "00958822",
    "01042623", "01701531", "01801646", "01760118", "00267526",
    "00170460", "00222374", "00461609", "00243395", "00229058",
)


def cleanup_junk_corps(path: Optional[Path] = None) -> int:
    """지시 #54: 비IPO 45개 corp 삭제.

    삭제 테이블: ipos, sources, parse_warnings (holdings 는 건드리지 않음).
    반환값: 삭제된 ipos 행 수 (멱등 — 0 ~ 45).

    IN 절로 **쿼리 3번** 만 사용 (쿼리 당 45 corp 적용) — 호출당 쿼리 수 최소화.
    """
    with store.connect(path) as conn:
        # 삭제 전 ipos 매치 건수 선계산 (rowcount 가 어댑터마다 다르게 보고될 수 있음)
        placeholders = ",".join(["?"] * len(_JUNK45_CORP_CODES))
        before_row = conn.execute(
            f"SELECT COUNT(*) AS n FROM ipos WHERE corp_code IN ({placeholders})",
            _JUNK45_CORP_CODES,
        ).fetchone()
        deleted = (before_row["n"] if isinstance(before_row, dict) or hasattr(before_row, "keys")
                   else before_row[0])
        # 자식 테이블부터 (FK CASCADE 미지원 어댑터 대비)
        conn.execute(
            f"DELETE FROM parse_warnings WHERE corp_code IN ({placeholders})",
            _JUNK45_CORP_CODES,
        )
        conn.execute(
            f"DELETE FROM sources WHERE corp_code IN ({placeholders})",
            _JUNK45_CORP_CODES,
        )
        conn.execute(
            f"DELETE FROM ipos WHERE corp_code IN ({placeholders})",
            _JUNK45_CORP_CODES,
        )
    return int(deleted or 0)


def run_startup_cleanup() -> None:
    """지시 #54: 기동 시 1회 호출. 실패는 서비스 기동을 막지 않도록 흡수.

    로그: `"비IPO 정리: ipos N건 삭제"` (값 미노출, 건수만).
    """
    log = logging.getLogger(__name__)
    try:
        deleted = cleanup_junk_corps()
        log.info("비IPO 정리: ipos %d건 삭제", deleted)
    except Exception:
        log.exception("비IPO 정리 중 예외 발생 — 서비스 기동은 계속")
