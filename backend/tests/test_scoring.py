"""판정 로직 단위 테스트 — v0.3 (하드 필터 폐지).

requirements.md v2 2~4·9장 + api-contract v0.3 판정 규칙·불변식 검증.
"""
from __future__ import annotations

from app.scoring import (
    build_checklist,
    build_verdict,
    calc_min_deposit,
    evaluate,
)
from app.schemas import Indicators


def _ind(**over):
    base = dict(
        competition_rate=2000.0,
        competition_rate_type="weighted",
        demand_amount_krw=1_000_000_000_000,
        price_position="TOP_OF_BAND",
        lockup_ratio=40.0,
        lockup_ratio_basis="allocated",
        tradable_ratio=20.0,
        old_share_ratio=0.0,
        new_share_count=8_000_000,
        old_share_count=0,
        total_offering_count=8_000_000,
        offering_amount_krw=50_000_000_000,     # 500억 — 가산 미달 (<1000억)
        report_rcept_no="20261024000022",
    )
    base.update(over)
    return Indicators(**base)


# ---------------------- PENDING ----------------------

def test_pending_when_competition_rate_null(cfg):
    r = evaluate(_ind(competition_rate=None), cfg)
    assert r.status == "PENDING"
    assert r.grade is None
    assert r.scores.total is None
    assert r.reject_reasons == []


def test_pending_when_price_position_null(cfg):
    r = evaluate(_ind(price_position=None), cfg)
    assert r.status == "PENDING"
    assert r.reject_reasons == []


def test_pending_invariant_all_scores_null(cfg):
    r = evaluate(_ind(competition_rate=None, price_position=None), cfg)
    assert r.status == "PENDING"
    assert r.scores.total is None
    assert r.scores.comp is None


# ---------------------- 하드 필터 폐지 (v0.3) — 미공시여도 PENDING, REJECT 아님 ----------------------

def test_hard_filter_abolished_low_competition_still_scored(cfg):
    # v0.3: 하드 필터 없음. 핵심 2개(경쟁률·공모가 위치)만 있으면 점수로만 판정.
    r = evaluate(_ind(competition_rate=400.0, price_position="BELOW_BAND"), cfg)
    assert r.status == "REJECT"
    assert r.scores.total is not None       # v0.3: REJECT 도 scores 보유
    assert r.scores.comp == 0 and r.scores.price == 0


# ---------------------- REJECT (v0.3: 점수 보유) ----------------------

def test_reject_keeps_scores_and_score(cfg):
    r = evaluate(
        _ind(
            competition_rate=400.0,       # 0
            demand_amount_krw=100_000_000_000,
            price_position="BELOW_BAND",  # 0
            lockup_ratio=3.0,             # 0
            tradable_ratio=50.0,          # 0 (zero_if)
            old_share_ratio=10.0,
        ),
        cfg,
    )
    assert r.status == "REJECT"
    assert r.grade is None
    assert r.scores.comp == 0 and r.scores.price == 0
    assert r.scores.lockup == 0 and r.scores.flow == 0
    assert r.scores.total == 0
    assert any("50점 미만" in m for m in r.reject_reasons)


def test_reject_near_threshold(cfg):
    # 1000:1(25) + WITHIN_BAND(10) + 10%(15) + flow 0(zero_if) = 50 → PASS B (경계)
    r = evaluate(
        _ind(
            competition_rate=1000.0,
            demand_amount_krw=100_000_000_000,
            price_position="WITHIN_BAND",
            lockup_ratio=10.0,
            tradable_ratio=40.0,          # >35 → 0
            old_share_ratio=5.0,
        ),
        cfg,
    )
    # 경계값 체크: 50점이면 PASS B
    assert r.scores.total == 50
    assert r.status == "PASS"
    assert r.grade == "B"


# ---------------------- PASS 등급 ----------------------

def test_pass_s_grade_with_bonus(cfg):
    """v0.6: 가산 조건 = 공모 금액 ≥ 1000억 AND 경쟁률 ≥ 800:1."""
    r = evaluate(
        _ind(
            competition_rate=2500.0,
            offering_amount_krw=500_000_000_000,  # 5000억 → 가산 조건 충족
            price_position="ABOVE_BAND",
            lockup_ratio=45.0,
            tradable_ratio=20.0,
            old_share_ratio=0.0,
        ),
        cfg,
    )
    # comp 35(+5 capped at 35) + price 25 + lockup 20 + flow 20 = 100
    assert r.scores.comp == 35
    assert r.scores.total == 100
    assert r.grade == "S"


def test_pass_a_grade(cfg):
    r = evaluate(
        _ind(
            competition_rate=1200.0,             # 25
            demand_amount_krw=1_000_000_000_000, # 가산 없음
            price_position="TOP_OF_BAND",        # 20
            lockup_ratio=15.0,                   # 15
            tradable_ratio=22.0,
            old_share_ratio=0.0,                 # 20 (top_if)
        ),
        cfg,
    )
    # 25+20+15+20 = 80 → S (경계) — A 등급 테스트는 다른 조합으로
    assert r.scores.total == 80
    assert r.grade == "S"


def test_pass_a_explicit_a(cfg):
    r = evaluate(
        _ind(
            competition_rate=1200.0,             # 25
            demand_amount_krw=1_000_000_000_000,
            price_position="WITHIN_BAND",        # 10
            lockup_ratio=25.0,                   # 20
            tradable_ratio=22.0,
            old_share_ratio=0.0,                 # 20
        ),
        cfg,
    )
    # 25+10+20+20 = 75 → A
    assert r.scores.total == 75
    assert r.grade == "A"


def test_pass_b_grade(cfg):
    r = evaluate(
        _ind(
            competition_rate=800.0,              # 15 (500~1000)
            demand_amount_krw=100_000_000_000,
            price_position="TOP_OF_BAND",        # 20
            lockup_ratio=10.0,                   # 15
            tradable_ratio=30.0,
            old_share_ratio=5.0,                 # otherwise 12
        ),
        cfg,
    )
    # 15+20+15+12 = 62 → B
    assert r.scores.total == 62
    assert r.grade == "B"


def test_large_cap_bonus_cap_at_max(cfg):
    # comp 가 이미 최상 35이면 가산해도 35 유지
    r = evaluate(
        _ind(
            competition_rate=1500.0,
            offering_amount_krw=200_000_000_000,   # 2000억 → 가산 조건 충족
            price_position="TOP_OF_BAND",
        ),
        cfg,
    )
    assert r.scores.comp == 35


def test_large_cap_bonus_lifts_from_lower_tier(cfg):
    # 1200(25) + 가산 5 → comp 30
    r = evaluate(
        _ind(
            competition_rate=1200.0,
            offering_amount_krw=150_000_000_000,   # 1500억
            price_position="TOP_OF_BAND",
        ),
        cfg,
    )
    assert r.scores.comp == 30


def test_large_cap_bonus_requires_both_conditions(cfg):
    """공모 금액만 충족, 경쟁률(<800:1) 미달 → 가산 없음."""
    r = evaluate(
        _ind(
            competition_rate=700.0,                # <800 → 가산 미달
            offering_amount_krw=500_000_000_000,   # 5000억
            price_position="TOP_OF_BAND",
        ),
        cfg,
    )
    # 경쟁률 700:1 → tier 500~1000 → 15. 가산 없음.
    assert r.scores.comp == 15


def test_large_cap_bonus_offering_threshold_boundary(cfg):
    # 공모 금액 999억 → 가산 없음
    r = evaluate(
        _ind(
            competition_rate=1000.0,
            offering_amount_krw=99_900_000_000,    # 999억
            price_position="TOP_OF_BAND",
        ),
        cfg,
    )
    assert r.scores.comp == 25
    # 1000억 정확히 → 가산 적용
    r2 = evaluate(
        _ind(
            competition_rate=1000.0,
            offering_amount_krw=100_000_000_000,
            price_position="TOP_OF_BAND",
        ),
        cfg,
    )
    assert r2.scores.comp == 30


def test_large_cap_bonus_competition_boundary(cfg):
    # 799:1 → tier 500~1000 → 15, 가산 X
    r = evaluate(
        _ind(
            competition_rate=799.0,
            offering_amount_krw=200_000_000_000,
            price_position="TOP_OF_BAND",
        ),
        cfg,
    )
    assert r.scores.comp == 15
    # 800:1 → 15 + 5 = 20
    r2 = evaluate(
        _ind(
            competition_rate=800.0,
            offering_amount_krw=200_000_000_000,
            price_position="TOP_OF_BAND",
        ),
        cfg,
    )
    assert r2.scores.comp == 20


def test_large_cap_bonus_not_applied_when_offering_null(cfg):
    r = evaluate(_ind(competition_rate=2000.0, offering_amount_krw=None), cfg)
    assert r.scores.comp == 35  # 가산 없이도 tier 1500 → 35


def test_large_cap_bonus_reason_line(cfg):
    r = evaluate(
        _ind(
            competition_rate=1000.0,
            offering_amount_krw=150_000_000_000,   # 1500억
            price_position="TOP_OF_BAND",
        ),
        cfg,
    )
    assert any("대형주 보완" in line for line in r.reasons)


# ---------------------- Flow 판정 순서 ----------------------

def test_flow_zero_by_tradable_gt(cfg):
    r = evaluate(_ind(tradable_ratio=36.0, old_share_ratio=0.0), cfg)
    assert r.scores.flow == 0


def test_flow_zero_by_old_share_gte_30(cfg):
    r = evaluate(_ind(tradable_ratio=20.0, old_share_ratio=30.0), cfg)
    assert r.scores.flow == 0


def test_flow_top_only_when_both(cfg):
    r = evaluate(_ind(tradable_ratio=24.9, old_share_ratio=0.0), cfg)
    assert r.scores.flow == 20


def test_flow_otherwise(cfg):
    r = evaluate(_ind(tradable_ratio=25.0, old_share_ratio=5.0), cfg)
    assert r.scores.flow == 12


# ---------------------- 미공시 (0점 + reasons) ----------------------

def test_null_lockup_zero_point_with_reason(cfg):
    r = evaluate(_ind(lockup_ratio=None), cfg)
    assert r.scores.lockup == 0
    assert any("확약" in line and "미공시" in line for line in r.reasons)


def test_null_flow_pair_zero_with_reason(cfg):
    r = evaluate(_ind(tradable_ratio=None, old_share_ratio=None), cfg)
    assert r.scores.flow == 0
    assert any("유통가능" in line and "미공시" in line for line in r.reasons)


# ---------------------- 증거금 v0.3 ----------------------

def test_min_deposit_includes_fee_and_total(cfg):
    d = calc_min_deposit(30_000, 10, cfg)
    assert d.shares == 10
    assert d.deposit_krw == 150_000
    assert d.fee_krw == 2000
    assert d.total_krw == 152_000


def test_min_deposit_custom_shares(cfg):
    d = calc_min_deposit(50_000, 20, cfg)
    assert d.deposit_krw == 500_000
    assert d.total_krw == 502_000


def test_min_deposit_none_when_no_price(cfg):
    assert calc_min_deposit(None, 10, cfg) is None


# ---------------------- 불변식 ----------------------

def test_verdict_score_equals_scores_total_pass(cfg):
    r = evaluate(_ind(), cfg)
    v = build_verdict(r)
    assert r.status == "PASS"
    assert v.score == r.scores.total


def test_verdict_score_equals_scores_total_reject(cfg):
    r = evaluate(_ind(competition_rate=200.0, price_position="BELOW_BAND",
                      lockup_ratio=0.0, tradable_ratio=60.0, old_share_ratio=40.0), cfg)
    v = build_verdict(r)
    assert r.status == "REJECT"
    assert v.score == r.scores.total
    assert v.grade is None  # REJECT 는 grade 없음


def test_verdict_null_when_pending(cfg):
    r = evaluate(_ind(competition_rate=None), cfg)
    v = build_verdict(r)
    assert v.score is None and v.grade is None


# ---------------------- 체크리스트 (v0.3) ----------------------

def test_checklist_six_items_fixed_order(cfg):
    md = calc_min_deposit(20000, 10, cfg)
    cl = build_checklist(_ind(), md, cfg)
    assert [c.key for c in cl] == [
        "competition", "price_position", "lockup", "flow", "min_deposit", "sell_timing"
    ]


def test_checklist_all_met_when_strong(cfg):
    md = calc_min_deposit(50000, 10, cfg)
    cl = build_checklist(_ind(), md, cfg)
    by_key = {c.key: c for c in cl}
    assert by_key["competition"].result == "MET"
    assert by_key["price_position"].result == "MET"
    assert by_key["lockup"].result == "MET"
    assert by_key["flow"].result == "MET"
    assert by_key["min_deposit"].result == "INFO"
    assert by_key["sell_timing"].result == "INFO"


def test_checklist_unknown_when_values_null(cfg):
    ind = _ind(
        competition_rate=None,
        price_position=None,
        lockup_ratio=None,
        tradable_ratio=None,
        old_share_ratio=None,
    )
    cl = build_checklist(ind, None, cfg)
    by_key = {c.key: c for c in cl}
    for k in ["competition", "price_position", "lockup", "flow"]:
        assert by_key[k].result == "UNKNOWN"
        assert by_key[k].actual is None
    assert by_key["min_deposit"].actual is None  # 확정가 없으면 None
    assert by_key["sell_timing"].result == "INFO"


def test_checklist_flow_strict_less_than_30(cfg):
    """requirements 9장 확인 — flow MET 조건은 old_share < 30 (strict '<', equal 포함 안 함)."""
    md = calc_min_deposit(10000, 10, cfg)
    # old_share == 30.0 → NOT_MET
    cl = build_checklist(_ind(tradable_ratio=20.0, old_share_ratio=30.0), md, cfg)
    assert next(c for c in cl if c.key == "flow").result == "NOT_MET"
    # old_share == 29.99 → MET
    cl2 = build_checklist(_ind(tradable_ratio=20.0, old_share_ratio=29.99), md, cfg)
    assert next(c for c in cl2 if c.key == "flow").result == "MET"


def test_checklist_not_met_when_values_fail(cfg):
    md = calc_min_deposit(10000, 10, cfg)
    ind = _ind(
        competition_rate=800.0,                 # < 1500 → NOT_MET
        price_position="BELOW_BAND",            # not in met set → NOT_MET
        lockup_ratio=5.0,                       # < 10 → NOT_MET
        tradable_ratio=40.0,
        old_share_ratio=15.0,                   # tradable > 35 → flow NOT_MET
    )
    cl = build_checklist(ind, md, cfg)
    by_key = {c.key: c for c in cl}
    assert by_key["competition"].result == "NOT_MET"
    assert by_key["price_position"].result == "NOT_MET"
    assert by_key["lockup"].result == "NOT_MET"
    assert by_key["flow"].result == "NOT_MET"


def test_checklist_actual_formats(cfg):
    md = calc_min_deposit(28000, 10, cfg)
    cl = build_checklist(_ind(), md, cfg, listing_date=None)
    by_key = {c.key: c for c in cl}
    assert by_key["competition"].actual == "2,000.00:1"
    assert by_key["price_position"].actual == "밴드 최상단"
    assert by_key["lockup"].actual == "40.0%"
    assert by_key["flow"].actual == "유통 20.0% · 구주 0.0%"
    assert by_key["min_deposit"].actual == "10주 · 140,000원 + 수수료 2,000원"
    assert by_key["sell_timing"].actual is None   # listing_date 없음 → null


def test_checklist_sell_timing_with_listing_date(cfg):
    md = calc_min_deposit(28000, 10, cfg)
    cl = build_checklist(_ind(), md, cfg, listing_date="2026-12-05")
    by_key = {c.key: c for c in cl}
    assert by_key["sell_timing"].actual == "상장일 2026-12-05"


def test_checklist_criterion_min_deposit_from_config(cfg):
    md = calc_min_deposit(28000, 10, cfg)
    cl = build_checklist(_ind(), md, cfg)
    md_item = next(c for c in cl if c.key == "min_deposit")
    # 설정값 반영 — "(확정 공모가 × 10주) × 0.5 + 수수료 약 2,000원"
    assert "10주" in md_item.criterion
    assert "0.5" in md_item.criterion
    assert "2,000원" in md_item.criterion


def test_checklist_criterion_sell_timing_spec(cfg):
    cl = build_checklist(_ind(), None, cfg)
    item = next(c for c in cl if c.key == "sell_timing")
    assert item.criterion == "상장일 시초가 ~ 오전 10시 이전 매도"
