"""판정 로직 — v0.3 (하드 필터 폐지, 점수만으로 판정 + 체크리스트).

정본: requirements.md v2 2~4·6·9장 + api-contract.md v0.3 판정 규칙 표.
기준값은 config_files/scoring.yaml 에서 읽는다(코드 수정 없이 조정).

판정 상태 불변식 (v0.3):
- PENDING: competition_rate 또는 price_position 중 하나라도 null
  → scores 전부 null, verdict.grade/score null, reject_reasons 빈 배열
- PASS: 두 값 모두 있고 총점 >= pass_min (기본 50)
  → verdict.score == scores.total, grade 는 s_min/a_min 로 구분, reject_reasons 빈 배열
- REJECT: 두 값 모두 있고 총점 < pass_min
  → verdict.score == scores.total, grade = null, reject_reasons >= 1

주: 하드 필터 없음. 미공시 → REJECT 금지 (PENDING).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import ScoringConfig
from .schemas import (
    ChecklistItem,
    Grade,
    IpoDetail,
    IpoSummary,
    Indicators,
    MinDeposit,
    PricePosition,
    Scores,
    Status,
    Verdict,
)


@dataclass
class EvaluationResult:
    status: Status
    grade: Optional[Grade]
    scores: Scores
    reasons: list[str]
    reject_reasons: list[str]


# ---------- PENDING ----------

def _is_pending(ind: Indicators) -> bool:
    return ind.competition_rate is None or ind.price_position is None


# ---------- 지표별 점수 ----------

def _score_comp(
    rate: float,
    offering_amount_krw: Optional[int],
    cfg: ScoringConfig,
) -> tuple[int, bool]:
    """
    (최종점수, 대형주 보완 가산 적용 여부).
    tiers 중 처음 만족하는 점수 → large_cap_bonus 조건(공모 금액·경쟁률 둘 다) 만족이면 가산 → max 상한.
    v0.6 변경: demand_amount_krw(파생값) 대신 offering_amount_krw + 경쟁률 조건 사용.
    """
    s = cfg.score.comp
    base = s.default
    for tier in s.tiers:
        if rate >= tier.gte:
            base = tier.points
            break
    bonus_applied = False
    bonus = s.large_cap_bonus
    if (
        offering_amount_krw is not None
        and offering_amount_krw >= bonus.min_offering_amount_krw
        and rate >= bonus.min_competition_rate
    ):
        base += bonus.points
        bonus_applied = True
    return min(base, s.max), bonus_applied


def _score_price(pos: PricePosition, cfg: ScoringConfig) -> int:
    return cfg.score.price.points[pos]


def _score_lockup(ratio: Optional[float], cfg: ScoringConfig) -> int:
    """null → 0 (호출자가 미공시 reason 추가)."""
    s = cfg.score.lockup
    if ratio is None:
        return 0
    for tier in s.tiers:
        if ratio >= tier.gte:
            return tier.points
    return s.default


def _score_flow(
    tradable: Optional[float],
    old_share: Optional[float],
    cfg: ScoringConfig,
) -> int:
    """판정 순서: zero_if → top_if → otherwise. 지표 하나라도 null → 0."""
    s = cfg.score.flow
    if tradable is None or old_share is None:
        return 0
    # zero_if (OR)
    if tradable > s.zero_if.tradable_gt or old_share >= s.zero_if.old_share_gte:
        return 0
    # top_if (AND)
    if tradable < s.top_if.tradable_lt and old_share == s.top_if.old_share_eq:
        return s.top_if.points
    return s.otherwise


def _grade(total: int, cfg: ScoringConfig) -> Optional[Grade]:
    """PASS 등급. REJECT (total < pass_min) 는 None."""
    g = cfg.grade
    if total < g.pass_min:
        return None
    if total >= g.s_min:
        return "S"
    if total >= g.a_min:
        return "A"
    return "B"


# ---------- 근거 문장 ----------

def _is_incomplete(ind: Indicators) -> bool:
    """v1.0 (지시 #19): 경쟁률·가격 있지만 다음 지표 중 하나라도 null 이면 판정 보류.

    - lockup_ratio null
    - tradable_ratio null
    - tradable ≤ 35 이면서 old_share null (flow 가 0 로 확정될 수 없음)

    tradable > 35 이면 어차피 flow=0 (zero_if) 로 확정되므로 old_share null 이어도 PASS/REJECT 진행 가능.
    """
    if ind.lockup_ratio is None:
        return True
    if ind.tradable_ratio is None:
        return True
    if ind.tradable_ratio <= 35 and ind.old_share_ratio is None:
        return True
    return False


def _reason_lines(
    ind: Indicators,
    scores: Scores,
    comp_bonus_applied: bool,
    cfg: ScoringConfig,
) -> list[str]:
    """사용자 노출용 한국어 판정 근거.

    v1.0 (지시 #19): "미공시 — 0점 처리" 문구 제거. 미공시 지표는 status=INCOMPLETE 분기에서
    "○○ 확인 필요 — 판정 보류" 로 별도 기록(아래 incomplete_reason_lines).
    여기서는 **확정된 지표만** 점수 라인을 출력한다.
    """
    lines: list[str] = []
    assert ind.competition_rate is not None
    assert ind.price_position is not None

    comp_line = f"기관 수요예측 경쟁률 {ind.competition_rate:,.1f}:1 → {scores.comp}/{cfg.score.comp.max}점"
    lines.append(comp_line)
    if comp_bonus_applied:
        bonus = cfg.score.comp.large_cap_bonus
        offering = ind.offering_amount_krw or 0
        lines.append(
            f"대형주 보완 +{bonus.points}점 "
            f"(공모 금액 {offering/100000000:,.0f}억 원, 경쟁률 {ind.competition_rate:,.1f}:1)"
        )

    pos_label = {
        "ABOVE_BAND": "밴드 상단 초과",
        "TOP_OF_BAND": "밴드 최상단",
        "WITHIN_BAND": "밴드 내",
        "BELOW_BAND": "밴드 하단 미만",
    }[ind.price_position]
    lines.append(f"확정 공모가 위치: {pos_label} → {scores.price}/{cfg.score.price.max}점")

    if ind.lockup_ratio is not None and scores.lockup is not None:
        lines.append(
            f"기관 의무보유확약 비율 {ind.lockup_ratio:.1f}% → {scores.lockup}/{cfg.score.lockup.max}점"
        )
    if ind.tradable_ratio is not None and scores.flow is not None:
        old_s = ind.old_share_ratio if ind.old_share_ratio is not None else 0.0
        lines.append(
            f"상장일 유통가능 {ind.tradable_ratio:.1f}%, 구주매출 {old_s:.1f}% "
            f"→ {scores.flow}/{cfg.score.flow.max}점"
        )

    return lines


def _incomplete_reasons(ind: Indicators) -> list[str]:
    """INCOMPLETE 상태에서 "○○ 확인 필요 — 판정 보류" 라인들."""
    lines: list[str] = []
    assert ind.competition_rate is not None
    assert ind.price_position is not None
    # 확정된 지표도 확인용으로 짧게 같이 보여줌
    lines.append(f"기관 수요예측 경쟁률 {ind.competition_rate:,.1f}:1")
    lines.append(f"확정 공모가 위치: {ind.price_position}")
    if ind.lockup_ratio is None:
        lines.append("의무보유확약 비율 확인 필요 — 판정 보류")
    if ind.tradable_ratio is None:
        lines.append("유통가능 비율 확인 필요 — 판정 보류")
    elif ind.tradable_ratio <= 35 and ind.old_share_ratio is None:
        lines.append("구주매출 비율 확인 필요 — 판정 보류 (유통가능 ≤ 35% 로 flow 점수가 확정되지 않음)")
    return lines


# ---------- 공개 API ----------

def evaluate(ind: Indicators, cfg: ScoringConfig) -> EvaluationResult:
    """지표를 받아 상태·점수·등급·근거를 계산."""
    if _is_pending(ind):
        return EvaluationResult(
            status="PENDING",
            grade=None,
            scores=Scores(),
            reasons=["정정 증권신고서(수요예측 결과) 공시 전으로 판정 대기 중입니다."],
            reject_reasons=[],
        )

    assert ind.competition_rate is not None
    assert ind.price_position is not None

    # v1.0 (지시 #19): 미공시 지표가 있으면 INCOMPLETE (0점으로 묻히지 않음).
    if _is_incomplete(ind):
        comp, _bonus = _score_comp(ind.competition_rate, ind.offering_amount_krw, cfg)
        price = _score_price(ind.price_position, cfg)
        lockup = _score_lockup(ind.lockup_ratio, cfg) if ind.lockup_ratio is not None else None
        if ind.tradable_ratio is not None and (ind.tradable_ratio > 35 or ind.old_share_ratio is not None):
            flow = _score_flow(ind.tradable_ratio, ind.old_share_ratio, cfg)
        else:
            flow = None
        return EvaluationResult(
            status="INCOMPLETE",
            grade=None,
            scores=Scores(comp=comp, price=price, lockup=lockup, flow=flow, total=None),
            reasons=_incomplete_reasons(ind),
            reject_reasons=[],
        )

    comp, bonus = _score_comp(ind.competition_rate, ind.offering_amount_krw, cfg)
    price = _score_price(ind.price_position, cfg)
    lockup = _score_lockup(ind.lockup_ratio, cfg)
    flow = _score_flow(ind.tradable_ratio, ind.old_share_ratio, cfg)
    total = comp + price + lockup + flow
    scores = Scores(comp=comp, price=price, lockup=lockup, flow=flow, total=total)
    reasons = _reason_lines(ind, scores, bonus, cfg)
    grade = _grade(total, cfg)

    if grade is None:
        return EvaluationResult(
            status="REJECT",
            grade=None,
            scores=scores,
            reasons=reasons,
            reject_reasons=[f"종합 점수 {total}점 — {cfg.grade.pass_min}점 미만"],
        )

    return EvaluationResult(
        status="PASS",
        grade=grade,
        scores=scores,
        reasons=reasons,
        reject_reasons=[],
    )


# ---------- 증거금 (v0.3: fee_krw / total_krw) ----------

def calc_min_deposit(
    final_price: Optional[int], shares: int, cfg: ScoringConfig
) -> Optional[MinDeposit]:
    """균등 배정 최소 증거금. 확정가 없으면 None."""
    if final_price is None:
        return None
    deposit = int(shares * final_price * cfg.deposit.margin_rate)
    fee = cfg.deposit.fee_krw
    return MinDeposit(
        shares=shares,
        deposit_krw=deposit,
        fee_krw=fee,
        total_krw=deposit + fee,
    )


# ---------- 체크리스트 (requirements.md 9장, v0.3) ----------

def _fmt_rate(ind: Indicators) -> Optional[str]:
    if ind.competition_rate is None:
        return None
    return f"{ind.competition_rate:,.2f}:1"


def _fmt_price_position(ind: Indicators) -> Optional[str]:
    pos = ind.price_position
    if pos is None:
        return None
    return {
        "ABOVE_BAND": "밴드 상단 초과",
        "TOP_OF_BAND": "밴드 최상단",
        "WITHIN_BAND": "밴드 내",
        "BELOW_BAND": "밴드 하단 미만",
    }[pos]


def _fmt_lockup(ind: Indicators) -> Optional[str]:
    if ind.lockup_ratio is None:
        return None
    return f"{ind.lockup_ratio:.1f}%"


def _fmt_flow(ind: Indicators) -> Optional[str]:
    if ind.tradable_ratio is None or ind.old_share_ratio is None:
        return None
    return f"유통 {ind.tradable_ratio:.1f}% · 구주 {ind.old_share_ratio:.1f}%"


def _fmt_min_deposit(md: Optional[MinDeposit]) -> Optional[str]:
    if md is None:
        return None
    return f"{md.shares}주 · {md.deposit_krw:,}원 + 수수료 {md.fee_krw:,}원"


def build_checklist(
    ind: Indicators,
    md: Optional[MinDeposit],
    cfg: ScoringConfig,
    *,
    listing_date: Optional[str] = None,
) -> list[ChecklistItem]:
    """6항목 고정 순서. PENDING 종목도 호출된다 — UNKNOWN 비율이 자연히 많아진다."""
    cl = cfg.checklist
    items: list[ChecklistItem] = []

    # 1) competition
    actual = _fmt_rate(ind)
    if ind.competition_rate is None:
        comp_result = "UNKNOWN"
    elif ind.competition_rate >= cl.competition_min:
        comp_result = "MET"
    else:
        comp_result = "NOT_MET"
    items.append(ChecklistItem(
        key="competition",
        label="기관 경쟁률",
        indicator="기관 수요예측 경쟁률",
        criterion=f"{cl.competition_min:,.0f}:1 이상",
        actual=actual,
        result=comp_result,
    ))

    # 2) price_position
    pos_actual = _fmt_price_position(ind)
    if ind.price_position is None:
        pp_result = "UNKNOWN"
    elif ind.price_position in cl.price_positions_met:
        pp_result = "MET"
    else:
        pp_result = "NOT_MET"
    pp_criterion = " 또는 ".join(
        {"ABOVE_BAND": "밴드 상단 초과", "TOP_OF_BAND": "밴드 최상단",
         "WITHIN_BAND": "밴드 내", "BELOW_BAND": "밴드 하단 미만"}[p]
        for p in cl.price_positions_met
    )
    items.append(ChecklistItem(
        key="price_position",
        label="공모가 위치",
        indicator="확정 공모가 밴드 위치",
        criterion=pp_criterion,
        actual=pos_actual,
        result=pp_result,
    ))

    # 3) lockup
    lk_actual = _fmt_lockup(ind)
    if ind.lockup_ratio is None:
        lk_result = "UNKNOWN"
    elif ind.lockup_ratio >= cl.lockup_min:
        lk_result = "MET"
    else:
        lk_result = "NOT_MET"
    items.append(ChecklistItem(
        key="lockup",
        label="의무보유 확약",
        indicator="기관 확약 비율",
        criterion=f"{cl.lockup_min:.0f}% 이상",
        actual=lk_actual,
        result=lk_result,
    ))

    # 4) flow
    fl_actual = _fmt_flow(ind)
    if ind.tradable_ratio is None or ind.old_share_ratio is None:
        fl_result = "UNKNOWN"
    elif ind.tradable_ratio <= cl.flow_tradable_max and ind.old_share_ratio < cl.flow_old_share_lt:
        fl_result = "MET"
    else:
        fl_result = "NOT_MET"
    items.append(ChecklistItem(
        key="flow",
        label="유통 가능 물량",
        indicator="유통가능 비율 · 구주매출 비율",
        criterion=f"유통 {cl.flow_tradable_max:.0f}% 이하 그리고 구주매출 {cl.flow_old_share_lt:.0f}% 미만",
        actual=fl_actual,
        result=fl_result,
    ))

    # 5) min_deposit (INFO) — frontend 가 그대로 노출. 설정값 반영.
    md_cfg = cfg.deposit
    items.append(ChecklistItem(
        key="min_deposit",
        label="최소 증거금",
        indicator="균등배정 최소 증거금 (수수료 포함)",
        criterion=(
            f"(확정 공모가 × {md_cfg.default_shares}주) × {md_cfg.margin_rate} "
            f"+ 수수료 약 {md_cfg.fee_krw:,}원"
        ),
        actual=_fmt_min_deposit(md),
        result="INFO",
    ))

    # 6) sell_timing (INFO)
    items.append(ChecklistItem(
        key="sell_timing",
        label="매도 타이밍",
        indicator="상장일 매도 시점",
        criterion="상장일 시초가 ~ 오전 10시 이전 매도",
        actual=(f"상장일 {listing_date}" if listing_date else None),
        result="INFO",
    ))

    return items


# ---------- 요약·verdict ----------

def summary_from_detail(detail: IpoDetail) -> IpoSummary:
    return IpoSummary(
        id=detail.id,
        corp_name=detail.corp_name,
        market=detail.market,
        subscription_start=detail.subscription_start,
        subscription_end=detail.subscription_end,
        listing_date=detail.listing_date,
        band_low=detail.band_low,
        band_high=detail.band_high,
        final_price=detail.final_price,
        verdict=detail.verdict,
        updated_at=detail.updated_at,
    )


def build_verdict(result: EvaluationResult) -> Verdict:
    """불변식: PASS·REJECT 모두 score 존재(scores.total 과 동일). grade 는 PASS 일 때만."""
    return Verdict(status=result.status, grade=result.grade, score=result.scores.total)
