"""내 공모주 holdings API 테스트 (지시 #51 dd93b259, api-contract v1.7, requirements 24장).

커버:
- CRUD (GET 목록, PUT upsert, DELETE)
- 404: corp_code 가 ipos 에 없음
- 422: shares/price < 1, memo > 60자
- 결합 필드(corp_name, listing_date, amount_krw)
- 수집(collect)이 holdings 를 건드리지 않음을 고정
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import collect_service, dart_client, store
from app.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _reset(tmp_path, monkeypatch):
    from app import collect as _collect
    monkeypatch.setattr(_collect, "CACHE_DIR", tmp_path / "cache")
    store.init_db()
    collect_service._reset_for_tests()
    yield


@pytest.fixture
def client() -> TestClient:
    s = get_settings()
    orig = s.use_sample_data
    s.use_sample_data = False
    yield TestClient(create_app())
    s.use_sample_data = orig


def _seed_ipo(corp_code: str, corp_name: str, listing_date: str | None = None) -> None:
    with store.connect() as conn:
        store.upsert_ipo(
            conn,
            corp_code=corp_code, corp_name=corp_name, market="KOSDAQ",
            subscription_start=None, subscription_end=None, listing_date=listing_date,
            band_low=None, band_high=None, final_price=None, price_position=None,
            competition_rate=None, competition_rate_type=None,
            demand_quantity=None, demand_amount_krw=None,
            lockup_ratio=None, lockup_ratio_basis=None,
            tradable_ratio=None, old_share_ratio=None,
            new_share_count=None, old_share_count=None,
            total_offering_count=None, offering_amount_krw=None,
            report_rcept_no=None, parser_version="v33",
            price_confirm_date=None,
            demand_forecast_start=None, demand_forecast_end=None,
            correction_requested_at=None, correction_amended_at=None,
            underwriters_json=None,
        )


# ---------- CRUD ----------

def test_51_list_empty(client):
    r = client.get("/api/holdings")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_51_upsert_create_then_update(client):
    _seed_ipo("01378005", "이에스티", "2026-11-04")
    # create
    r = client.put("/api/holdings/01378005", json={"shares": 10, "price": 12400, "memo": "청약 참여"})
    assert r.status_code == 200
    body = r.json()
    assert body["corp_code"] == "01378005"
    assert body["shares"] == 10
    assert body["price"] == 12400
    assert body["memo"] == "청약 참여"
    assert body["corp_name"] == "이에스티"
    assert body["listing_date"] == "2026-11-04"
    assert body["amount_krw"] == 10 * 12400
    first_created = body["created_at"]

    # update — created_at 유지, updated_at 갱신
    r = client.put("/api/holdings/01378005", json={"shares": 20, "price": 12400, "memo": "증권사 2곳"})
    assert r.status_code == 200
    body2 = r.json()
    assert body2["shares"] == 20
    assert body2["memo"] == "증권사 2곳"
    assert body2["created_at"] == first_created
    assert body2["amount_krw"] == 20 * 12400


def test_51_list_after_upserts(client):
    _seed_ipo("01378005", "이에스티")
    _seed_ipo("00534729", "디티에스")
    client.put("/api/holdings/01378005", json={"shares": 10, "price": 12400, "memo": ""})
    client.put("/api/holdings/00534729", json={"shares": 5, "price": 18500, "memo": "소량"})
    r = client.get("/api/holdings")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    codes = {it["corp_code"] for it in items}
    assert codes == {"01378005", "00534729"}


def test_51_delete(client):
    _seed_ipo("01378005", "이에스티")
    client.put("/api/holdings/01378005", json={"shares": 10, "price": 12400, "memo": ""})
    r = client.delete("/api/holdings/01378005")
    assert r.status_code == 204
    # 다시 삭제해도 204 (없어도 OK)
    r2 = client.delete("/api/holdings/01378005")
    assert r2.status_code == 204
    r3 = client.get("/api/holdings")
    assert r3.json()["items"] == []


# ---------- 404 / 422 ----------

def test_51_upsert_404_when_corp_not_in_ipos(client):
    r = client.put("/api/holdings/99999999", json={"shares": 10, "price": 10000, "memo": ""})
    assert r.status_code == 404


def test_51_upsert_422_on_shares_zero(client):
    _seed_ipo("01378005", "이에스티")
    r = client.put("/api/holdings/01378005", json={"shares": 0, "price": 10000, "memo": ""})
    assert r.status_code == 422


def test_51_upsert_422_on_price_negative(client):
    _seed_ipo("01378005", "이에스티")
    r = client.put("/api/holdings/01378005", json={"shares": 10, "price": -1, "memo": ""})
    assert r.status_code == 422


def test_51_upsert_422_on_memo_too_long(client):
    _seed_ipo("01378005", "이에스티")
    r = client.put("/api/holdings/01378005",
                   json={"shares": 10, "price": 10000, "memo": "x" * 61})
    assert r.status_code == 422


# ---------- 결합 필드 ----------

def test_51_list_includes_corp_name_and_listing_date(client):
    _seed_ipo("01378005", "이에스티", "2026-11-04")
    client.put("/api/holdings/01378005", json={"shares": 10, "price": 12400, "memo": ""})
    r = client.get("/api/holdings")
    item = r.json()["items"][0]
    assert item["corp_name"] == "이에스티"
    assert item["listing_date"] == "2026-11-04"
    assert item["amount_krw"] == 124000


# ---------- 수집이 holdings 를 건드리지 않음 ----------

def test_51_collect_does_not_touch_holdings(client, monkeypatch):
    """수집·재파싱 전후로 holdings 가 유지되는지 고정."""
    _seed_ipo("01378005", "이에스티", "2026-11-04")
    client.put("/api/holdings/01378005",
               json={"shares": 10, "price": 12400, "memo": "청약"})
    before = client.get("/api/holdings").json()["items"][0]

    # 수집 모킹 — 신규 공시 없음
    def fake_list(**kw):
        return {"status": "013", "message": "no result", "list": []}
    monkeypatch.setattr(dart_client, "list_disclosures", fake_list)
    client.post("/api/collect")
    # 수집 완료 대기
    import time
    deadline = time.time() + 10
    while time.time() < deadline:
        s = client.get("/api/collect/status").json()
        if s["status"] in ("SUCCEEDED", "FAILED", "IDLE"):
            break
        time.sleep(0.05)

    after = client.get("/api/holdings").json()["items"][0]
    assert after["corp_code"] == before["corp_code"]
    assert after["shares"] == before["shares"]
    assert after["price"] == before["price"]
    assert after["memo"] == before["memo"]
    assert after["created_at"] == before["created_at"]
