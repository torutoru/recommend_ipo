"""IPO 식별 — 스팩 키워드 제외 (지시 #15)."""
from __future__ import annotations

from app.collect import is_ipo_candidate
from app.config import get_settings


def _disc(corp_name: str, *, corp_cls: str = "E", stock_code: str = "") -> dict:
    return {"corp_name": corp_name, "corp_cls": corp_cls, "stock_code": stock_code}


def test_normal_company_passes():
    assert is_ipo_candidate(_disc("디티에스")) is True
    assert is_ipo_candidate(_disc("세종바이오")) is True


def test_corp_name_with_기업인수목적_excluded():
    assert is_ipo_candidate(_disc("에스케이증권제14호기업인수목적")) is False


def test_corp_name_with_스팩_excluded():
    """새 키워드 — '스팩' 포함 시 제외."""
    assert is_ipo_candidate(_disc("OO스팩4호")) is False
    assert is_ipo_candidate(_disc("한국스팩2호")) is False
    assert is_ipo_candidate(_disc("라이프스팩투자")) is False   # 중간 포함도 제외


def test_already_listed_excluded():
    assert is_ipo_candidate(_disc("에코프로비엠", corp_cls="K", stock_code="247540")) is False


def test_configurable_via_settings():
    """설정값으로 키워드 조정 가능 — 기본값이 맞는지 + 확장 테스트."""
    s = get_settings()
    kws = s.spac_keywords()
    assert "기업인수목적" in kws
    assert "스팩" in kws
    # 임시로 "스팩" 제거해도 키워드 집합이 바뀜
    original = s.spac_exclusion_keywords
    s.spac_exclusion_keywords = "기업인수목적"
    try:
        assert is_ipo_candidate(_disc("가나스팩3호")) is True   # 이제는 제외 안 됨
        assert is_ipo_candidate(_disc("가나기업인수목적")) is False
    finally:
        s.spac_exclusion_keywords = original
