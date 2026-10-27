"""IPO 식별 — 스팩 키워드 제외 (지시 #15)."""
from __future__ import annotations

from app.collect import choose_core_disclosure, is_ipo_candidate
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


# ---------- 지시 #55 — [첨부정정] core 후보 제외 ----------


def _d(rcept_no: str, report_nm: str, rcept_dt: str) -> dict:
    return {
        "rcept_no": rcept_no,
        "report_nm": report_nm,
        "rcept_dt": rcept_dt,
        "corp_name": "제논",
    }


def test_55_attachment_only_excluded_from_core():
    """지시 #55: 최신 공시가 [첨부정정] 이면 **직전 [기재정정]** 이 core 로 선정."""
    # 최신 10/26 [첨부정정] 과 그 직전 10/26 [기재정정]
    attachment = _d("20261026000367", "[첨부정정]증권신고서(지분증권)", "20261026")
    amendment = _d("20261026000001", "[기재정정]증권신고서(지분증권)", "20261026")
    core, sources = choose_core_disclosure([amendment, attachment])
    # core 는 [첨부정정] 아니고 [기재정정] 이어야
    assert core is not None
    assert core["rcept_no"] == "20261026000001"
    # sources 에는 둘 다 메타로 남음
    rcept_nos = {s["disclosure"]["rcept_no"] for s in sources}
    assert "20261026000367" in rcept_nos
    assert "20261026000001" in rcept_nos


def test_55_attachment_only_no_other_core_null():
    """지시 #55: [첨부정정] 만 있고 다른 신고서 없으면 core=None (호출자가 preserved 처리)."""
    attachment = _d("20261026000367", "[첨부정정]증권신고서(지분증권)", "20261026")
    core, _ = choose_core_disclosure([attachment])
    assert core is None


def test_55_attachment_only_vs_final_release():
    """[발행조건확정] 이 있으면 그게 우선. [첨부정정] 은 어차피 skip."""
    final = _d("20261020000001", "[발행조건확정]증권신고서(지분증권)", "20261020")
    attachment = _d("20261026000367", "[첨부정정]증권신고서(지분증권)", "20261026")
    core, _ = choose_core_disclosure([final, attachment])
    assert core is not None
    assert core["rcept_no"] == "20261020000001"


def test_55_attachment_only_via_regex():
    """`_is_attachment_only` 는 "[첨부정정]" 접두 포함 서술만 매치."""
    from app.collect import _is_attachment_only
    assert _is_attachment_only({"report_nm": "[첨부정정]증권신고서(지분증권)"}) is True
    assert _is_attachment_only({"report_nm": "[기재정정]증권신고서(지분증권)"}) is False
    assert _is_attachment_only({"report_nm": "증권신고서(지분증권)"}) is False
    assert _is_attachment_only({"report_nm": "[발행조건확정]증권신고서(지분증권)"}) is False


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
