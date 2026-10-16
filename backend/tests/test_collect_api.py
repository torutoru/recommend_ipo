"""/api/collect 통합 테스트 — DART 호출은 monkeypatch 로 교체.

시나리오:
- 샘플 모드에서 POST → 409
- DB 모드에서 POST → 202 (RUNNING), 완료되면 SUCCEEDED
- 동일 호출 2회차 → 모든 공시가 이미 known → unchanged
- 신규 공시가 섞이면 updated/new
- 철회 종목 → withdrawn
- 전역 실패(list.json status != 000) → FAILED
- 동시 실행 → 409
- 수집 키 설정 시 X-Collect-Key 누락 → 401, 올바른 키 → 202
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import collect_service, dart_client, store
from app.config import get_settings
from app.main import create_app


# ---------- 공통 fixture ----------

@pytest.fixture(autouse=True)
def _reset_collect_state():
    """각 테스트 전에 collect_service 상태(IDLE) + Lock 리셋.

    sqlite_path 는 conftest 의 `_force_tmp_sqlite_path` 가 이미 tmp 로 돌려 둠.
    """
    store.init_db()
    collect_service._reset_for_tests()
    yield


@pytest.fixture
def db_mode():
    """use_sample_data=False (수집 API 가능)."""
    s = get_settings()
    orig = s.use_sample_data
    s.use_sample_data = False
    yield
    s.use_sample_data = orig


@pytest.fixture
def client(db_mode) -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def sample_client() -> TestClient:
    """use_sample_data=True 유지."""
    return TestClient(create_app())


# ---------- 작은 유틸: 가짜 공시 메타 + 가짜 ZIP ----------

def _disc(rcept_no: str, report_nm: str, corp_code: str, corp_name: str,
          rcept_dt: str = "20261012", corp_cls: str = "E", stock_code: str = "") -> dict:
    return {
        "rcept_no": rcept_no,
        "report_nm": report_nm,
        "corp_code": corp_code,
        "corp_name": corp_name,
        "rcept_dt": rcept_dt,
        "corp_cls": corp_cls,
        "stock_code": stock_code,
        "flr_nm": corp_name,
        "rm": "",
    }


def _list_resp(items: list[dict]) -> dict:
    return {"status": "000", "message": "정상", "page_no": 1, "page_count": len(items),
            "total_count": len(items), "total_page": 1, "list": items}


def _zip_bytes(xml_text: str) -> bytes:
    """단일 XML 을 담은 ZIP 바이트."""
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("doc.xml", xml_text)
    return bio.getvalue()


_MIN_XML = """<?xml version="1.0" encoding="utf-8"?>
<DOC>
<P>공모희망가액 범위(10,000원 ~ 12,000원)</P>
<P>확정공모가액 12,000원</P>
<P>본 공시 접수일 2026-10-12</P>
<TR><TD>경쟁률</TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>4</TD><TD>5</TD><TD>6</TD><TD>7</TD><TD>8</TD><TD>9</TD><TD>1200.00</TD></TR>
<TR><TD>수량</TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>4</TD><TD>5</TD><TD>6</TD><TD>7</TD><TD>8</TD><TD>9</TD><TD>500000</TD></TR>
<P>청약기간: 2026년 10월 20일 ~ 2026년 10월 21일</P>
<P>회사는 코스닥시장에 상장합니다.</P>
</DOC>
"""


def _mock_dart(monkeypatch, *, list_items: list[dict], zip_map: dict[str, bytes] | None = None,
               list_status_err: str | None = None) -> None:
    """dart_client.list_disclosures / download_document_zip 교체."""
    zip_map = zip_map or {}

    def fake_list(**kw):
        if list_status_err is not None:
            return {"status": list_status_err, "message": "mock 에러", "list": []}
        return _list_resp(list_items)

    def fake_download(*, rcept_no, timeout=20.0):
        if rcept_no in zip_map:
            return zip_map[rcept_no]
        return _zip_bytes(_MIN_XML)

    monkeypatch.setattr(dart_client, "list_disclosures", fake_list)
    monkeypatch.setattr(dart_client, "download_document_zip", fake_download)


def _wait_done(client: TestClient, timeout: float = 5.0) -> dict:
    """RUNNING 이면 짧게 폴링. 완료되면 상태 dict 반환."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = client.get("/api/collect/status").json()
        if s["status"] in ("SUCCEEDED", "FAILED", "IDLE"):
            return s
        time.sleep(0.05)
    raise AssertionError(f"수집이 {timeout}s 안에 완료되지 않음")


# ---------- 테스트 ----------

def test_sample_mode_rejects_collect(sample_client):
    r = sample_client.post("/api/collect")
    assert r.status_code == 409
    assert "샘플 모드" in r.json()["detail"]


def test_initial_collect_new_ipo(client, monkeypatch):
    items = [_disc("20261012000308", "[발행조건확정]증권신고서(지분증권)",
                   "00534729", "디티에스")]
    _mock_dart(monkeypatch, list_items=items)

    r = client.post("/api/collect")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "RUNNING"

    s = _wait_done(client)
    assert s["status"] == "SUCCEEDED"
    assert s["summary"]["new_count"] == 1
    assert s["summary"]["updated_count"] == 0
    assert s["last_collected_at"] is not None

    # 수집된 종목이 /api/ipos 로 보여야 함
    ipos = client.get("/api/ipos").json()["items"]
    assert any(it["id"] == "00534729" for it in ipos)


def test_second_call_reports_unchanged(client, monkeypatch):
    items = [_disc("20261012000308", "[발행조건확정]증권신고서(지분증권)",
                   "00534729", "디티에스")]
    _mock_dart(monkeypatch, list_items=items)

    client.post("/api/collect")
    _wait_done(client)
    # 2회차 — 같은 공시만 → unchanged
    client.post("/api/collect")
    s = _wait_done(client)
    assert s["status"] == "SUCCEEDED"
    assert s["summary"]["unchanged_count"] == 1
    assert s["summary"]["new_count"] == 0
    assert s["summary"]["updated_count"] == 0


def test_new_disclosure_triggers_update(client, monkeypatch):
    # 1회차: 최초 증권신고서
    first = [_disc("20261012000308", "증권신고서(지분증권)", "00534729", "디티에스")]
    _mock_dart(monkeypatch, list_items=first)
    client.post("/api/collect")
    _wait_done(client)

    # 2회차: 발행조건확정 추가 공시 — 같은 종목에 새 문서
    second = first + [_disc("20261024000022", "[발행조건확정]증권신고서(지분증권)",
                            "00534729", "디티에스", rcept_dt="20261024")]
    _mock_dart(monkeypatch, list_items=second)
    client.post("/api/collect")
    s = _wait_done(client)
    assert s["summary"]["updated_count"] == 1
    assert s["summary"]["unchanged_count"] == 0


def test_withdrawn_disclosure_excludes_corp(client, monkeypatch):
    # 1회차: 신고서로 수집
    items = [_disc("20261012000308", "[발행조건확정]증권신고서(지분증권)",
                   "00534729", "디티에스")]
    _mock_dart(monkeypatch, list_items=items)
    client.post("/api/collect")
    _wait_done(client)
    ids_before = {it["id"] for it in client.get("/api/ipos").json()["items"]}
    assert "00534729" in ids_before

    # 2회차: 철회신고서 추가
    items2 = items + [_disc("20261020000099", "철회신고서", "00534729", "디티에스",
                            rcept_dt="20261020")]
    _mock_dart(monkeypatch, list_items=items2)
    client.post("/api/collect")
    s = _wait_done(client)
    assert s["summary"]["withdrawn_count"] == 1

    # 목록에서 사라져야 함
    ids_after = {it["id"] for it in client.get("/api/ipos").json()["items"]}
    assert "00534729" not in ids_after
    # 상세도 404
    assert client.get("/api/ipos/00534729").status_code == 404


def test_list_api_failure_marks_failed(client, monkeypatch):
    _mock_dart(monkeypatch, list_items=[], list_status_err="010")
    client.post("/api/collect")
    s = _wait_done(client)
    assert s["status"] == "FAILED"
    assert s["error"] and "OpenDART" in s["error"]


def test_concurrent_call_returns_409(client, monkeypatch):
    """시작 중인 상태를 유지하기 위해 download 를 느리게 만듦."""
    items = [_disc("20261012000308", "[발행조건확정]증권신고서(지분증권)",
                   "00534729", "디티에스")]
    _mock_dart(monkeypatch, list_items=items)

    def slow_download(*, rcept_no, timeout=20.0):
        time.sleep(0.3)
        return _zip_bytes(_MIN_XML)
    monkeypatch.setattr(dart_client, "download_document_zip", slow_download)

    r1 = client.post("/api/collect")
    assert r1.status_code == 202
    r2 = client.post("/api/collect")
    assert r2.status_code == 409
    assert r2.json()["status"] == "RUNNING"
    _wait_done(client)   # cleanup


def test_collect_key_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "collect_key", "secret-xyz")
    items = [_disc("20261012000308", "[발행조건확정]증권신고서(지분증권)",
                   "00534729", "디티에스")]
    _mock_dart(monkeypatch, list_items=items)

    # 키 없음 → 401
    r = client.post("/api/collect")
    assert r.status_code == 401
    assert "수집 키" in r.json()["detail"]

    # 틀린 키 → 401
    r2 = client.post("/api/collect", headers={"X-Collect-Key": "wrong"})
    assert r2.status_code == 401

    # 올바른 키 → 202
    r3 = client.post("/api/collect", headers={"X-Collect-Key": "secret-xyz"})
    assert r3.status_code == 202
    _wait_done(client)


def test_status_does_not_require_collect_key(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "collect_key", "secret-xyz")
    r = client.get("/api/collect/status")
    assert r.status_code == 200


def test_idle_status_before_any_run(client):
    r = client.get("/api/collect/status")
    assert r.status_code == 200
    assert r.json()["status"] == "IDLE"
