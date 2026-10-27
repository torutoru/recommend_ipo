"""지시 #54 — 비IPO 45개 일회성 정리 테스트.

커버:
- 대상 corp 는 ipos/sources/parse_warnings 에서 삭제
- 정상 corp 는 유지
- holdings 는 어떤 경우에도 건드리지 않음
- 멱등 (두 번 호출해도 안전)
- 로그 출력 (값 미노출, 건수만)
"""
from __future__ import annotations

import logging

import pytest

from app import maintenance, store


@pytest.fixture(autouse=True)
def _init(tmp_path, monkeypatch):
    store.init_db()
    yield


def _upsert(conn, corp_code: str, corp_name: str) -> None:
    store.upsert_ipo(
        conn,
        corp_code=corp_code, corp_name=corp_name, market=None,
        subscription_start=None, subscription_end=None, listing_date=None,
        band_low=None, band_high=None, final_price=None, price_position=None,
        competition_rate=None, competition_rate_type=None,
        demand_quantity=None, demand_amount_krw=None,
        lockup_ratio=None, lockup_ratio_basis=None,
        tradable_ratio=None, old_share_ratio=None,
        new_share_count=None, old_share_count=None,
        total_offering_count=None, offering_amount_krw=None,
        report_rcept_no=None, parser_version="v34",
        price_confirm_date=None,
        demand_forecast_start=None, demand_forecast_end=None,
        correction_requested_at=None, correction_amended_at=None,
        underwriters_json=None,
    )


def test_54_deletes_junk_corps_and_preserves_others():
    """junk45 대상 2건 + 정상 1건 + holdings 1건 → 정리 후 대상만 삭제."""
    with store.connect() as conn:
        # 삭제 대상 2건
        _upsert(conn, "00251400", "BNK투자증권")
        _upsert(conn, "00120191", "키움투자자산운용")
        # 정상 IPO 1건
        _upsert(conn, "01378005", "이에스티")
        # sources·warnings 도 추가
        store.replace_sources(conn, "00251400", [
            {"doc_type": "PROSPECTUS", "rcept_no": "20261027000001",
             "rcept_dt": "2026-10-27",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261027000001"}
        ])
        store.replace_warnings(conn, "00251400", ["펀드 신고서"])
        # holdings 1건 (삭제 대상 corp_code 와는 무관)
        from app.time_utils import now_iso_kst
        now = now_iso_kst()
        conn.execute(
            "INSERT INTO holdings (corp_code, shares, price, memo, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("01378005", 10, 12400, "", now, now),
        )

    deleted = maintenance.cleanup_junk_corps()
    assert deleted == 2

    with store.connect() as conn:
        # 대상 2건 전부 삭제
        assert conn.execute(
            "SELECT 1 FROM ipos WHERE corp_code = '00251400'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM ipos WHERE corp_code = '00120191'"
        ).fetchone() is None
        # 자식 테이블도 비어 있음
        assert conn.execute(
            "SELECT 1 FROM sources WHERE corp_code = '00251400'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM parse_warnings WHERE corp_code = '00251400'"
        ).fetchone() is None
        # 정상 corp 유지
        assert conn.execute(
            "SELECT 1 FROM ipos WHERE corp_code = '01378005'"
        ).fetchone() is not None
        # holdings 유지 (절대 건드리지 않음)
        assert conn.execute(
            "SELECT shares FROM holdings WHERE corp_code = '01378005'"
        ).fetchone()["shares"] == 10


def test_54_idempotent():
    """두 번 호출해도 안전 — 두 번째는 0건 반환."""
    with store.connect() as conn:
        _upsert(conn, "00251400", "BNK투자증권")
    assert maintenance.cleanup_junk_corps() == 1
    assert maintenance.cleanup_junk_corps() == 0


def test_54_empty_db():
    """빈 DB — 0건 반환, 예외 없음."""
    assert maintenance.cleanup_junk_corps() == 0


def test_54_startup_cleanup_logs_count(caplog):
    """`run_startup_cleanup` 가 건수를 로그로 남긴다 (값 미노출)."""
    with store.connect() as conn:
        _upsert(conn, "00251400", "BNK투자증권")
    caplog.set_level(logging.INFO, logger="app.maintenance")
    maintenance.run_startup_cleanup()
    assert "비IPO 정리" in caplog.text
    assert "1" in caplog.text   # 건수 1
    # corp_code / corp_name 값은 로그에 포함되지 않음
    assert "00251400" not in caplog.text
    assert "BNK" not in caplog.text


def test_54_holdings_table_never_touched_even_if_holding_corp_in_junk_list():
    """만약 사용자가 junk 목록의 corp 에 holding 을 등록했어도 holdings 는 건드리지 않음.

    (실제론 maintenance 가 corp_code 를 기준으로 ipos/sources/parse_warnings 만 건드리므로
    holdings 는 자연히 보존되지만, 명시적으로 fence 테스트.)
    """
    with store.connect() as conn:
        _upsert(conn, "00251400", "BNK투자증권")
        from app.time_utils import now_iso_kst
        now = now_iso_kst()
        conn.execute(
            "INSERT INTO holdings (corp_code, shares, price, memo, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("00251400", 5, 10000, "실수 입력", now, now),
        )
    maintenance.cleanup_junk_corps()
    # holdings 는 그대로
    with store.connect() as conn:
        row = conn.execute(
            "SELECT shares FROM holdings WHERE corp_code = '00251400'"
        ).fetchone()
        assert row is not None
        assert row["shares"] == 5
