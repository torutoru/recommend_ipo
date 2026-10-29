"""지시 #56 — IpoDetail.data_notes (api-contract v1.8, requirements 27장)."""
from __future__ import annotations

import pytest

from app import store
from app.repository import _detail_from_row, _data_notes_from_row


@pytest.fixture(autouse=True)
def _init(tmp_path, monkeypatch):
    store.init_db()
    yield


def _upsert(conn, corp_code: str, corp_name: str, report_rcept_no: str) -> None:
    store.upsert_ipo(
        conn,
        corp_code=corp_code, corp_name=corp_name, market="KOSDAQ",
        subscription_start=None, subscription_end=None, listing_date=None,
        band_low=None, band_high=None, final_price=None, price_position=None,
        competition_rate=None, competition_rate_type=None,
        demand_quantity=None, demand_amount_krw=None,
        lockup_ratio=None, lockup_ratio_basis=None,
        tradable_ratio=None, old_share_ratio=None,
        new_share_count=None, old_share_count=None,
        total_offering_count=None, offering_amount_krw=None,
        report_rcept_no=report_rcept_no, parser_version="v36",
        price_confirm_date=None,
        demand_forecast_start=None, demand_forecast_end=None,
        correction_requested_at=None, correction_amended_at=None,
        underwriters_json=None,
    )


def test_56_data_notes_attachment_only_newer_than_core():
    """core 보다 접수 순서상 뒤인 [첨부정정] 이 sources 에 있으면 data_notes 1건."""
    with store.connect() as conn:
        _upsert(conn, "01950720", "제논", report_rcept_no="20261026000001")
        store.replace_sources(conn, "01950720", [
            {"doc_type": "REGISTRATION_AMENDED",
             "rcept_no": "20261026000001", "rcept_dt": "2026-10-26",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261026000001",
             "report_nm": "[기재정정]증권신고서(지분증권)"},
            {"doc_type": "REGISTRATION_AMENDED",
             "rcept_no": "20261027000367", "rcept_dt": "2026-10-27",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261027000367",
             "report_nm": "[첨부정정]증권신고서(지분증권)"},
        ])
    row = store.get_ipo("01950720")
    detail = _detail_from_row(row)
    assert len(detail.data_notes) == 1
    note = detail.data_notes[0]
    assert "[첨부정정]" in note
    assert "10월 27일" in note
    assert "10월 26일" in note
    assert "[기재정정]" in note
    # 비밀값·URL 없음
    assert "https://" not in note
    assert "rcpNo=" not in note


def test_57_data_notes_same_day_attachment_newer_by_rcept_no():
    """지시 #57: 제논 실데이터 — core 와 [첨부정정] 이 같은 날(10/26) 이고 접수 순서가 뒤면 안내."""
    with store.connect() as conn:
        _upsert(conn, "01950720", "제논", report_rcept_no="20261026000001")
        store.replace_sources(conn, "01950720", [
            {"doc_type": "REGISTRATION_AMENDED",
             "rcept_no": "20261026000001", "rcept_dt": "2026-10-26",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261026000001",
             "report_nm": "[기재정정]증권신고서(지분증권)"},
            {"doc_type": "REGISTRATION_AMENDED",
             "rcept_no": "20261026000367", "rcept_dt": "2026-10-26",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261026000367",
             "report_nm": "[첨부정정]증권신고서(지분증권)"},
        ])
    row = store.get_ipo("01950720")
    detail = _detail_from_row(row)
    assert len(detail.data_notes) == 1
    note = detail.data_notes[0]
    # 제논 실데이터 형태: "10월 26일 [첨부정정] 증권신고서는 본문 원문이 없어 10월 26일 [기재정정] 공시 기준으로 표시합니다."
    assert "10월 26일 [첨부정정]" in note
    assert "10월 26일 [기재정정] 공시" in note
    assert "본문 원문이 없어" in note


def test_57_data_notes_fallback_label_when_core_report_nm_missing():
    """core 의 report_nm 에 [...] 접두가 없으면 '공시' 로 폴백."""
    with store.connect() as conn:
        _upsert(conn, "99999999", "테스트", report_rcept_no="20261026000001")
        store.replace_sources(conn, "99999999", [
            {"doc_type": "REGISTRATION_AMENDED",
             "rcept_no": "20261026000001", "rcept_dt": "2026-10-26",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261026000001",
             "report_nm": "증권신고서(지분증권)"},   # 접두 없음
            {"doc_type": "REGISTRATION_AMENDED",
             "rcept_no": "20261026000367", "rcept_dt": "2026-10-26",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261026000367",
             "report_nm": "[첨부정정]증권신고서(지분증권)"},
        ])
    row = store.get_ipo("99999999")
    detail = _detail_from_row(row)
    assert len(detail.data_notes) == 1
    note = detail.data_notes[0]
    # 접두 라벨 없으면 "공시" 가 두 번 반복되지 않도록 — "10월 26일  공시" 형태 (라벨 빈 문자열)
    assert "10월 26일" in note
    assert "본문 원문이 없어" in note
    assert "공시 기준으로 표시합니다" in note


def test_56_data_notes_empty_when_no_attachment():
    with store.connect() as conn:
        _upsert(conn, "99999999", "테스트", report_rcept_no="20261020000001")
        store.replace_sources(conn, "99999999", [
            {"doc_type": "REGISTRATION_AMENDED",
             "rcept_no": "20261020000001", "rcept_dt": "2026-10-20",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261020000001",
             "report_nm": "[기재정정]증권신고서(지분증권)"},
        ])
    row = store.get_ipo("99999999")
    detail = _detail_from_row(row)
    assert detail.data_notes == []


def test_56_data_notes_attachment_older_than_core_no_note():
    """[첨부정정] 이 core 보다 접수 순서상 앞이면 data_notes 생성 안 함."""
    with store.connect() as conn:
        _upsert(conn, "99999999", "테스트", report_rcept_no="20261026000001")
        store.replace_sources(conn, "99999999", [
            {"doc_type": "REGISTRATION_AMENDED",
             "rcept_no": "20261020000367", "rcept_dt": "2026-10-20",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261020000367",
             "report_nm": "[첨부정정]증권신고서(지분증권)"},
            {"doc_type": "REGISTRATION_AMENDED",
             "rcept_no": "20261026000001", "rcept_dt": "2026-10-26",
             "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261026000001",
             "report_nm": "[기재정정]증권신고서(지분증권)"},
        ])
    row = store.get_ipo("99999999")
    detail = _detail_from_row(row)
    assert detail.data_notes == []


def test_56_data_notes_from_row_handles_missing_sources():
    assert _data_notes_from_row({"sources": [], "report_rcept_no": None}) == []
    assert _data_notes_from_row({}) == []


def test_56_dart_client_recognizes_014_as_file_missing():
    """지시 #56: 다운로드 014 응답을 "DART 014 파일 없음" 문구로 식별하는 로직 존재 검증."""
    from app import dart_client
    import inspect
    src = inspect.getsource(dart_client.download_document_zip)
    assert "DART 014 파일 없음" in src
    assert "014" in src


# ---- 지시 #58 (옵토닉스) — 신주/구주 명시 없을 때 추정 안내 ----

def test_58_data_notes_offering_structure_inferred():
    """parser 가 공모 구성 추정 warning 을 기록하면 data_notes 에 안내 1건."""
    row = {
        "sources": [],
        "report_rcept_no": "20261029000504",
        "warnings": ["공모 구성 추정 — 모집방법 '일반공모' 기준 전량 신주 처리"],
    }
    notes = _data_notes_from_row(row)
    assert len(notes) == 1
    note = notes[0]
    assert "신주" in note and "구주" in note
    assert "일반공모" in note
    # 비밀값/URL 없음
    assert "https://" not in note


def test_58_data_notes_no_inference_note_when_no_warning():
    row = {"sources": [], "report_rcept_no": "X", "warnings": []}
    assert _data_notes_from_row(row) == []


def test_58_data_notes_handles_missing_warnings_key():
    """row 에 'warnings' 키가 없어도 KeyError 없이 통과."""
    row = {"sources": [], "report_rcept_no": "X"}
    assert _data_notes_from_row(row) == []
