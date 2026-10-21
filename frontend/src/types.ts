// .claude/co-work/api-contract.md (v1.6) 와 1:1 매칭. 변경 전 pm 과 협상.

// v0.8 CORRECTION = 정정 요구·일정 변경 가능
// v1.0 INCOMPLETE = 판정 보류·데이터 확인 필요 (미공시 0점 처리 폐지)
export type Status = 'PENDING' | 'PASS' | 'REJECT' | 'CORRECTION' | 'INCOMPLETE'

// v0.8: 정정 요구 정보 (`Verdict.correction`). 해당 없으면 null.
export interface Correction {
  requested_at: string          // 금감원 정정신고서 제출요구일 (YYYY-MM-DD)
  amended_at: string | null     // 그 이후 정정신고서 제출일. 아직이면 null
}

// v0.9 ChecklistItem.level — MET 일 때 단계 (현재 competition 만 사용).
export type ChecklistLevel = 'VERY_GOOD' | 'GOOD'
export type Grade = 'S' | 'A' | 'B' // v0.3: C 삭제
export type Market = 'KOSPI' | 'KOSDAQ' | 'KONEX'
export type PricePosition =
  | 'ABOVE_BAND'   // 확정가 > 밴드 상단
  | 'TOP_OF_BAND'  // 확정가 = 밴드 상단
  | 'WITHIN_BAND'  // 밴드 하단 <= 확정가 < 밴드 상단  (v0.3)
  | 'BELOW_BAND'   // 확정가 < 밴드 하단               (v0.3)
export type DocType =
  | 'PROSPECTUS'
  | 'PROSPECTUS_AMENDED'
  | 'REGISTRATION_AMENDED'
  | 'ISSUANCE_REPORT'
export type CompetitionRateType = 'simple' | 'weighted'
export type LockupRatioBasis = 'allocated' | 'applied'

// v1.5 (#22): 체크리스트는 4항목만 — min_deposit·sell_timing 삭제.
export type ChecklistKey =
  | 'competition'
  | 'price_position'
  | 'lockup'
  | 'flow'

export type ChecklistResult = 'MET' | 'NOT_MET' | 'UNKNOWN'

export interface ChecklistItem {
  key: ChecklistKey
  label: string
  indicator: string
  criterion: string
  actual: string | null
  result: ChecklistResult
  // v0.9 — MET 일 때만 사용되는 단계 (≥1500 VERY_GOOD, ≥1000 GOOD).
  // 다른 항목·결과는 null.
  level: ChecklistLevel | null
}

export interface Verdict {
  status: Status
  grade: Grade | null
  // PASS·REJECT 일 때 값. PENDING·CORRECTION 은 null. PASS 와 score_range 가 있는 경우 score = min.
  score: number | null
  correction: Correction | null  // v0.8 — status === 'CORRECTION' 이면 값, 그 외 null
  // v1.4: 미확인 지표가 있어도 결과가 바뀌지 않는 경우 범위로 확정.
  // PASS 확정 (min ≥ 50) · REJECT 확정 (max < 50) 둘 중 하나.
  // null 이거나 필드가 없으면 기존 단일 점수 표시로 degraded.
  score_range: { min: number; max: number } | null
}

export interface IpoSummary {
  id: string
  corp_name: string
  // MVP: 항상 null (requirements 8장)
  market: Market | null
  subscription_start: string | null
  subscription_end: string | null
  // MVP: 항상 null (requirements 8장)
  listing_date: string | null
  band_low: number | null
  band_high: number | null
  final_price: number | null
  verdict: Verdict
  // v1.1: 공모가 확정공고일 (이날 [발행조건확정] 공시로 기관 데이터 공개). 못 찾으면 null.
  price_confirm_date: string | null
  demand_forecast_start: string | null
  demand_forecast_end: string | null
  updated_at: string
}

export interface Indicators {
  competition_rate: number | null
  competition_rate_type: CompetitionRateType | null
  // 기관 신청 금액. v0.6: 가산 기준에서 제외됨 (참고 지표).
  demand_amount_krw: number | null
  price_position: PricePosition | null
  lockup_ratio: number | null
  lockup_ratio_basis: LockupRatioBasis | null
  tradable_ratio: number | null
  old_share_ratio: number | null
  new_share_count: number | null
  old_share_count: number | null
  total_offering_count: number | null
  // v0.6: 공모 금액. 원문 모집(매출) 총액 우선, 없으면 total_offering_count × final_price. 둘 다 없으면 null.
  // 대형주 보완 가산의 판정 기준.
  offering_amount_krw: number | null
  report_rcept_no: string | null
}

export interface Scores {
  comp: number | null   // 0~35
  price: number | null  // 0~25
  lockup: number | null // 0~20
  flow: number | null   // 0~20
  total: number | null  // 0~100
}

export interface SourceDoc {
  doc_type: DocType
  rcept_no: string
  rcept_dt: string
  url: string
}

// v1.6 (#23): MinDeposit interface 제거.

export interface IpoDetail extends IpoSummary {
  indicators: Indicators
  scores: Scores
  reasons: string[]
  reject_reasons: string[]
  // v1.6: `min_deposit` 는 폐지. backend 가 아직 보내도 UI 에서 참조하지 않음 — 타입에서도 제거.
  sources: SourceDoc[]
  // v1.5 (#22): 체크리스트 4항목 — min_deposit·sell_timing 삭제
  checklist: ChecklistItem[]
  // v1.2: 주관사·공동주관사 이름 (사람이 읽는 그대로). 빈 배열이면 미공시.
  underwriters: string[]
}

export interface ListParams {
  status?: Status
  from?: string
  to?: string
}

export interface Health {
  status: string
  last_collected_at: string | null
  // v1.5: backend #31 반영 예정. 미반영 응답은 필드 자체가 없을 수 있어 optional.
  parser_version?: string | null
  commit?: string | null
}

// --- v0.5 수집 실행 (POST /api/collect, GET /api/collect/status) ---------

export type CollectState = 'IDLE' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'

export interface CollectProgress {
  done: number
  total: number | null
}

export interface CollectSummary {
  new_count: number
  updated_count: number
  unchanged_count: number
  failed_count: number
  withdrawn_count: number
}

// v1.3: 실패 종목별 사유 (키·URL·경로 제거된 300자 이내 요약).
export interface CollectFailure {
  corp_code: string
  corp_name: string
  reason: string
}

export interface CollectStatus {
  status: CollectState
  started_at: string | null
  finished_at: string | null
  progress: CollectProgress | null
  summary: CollectSummary | null
  error: string | null
  // /api/health 와 동일한 "마지막 성공 수집 시각".
  last_collected_at: string | null
  // v1.3: 실패 종목·사유. backend 미반영 응답은 필드가 없을 수 있어 optional.
  failures?: CollectFailure[]
}

// POST /api/collect 응답 분기.
// 202 → STARTED(새 작업 시작, data=시작 직후 CollectStatus)
// 409 + CollectStatus → RUNNING(이미 실행 중, data=현재 상태)
// 409 + {detail:...} → BLOCKED(샘플 모드 등 수집 불가, 메시지만)
export type CollectStartResult =
  | { kind: 'STARTED'; data: CollectStatus }
  | { kind: 'RUNNING'; data: CollectStatus }
  | { kind: 'BLOCKED'; detail: string }

// GET /api/scoring-config v0.3 확정 구조
export interface ScoringTier {
  gte: number
  points: number
}

export interface ScoringConfig {
  score: {
    comp: {
      max: number
      tiers: ScoringTier[]
      default: number
      // v0.6: 신청 금액 기반 가산 폐지 → 공모 금액 + 경쟁률 기반 "대형주 보완" 가산.
      large_cap_bonus: {
        min_offering_amount_krw: number
        min_competition_rate: number
        points: number
      }
    }
    price: {
      max: number
      points: Record<PricePosition, number>
    }
    lockup: {
      max: number
      tiers: ScoringTier[]
      default: number
    }
    flow: {
      max: number
      zero_if: { tradable_gt: number; old_share_gte: number }
      top_if: { tradable_lt: number; old_share_eq: number; points: number }
      otherwise: number
    }
  }
  grade: {
    pass_min: number
    s_min: number
    a_min: number
  }
  // v1.6 (#23): deposit 삭제.
  checklist: {
    // v0.9: competition_min → good_min + very_good_min 로 분리.
    competition_good_min: number
    competition_very_good_min: number
    price_positions_met: PricePosition[]
    lockup_min: number
    flow_tradable_max: number
    flow_old_share_lt: number
  }
}
