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
def _reset_collect_state(tmp_path, monkeypatch):
    """각 테스트 전에 collect_service 상태(IDLE) + Lock 리셋.

    sqlite_path 는 conftest 의 `_force_tmp_sqlite_path` 가 이미 tmp 로 돌려 둠.
    CACHE_DIR 도 tmp 로 돌려 운영 캐시 영향 격리 (지시 #22 테스트 안정화).
    """
    from app import collect as _collect
    monkeypatch.setattr(_collect, "CACHE_DIR", tmp_path / "cache_default")
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


def _wait_done(client: TestClient, timeout: float = 15.0) -> dict:
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


def test_download_failure_does_not_overwrite_existing(client, monkeypatch, tmp_path):
    """지시 #22 핵심 — 다운로드 실패해도 기존 종목 데이터를 null 로 덮지 않음.

    1회차: 정상 수집 → ipos 1건, 핵심 지표 set
    2회차: ZIP 다운로드가 모두 실패 → "download_failed" 로 분류 → upsert·parser_version 갱신 skip
    → 기존 competition_rate / price_position 가 **그대로 유지** 되어야 함
    """
    from app import collect as collect_mod, dart_client
    # 캐시 디렉토리를 tmp 로 돌려 2회차에서 "캐시 없음" 상태 재현
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    items = [_disc("20261012000308", "[발행조건확정]증권신고서(지분증권)",
                   "00534729", "디티에스")]

    # 1회차: 정상
    _mock_dart(monkeypatch, list_items=items)
    client.post("/api/collect")
    _wait_done(client)
    before = client.get("/api/ipos/00534729").json()
    assert before["indicators"]["competition_rate"] is not None

    # 2회차: parser_version 을 강제로 bump → 저장된 "v3" != "forced-v99" → stale → process_corp 재호출
    monkeypatch.setattr(collect_mod, "PARSER_VERSION", "forced-v99")
    # 그 상태에서 download 는 모두 실패 (RuntimeError)
    def failing_download(*, rcept_no, timeout=20.0):
        raise RuntimeError("fake network down")
    monkeypatch.setattr(dart_client, "download_document_zip", failing_download)
    # 캐시 비움
    import shutil
    if (tmp_path / "cache").exists():
        shutil.rmtree(tmp_path / "cache")

    client.post("/api/collect")
    s = _wait_done(client)

    # SUCCEEDED (전체 작업은 성공) 지만 failed_count >=1
    assert s["summary"]["failed_count"] >= 1
    assert len(s["failures"]) >= 1
    assert s["failures"][0]["corp_code"] == "00534729"

    # 핵심: 기존 데이터가 **보존** 되어야 함
    after = client.get("/api/ipos/00534729").json()
    assert after["indicators"]["competition_rate"] == before["indicators"]["competition_rate"]
    assert after["indicators"]["price_position"] == before["indicators"]["price_position"]
    assert after["final_price"] == before["final_price"]


def test_failures_reason_sanitized_of_secrets(client, monkeypatch, tmp_path):
    """실패 사유에 TURSO/DART 토큰·내부 경로 노출 금지."""
    from app import collect as collect_mod, dart_client
    from app.config import get_settings
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")
    s = get_settings()
    s.dart_cert_key = "SUPERSECRETDARTKEY"

    items = [_disc("20261012000308", "[발행조건확정]증권신고서(지분증권)",
                   "00534729", "디티에스")]
    _mock_dart(monkeypatch, list_items=items)

    # 1회차: 정상 수집 — 저장된 종목 하나 생성
    client.post("/api/collect")
    _wait_done(client)

    # 2회차: parser_version bump + 캐시 비움 (Render 재시작 시나리오) + download 실패에 시크릿 포함
    monkeypatch.setattr(collect_mod, "PARSER_VERSION", "forced-v99")
    import shutil
    if collect_mod.CACHE_DIR.exists():
        shutil.rmtree(collect_mod.CACHE_DIR)

    def leaky_download(*, rcept_no, timeout=20.0):
        raise RuntimeError(f"error with key=SUPERSECRETDARTKEY at C:/workspace/recommend_ipo/secret.txt")
    monkeypatch.setattr(dart_client, "download_document_zip", leaky_download)

    client.post("/api/collect")
    done = _wait_done(client)
    assert done["failures"]
    reason = done["failures"][0]["reason"]
    assert "SUPERSECRETDARTKEY" not in reason
    assert "C:/workspace" not in reason


def test_stale_corp_full_history_prefers_final_release(client, monkeypatch, tmp_path):
    """지시 #24: stale 재파싱 시 증분 범위에 ISSUANCE_REPORT 만 들어와도
    corp_code 로 전체 이력을 다시 받아와 발행조건확정을 정본으로 선정하고 지표를 보존.
    """
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    final_rcept = "20260301000011"
    issuance_rcept = "20261015000055"
    final_disc = _disc(final_rcept, "[발행조건확정]증권신고서(지분증권)",
                       "00534729", "디티에스", rcept_dt="20260301")
    issuance_disc = _disc(issuance_rcept, "증권발행실적보고서",
                          "00534729", "디티에스", rcept_dt="20261015")

    # 1회차 — 발행조건확정만 보여 정상 수집
    monkeypatch.setattr(_dc, "list_disclosures", lambda **kw: _list_resp([final_disc]))
    monkeypatch.setattr(_dc, "download_document_zip",
                        lambda *, rcept_no, timeout=20.0: _zip_bytes(_MIN_XML))
    client.post("/api/collect")
    _wait_done(client)
    before = client.get("/api/ipos/00534729").json()
    before_rate = before["indicators"]["competition_rate"]
    assert before_rate is not None

    # 2회차 — 증분엔 ISSUANCE_REPORT 만, corp_code 조회(full history)에는 [발행조건확정 + ISSUANCE_REPORT]
    monkeypatch.setattr(collect_mod, "PARSER_VERSION", "forced-v99")

    def fake_list(**kw):
        if kw.get("corp_code"):
            return _list_resp([final_disc, issuance_disc])
        return _list_resp([issuance_disc])
    monkeypatch.setattr(_dc, "list_disclosures", fake_list)

    import shutil
    if (tmp_path / "cache").exists():
        shutil.rmtree(tmp_path / "cache")
    downloaded: list[str] = []

    def fake_download(*, rcept_no, timeout=20.0):
        downloaded.append(rcept_no)
        return _zip_bytes(_MIN_XML)
    monkeypatch.setattr(_dc, "download_document_zip", fake_download)

    client.post("/api/collect")
    s2 = _wait_done(client)
    assert s2["status"] == "SUCCEEDED"
    # 발행조건확정이 정본으로 선정되어 다운로드됨 (ISSUANCE_REPORT 아님)
    assert final_rcept in downloaded, f"다운로드 리스트: {downloaded}"

    after = client.get("/api/ipos/00534729").json()
    assert after["indicators"]["competition_rate"] == before_rate

    # sources 에 두 문서가 모두 들어가 있어야 함
    source_types = {sr["doc_type"] for sr in after["sources"]}
    assert "ISSUANCE_REPORT" in source_types
    assert "REGISTRATION_AMENDED" in source_types


def test_core_none_with_existing_preserves_metrics(client, monkeypatch, tmp_path):
    """지시 #24: 재파싱에서 ISSUANCE_REPORT 만 보이면(core=None) 다운로드 자체가 발생하지 않고 기존 지표 보존."""
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    final_rcept = "20260301000011"
    issuance_rcept = "20261015000055"
    final_disc = _disc(final_rcept, "[발행조건확정]증권신고서(지분증권)",
                       "00534729", "디티에스", rcept_dt="20260301")
    issuance_disc = _disc(issuance_rcept, "증권발행실적보고서",
                          "00534729", "디티에스", rcept_dt="20261015")

    # 1회차 — 정상 수집
    monkeypatch.setattr(_dc, "list_disclosures", lambda **kw: _list_resp([final_disc]))
    monkeypatch.setattr(_dc, "download_document_zip",
                        lambda *, rcept_no, timeout=20.0: _zip_bytes(_MIN_XML))
    client.post("/api/collect")
    _wait_done(client)
    before = client.get("/api/ipos/00534729").json()
    before_rate = before["indicators"]["competition_rate"]
    assert before_rate is not None

    # 2회차 — 증분도 full history 조회도 ISSUANCE_REPORT 만 → core=None
    monkeypatch.setattr(collect_mod, "PARSER_VERSION", "forced-v99")
    monkeypatch.setattr(_dc, "list_disclosures", lambda **kw: _list_resp([issuance_disc]))

    def should_not_download(*, rcept_no, timeout=20.0):
        raise AssertionError(f"core=None 분기면 다운로드가 발생하지 않아야 함: {rcept_no}")
    monkeypatch.setattr(_dc, "download_document_zip", should_not_download)

    import shutil
    if (tmp_path / "cache").exists():
        shutil.rmtree(tmp_path / "cache")

    client.post("/api/collect")
    s = _wait_done(client)
    assert s["status"] == "SUCCEEDED"
    # preserved → unchanged 로 계수(지시 #24)
    assert s["summary"]["unchanged_count"] >= 1
    assert s["summary"]["new_count"] == 0
    assert s["summary"]["updated_count"] == 0

    after = client.get("/api/ipos/00534729").json()
    assert after["indicators"]["competition_rate"] == before_rate
    # ISSUANCE_REPORT 가 sources 에 추가됐어야 함
    source_types = {sr["doc_type"] for sr in after["sources"]}
    assert "ISSUANCE_REPORT" in source_types


def test_issuance_report_supplements_listing_date_and_market(client, monkeypatch, tmp_path):
    """지시 #25: 발행조건확정에 listing_date/market 가 없고 ISSUANCE_REPORT 가 함께 있으면
    실적보고서를 추가 다운로드·파싱해 두 값을 보강(기존 지표는 유지)."""
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    final_rcept = "20261007000327"
    issuance_rcept = "20261015000326"
    final_disc = _disc(final_rcept, "[발행조건확정]증권신고서(지분증권)",
                       "01749559", "엠에스바이오", rcept_dt="20261007")
    issuance_disc = _disc(issuance_rcept, "증권발행실적보고서",
                          "01749559", "엠에스바이오", rcept_dt="20261015")

    # 발행조건확정 XML — 밴드·확정가·경쟁률 등은 있지만 상장일·시장 없음(의도적)
    final_xml = """<?xml version="1.0" encoding="utf-8"?>
<DOC>
<P>공모희망가액 범위(10,000원 ~ 12,000원)</P>
<P>확정공모가액 12,000원</P>
<P>본 공시 접수일 2026-10-07</P>
<P>청약기간: 2026년 10월 13일 ~ 2026년 10월 14일</P>
<TR><TD>경쟁률</TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>4</TD><TD>5</TD><TD>6</TD><TD>7</TD><TD>8</TD><TD>9</TD><TD>1096.56</TD></TR>
<TR><TD>수량</TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>4</TD><TD>5</TD><TD>6</TD><TD>7</TD><TD>8</TD><TD>9</TD><TD>500000</TD></TR>
</DOC>
"""
    # 실적보고서 XML — 상장일(매매개시일)·상장구분만
    issuance_xml = """<?xml version="1.0" encoding="utf-8"?>
<DOC>
<TABLE>
<TR><TD>상장구분</TD><TD>기업규모</TD><TD>업종구분</TD></TR>
<TR><TD>코스닥</TD><TD>중소기업</TD><TD>생명과학</TD></TR>
</TABLE>
<P>3. 상장일(매매개시일) 2026년 10월 22일 (예정)</P>
</DOC>
"""

    def fake_list(**kw):
        return _list_resp([final_disc, issuance_disc])

    def fake_download(*, rcept_no, timeout=20.0):
        if rcept_no == final_rcept:
            return _zip_bytes(final_xml)
        if rcept_no == issuance_rcept:
            return _zip_bytes(issuance_xml)
        raise AssertionError(f"예상치 못한 다운로드: {rcept_no}")

    monkeypatch.setattr(_dc, "list_disclosures", fake_list)
    monkeypatch.setattr(_dc, "download_document_zip", fake_download)

    client.post("/api/collect")
    s = _wait_done(client)
    assert s["status"] == "SUCCEEDED"
    assert s["summary"]["failed_count"] == 0

    detail = client.get("/api/ipos/01749559").json()
    assert detail["market"] == "KOSDAQ"
    assert detail["listing_date"] == "2026-10-22"
    # 경쟁률은 발행조건확정에서 그대로 유지되어야 함(실적보고서가 덮어쓰지 않음)
    assert detail["indicators"]["competition_rate"] == 1096.56
    # report_rcept_no 는 발행조건확정의 접수번호(보강이 바꾸지 않음)
    assert detail["indicators"]["report_rcept_no"] == final_rcept


def test_issuance_supplement_skipped_when_both_already_present(client, monkeypatch, tmp_path):
    """지시 #25: 발행조건확정에 이미 listing_date·market 둘 다 있으면 실적보고서 다운로드 안 함(비용 절감)."""
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    final_rcept = "20261012000308"
    issuance_rcept = "20261024000099"
    final_disc = _disc(final_rcept, "[발행조건확정]증권신고서(지분증권)",
                       "00534729", "디티에스", rcept_dt="20261012")
    issuance_disc = _disc(issuance_rcept, "증권발행실적보고서",
                          "00534729", "디티에스", rcept_dt="20261024")

    monkeypatch.setattr(_dc, "list_disclosures", lambda **kw: _list_resp([final_disc, issuance_disc]))

    # 발행조건확정 XML 에 상장일·시장 모두 포함되게 — 보강이 호출되면 안 됨
    full_xml = """<?xml version="1.0" encoding="utf-8"?>
<DOC>
<P>공모희망가액 범위(10,000원 ~ 12,000원)</P>
<P>확정공모가액 12,000원</P>
<P>본 공시 접수일 2026-10-12</P>
<P>청약기간: 2026년 10월 20일 ~ 2026년 10월 21일</P>
<P>본 공모 주식은 코스닥시장에 신규상장될 예정입니다.</P>
<P>상장예정일 2026년 10월 30일로 결정되었습니다.</P>
<TR><TD>경쟁률</TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>4</TD><TD>5</TD><TD>6</TD><TD>7</TD><TD>8</TD><TD>9</TD><TD>983.98</TD></TR>
<TR><TD>수량</TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>4</TD><TD>5</TD><TD>6</TD><TD>7</TD><TD>8</TD><TD>9</TD><TD>500000</TD></TR>
</DOC>
"""
    downloads: list[str] = []

    def fake_download(*, rcept_no, timeout=20.0):
        downloads.append(rcept_no)
        if rcept_no == final_rcept:
            return _zip_bytes(full_xml)
        raise AssertionError(f"보강이 skip 되어야 하는데 ISSUANCE_REPORT 다운로드가 호출됨: {rcept_no}")

    monkeypatch.setattr(_dc, "download_document_zip", fake_download)

    client.post("/api/collect")
    s = _wait_done(client)
    assert s["status"] == "SUCCEEDED"

    # 발행조건확정만 다운로드되고 ISSUANCE_REPORT 는 호출되지 않음
    assert final_rcept in downloads
    assert issuance_rcept not in downloads


def test_price_confirm_date_falls_back_to_final_release_rcept_dt(client, monkeypatch, tmp_path):
    """지시 #20: 본문에 '확정공고 YYYY-MM-DD' 명시가 없어도 **발행조건확정 공시의 접수일**이
    price_confirm_date 로 저장된다. 명세: '이날 [발행조건확정] 공시로 기관 데이터 공개'."""
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    final_disc = _disc("20261016000055", "[발행조건확정]증권신고서(지분증권)",
                       "01543043", "티앤이코리아", rcept_dt="20261016")
    monkeypatch.setattr(_dc, "list_disclosures", lambda **kw: _list_resp([final_disc]))
    monkeypatch.setattr(_dc, "download_document_zip",
                        lambda *, rcept_no, timeout=20.0: _zip_bytes(_MIN_XML))

    client.post("/api/collect")
    _wait_done(client)
    d = client.get("/api/ipos/01543043").json()
    # 명시 매치 없음(_MIN_XML 에 없음) → 접수일 fallback: "20261016" → "2026-10-16"
    assert d["price_confirm_date"] == "2026-10-16"


def test_price_confirm_date_prefers_parsed_explicit_over_fallback(client, monkeypatch, tmp_path):
    """지시 #20: 본문에 명시 '공모가액 확정공고 YYYY-MM-DD' 가 있으면 그걸 **우선**(접수일 fallback 보다)."""
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    final_disc = _disc("20261016000055", "[발행조건확정]증권신고서(지분증권)",
                       "01543043", "티앤이코리아", rcept_dt="20261016")

    # 본문에 명시: "공모가액 확정공고 2026년 10월 15일" (접수일 10/16 과 다르게 — 우선순위 확인)
    xml = """<?xml version="1.0" encoding="utf-8"?>
<DOC>
<P>공모희망가액 범위(10,000원 ~ 12,000원)</P>
<P>확정공모가액 12,000원</P>
<P>본 공시 접수일 2026-10-16</P>
<P>공모가액 확정공고 2026년 10월 15일</P>
<P>수요예측 기간: 2026년 10월 13일 ~ 2026년 10월 14일</P>
<P>청약기간: 2026년 10월 20일 ~ 2026년 10월 21일</P>
<TR><TD>경쟁률</TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>4</TD><TD>5</TD><TD>6</TD><TD>7</TD><TD>8</TD><TD>9</TD><TD>1200.00</TD></TR>
<TR><TD>수량</TD><TD>1</TD><TD>2</TD><TD>3</TD><TD>4</TD><TD>5</TD><TD>6</TD><TD>7</TD><TD>8</TD><TD>9</TD><TD>500000</TD></TR>
</DOC>
"""
    monkeypatch.setattr(_dc, "list_disclosures", lambda **kw: _list_resp([final_disc]))
    monkeypatch.setattr(_dc, "download_document_zip",
                        lambda *, rcept_no, timeout=20.0: _zip_bytes(xml))

    client.post("/api/collect")
    _wait_done(client)
    d = client.get("/api/ipos/01543043").json()
    # 명시 매치 우선
    assert d["price_confirm_date"] == "2026-10-15"
    assert d["demand_forecast_start"] == "2026-10-13"
    assert d["demand_forecast_end"] == "2026-10-14"


def test_fss_notice_rcept_no_detection():
    """지시 #28: 접수번호 9~10번째 '10' 이면 금감원 공지 — 다운로드/정본에서 제외."""
    from app.collect import _is_fss_notice_rcept_no
    assert _is_fss_notice_rcept_no("20260916100012") is True   # 공지
    assert _is_fss_notice_rcept_no("20260921100009") is True
    assert _is_fss_notice_rcept_no("20261012000308") is False  # 회사 신고서(디티에스)
    assert _is_fss_notice_rcept_no("20261019000150") is False  # 크리에이츠 발행조건확정
    assert _is_fss_notice_rcept_no("short") is False


def test_fss_notice_excluded_from_core_and_download(client, monkeypatch, tmp_path):
    """지시 #28: 금감원 공지 접수번호(100xxx)는 core 후보에서 제외되고 다운로드도 호출 안 됨."""
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    # 회사 신고서 + 효력발생안내(공지, 분류 안 됨 또는 공지 접수번호)
    company_doc = _disc("20260910000011", "증권신고서(지분증권)",
                        "01555555", "인텔리빅스", rcept_dt="20260910")
    # 공지(접수번호 9-10 '10')가 "증권신고서(지분증권)" 를 포함해 REGISTRATION_AMENDED 로 잘못 분류될 가능성
    fss_notice = _disc("20260916100012", "효력발생안내 (지분증권) 증권신고서(지분증권)",
                       "01555555", "인텔리빅스", rcept_dt="20260916")

    monkeypatch.setattr(_dc, "list_disclosures",
                        lambda **kw: _list_resp([company_doc, fss_notice]))

    downloaded: list[str] = []
    def fake_dl(*, rcept_no, timeout=20.0):
        downloaded.append(rcept_no)
        if rcept_no == "20260916100012":
            raise AssertionError(f"공지 접수번호 다운로드 시도됨: {rcept_no}")
        return _zip_bytes(_MIN_XML)
    monkeypatch.setattr(_dc, "download_document_zip", fake_dl)

    client.post("/api/collect")
    s = _wait_done(client)
    assert s["status"] == "SUCCEEDED"
    # 회사 신고서 접수번호만 다운로드됨
    assert "20260910000011" in downloaded
    assert "20260916100012" not in downloaded


def test_db_stale_only_corp_reprocessed(client, monkeypatch, tmp_path):
    """지시 #28: 증분 조회에는 없지만 DB 에 있고 parser_version 이 낡은 종목은 전체 이력 조회 후 재처리."""
    from app import collect as collect_mod, dart_client as _dc, store
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    # 1회차: 수집 → DB 저장 (parser_version=v9)
    first = _disc("20260901000011", "[발행조건확정]증권신고서(지분증권)",
                  "01333333", "다비오", rcept_dt="20260901")
    monkeypatch.setattr(_dc, "list_disclosures", lambda **kw: _list_resp([first]))
    monkeypatch.setattr(_dc, "download_document_zip",
                        lambda *, rcept_no, timeout=20.0: _zip_bytes(_MIN_XML))
    client.post("/api/collect")
    _wait_done(client)

    # 2회차: parser_version bump + **증분 조회에 다비오 공시 없음** (현재 활동 없음)
    monkeypatch.setattr(collect_mod, "PARSER_VERSION", "forced-v99")

    # 증분 조회는 다른 종목만 반환(다비오 공시 없음)
    def fake_list(**kw):
        if kw.get("corp_code") == "01333333":
            # corp_code 지정 전체 이력 조회에만 다비오 데이터 제공
            return _list_resp([first])
        # 증분(C001)에는 아무 공시도 없음
        return _list_resp([])
    monkeypatch.setattr(_dc, "list_disclosures", fake_list)

    import shutil
    if (tmp_path / "cache").exists():
        shutil.rmtree(tmp_path / "cache")

    client.post("/api/collect")
    s = _wait_done(client)
    assert s["status"] == "SUCCEEDED"
    # 증분 조회에 공시 없음 → 메인 for 루프는 다비오 안 보임.
    # DB stale-only 재처리 루프가 돌아 updated_count ≥ 1
    assert s["summary"]["updated_count"] >= 1
    assert s["summary"]["failed_count"] == 0


def test_correction_notice_marks_correction_davio_shape(client, monkeypatch, tmp_path):
    """지시 #17 (pm 수정): 다비오 형태 — [정정제출요구] 접두 신고서(회사 원 신고서) +
    "정정신고서제출요구( ... )" 공지 + [기재정정] 신고서(회사 재제출). 발행조건확정 없음.
    → CORRECTION, requested_at = 공지 접수일(10/06), amended_at = 기재정정 접수일(10/08)."""
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    bracket_doc = _disc("20260915000390", "[정정제출요구]증권신고서(지분증권)",
                        "01888888", "다비오", rcept_dt="20260915")   # 회사 원 신고서
    notice = _disc("20261006100034",
                   "정정신고서제출요구( 2026.09.15. 제출 증권신고서(지분증권) )",
                   "01888888", "다비오", rcept_dt="20261006")        # 금감원 공지
    amended = _disc("20261008000705", "[기재정정]증권신고서(지분증권)",
                    "01888888", "다비오", rcept_dt="20261008")

    monkeypatch.setattr(_dc, "list_disclosures",
                        lambda **kw: _list_resp([bracket_doc, notice, amended]))
    monkeypatch.setattr(_dc, "download_document_zip",
                        lambda *, rcept_no, timeout=20.0: _zip_bytes(_MIN_XML))

    client.post("/api/collect")
    _wait_done(client)
    d = client.get("/api/ipos/01888888").json()
    assert d["verdict"]["status"] == "CORRECTION"
    assert d["verdict"]["correction"]["requested_at"] == "2026-10-06"   # 공지일, not 신고서 접수일
    assert d["verdict"]["correction"]["amended_at"] == "2026-10-08"
    # 접두 '[정정제출요구]' 신고서는 **정본 후보로 유지**됨 → sources 에 REGISTRATION_AMENDED 로 포함
    source_types = {s["doc_type"] for s in d["sources"]}
    assert "REGISTRATION_AMENDED" in source_types
    assert "CORRECTION_REQUEST" in source_types


def test_correction_fallback_to_bracket_prefix_when_no_notice(client, monkeypatch, tmp_path):
    """공지 공시가 못 잡힌 경우(유캐스트 유사 상태) — fallback 로 접두 '[정정제출요구]' 신고서 접수일 사용 + warning 명시."""
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    bracket_only = _disc("20260909000378", "[정정제출요구]증권신고서(지분증권)",
                         "01777777", "유캐스트", rcept_dt="20260909")

    monkeypatch.setattr(_dc, "list_disclosures",
                        lambda **kw: _list_resp([bracket_only]))
    monkeypatch.setattr(_dc, "download_document_zip",
                        lambda *, rcept_no, timeout=20.0: _zip_bytes(_MIN_XML))

    client.post("/api/collect")
    _wait_done(client)
    d = client.get("/api/ipos/01777777").json()
    assert d["verdict"]["status"] == "CORRECTION"
    # 공지 없음 → fallback = 신고서 접수일(접두 '[정정제출요구]')
    assert d["verdict"]["correction"]["requested_at"] == "2026-09-09"
    assert d["verdict"]["correction"]["amended_at"] is None
    # 접두 신고서는 REGISTRATION_AMENDED 로 정본 후보 유지
    assert "REGISTRATION_AMENDED" in {s["doc_type"] for s in d["sources"]}


def test_correction_cleared_when_final_release_comes_after(client, monkeypatch, tmp_path):
    """지시 #17: 정정요구 이후 발행조건확정이 들어오면 CORRECTION 아님(정상 PASS/REJECT 평가)."""
    from app import collect as collect_mod, dart_client as _dc
    monkeypatch.setattr(collect_mod, "CACHE_DIR", tmp_path / "cache")

    bracket_doc = _disc("20260915000390", "[정정제출요구]증권신고서(지분증권)",
                        "01999999", "다비오", rcept_dt="20260915")
    notice = _disc("20261006100034", "정정신고서제출요구( 2026.09.15. 제출 증권신고서(지분증권) )",
                   "01999999", "다비오", rcept_dt="20261006")
    final = _disc("20261010000044", "[발행조건확정]증권신고서(지분증권)",
                  "01999999", "다비오", rcept_dt="20261010")

    monkeypatch.setattr(_dc, "list_disclosures",
                        lambda **kw: _list_resp([bracket_doc, notice, final]))
    monkeypatch.setattr(_dc, "download_document_zip",
                        lambda *, rcept_no, timeout=20.0: _zip_bytes(_MIN_XML))

    client.post("/api/collect")
    _wait_done(client)
    d = client.get("/api/ipos/01999999").json()
    assert d["verdict"]["status"] != "CORRECTION"
    assert d["verdict"]["correction"] is None


def test_list_disclosures_passes_corp_code(monkeypatch):
    """지시 #24: dart_client.list_disclosures(corp_code=...) 가 OpenDART 파라미터에 corp_code 를 그대로 전달,
    기본 호출에는 포함되지 않는다.
    """
    import httpx as _httpx
    from app import dart_client as _dc
    from app.config import get_settings as _gs

    _gs().dart_cert_key = "testkey"
    captured: dict = {}

    class _Resp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"status": "013", "list": []}

    def fake_get(url, params=None, timeout=20.0):
        captured["params"] = dict(params or {})
        return _Resp()

    monkeypatch.setattr(_httpx, "get", fake_get)

    _dc.list_disclosures(bgn_de="20260101", end_de="20261001", corp_code="00534729")
    assert captured["params"].get("corp_code") == "00534729"

    _dc.list_disclosures(bgn_de="20260101", end_de="20261001")
    assert "corp_code" not in captured["params"]


def test_persistence_check_failed_marks_failed(client, monkeypatch):
    """지시 #14 — 수집은 성공했는데 DB 에 쓰기가 안 됐으면 FAILED.

    monkeypatch 로 upsert_ipo 를 no-op 으로 만들어 "쓰기 손실" 상황을 재현.
    """
    from app import collect as collect_mod
    from app import store

    items = [_disc("20261012000308", "[발행조건확정]증권신고서(지분증권)",
                   "00534729", "디티에스")]
    _mock_dart(monkeypatch, list_items=items)

    original_process = collect_mod.process_corp

    def process_but_lose_write(corp_code, items, *, log):
        # 처리 흉내 — 반환값만 그대로, 실제 DB 쓰기 skip
        return {"corp_code": corp_code, "corp_name": corp_code,
                "status": "collected", "warnings_count": 0, "has_core_release": True}

    monkeypatch.setattr(collect_mod, "process_corp", process_but_lose_write)

    client.post("/api/collect")
    s = _wait_done(client)
    assert s["status"] == "FAILED"
    assert "쓰기 검증" in s["error"]
