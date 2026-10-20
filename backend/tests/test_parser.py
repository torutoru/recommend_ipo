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
    extract_lockup,
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
    # 확약은 v0.5 보강으로 테이블 집계 — 디티에스 14.13% (applied)
    assert p.lockup_ratio == 13.31
    assert p.lockup_ratio_basis == "applied"


# ---------------------- offering 추출 fail-soft ----------------------

def test_offering_counts_graceful_when_absent():
    # 구조에 명확한 "신주 모집 N 주" 패턴이 없을 수 있음 — None 허용
    off = extract_offering_counts("아무 텍스트도 없음")
    assert off == {"new": None, "old": None, "total": None}


# ---------------------- v0.5 보강 — 의무보유확약 (테이블 집계) ----------------------

def test_dtis_lockup_ratio_applied_basis(dtis_xml_text):
    """실측 — 디티에스 의무보유확약 비율 (신청 기준, applied).

    계산:
      전체 신청 수량(합계 TR) - 미확약 수량(미확약 TR) = 확약 수량
      확약 수량 / 전체 × 100 = lockup_ratio
    기관 7유형 각각 (건수, 수량, 신청가격) 셀 중 >=1,000,000 인 셀만 수량으로 합산.
    """
    ratio, basis = extract_lockup(dtis_xml_text)
    assert basis == "applied"
    assert ratio is not None
    # 디티에스 실측: 14.13% (총 신청 수량 중 확약 비율)
    assert ratio == 13.31      # (다) 섹션 두 표(신청+추가) 합산 결과. 전회 14.13 은 첫 표만 사용했던 값


def test_dtis_parse_fills_lockup(dtis_xml_bytes):
    p = parse(dtis_xml_bytes, rcept_no="20261012000308", corp_name="디티에스",
              rcept_dt="2026-10-12")
    assert p.lockup_ratio == 13.31
    assert p.lockup_ratio_basis == "applied"


def test_extract_lockup_none_when_no_section():
    assert extract_lockup("아무 섹션 없음") == (None, None)


# ---------------------- 티앤이코리아 — 지시 #16 회귀 ----------------------

TNEC_SECTION = FIXTURE_DIR / "tnec_lockup_tradable_section.xml"


def test_tnec_lockup_and_tradable_sections():
    """pm 실측 기대값 (사용자 제보 + 원문 대조):
    - 확약 29.52% (applied) — (다) 섹션의 **두 표(국내 + 외국)** 합산
      미확약 1,320,623,000 / 합계 1,873,827,000 → 확약 553,204,000 / 합계 29.52%
    - 유통가능 31.27% — "31.27%에 해당하는 3,551,856주는 상장직후 유통가능 물량에 해당됩니다"
      → "약" 없음, "유통가능 물량" 띄어쓰기 (디티에스 포맷과 다름)
    """
    xml = TNEC_SECTION.read_text(encoding="utf-8")
    assert extract_lockup(xml) == (29.52, "applied")
    assert extract_tradable_ratio(xml) == 31.27


def test_tnec_parse_fills_expected():
    xml_bytes = TNEC_SECTION.read_bytes()
    p = parse(xml_bytes, rcept_no="20261016000158", corp_name="티앤이코리아",
              rcept_dt="2026-10-16")
    assert p.lockup_ratio == 29.52
    assert p.lockup_ratio_basis == "applied"
    assert p.tradable_ratio == 31.27


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


def test_tradable_ratio_table_fallback_when_narrative_missing():
    """서술형 패턴 없이 '유통가능물량(A-B)' 테이블 셀만 있어도 추출."""
    text = (
        "<P>어떤 서술도 없음</P>"
        "<TD>유통가능물량(A-B)</TD>"
        "<TD>2,250,787</TD>"
        "<TD>15.15%</TD>"
    )
    assert extract_tradable_ratio(text) == 15.15


def test_tradable_ratio_table_fallback_blocked_by_other_section():
    """중간에 한글 라벨이 있으면 다른 섹션으로 보고 매치 안 함."""
    text = "유통가능물량 2,250,787  최대주주 등 100,000  44.24%"
    assert extract_tradable_ratio(text) is None


# ---------------------- v0.6 — offering_amount_krw ----------------------

def test_dtis_offering_amount_from_explicit_total(dtis_xml_text):
    """디티에스 '모집(매출)총액(예정): 37,891,589,000원 ~ ...' 매칭 → lower bound 수용."""
    assert extract_offering_amount_krw(dtis_xml_text) == 37_891_589_000


def test_dtis_parse_offering_amount_recalculates_total_times_final(dtis_xml_bytes):
    """지시 #29: 디티에스 — 원문 명시 '379억(17,000 기준 예정)' 거부, total × final(18,500) 재계산."""
    p = parse(dtis_xml_bytes, rcept_no="20261012000308", corp_name="디티에스",
              rcept_dt="2026-10-12")
    assert p.final_price == 18_500
    assert p.total_offering_count is not None
    # 재계산값: pm 실측 기대값 41,234,964,500 (= 2,229,998 × 18,500 등)
    assert p.offering_amount_krw == p.total_offering_count * p.final_price
    # 원문 명시(37,891,589,000)와 **불일치** 경고 포함
    assert any("불일치" in w and "재계산값" in w for w in p.warnings)


# ---------------------- 다비오 — offering_amount 오탐 회귀 (pm 지시 c2f572c5) ----------------------

DAVIO_SECTION = FIXTURE_DIR / "davio_offering_section.xml"


def test_davio_parse_rejects_tiny_offering_falls_back_null_before_final_price():
    """다비오 공시(20261008000705) 핵심 섹션 fixture — 지시 #75aebc23 반영:
    - 서술형 밴드 "공모희망가액인 12,300원 ~ 16,600원" → band 추출 OK
    - "모집 또는 매출주식의 수 기명식 보통주 1,000,000주" → total_offering_count 추출 OK
    - 확정가 없음(PENDING 단계) → offering_amount_krw 는 **null** (band_low 추정 제거)
    """
    xml_bytes = DAVIO_SECTION.read_bytes()
    p = parse(xml_bytes, rcept_no="20261008000705", corp_name="다비오",
              rcept_dt="2026-10-08")
    assert p.band_low == 12_300
    assert p.band_high == 16_600
    assert p.total_offering_count == 1_000_000
    assert p.final_price is None
    # 핵심: 공모 금액이 '12,300원 오탐'이 아니라 null (band_low 추정 제거, "최저가액 기준" 명시도 거부)
    assert p.offering_amount_krw is None
    assert any("확정가 전" in w or "band_low" in w or "null" in w for w in p.warnings)


def test_offering_amount_rejects_tiny_value_when_total_and_band_present(dtis_xml_bytes):
    """타당성 검사 단위 — total·band_low 가 있고 명시 매치값이 min_required 미만이면 fallback 으로 전환."""
    import re as _re
    xml = dtis_xml_bytes.decode("utf-8")
    # 디티에스 '모집(매출)총액(예정): 37,891,589,000원' 을 '12,300원' 으로 치환
    tampered = _re.sub(
        r"(모집\(매출\)총액\(예정\):?\s*)[0-9,]+원",
        r"\g<1>12,300원",
        xml,
        count=1,
    )
    p = parse(tampered.encode("utf-8"), rcept_no="20261012000308",
              corp_name="디티에스-tamper", rcept_dt="2026-10-12")
    # 명시값(12,300) 은 min_absolute(1억) 미만 → 거부
    # fallback 가능 (확정가 18,500 있으므로)
    assert p.offering_amount_krw != 12_300
    # 거부 경고 명시
    assert any("타당성 기준" in w for w in p.warnings)


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


# ---------------- 지시 #25: 실적보고서 상장일(매매개시일) + 상장구분 ----------------

def test_extract_listing_date_from_issuance_market_open_label():
    """실적보고서 '상장일(매매개시일) 2026년 10월 22일 (예정)' 매칭."""
    text = "<P>3. 상장일(매매개시일) 2026년 10월 22일 (예정)</P>"
    assert extract_listing_date(text) == "2026-10-22"


def test_extract_listing_date_from_issuance_market_open_no_predict():
    """'(예정)' 없이도 매칭. (디티에스 실적보고서 형태)."""
    text = "<P>3. 상장일(매매개시일) 2026년 10월 23일</P>"
    assert extract_listing_date(text) == "2026-10-23"


def test_extract_market_from_listing_class_kosdaq():
    """실적보고서 기업개요 '상장구분 … 코스닥' → KOSDAQ."""
    text = (
        "<TABLE><TR><TD>상장구분</TD><TD>기업규모</TD><TD>업종구분</TD></TR>"
        "<TR><TD>코스닥</TD><TD>중소기업</TD><TD>생명과학</TD></TR></TABLE>"
    )
    assert extract_market(text) == "KOSDAQ"


def test_extract_market_from_listing_class_kospi():
    text = "<TR><TD>상장구분</TD><TD>유가증권</TD></TR>"
    assert extract_market(text) == "KOSPI"


def test_extract_market_from_listing_class_konex():
    text = "<TR><TD>상장구분</TD><TD>코넥스</TD></TR>"
    assert extract_market(text) == "KONEX"


def test_extract_market_listing_class_takes_priority_or_matches_narrative():
    """상장구분 + 서술형이 동일 시장을 가리키면 그 시장. 상충하면 null."""
    # 같은 시장 — 단일 결과
    text_same = (
        "<P>상장구분 코스닥</P>"
        "<P>본 공모 주식은 코스닥시장에 신규상장될 예정입니다.</P>"
    )
    assert extract_market(text_same) == "KOSDAQ"
    # 상충 — 단일 명시 패턴이 코스닥·유가증권 둘 다 → 둘 다 hit → None
    text_conflict = (
        "<P>상장구분 코스닥</P>"
        "<P>본 공모 주식은 유가증권시장에 신규상장될 예정입니다.</P>"
    )
    assert extract_market(text_conflict) is None


def test_issuance_report_sample_fixture_parses_both_fields():
    """pm 이 준 fixture — 상장일(매매개시일)·상장구분 둘 다 추출."""
    xml_path = FIXTURE_DIR / "issuance_report_sample.xml"
    xml_bytes = xml_path.read_bytes()
    text = xml_bytes.decode("utf-8")
    assert extract_listing_date(text) == "2026-10-22"
    assert extract_market(text) == "KOSDAQ"


# ---------------- 지시 #26: 삼성증권 형식(크리에이츠) 확약/유통 ----------------

def test_creatz_lockup_section_label_variant():
    """크리에이츠 (다) 섹션명 "의무보유 확약 신청내역" 수용."""
    xml = (FIXTURE_DIR / "creatz_lockup_tradable_section.xml").read_text(encoding="utf-8")
    ratio, basis = extract_lockup(xml)
    assert basis == "applied"
    assert ratio == 0.00    # 실질 미확약 (15일 1건 5,000주만)


def test_creatz_tradable_narrative_inverted_order():
    """크리에이츠 서술형 역순 — '상장 직후 ... 유통가능 ... 상장예정주식수 기준으로 39.47%' 매치."""
    text = (
        "<P>상기의 의무보유 수량을 제외한 주식수 5,176,832주는 상장 직후 시장에서 "
        "유통가능한 물량이며, 상past예정주식수 기준으로 39.47%에 해당합니다.</P>"
    )
    # strip_tags 가 태그 제거하므로 그 상태의 매치만 확인
    assert extract_tradable_ratio(text) == 39.47


def test_creatz_full_fixture_lockup_and_tradable():
    """크리에이츠 fixture(필요 섹션만) → lockup 0.00, tradable 39.47."""
    xml = (FIXTURE_DIR / "creatz_lockup_tradable_section.xml").read_text(encoding="utf-8")
    ratio, basis = extract_lockup(xml)
    assert ratio == 0.00
    assert basis == "applied"
    assert extract_tradable_ratio(xml) == 39.47


def test_tradable_narrative_inverted_requires_sang_jang_jik_hu():
    """유통가능 역순 regex 는 '상장 직후' 가 있어야 매치 — 상장 후 N개월 뒤 테이블은 거부."""
    # "상장 직후" 없이 "상장 후 2개월 뒤 유통가능 ... 50.00%" 는 매치 안 돼야 함
    text = "<P>상장 후 2개월 뒤 유통가능 물량은 상장예정주식수 기준 50.00% 입니다</P>"
    # fallback(table regex 등) 가 매치할 수 있으므로 narrative_inverted 단독 확인은 regex 로
    from app.parser import _RE_TRADABLE_RATIO_NARRATIVE_INVERTED
    assert _RE_TRADABLE_RATIO_NARRATIVE_INVERTED.search(text) is None


# ---------------- 지시 #20: 공모가 확정공고일 + 수요예측 기간 ----------------

def test_extract_price_confirm_date_explicit_label():
    """본문 '공모가액 확정공고 2026년 10월 16일' 명시 매치."""
    from app.parser import extract_price_confirm_date
    text = "<P>공모가액 확정공고 2026년 10월 16일(목)에 실시합니다.</P>"
    assert extract_price_confirm_date(text) == "2026-10-16"


def test_extract_price_confirm_date_matulip_label():
    """'모집 또는 매출가액 확정의 공고' 라벨도 매치."""
    from app.parser import extract_price_confirm_date
    text = "<P>모집 또는 매출가액 확정의 공고 2026년 10월 20일</P>"
    assert extract_price_confirm_date(text) == "2026-10-20"


def test_extract_price_confirm_date_null_when_no_match():
    """명시 서술 없으면 null (디티에스 발행조건확정 패턴 — collect 에서 접수일로 fallback)."""
    from app.parser import extract_price_confirm_date
    text = "<P>청약공고일 2026년 10월 13일</P>"   # "확정공고" 아니라 "청약공고"
    assert extract_price_confirm_date(text) is None


def test_extract_demand_forecast_period_full_year():
    """'수요예측 기간: 2026년 10월 15일 ~ 2026년 10월 16일' 매치."""
    from app.parser import extract_demand_forecast_period
    text = "<P>수요예측 기간: 2026년 10월 15일 ~ 2026년 10월 16일</P>"
    s, e = extract_demand_forecast_period(text)
    assert s == "2026-10-15"
    assert e == "2026-10-16"


def test_extract_demand_forecast_period_short_year():
    """연도 반복 생략 '수요예측기간 2026년 10월 15일 ~ 10월 16일' 매치."""
    from app.parser import extract_demand_forecast_period
    text = "<P>수요예측기간 2026년 10월 15일 ~ 10월 16일</P>"
    s, e = extract_demand_forecast_period(text)
    assert s == "2026-10-15"
    assert e == "2026-10-16"


def test_extract_demand_forecast_period_null_when_no_match():
    from app.parser import extract_demand_forecast_period
    text = "<P>청약기간: 2026년 10월 20일 ~ 2026년 10월 21일</P>"
    s, e = extract_demand_forecast_period(text)
    assert s is None and e is None


def test_extract_demand_forecast_period_weekday_parentheses():
    """정확도 보강: '수요예측 일시 2026년 10월 12일(월) ~ 2026년 10월 16일(금)' — 인텔리빅스 포맷."""
    from app.parser import extract_demand_forecast_period
    text = "<P>수요예측 일시 2026년 10월 12일(월) ~ 2026년 10월 16일(금)</P>"
    s, e = extract_demand_forecast_period(text)
    assert s == "2026-10-12"
    assert e == "2026-10-16"


def test_extract_demand_forecast_period_weekday_short_year():
    """요일 괄호 + 연도 반복 생략."""
    from app.parser import extract_demand_forecast_period
    text = "<P>수요예측기간 2026년 10월 15일(목) ~ 10월 16일(금)</P>"
    s, e = extract_demand_forecast_period(text)
    assert s == "2026-10-15"
    assert e == "2026-10-16"


# ---------------- 정확도 보강: 신주/구주 라벨 변형 ----------------

def test_extract_offering_counts_new_variants():
    """'신주모집' 뒤 라벨 변형(수량/주식수/주식의 수) 수용."""
    xmls = [
        '<DOC><P>신주모집 1,000,000주</P></DOC>',                   # 기존
        '<DOC><P>신주모집수량 1,000,000주</P></DOC>',
        '<DOC><P>신주모집주식수 1,000,000주</P></DOC>',
        '<DOC><P>신주모집주식의 수 1,000,000주</P></DOC>',
    ]
    for xml in xmls:
        res = extract_offering_counts(xml)
        assert res["new"] == 1_000_000, xml


def test_extract_offering_counts_old_variants():
    """'구주매출' 뒤 라벨 변형 수용."""
    xmls = [
        '<DOC><P>구주매출 200,000주</P></DOC>',
        '<DOC><P>구주매출수량 200,000주</P></DOC>',
        '<DOC><P>구주매출주식수 200,000주</P></DOC>',
        '<DOC><P>구주매출주식의 수 200,000주</P></DOC>',
    ]
    for xml in xmls:
        res = extract_offering_counts(xml)
        assert res["old"] == 200_000, xml


# ---------------- 지시 #21: 주관사·인수회사 추출 ----------------

def test_extract_underwriters_basic():
    from app.parser import extract_underwriters
    text = "<P>대표주관회사인 삼성증권㈜과 발행회사가 협의하여 결정합니다.</P>"
    assert extract_underwriters(text) == ["삼성증권"]


def test_extract_underwriters_lead_plus_joint():
    from app.parser import extract_underwriters
    text = (
        "<P>대표주관회사는 신한투자증권주식회사입니다.</P>"
        "<P>공동주관회사 하나증권이 참여합니다.</P>"
    )
    assert extract_underwriters(text) == ["신한투자증권", "하나증권"]


def test_extract_underwriters_dedup_and_order():
    """대표 → 공동 → 인수 순, 중복 제거."""
    from app.parser import extract_underwriters
    text = (
        "<P>대표주관회사인 대신증권</P>"
        "<P>인수회사 대신증권</P>"      # 대표와 같은 이름 — 중복 제거
        "<P>인수회사인 하나증권</P>"
    )
    assert extract_underwriters(text) == ["대신증권", "하나증권"]


def test_extract_underwriters_empty_when_no_match():
    from app.parser import extract_underwriters
    assert extract_underwriters("<P>본 공모는 2026년 10월에 진행됩니다.</P>") == []


# ---------------- 지시 #75aebc23: 확정가 전 공모 금액 null ----------------

def test_offering_amount_null_when_no_final_price():
    """final_price 없음(확정가 전) → offering_amount_krw 는 반드시 null, band_low 추정 제거."""
    xml = (
        '<DOC>'
        '<P>공모희망가액 범위(10,000원 ~ 12,000원)</P>'
        '<P>본 공시 접수일 2026-10-12</P>'
        '<P>청약기간: 2026년 10월 20일 ~ 2026년 10월 21일</P>'
        # 총수량 명시 (fallback band_low×total 유혹)
        '<P>모집(매출)총수량 1,000,000주</P>'
        '</DOC>'
    ).encode("utf-8")
    p = parse(xml, rcept_no="x", corp_name="t", rcept_dt="2026-10-12")
    assert p.final_price is None
    assert p.offering_amount_krw is None   # band_low × total 거부
    assert any("band_low" in w or "확정가 전" in w or "null" in w for w in p.warnings)


def test_offering_amount_explicit_rejected_without_final_price():
    """확정가 전 원문 명시('최저가액 기준' 가능성) → explicit 이 있어도 null."""
    xml = (
        '<DOC>'
        '<P>공모희망가액 범위(10,000원 ~ 12,000원)</P>'
        '<P>본 공시 접수일 2026-10-12</P>'
        '<P>청약기간: 2026년 10월 20일 ~ 2026년 10월 21일</P>'
        '<P>모집(매출)총액(예정): 12,300,000,000원</P>'    # 최저가 기준 예정 총액
        '</DOC>'
    ).encode("utf-8")
    p = parse(xml, rcept_no="x", corp_name="t", rcept_dt="2026-10-12")
    assert p.final_price is None
    assert p.offering_amount_krw is None


def test_offering_amount_keeps_explicit_when_final_price_present(dtis_xml_bytes):
    """지시 #29: final_price 있고 total 있으면 **total × final** 를 우선. 디티에스 확정 18,500."""
    p = parse(dtis_xml_bytes, rcept_no="20261012000308", corp_name="디티에스", rcept_dt="2026-10-12")
    assert p.final_price == 18_500
    assert p.total_offering_count is not None
    # 재계산 값 (원문 명시 "17,000 기준 예정" 거부)
    assert p.offering_amount_krw == p.total_offering_count * p.final_price


def test_offering_amount_recalculates_total_times_final():
    """지시 #29: 원문에 '최저가액 기준 예정 총액'이 있어도 total × final 재계산 우선."""
    xml = (
        '<DOC>'
        '<P>공모희망가액 범위(12,600원 ~ 15,300원)</P>'
        '<P>확정공모가액 15,300원</P>'
        '<P>본 공시 접수일 2026-10-15</P>'
        '<P>청약기간: 2026년 10월 20일 ~ 2026년 10월 21일</P>'
        '<P>모집(매출)총액(예정): 30,240,000,000원</P>'   # 최저가(12,600) 기준 — 거부
        '<P>모집(매출)주식수 2,400,000주</P>'
        '</DOC>'
    ).encode("utf-8")
    p = parse(xml, rcept_no="x", corp_name="t", rcept_dt="2026-10-15")
    assert p.final_price == 15_300
    assert p.total_offering_count == 2_400_000
    assert p.offering_amount_krw == 2_400_000 * 15_300   # = 36,720,000,000
    assert any("불일치" in w and "재계산값" in w for w in p.warnings)
