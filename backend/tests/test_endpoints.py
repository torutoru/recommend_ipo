"""API 엔드포인트 통합 테스트 — v0.3.

FastAPI TestClient 로 응답 shape · 불변식 · CORS 를 검증.
샘플 데이터만 사용. DART 호출 없음.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# ---------------------- health ----------------------

def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "last_collected_at" in body


# ---------------------- list ----------------------

def test_list_contains_all_statuses(client):
    items = client.get("/api/ipos").json()["items"]
    statuses = {it["verdict"]["status"] for it in items}
    assert {"PENDING", "PASS", "REJECT"}.issubset(statuses)


def test_list_sorted_by_subscription_start(client):
    items = client.get("/api/ipos").json()["items"]
    starts = [it["subscription_start"] for it in items]
    assert starts == sorted(starts, key=lambda s: s or "9999-99-99")


def test_list_v4_market_and_listing_date_mixed(client):
    """v0.4 — market/listing_date 는 원문 파싱 결과(없으면 null). 섞여서 등장."""
    items = client.get("/api/ipos").json()["items"]
    markets = {it["market"] for it in items}
    listings = {it["listing_date"] for it in items}
    # 섞여 있어야 함: null 과 null 이 아닌 값 공존
    assert None in markets and (markets - {None})
    assert None in listings and (listings - {None})


def test_list_summary_has_updated_at(client):
    for it in client.get("/api/ipos").json()["items"]:
        assert it["updated_at"]


def test_list_filter_status(client):
    for it in client.get("/api/ipos?status=PASS").json()["items"]:
        assert it["verdict"]["status"] == "PASS"


def test_list_v4_overlap_subscription_in_range(client):
    """v0.4 — 청약기간이 범위에 걸치면 포함."""
    # 세종바이오 subscription_start=2026-10-30 → [10/25, 11/01] 에 겹침
    items = client.get("/api/ipos?from=2026-10-25&to=2026-11-01").json()["items"]
    ids = {it["id"] for it in items}
    assert "00990002" in ids


def test_list_v4_overlap_listing_date_in_range(client):
    """v0.4 — 청약 자체는 범위 밖이지만 listing_date 가 범위 안이면 포함."""
    # 세종바이오 listing_date=2026-11-11, subscription=10/30~10/31 → 11월 중순 범위에 listing_date 로 들어와야 함
    items = client.get("/api/ipos?from=2026-11-10&to=2026-11-20").json()["items"]
    ids = {it["id"] for it in items}
    assert "00990002" in ids   # listing_date 로 겹침
    # 가야반도체 subscription=12/15~16 는 11월 범위와 겹치지 않음
    assert "00990006" not in ids


def test_list_v4_pending_without_listing_date(client):
    """subscription_start 는 10/28 — [10/25, 10/31] 와 겹침, listing_date 없어도 포함."""
    items = client.get("/api/ipos?from=2026-10-25&to=2026-10-31").json()["items"]
    ids = {it["id"] for it in items}
    assert "00990001" in ids


def test_list_v4_range_excludes_future(client):
    """12월 범위에 10월 종목 안 들어와야 함."""
    items = client.get("/api/ipos?from=2026-12-01&to=2026-12-31").json()["items"]
    ids = {it["id"] for it in items}
    assert "00990001" not in ids   # 10월
    assert "00990006" in ids       # 12월


# ---------------------- detail · 불변식 ----------------------

def test_detail_pass_s(client):
    """세종바이오 (00990002) — ABOVE_BAND + 가산 → 100점 S."""
    d = client.get("/api/ipos/00990002").json()
    assert d["verdict"]["status"] == "PASS"
    assert d["verdict"]["grade"] == "S"
    assert d["verdict"]["score"] == d["scores"]["total"] == 100
    assert d["indicators"]["price_position"] == "ABOVE_BAND"


def test_detail_pass_range_locked_lockup_unknown(client):
    """v1.4 (지시 #27): 북극로보틱스 (00990005) — lockup=null 이지만 min=75 ≥ 50
    → **PASS 확정**, 등급은 min 기준(A). score·scores.total 은 null, score_range 노출.
    체크리스트 lockup 은 여전히 UNKNOWN(지표 자체는 미확인)."""
    d = client.get("/api/ipos/00990005").json()
    assert d["verdict"]["status"] == "PASS"
    assert d["verdict"]["grade"] == "A"
    assert d["verdict"]["score"] is None
    assert d["verdict"]["score_range"] == {"min": 75, "max": 95}
    assert d["scores"]["total"] is None
    assert d["scores"]["lockup"] is None   # 확정 지표만 scores 에 값, 미확인은 null
    checklist = {c["key"]: c for c in d["checklist"]}
    assert checklist["lockup"]["result"] == "UNKNOWN"
    assert checklist["lockup"]["actual"] is None


def test_detail_pass_b_mixed_checklist(client):
    """대륙중공업 (00990004) — WITHIN_BAND + 유통 38% → B 등급 + 체크리스트 혼재."""
    d = client.get("/api/ipos/00990004").json()
    assert d["verdict"]["status"] == "PASS"
    assert d["verdict"]["grade"] == "B"
    checklist = {c["key"]: c for c in d["checklist"]}
    assert checklist["competition"]["result"] == "MET"
    assert checklist["price_position"]["result"] == "NOT_MET"
    assert checklist["lockup"]["result"] == "MET"
    assert checklist["flow"]["result"] == "NOT_MET"


def test_detail_pending_invariant(client):
    d = client.get("/api/ipos/00990001").json()
    assert d["verdict"]["status"] == "PENDING"
    assert d["verdict"]["grade"] is None
    assert d["verdict"]["score"] is None
    assert d["scores"]["total"] is None
    assert d["reject_reasons"] == []
    assert d["min_deposit"] is None
    # 체크리스트는 PENDING 에도 내려와야 함 (대부분 UNKNOWN)
    assert len(d["checklist"]) == 6
    assert any(c["result"] == "UNKNOWN" for c in d["checklist"])


def test_detail_reject_keeps_scores_v3(client):
    """한강에너지 (00990003) — v0.3: REJECT 도 score/scores 보유."""
    d = client.get("/api/ipos/00990003").json()
    assert d["verdict"]["status"] == "REJECT"
    assert d["verdict"]["grade"] is None
    assert d["verdict"]["score"] is not None            # v0.3 변경
    assert d["scores"]["total"] is not None
    assert d["verdict"]["score"] == d["scores"]["total"]
    assert d["reject_reasons"] and any("50점 미만" in r for r in d["reject_reasons"])


def test_detail_v3_price_position_within_band(client):
    """WITHIN_BAND Literal 수용 확인."""
    d = client.get("/api/ipos/00990004").json()
    assert d["indicators"]["price_position"] == "WITHIN_BAND"


def test_detail_v3_price_position_below_band(client):
    d = client.get("/api/ipos/00990003").json()
    assert d["indicators"]["price_position"] == "BELOW_BAND"


# ---------------------- min_deposit v0.3 ----------------------

def test_min_deposit_v3_fields(client):
    d = client.get("/api/ipos/00990002").json()
    md = d["min_deposit"]
    assert set(md.keys()) == {"shares", "deposit_krw", "fee_krw", "total_krw"}
    assert md["fee_krw"] == 2000
    assert md["total_krw"] == md["deposit_krw"] + md["fee_krw"]


def test_detail_custom_shares(client):
    d = client.get("/api/ipos/00990002?shares=20").json()
    assert d["min_deposit"]["shares"] == 20


def test_detail_shares_422_on_zero_or_negative(client):
    assert client.get("/api/ipos/00990002?shares=0").status_code == 422
    assert client.get("/api/ipos/00990002?shares=-5").status_code == 422


def test_detail_404(client):
    r = client.get("/api/ipos/doesnotexist")
    assert r.status_code == 404
    assert "detail" in r.json()


# ---------------------- scoring-config v0.3 구조 ----------------------

def test_scoring_config_v3_shape(client):
    cfg = client.get("/api/scoring-config").json()
    assert set(cfg.keys()) == {"score", "grade", "deposit", "checklist"}
    assert cfg["score"]["comp"]["max"] == 35
    assert cfg["score"]["comp"]["large_cap_bonus"]["min_offering_amount_krw"] == 100_000_000_000
    assert cfg["score"]["comp"]["large_cap_bonus"]["min_competition_rate"] == 800.0
    assert cfg["score"]["price"]["points"]["ABOVE_BAND"] == 25
    assert cfg["score"]["price"]["points"]["WITHIN_BAND"] == 10
    assert cfg["grade"]["pass_min"] == 50
    assert cfg["deposit"]["fee_krw"] == 2000
    assert "competition_min" in cfg["checklist"]


# ---------------------- CORS ----------------------

def test_cors_header(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
