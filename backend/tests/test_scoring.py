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
from app.schemas import CorrectionInfo, Indicators


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


# ---------------------- 미공시 (v1.4 — 지시 #27 범위 확정) ----------------------

def test_null_lockup_still_pass_when_range_locked(cfg):
    """v1.4 (지시 #27): lockup null 이지만 나머지가 충분하면 PASS 확정 — min 기준 등급."""
    r = evaluate(_ind(lockup_ratio=None), cfg)
    # comp 35 + price 20 + flow 20 (tradable 20·old 0 → top_if) = 75 (lockup 0 가정 min)
    # max = 75 + 20 = 95. min=75 >= 50 → PASS 확정
    assert r.status == "PASS"
    assert r.scores.lockup is None
    assert r.scores.total is None
    assert r.score_range is not None and r.score_range == (75, 95)
    # 등급은 min(75) 기준 — A (65 ≤ 75 < 80)
    assert r.grade == "A"
    assert any("최소" in line and "등급" in line for line in r.reasons)


def test_null_flow_pair_still_pass_when_range_locked(cfg):
    """v1.4: tradable null + old null 이지만 min=75 이상이면 PASS 확정."""
    r = evaluate(_ind(tradable_ratio=None, old_share_ratio=None), cfg)
    # comp 35 + price 20 + lockup 20 + flow {0,12,20} → min=75, max=95
    assert r.status == "PASS"
    assert r.scores.flow is None
    assert r.score_range == (75, 95)
    assert r.grade == "A"


def test_tradable_above_35_with_old_null_still_proceeds(cfg):
    """v1.0 유지: tradable > 35 → flow=0 확정 → scores.flow 에 0 들어감."""
    r = evaluate(_ind(tradable_ratio=40.0, old_share_ratio=None), cfg)
    # confirmed: comp 35 + price 20 + lockup 20 + flow 0 = 75 → PASS/A
    assert r.status == "PASS"
    assert r.scores.flow == 0
    assert r.score_range is None   # 모든 지표 확정 → 범위 없음


# ---------------------- 지시 #27: 범위 확정 (PASS / REJECT / INCOMPLETE) ----------------------

def test_27_incomplete_when_range_straddles_pass_min(cfg):
    """크리에이츠 시나리오: comp 0 + price 10 + lockup null + tradable null
    → min=10+0+0=10, max=10+20+20=50. max=50 은 50 미만 아님, min<50 → INCOMPLETE."""
    r = evaluate(_ind(
        competition_rate=240.46,         # tier 미달 → 0점
        price_position="WITHIN_BAND",     # 10점
        offering_amount_krw=1_000_000_000,
        lockup_ratio=None,
        tradable_ratio=None,
        old_share_ratio=0.0,
    ), cfg)
    assert r.status == "INCOMPLETE"
    assert r.grade is None
    assert r.scores.total is None
    assert r.score_range == (10, 50)


def test_27_reject_confirmed_when_max_below_pass_min(cfg):
    """max 가 pass_min 미만이면 REJECT 확정 (미확인 지표를 만점으로 가정해도 미달)."""
    # comp 0 + price 0 + lockup null + flow 확정(tradable>35 → 0) → min=max=0 → REJECT
    r = evaluate(_ind(
        competition_rate=100.0,          # 0점
        price_position="BELOW_BAND",      # 0점
        lockup_ratio=None,                # 가능범위 [0,20]
        tradable_ratio=50.0,              # > 35 → flow=0 확정
        old_share_ratio=None,
    ), cfg)
    assert r.status == "REJECT"
    assert r.scores.total is None
    assert r.score_range == (0, 20)
    assert any("최대" in line and "50" in line for line in r.reject_reasons)


def test_27_pass_confirmed_when_min_above_pass_min(cfg):
    """min 이 pass_min 이상이면 PASS 확정 (0점 가정해도 통과). 등급은 min 기준."""
    # 기본 _ind 는 tradable 20 · old 0 → flow 20 확정. lockup 만 null:
    # comp 35 + price 20 + flow 20 = 75 → min=75(+0 lockup), max=95(+20 lockup). min≥50 → PASS/A
    r = evaluate(_ind(lockup_ratio=None), cfg)
    assert r.status == "PASS"
    assert r.grade == "A"
    assert r.score_range == (75, 95)


def test_27_flow_subset_tradable_less_than_25_old_null(cfg):
    """tradable < 25 & old null → flow 가능값 {0, 12, 20}."""
    # comp 35 + price 20 + lockup 20 + flow {0,12,20} → min=75, max=95 → PASS/A
    r = evaluate(_ind(tradable_ratio=20.0, old_share_ratio=None), cfg)
    assert r.status == "PASS"
    assert r.grade == "A"
    assert r.score_range == (75, 95)


def test_27_flow_subset_25_to_35_old_null(cfg):
    """25 ≤ tradable ≤ 35 & old null → flow 가능값 {0, 12} (top_if 불가)."""
    # comp 35 + price 20 + lockup 20 + flow {0, 12} → min=75, max=87 → PASS/A (65 ≤ 75)
    r = evaluate(_ind(tradable_ratio=30.0, old_share_ratio=None), cfg)
    assert r.status == "PASS"
    assert r.scores.flow is None       # old_share 가 null 이라 flow 미확정
    assert r.score_range == (75, 87)   # min=20(lockup)+0, max=20(lockup)+12 를 confirmed_sum 55 에 더함


def test_27_boundary_min_equals_pass_min_is_pass(cfg):
    """경계: min == pass_min(50) → PASS 확정 (명세: '**min ≥ 50**')."""
    # comp 15 (rate 600 → tier 500) + price 10 (WITHIN) + lockup null + flow 확정 25...
    # 손쉽게: comp 25 (rate 1000) + price 25 (ABOVE) + lockup null → min = 50
    # flow 확정 되게 tradable>35: flow=0
    r = evaluate(_ind(
        competition_rate=1000.0,
        price_position="ABOVE_BAND",      # 25
        lockup_ratio=None,                # [0,20]
        tradable_ratio=50.0,              # flow=0 확정
        old_share_ratio=None,
    ), cfg)
    # confirmed = 25 + 25 + 0 = 50. lockup opts [0,20] → min=50, max=70
    assert r.status == "PASS"
    assert r.score_range == (50, 70)
    assert r.grade == "B"   # 50 → B (65 미만)


def test_27_verdict_carries_score_range_when_range_locked(cfg):
    """build_verdict 는 score_range 가 있으면 그대로 노출, score 는 null."""
    r = evaluate(_ind(lockup_ratio=None), cfg)
    v = build_verdict(r)
    assert v.status == "PASS"
    assert v.score is None
    assert v.score_range is not None
    assert v.score_range.min == 75
    assert v.score_range.max == 95


def test_27_verdict_score_range_null_when_all_confirmed(cfg):
    """모든 지표 확정이면 score_range null."""
    r = evaluate(_ind(), cfg)
    v = build_verdict(r)
    assert v.score is not None
    assert v.score_range is None


# ---------------------- 지시 #17: CORRECTION 상태 ----------------------

def test_17_correction_overrides_pending(cfg):
    """정정요구 정보가 있으면 PENDING 보다 먼저 CORRECTION. 지표가 null 이든 아니든 무관."""
    corr = CorrectionInfo(requested_at="2026-09-30", amended_at=None)
    r = evaluate(_ind(competition_rate=None, price_position=None), cfg, correction=corr)
    assert r.status == "CORRECTION"
    assert r.grade is None
    assert r.scores.total is None
    assert r.correction is not None
    assert r.correction.requested_at == "2026-09-30"
    assert r.correction.amended_at is None
    assert any("정정신고서 제출요구" in line for line in r.reasons)


def test_17_correction_overrides_pass(cfg):
    """정정요구가 있으면 지표가 모두 PASS 수준이어도 CORRECTION 로 가린다 (일정 자체 미확정)."""
    corr = CorrectionInfo(requested_at="2026-09-30", amended_at="2026-10-05")
    r = evaluate(_ind(), cfg, correction=corr)
    assert r.status == "CORRECTION"
    assert r.correction is not None
    assert r.correction.amended_at == "2026-10-05"
    assert any("기재정정 2026-10-05" in line for line in r.reasons)


def test_17_no_correction_normal_evaluation(cfg):
    """correction=None 전달이면 기존 로직(PASS/REJECT/INCOMPLETE)."""
    r = evaluate(_ind(), cfg, correction=None)
    assert r.status == "PASS"
    assert r.correction is None


def test_17_build_verdict_carries_correction(cfg):
    """build_verdict 가 correction 정보를 Verdict.correction 에 그대로 노출."""
    corr = CorrectionInfo(requested_at="2026-09-30", amended_at="2026-10-05")
    r = evaluate(_ind(), cfg, correction=corr)
    v = build_verdict(r)
    assert v.status == "CORRECTION"
    assert v.correction is not None
    assert v.correction.requested_at == "2026-09-30"
    assert v.correction.amended_at == "2026-10-05"
    assert v.score is None
    assert v.grade is None


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


# ---------------------- 지시 #18: 체크리스트 경쟁률 2단계 ----------------------

def _checklist_comp(cfg, rate):
    md = calc_min_deposit(10000, 10, cfg)
    cl = build_checklist(_ind(competition_rate=rate), md, cfg)
    return next(c for c in cl if c.key == "competition")


def test_18_competition_level_very_good_at_1500(cfg):
    """경계 1500 — VERY_GOOD 'MET'."""
    c = _checklist_comp(cfg, 1500.0)
    assert c.result == "MET"
    assert c.level == "VERY_GOOD"


def test_18_competition_level_good_just_above_1000(cfg):
    """경계 1000 → GOOD MET (1499.9 도 GOOD, 1500 미만)."""
    c = _checklist_comp(cfg, 1000.0)
    assert c.result == "MET"
    assert c.level == "GOOD"
    c2 = _checklist_comp(cfg, 1499.9)
    assert c2.result == "MET"
    assert c2.level == "GOOD"


def test_18_competition_level_not_met_below_1000(cfg):
    """999.9 → NOT_MET, level 없음."""
    c = _checklist_comp(cfg, 999.9)
    assert c.result == "NOT_MET"
    assert c.level is None


def test_18_competition_level_unknown_when_null(cfg):
    """null → UNKNOWN, level 없음."""
    c = _checklist_comp(cfg, None)
    assert c.result == "UNKNOWN"
    assert c.level is None


def test_18_competition_criterion_text_two_tier(cfg):
    """criterion 문구: '1,000:1 이상 좋음 · 1,500:1 이상 아주 좋음'."""
    c = _checklist_comp(cfg, 2000.0)
    assert "1,000:1 이상 좋음" in c.criterion
    assert "1,500:1 이상 아주 좋음" in c.criterion


def test_18_tnec_1041_is_met_good(cfg):
    """티앤이코리아 실측(rate 1041) → 체크리스트 MET + level=GOOD (운영 상세에서 '✗ 불만족' 사라져야 함)."""
    c = _checklist_comp(cfg, 1041.02)
    assert c.result == "MET"
    assert c.level == "GOOD"


def test_18_other_items_still_have_no_level(cfg):
    """level 은 competition 전용. 다른 항목은 None 유지."""
    md = calc_min_deposit(10000, 10, cfg)
    cl = build_checklist(_ind(), md, cfg)
    for item in cl:
        if item.key != "competition":
            assert item.level is None


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
