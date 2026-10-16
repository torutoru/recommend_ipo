"""파서 유닛·골든 테스트 (지시 #3 B / #4-F).

디티에스 공시 원문(fixture)으로 밴드·확정가·경쟁률·신청수량·price_position 4값 검증.
확약·유통 비율은 1차 파서에서 미구현 → null + 경고 처리 확인.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.parser import (
    classify_price_position,
    extract_band,
    extract_final_price,
    extract_demand_result,
    extract_listing_date,
    extract_market,
    extract_offering_amount_krw,
    extract_offering_counts,
    extract_tradable_ratio,
    parse,
)


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
DTIS_XML = FIXTURE_DIR / "document_20261012000308.xml"


@pytest.fixture(scope="module")
def dtis_xml_bytes() -> bytes:
    with DTIS_XML.open("rb") as f:
        return f.read()


@pytest.fixture(scope="module")
def dtis_xml_text(dtis_xml_bytes) -> str:
    return dtis_xml_bytes.decode("utf-8")


# ---------------------- price_position 4값 ----------------------

def test_classify_price_position_above():
    assert classify_price_position(10000, 15000, 16000) == "ABOVE_BAND"


def test_classify_price_position_top():
    assert classify_price_position(10000, 15000, 15000) == "TOP_OF_BAND"


def test_classify_price_position_within():
    assert classify_price_position(10000, 15000, 12000) == "WITHIN_BAND"
    assert classify_price_position(10000, 15000, 10000) == "WITHIN_BAND"


def test_classify_price_position_below():
    assert classify_price_position(10000, 15000, 9999) == "BELOW_BAND"


def test_classify_price_position_null_when_band_low_missing():
    assert classify_price_position(None, 15000, 14000) is None


# ---------------------- 디티에스 골든 ----------------------

def test_dtis_band(dtis_xml_text):
    low, high = extract_band(dtis_xml_text)
    assert low == 17_000
    assert high == 18_500


def test_dtis_final_price(dtis_xml_text):
    assert extract_final_price(dtis_xml_text) == 18_500


def test_dtis_price_position_top_of_band(dtis_xml_text):
    low, high = extract_band(dtis_xml_text)
    final = extract_final_price(dtis_xml_text)
    assert classify_price_position(low, high, final) == "TOP_OF_BAND"


def test_dtis_demand_result(dtis_xml_text):
    d = extract_demand_result(dtis_xml_text)
    assert d["competition_rate"] == pytest.approx(983.98, abs=0.01)
    assert d["demand_quantity"] == 1_644_913_000
    assert d["competition_rate_type"] == "simple"


def test_dtis_parse_full(dtis_xml_bytes):
    p = parse(dtis_xml_bytes, rcept_no="20261012000308", corp_name="디티에스")
    assert p.band_low == 17_000
    assert p.band_high == 18_500
    assert p.final_price == 18_500
    assert p.price_position == "TOP_OF_BAND"
    assert p.competition_rate == pytest.approx(983.98, abs=0.01)
    assert p.demand_quantity == 1_644_913_000
    # 신청 금액 = 수량 × 확정가
    assert p.demand_amount_krw == 1_644_913_000 * 18_500
    # 유통가능은 v0.5 서술형 파서로 추출됨 (15.15%)
    assert p.tradable_ratio == 15.15
    # 확약은 1차 파서 미구현 → null + 경고
    assert p.lockup_ratio is None
    assert any("의무보유확약" in w and "미구현" in w for w in p.warnings)


# ---------------------- offering 추출 fail-soft ----------------------

def test_offering_counts_graceful_when_absent():
    # 구조에 명확한 "신주 모집 N 주" 패턴이 없을 수 있음 — None 허용
    off = extract_offering_counts("아무 텍스트도 없음")
    assert off == {"new": None, "old": None, "total": None}


# ---------------------- v0.4 — market / listing_date ----------------------

def test_dtis_market_kosdaq(dtis_xml_text):
    """실측: 디티에스 코스닥 73회 / 유가증권 2회 / 코넥스 6회."""
    assert extract_market(dtis_xml_text) == "KOSDAQ"


def test_dtis_listing_date_null_no_explicit(dtis_xml_text):
    """실측: 디티에스 발행조건확정 신고서에는 '상장예정일 YYYY-MM-DD' 명시 없음."""
    assert extract_listing_date(dtis_xml_text) is None


def test_extract_market_explicit_kospi():
    assert extract_market("회사는 유가증권시장에 상장합니다. 유가증권시장 상장규정.") == "KOSPI"


def test_extract_market_explicit_konex():
    assert extract_market("코넥스시장 상장을 위한 신고서입니다.") == "KONEX"


def test_extract_market_none_when_absent():
    assert extract_market("아무 시장 언급 없음") is None


def test_extract_market_null_when_explicit_conflict():
    """두 시장이 모두 명시 상장 패턴을 가지면 null (상충)."""
    assert extract_market("코스닥시장에 상장. 유가증권시장에 상장.") is None


def test_extract_market_null_when_freq_tie():
    """빈도 fallback: 동률이면 null."""
    text = "코스닥시장 유가증권시장 코스닥시장 유가증권시장"
    assert extract_market(text) is None


def test_extract_market_null_when_freq_close():
    """빈도 1위:2위 비율이 지배 비율(기본 3배) 미만이면 null."""
    text = "코스닥시장 코스닥시장 유가증권시장"   # 2:1
    assert extract_market(text) is None


def test_extract_market_freq_when_dominant():
    text = "코스닥시장 " * 10 + "유가증권시장 " * 2   # 10:2 = 5배 → KOSDAQ
    assert extract_market(text) == "KOSDAQ"


def test_extract_market_configurable_ratio():
    text = "코스닥시장 코스닥시장 유가증권시장"   # 2:1
    assert extract_market(text, dominance_ratio=2.0) == "KOSDAQ"
    assert extract_market(text, dominance_ratio=3.0) is None


def test_extract_listing_date_explicit():
    assert extract_listing_date("상장예정일: 2026-11-20") == "2026-11-20"
    assert extract_listing_date("상장일자 2026년 12월 3일") == "2026-12-03"


def test_extract_listing_date_ignores_relative_mentions():
    # "상장일부터 6개월" 같은 상대 참조는 매칭하면 안 됨
    assert extract_listing_date("상장일부터 6개월 이상 보유합니다.") is None


# ---------------------- v0.5 — tradable_ratio (서술형) ----------------------

def test_dtis_tradable_ratio_narrative(dtis_xml_text):
    """실측: 디티에스 유통가능 15.15% (서술형)."""
    assert extract_tradable_ratio(dtis_xml_text) == 15.15


def test_dtis_parse_fills_tradable_ratio(dtis_xml_bytes):
    p = parse(dtis_xml_bytes, rcept_no="20261012000308", corp_name="디티에스",
              rcept_dt="2026-10-12")
    assert p.tradable_ratio == 15.15


# ---------------------- v0.6 — offering_amount_krw ----------------------

def test_dtis_offering_amount_from_explicit_total(dtis_xml_text):
    """디티에스 '모집(매출)총액(예정): 37,891,589,000원 ~ ...' 매칭 → lower bound 수용."""
    assert extract_offering_amount_krw(dtis_xml_text) == 37_891_589_000


def test_dtis_parse_offering_amount_prefers_explicit(dtis_xml_bytes):
    p = parse(dtis_xml_bytes, rcept_no="20261012000308", corp_name="디티에스",
              rcept_dt="2026-10-12")
    # 디티에스 공모 금액: 명시된 379억 (1000억 미달 → 가산 없음)
    assert p.offering_amount_krw == 37_891_589_000


# ---------------------- v0.5 fix — listing_date 과거 날짜 거부 ----------------------

def test_parse_rejects_past_listing_date(tmp_path):
    """상장일 후보가 접수일보다 과거면 null + warning. 과거 상장 이력 오탐 회귀."""
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<DOC>'
        '  <P>본 공시의 접수일은 2026년 10월 12일입니다.</P>'
        '  <P>참고: 모회사의 상장일 2003-08-18 이후 변경 사항 없음.</P>'
        '  <P>청약기간: 2026년 10월 20일 ~ 2026년 10월 21일</P>'
        '</DOC>'
    ).encode("utf-8")
    p = parse(xml, rcept_no="20261012000308", corp_name="테스트", rcept_dt="2026-10-12")
    assert p.listing_date is None
    assert any("과거 참조로 간주" in w for w in p.warnings)


def test_parse_accepts_future_listing_date():
    xml = (
        '<DOC>'
        '<P>상장예정일 2026년 11월 20일로 결정되었습니다.</P>'
        '<P>청약기간: 2026년 11월 10일 ~ 2026년 11월 11일</P>'
        '</DOC>'
    ).encode("utf-8")
    p = parse(xml, rcept_no="20261110000001", corp_name="테스트", rcept_dt="2026-11-10")
    assert p.listing_date == "2026-11-20"
