import type {
  ChecklistItem,
  ChecklistLevel,
  CollectStartResult,
  CollectStatus,
  Health,
  Indicators,
  IpoDetail,
  IpoSummary,
  ListParams,
  MinDeposit,
  ScoringConfig,
} from '../types'
import { fmtKrw, fmtPct, fmtRatio } from '../utils/format'
import { HttpError } from '../utils/httpError'

// --- scoring config (mock) — api-contract v1.0 ---------------------------
const CONFIG: ScoringConfig = {
  score: {
    comp: {
      max: 35,
      tiers: [
        { gte: 1500, points: 35 },
        { gte: 1000, points: 25 },
        { gte: 500, points: 15 },
      ],
      default: 0,
      large_cap_bonus: {
        min_offering_amount_krw: 100_000_000_000,
        min_competition_rate: 800,
        points: 5,
      },
    },
    price: {
      max: 25,
      points: { ABOVE_BAND: 25, TOP_OF_BAND: 20, WITHIN_BAND: 10, BELOW_BAND: 0 },
    },
    lockup: {
      max: 20,
      tiers: [
        { gte: 20, points: 20 },
        { gte: 10, points: 15 },
        { gte: 5, points: 10 },
      ],
      default: 0,
    },
    flow: {
      max: 20,
      zero_if: { tradable_gt: 35, old_share_gte: 30 },
      top_if: { tradable_lt: 25, old_share_eq: 0, points: 20 },
      otherwise: 12,
    },
  },
  grade: { pass_min: 50, s_min: 80, a_min: 65 },
  deposit: { default_shares: 10, margin_rate: 0.5, fee_krw: 2000 },
  checklist: {
    // v0.9: competition_min → good_min + very_good_min
    competition_good_min: 1000,
    competition_very_good_min: 1500,
    price_positions_met: ['TOP_OF_BAND', 'ABOVE_BAND'],
    lockup_min: 10,
    flow_tradable_max: 35,
    flow_old_share_lt: 30,
  },
}

const dartUrl = (rcept_no: string) =>
  `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${rcept_no}`

const PENDING_ID = '00111111'
const PASS_S_ID = '00222222'
const REJECT_ID = '00333333'
const INCOMPLETE_LOCKUP_ID = '00444444'   // v1.0: 과거 PASS A null-lockup → INCOMPLETE
const PASS_B_ID = '00555555'
const PASS_A_NOV_ID = '00666666'
const PENDING_NOV_ID = '00777777'
const PASS_B_DEC_ID = '00888888'
const PASS_A_LARGECAP_ID = '00999999'
const CORRECTION_UNAMENDED_ID = '01020201' // v0.8: 정정요구 미제출
const CORRECTION_AMENDED_ID = '01020202'   // v0.8: 정정요구 → 정정신고서 제출됨

// --- summaries ------------------------------------------------------------

const summaries: IpoSummary[] = [
  {
    id: PASS_S_ID,
    corp_name: '노브랜드컴퍼니',
    market: 'KOSPI',
    subscription_start: '2026-10-27',
    subscription_end: '2026-10-28',
    listing_date: '2026-11-11',
    band_low: 36000,
    band_high: 42000,
    final_price: 45000,
    verdict: { status: 'PASS', grade: 'S', score: 100, correction: null },
    price_confirm_date: '2026-10-24',
    demand_forecast_start: '2026-10-22',
    demand_forecast_end: '2026-10-23',
    updated_at: '2026-10-24T18:30:00+09:00',
  },
  {
    id: INCOMPLETE_LOCKUP_ID,
    corp_name: '미드스트림솔루션',
    market: 'KOSDAQ',
    subscription_start: '2026-10-29',
    subscription_end: '2026-10-30',
    listing_date: '2026-11-12',
    band_low: 19000,
    band_high: 23000,
    final_price: 23000,
    // v1.0: lockup null → INCOMPLETE (0점 처리 폐지)
    verdict: { status: 'INCOMPLETE', grade: null, score: null, correction: null },
    price_confirm_date: '2026-10-26',
    demand_forecast_start: '2026-10-23',
    demand_forecast_end: '2026-10-24',
    updated_at: '2026-10-26T17:00:00+09:00',
  },
  {
    id: PASS_B_ID,
    corp_name: '한양스마트메탈',
    market: null,
    subscription_start: '2026-10-29',
    subscription_end: '2026-10-30',
    listing_date: null,
    band_low: 11000,
    band_high: 13000,
    final_price: 11800,
    verdict: { status: 'PASS', grade: 'B', score: 52, correction: null },
    price_confirm_date: '2026-10-26',
    demand_forecast_start: '2026-10-23',
    demand_forecast_end: '2026-10-24',
    updated_at: '2026-10-26T17:30:00+09:00',
  },
  {
    id: REJECT_ID,
    corp_name: '하이퀄리티인프라',
    market: 'KOSDAQ',
    subscription_start: '2026-10-30',
    subscription_end: '2026-10-31',
    listing_date: '2026-11-13',
    band_low: 15000,
    band_high: 18000,
    final_price: 14000,
    verdict: { status: 'REJECT', grade: null, score: 15, correction: null },
    price_confirm_date: '2026-10-28',
    demand_forecast_start: '2026-10-24',
    demand_forecast_end: '2026-10-25',
    updated_at: '2026-10-28T17:10:00+09:00',
  },
  {
    id: PENDING_ID,
    corp_name: '리커머스코퍼레이션',
    market: 'KOSDAQ',
    subscription_start: '2026-11-05',
    subscription_end: '2026-11-06',
    listing_date: null,
    band_low: 24000,
    band_high: 28000,
    final_price: null,
    verdict: { status: 'PENDING', grade: null, score: null, correction: null },
    price_confirm_date: '2026-11-03',
    demand_forecast_start: '2026-10-30',
    demand_forecast_end: '2026-10-31',
    updated_at: '2026-10-18T09:10:00+09:00',
  },
  {
    id: PASS_A_NOV_ID,
    corp_name: '엑스퍼트푸드',
    market: 'KOSPI',
    subscription_start: '2026-11-10',
    subscription_end: '2026-11-11',
    listing_date: '2026-11-20',
    band_low: 32000,
    band_high: 38000,
    final_price: 38000,
    verdict: { status: 'PASS', grade: 'A', score: 70, correction: null },
    price_confirm_date: '2026-11-05',
    demand_forecast_start: '2026-11-03',
    demand_forecast_end: '2026-11-04',
    updated_at: '2026-11-07T16:40:00+09:00',
  },
  {
    id: CORRECTION_UNAMENDED_ID,
    corp_name: '정정요구다비오',
    market: 'KOSDAQ',
    subscription_start: '2026-11-16',
    subscription_end: '2026-11-17',
    listing_date: null,
    band_low: 14000,
    band_high: 17000,
    final_price: null,
    verdict: {
      status: 'CORRECTION',
      grade: null,
      score: null,
      correction: { requested_at: '2026-11-10', amended_at: null },
    },
    price_confirm_date: '2026-11-13',
    demand_forecast_start: '2026-11-10',
    demand_forecast_end: '2026-11-11',
    updated_at: '2026-11-10T15:00:00+09:00',
  },
  {
    id: PENDING_NOV_ID,
    corp_name: '뉴웨이브바이오',
    market: null,
    subscription_start: '2026-11-18',
    subscription_end: '2026-11-19',
    listing_date: null,
    band_low: 16000,
    band_high: 20000,
    final_price: null,
    verdict: { status: 'PENDING', grade: null, score: null, correction: null },
    price_confirm_date: '2026-11-16',
    demand_forecast_start: '2026-11-12',
    demand_forecast_end: '2026-11-13',
    updated_at: '2026-11-02T10:00:00+09:00',
  },
  {
    id: CORRECTION_AMENDED_ID,
    corp_name: '정정요구유캐스트',
    market: 'KOSDAQ',
    subscription_start: '2026-11-22',
    subscription_end: '2026-11-23',
    listing_date: null,
    band_low: 9000,
    band_high: 12000,
    final_price: null,
    verdict: {
      status: 'CORRECTION',
      grade: null,
      score: null,
      // 정정신고서는 제출됐지만 발행조건확정 전이므로 여전히 CORRECTION 유지.
      correction: { requested_at: '2026-11-15', amended_at: '2026-11-18' },
    },
    price_confirm_date: '2026-11-19',
    demand_forecast_start: '2026-11-16',
    demand_forecast_end: '2026-11-17',
    updated_at: '2026-11-18T14:20:00+09:00',
  },
  {
    id: PASS_A_LARGECAP_ID,
    corp_name: '큰물결디스플레이',
    market: 'KOSPI',
    subscription_start: '2026-11-24',
    subscription_end: '2026-11-25',
    listing_date: '2026-12-04',
    band_low: 60000,
    band_high: 70000,
    final_price: 70000,
    verdict: { status: 'PASS', grade: 'A', score: 77, correction: null },
    price_confirm_date: '2026-11-20',
    demand_forecast_start: '2026-11-18',
    demand_forecast_end: '2026-11-19',
    updated_at: '2026-11-22T18:40:00+09:00',
  },
  {
    id: PASS_B_DEC_ID,
    corp_name: '그린팜케미컬',
    market: 'KOSDAQ',
    subscription_start: '2026-12-08',
    subscription_end: '2026-12-09',
    listing_date: '2026-12-18',
    band_low: 9000,
    band_high: 11000,
    final_price: 10500,
    verdict: { status: 'PASS', grade: 'B', score: 55, correction: null },
    price_confirm_date: '2026-12-04',
    demand_forecast_start: '2026-12-02',
    demand_forecast_end: '2026-12-03',
    updated_at: '2026-12-05T15:20:00+09:00',
  },
]

type DetailSeed = Omit<IpoDetail, 'min_deposit' | 'checklist'>

const seed: Record<string, DetailSeed> = {
  [PASS_S_ID]: {
    ...summaries.find(s => s.id === PASS_S_ID)!,
    indicators: {
      competition_rate: 2134.7,
      competition_rate_type: 'simple',
      demand_amount_krw: 61_200_000_000_000,
      price_position: 'ABOVE_BAND',
      lockup_ratio: 42.3,
      lockup_ratio_basis: 'allocated',
      tradable_ratio: 21.5,
      old_share_ratio: 0,
      new_share_count: 2_800_000,
      old_share_count: 0,
      total_offering_count: 2_800_000,
      offering_amount_krw: 126_000_000_000,
      report_rcept_no: '20261024000222',
    },
    scores: { comp: 35, price: 25, lockup: 20, flow: 20, total: 100 },
    reasons: [
      '기관 경쟁률 2,134.7:1 (≥ 1,500) — 35점.',
      '대형주 보완 +5점 (공모 1,260억 ≥ 1,000억 그리고 경쟁률 2,134:1 ≥ 800:1) — 캡 35점 유지.',
      '확정 공모가 45,000원 (희망 밴드 상단 42,000원 초과) — 25점.',
      '의무보유 확약 42.3% (≥ 20%) — 20점.',
      '상장 당일 유통가능 21.5% + 구주매출 0% — 20점.',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261010000222', rcept_dt: '2026-10-10', url: dartUrl('20261010000222') },
      { doc_type: 'REGISTRATION_AMENDED', rcept_no: '20261024000222', rcept_dt: '2026-10-24', url: dartUrl('20261024000222') },
    ],
    underwriters: ['신한투자증권', '삼성증권'],
  },
  [INCOMPLETE_LOCKUP_ID]: {
    ...summaries.find(s => s.id === INCOMPLETE_LOCKUP_ID)!,
    indicators: {
      competition_rate: 1680.0,
      competition_rate_type: 'simple',
      demand_amount_krw: 18_400_000_000_000,
      price_position: 'TOP_OF_BAND',
      lockup_ratio: null,                        // 확약 비율 확정 불가
      lockup_ratio_basis: null,
      tradable_ratio: 24.1,
      old_share_ratio: 0,
      new_share_count: 1_600_000,
      old_share_count: 0,
      total_offering_count: 1_600_000,
      offering_amount_krw: 36_800_000_000,
      report_rcept_no: '20261026000444',
    },
    // v1.0: 확정된 지표만 점수. lockup null → 그 자리 null. total 도 null.
    scores: { comp: 35, price: 20, lockup: null, flow: 20, total: null },
    reasons: [
      '기관 경쟁률 1,680:1 (≥ 1,500) — 35점.',
      '확정 공모가 23,000원 (밴드 상단 23,000원 확정) — 20점.',
      '**의무보유 확약 비율 확인 필요 — 판정 보류.**',
      '상장 당일 유통가능 24.1% + 구주매출 0% — 20점.',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261018000444', rcept_dt: '2026-10-18', url: dartUrl('20261018000444') },
      { doc_type: 'PROSPECTUS_AMENDED', rcept_no: '20261022000444', rcept_dt: '2026-10-22', url: dartUrl('20261022000444') },
      { doc_type: 'REGISTRATION_AMENDED', rcept_no: '20261026000444', rcept_dt: '2026-10-26', url: dartUrl('20261026000444') },
    ],
    underwriters: ['한국투자증권'],
  },
  [PASS_B_ID]: {
    ...summaries.find(s => s.id === PASS_B_ID)!,
    indicators: {
      competition_rate: 912.5,
      competition_rate_type: 'weighted',
      demand_amount_krw: 2_100_000_000_000,
      price_position: 'WITHIN_BAND',
      lockup_ratio: 12.0,
      lockup_ratio_basis: 'allocated',
      tradable_ratio: 32.0,
      old_share_ratio: 8.5,
      new_share_count: 2_287_000,
      old_share_count: 213_000,
      total_offering_count: 2_500_000,
      offering_amount_krw: 29_500_000_000,
      report_rcept_no: '20261026000555',
    },
    scores: { comp: 15, price: 10, lockup: 15, flow: 12, total: 52 },
    reasons: [
      '기관 경쟁률 912.5:1 (500 ~ 1,000) — 15점.',
      '확정 공모가 11,800원 (밴드 내: 11,000 ~ 13,000) — 10점.',
      '의무보유 확약 12.0% (10 ~ 20%) — 15점.',
      '유통가능 32.0% + 구주매출 8.5% — 중간 구간 12점.',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261018000555', rcept_dt: '2026-10-18', url: dartUrl('20261018000555') },
      { doc_type: 'REGISTRATION_AMENDED', rcept_no: '20261026000555', rcept_dt: '2026-10-26', url: dartUrl('20261026000555') },
    ],
    underwriters: ['미래에셋증권', 'KB증권'],
  },
  [REJECT_ID]: {
    ...summaries.find(s => s.id === REJECT_ID)!,
    indicators: {
      competition_rate: 480.0,
      competition_rate_type: 'weighted',
      demand_amount_krw: 420_000_000_000,
      price_position: 'BELOW_BAND',
      lockup_ratio: 2.1,
      lockup_ratio_basis: 'applied',
      tradable_ratio: 46.8,
      old_share_ratio: 38.0,
      new_share_count: 620_000,
      old_share_count: 380_000,
      total_offering_count: 1_000_000,
      offering_amount_krw: 14_000_000_000,
      report_rcept_no: '20261028000333',
    },
    scores: { comp: 0, price: 0, lockup: 0, flow: 0, total: 0 },
    reasons: [],
    reject_reasons: [
      '종합 점수 0점 — 50점 미만 (청약 비추천).',
      '기관 경쟁률 480:1 (< 500) — 0점.',
      '확정 공모가 14,000원 < 밴드 하단 15,000원 — 0점.',
      '의무보유 확약 2.1% (< 5%) — 0점.',
      '유통가능 46.8% / 구주매출 38.0% — 매물 과다, 0점.',
    ],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261012000333', rcept_dt: '2026-10-12', url: dartUrl('20261012000333') },
      { doc_type: 'REGISTRATION_AMENDED', rcept_no: '20261028000333', rcept_dt: '2026-10-28', url: dartUrl('20261028000333') },
    ],
    underwriters: ['하나증권'],
  },
  [PENDING_ID]: {
    ...summaries.find(s => s.id === PENDING_ID)!,
    indicators: {
      competition_rate: null,
      competition_rate_type: null,
      demand_amount_krw: null,
      price_position: null,
      lockup_ratio: null,
      lockup_ratio_basis: null,
      tradable_ratio: 28.4,
      old_share_ratio: 0,
      new_share_count: 1_250_000,
      old_share_count: 0,
      total_offering_count: 1_250_000,
      offering_amount_krw: null,
      report_rcept_no: '20261018000111',
    },
    scores: { comp: null, price: null, lockup: null, flow: null, total: null },
    reasons: [
      '발행조건확정 증권신고서(수요예측 결과) 미공시 — 지표 부족으로 판정 보류.',
      '투자설명서상 유통가능 비율 28.4%, 구주매출 없음.',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261018000111', rcept_dt: '2026-10-18', url: dartUrl('20261018000111') },
    ],
    underwriters: [],
  },
  [PASS_A_NOV_ID]: {
    ...summaries.find(s => s.id === PASS_A_NOV_ID)!,
    indicators: {
      competition_rate: 1820.0,
      competition_rate_type: 'simple',
      demand_amount_krw: 8_100_000_000_000,
      price_position: 'ABOVE_BAND',
      lockup_ratio: 15.4,
      lockup_ratio_basis: 'allocated',
      tradable_ratio: 26.0,
      old_share_ratio: 4.0,
      new_share_count: 1_920_000,
      old_share_count: 80_000,
      total_offering_count: 2_000_000,
      offering_amount_krw: 76_000_000_000,
      report_rcept_no: '20261105000666',
    },
    scores: { comp: 35, price: 25, lockup: 15, flow: 12, total: 87 },
    reasons: [
      '기관 경쟁률 1,820:1 (≥ 1,500) — 35점.',
      '확정 공모가 38,000원 (밴드 상단 38,000원 확정 → 상단 초과 미미) — 25점.',
      '의무보유 확약 15.4% (10 ~ 20%) — 15점.',
      '유통가능 26.0% + 구주매출 4.0% — 중간 구간 12점.',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261028000666', rcept_dt: '2026-10-28', url: dartUrl('20261028000666') },
      { doc_type: 'REGISTRATION_AMENDED', rcept_no: '20261105000666', rcept_dt: '2026-11-05', url: dartUrl('20261105000666') },
    ],
    underwriters: ['NH투자증권', '메리츠증권', '키움증권'],
  },
  [CORRECTION_UNAMENDED_ID]: {
    ...summaries.find(s => s.id === CORRECTION_UNAMENDED_ID)!,
    indicators: {
      competition_rate: null, competition_rate_type: null, demand_amount_krw: null,
      price_position: null,
      lockup_ratio: null, lockup_ratio_basis: null,
      tradable_ratio: null, old_share_ratio: null,
      new_share_count: null, old_share_count: null, total_offering_count: null,
      offering_amount_krw: null, report_rcept_no: '20261110000201',
    },
    scores: { comp: null, price: null, lockup: null, flow: null, total: null },
    reasons: [
      '금감원 정정신고서 제출요구 (2026-11-10) — 정정신고서 미제출 상태.',
      '발행조건확정 전이므로 지표·판정 보류.',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261101000201', rcept_dt: '2026-11-01', url: dartUrl('20261101000201') },
    ],
    underwriters: ['교보증권'],
  },
  [PENDING_NOV_ID]: {
    ...summaries.find(s => s.id === PENDING_NOV_ID)!,
    indicators: {
      competition_rate: null, competition_rate_type: null, demand_amount_krw: null,
      price_position: null,
      lockup_ratio: null, lockup_ratio_basis: null,
      tradable_ratio: null, old_share_ratio: null,
      new_share_count: null, old_share_count: null, total_offering_count: null,
      offering_amount_krw: null, report_rcept_no: '20261102000777',
    },
    scores: { comp: null, price: null, lockup: null, flow: null, total: null },
    reasons: [
      '발행조건확정 증권신고서 미공시 — 수요예측 전 단계. 지표 전면 보류.',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261102000777', rcept_dt: '2026-11-02', url: dartUrl('20261102000777') },
    ],
    underwriters: [],
  },
  [CORRECTION_AMENDED_ID]: {
    ...summaries.find(s => s.id === CORRECTION_AMENDED_ID)!,
    indicators: {
      competition_rate: null, competition_rate_type: null, demand_amount_krw: null,
      price_position: null,
      lockup_ratio: null, lockup_ratio_basis: null,
      tradable_ratio: null, old_share_ratio: null,
      new_share_count: null, old_share_count: null, total_offering_count: null,
      offering_amount_krw: null, report_rcept_no: '20261118000202',
    },
    scores: { comp: null, price: null, lockup: null, flow: null, total: null },
    reasons: [
      '금감원 정정신고서 제출요구 (2026-11-15).',
      '정정신고서 제출됨 (2026-11-18) — 발행조건확정 전이므로 일정이 다시 잡혔는지 확정할 수 없음.',
      '판정 보류 유지, 증권사 공지 확인 권장.',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261101000202', rcept_dt: '2026-11-01', url: dartUrl('20261101000202') },
      { doc_type: 'REGISTRATION_AMENDED', rcept_no: '20261118000202', rcept_dt: '2026-11-18', url: dartUrl('20261118000202') },
    ],
    underwriters: ['대신증권', '유진투자증권'],
  },
  [PASS_A_LARGECAP_ID]: {
    ...summaries.find(s => s.id === PASS_A_LARGECAP_ID)!,
    indicators: {
      competition_rate: 1180.0,
      competition_rate_type: 'weighted',
      demand_amount_krw: 1_500_000_000_000,
      price_position: 'TOP_OF_BAND',
      lockup_ratio: 11.0,
      lockup_ratio_basis: 'allocated',
      tradable_ratio: 28.0,
      old_share_ratio: 4.0,
      new_share_count: 2_057_142,
      old_share_count: 85_714,
      total_offering_count: 2_142_857,
      offering_amount_krw: 150_000_000_000,
      report_rcept_no: '20261122000999',
    },
    scores: { comp: 30, price: 20, lockup: 15, flow: 12, total: 77 },
    reasons: [
      '기관 경쟁률 1,180:1 (1,000 ~ 1,500) — 기본 25점.',
      '대형주 보완 +5점 (공모 1,500억 ≥ 1,000억 그리고 경쟁률 1,180:1 ≥ 800:1) — 최종 30점.',
      '확정 공모가 70,000원 (밴드 상단 확정) — 20점.',
      '의무보유 확약 11.0% (10 ~ 20%) — 15점.',
      '유통가능 28.0% + 구주매출 4.0% — 중간 구간 12점.',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261112000999', rcept_dt: '2026-11-12', url: dartUrl('20261112000999') },
      { doc_type: 'REGISTRATION_AMENDED', rcept_no: '20261122000999', rcept_dt: '2026-11-22', url: dartUrl('20261122000999') },
    ],
    underwriters: ['KB증권'],
  },
  [PASS_B_DEC_ID]: {
    ...summaries.find(s => s.id === PASS_B_DEC_ID)!,
    indicators: {
      competition_rate: 1140.0,
      competition_rate_type: 'simple',
      demand_amount_krw: 1_900_000_000_000,
      price_position: 'TOP_OF_BAND',
      lockup_ratio: 7.2,
      lockup_ratio_basis: 'allocated',
      tradable_ratio: 28.0,
      old_share_ratio: 12.0,
      new_share_count: 440_000,
      old_share_count: 60_000,
      total_offering_count: 500_000,
      offering_amount_krw: 5_250_000_000,
      report_rcept_no: '20261205000888',
    },
    scores: { comp: 25, price: 20, lockup: 10, flow: 0, total: 55 },
    reasons: [
      '기관 경쟁률 1,140:1 (1,000 ~ 1,500) — 25점.',
      '확정 공모가 10,500원 (밴드 상단 확정) — 20점.',
      '의무보유 확약 7.2% (5 ~ 10%) — 10점.',
      '유통가능 28.0% + 구주매출 12.0% — pm 해석상 flow 저점 처리 샘플 (0점).',
    ],
    reject_reasons: [],
    sources: [
      { doc_type: 'PROSPECTUS', rcept_no: '20261125000888', rcept_dt: '2026-11-25', url: dartUrl('20261125000888') },
      { doc_type: 'REGISTRATION_AMENDED', rcept_no: '20261205000888', rcept_dt: '2026-12-05', url: dartUrl('20261205000888') },
    ],
    underwriters: ['IBK투자증권'],
  },
}

// --- helpers --------------------------------------------------------------

function delay<T>(v: T, ms = 150): Promise<T> {
  return new Promise(resolve => setTimeout(() => resolve(v), ms))
}

function computeMinDeposit(final_price: number | null, shares: number): MinDeposit | null {
  if (final_price === null) return null
  const deposit = Math.round(final_price * shares * CONFIG.deposit.margin_rate)
  const fee = CONFIG.deposit.fee_krw
  return { shares, deposit_krw: deposit, fee_krw: fee, total_krw: deposit + fee }
}

const POSITION_SHORT: Record<NonNullable<Indicators['price_position']>, string> = {
  ABOVE_BAND: '밴드 상단 초과',
  TOP_OF_BAND: '밴드 상단',
  WITHIN_BAND: '밴드 내',
  BELOW_BAND: '밴드 하단 미만',
}

function buildChecklist(ind: Indicators, final_price: number | null): ChecklistItem[] {
  const c = CONFIG.checklist

  // v0.9: competition — MET 기준은 good_min(1000), level 은 VERY_GOOD(≥1500) / GOOD(≥1000)
  const compActual = ind.competition_rate === null ? null : fmtRatio(ind.competition_rate)
  let compResult: ChecklistItem['result']
  let compLevel: ChecklistLevel | null = null
  if (ind.competition_rate === null) {
    compResult = 'UNKNOWN'
  } else if (ind.competition_rate >= c.competition_good_min) {
    compResult = 'MET'
    compLevel = ind.competition_rate >= c.competition_very_good_min ? 'VERY_GOOD' : 'GOOD'
  } else {
    compResult = 'NOT_MET'
  }

  const positionActual = ind.price_position === null ? null : POSITION_SHORT[ind.price_position]
  const positionResult: ChecklistItem['result'] =
    ind.price_position === null
      ? 'UNKNOWN'
      : c.price_positions_met.includes(ind.price_position)
        ? 'MET'
        : 'NOT_MET'

  const lockupActual = ind.lockup_ratio === null ? null : fmtPct(ind.lockup_ratio)
  const lockupResult: ChecklistItem['result'] =
    ind.lockup_ratio === null
      ? 'UNKNOWN'
      : ind.lockup_ratio >= c.lockup_min
        ? 'MET'
        : 'NOT_MET'

  const flowActual =
    ind.tradable_ratio === null || ind.old_share_ratio === null
      ? null
      : `유통 ${fmtPct(ind.tradable_ratio)} · 구주 ${fmtPct(ind.old_share_ratio)}`
  const flowResult: ChecklistItem['result'] =
    ind.tradable_ratio === null || ind.old_share_ratio === null
      ? 'UNKNOWN'
      : ind.tradable_ratio <= c.flow_tradable_max && ind.old_share_ratio < c.flow_old_share_lt
        ? 'MET'
        : 'NOT_MET'

  const depositActual =
    final_price === null
      ? null
      : fmtKrw(Math.round(final_price * CONFIG.deposit.default_shares * CONFIG.deposit.margin_rate) + CONFIG.deposit.fee_krw)

  return [
    {
      key: 'competition',
      label: '1. 기관 경쟁률',
      indicator: '기관 수요예측 경쟁률',
      criterion: `≥ ${c.competition_good_min.toLocaleString()}:1 좋음, ≥ ${c.competition_very_good_min.toLocaleString()}:1 아주 좋음`,
      actual: compActual,
      result: compResult,
      level: compLevel,
    },
    {
      key: 'price_position',
      label: '2. 공모가 위치',
      indicator: '확정 공모가 밴드 위치',
      criterion: '밴드 상단 또는 상단 초과',
      actual: positionActual,
      result: positionResult,
      level: null,
    },
    {
      key: 'lockup',
      label: '3. 의무보유 확약',
      indicator: '기관 의무보유 확약 비율',
      criterion: `≥ ${c.lockup_min}%`,
      actual: lockupActual,
      result: lockupResult,
      level: null,
    },
    {
      key: 'flow',
      label: '4. 유통 가능 물량',
      indicator: '유통가능 비율 · 구주매출',
      criterion: `유통 ≤ ${c.flow_tradable_max}% 그리고 구주 < ${c.flow_old_share_lt}%`,
      actual: flowActual,
      result: flowResult,
      level: null,
    },
    {
      key: 'min_deposit',
      label: '5. 최소 증거금',
      indicator: '균등배정 최소 증거금 (수수료 포함)',
      criterion: `${CONFIG.deposit.default_shares}주 × 확정가 × ${CONFIG.deposit.margin_rate * 100}% + 수수료 ${CONFIG.deposit.fee_krw.toLocaleString()}원`,
      actual: depositActual,
      result: 'INFO',
      level: null,
    },
    {
      key: 'sell_timing',
      label: '6. 매도 타이밍',
      indicator: '상장일 매도 시점',
      criterion: '상장일 시초가 ~ 오전 10시 이전',
      actual: '상장일 시초가 ~ 10시',
      result: 'INFO',
      level: null,
    },
  ]
}

// --- 수집 상태 머신 (목업) ------------------------------------------------

function nowIso(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}+09:00`
}

let collectState: CollectStatus = {
  status: 'IDLE',
  started_at: null,
  finished_at: null,
  progress: null,
  summary: null,
  error: null,
  last_collected_at: '2026-10-16T11:50:00+09:00',
}
let collectTimer: ReturnType<typeof setInterval> | null = null

function startMockCollect(): void {
  const total = 5
  collectState = {
    status: 'RUNNING',
    started_at: nowIso(),
    finished_at: null,
    progress: { done: 0, total },
    summary: null,
    error: null,
    last_collected_at: collectState.last_collected_at,
  }
  let done = 0
  collectTimer = setInterval(() => {
    done++
    if (done < total) {
      collectState = { ...collectState, progress: { done, total } }
    } else {
      const finished = nowIso()
      collectState = {
        status: 'SUCCEEDED',
        started_at: collectState.started_at,
        finished_at: finished,
        progress: { done: total, total },
        summary: {
          new_count: 2,
          updated_count: 3,
          unchanged_count: 1,
          failed_count: 0,
          withdrawn_count: 0,
        },
        error: null,
        last_collected_at: finished,
      }
      if (collectTimer) { clearInterval(collectTimer); collectTimer = null }
    }
  }, 800)
}

// --- api -------------------------------------------------------------------

function rangeOverlap(sStart: string | null, sEnd: string | null, listing: string | null, from?: string, to?: string): boolean {
  if (!from && !to) return true
  const lo = from ?? '0000-00-00'
  const hi = to ?? '9999-99-99'
  const subOverlap =
    sStart !== null && sEnd !== null
      ? !(sEnd < lo || sStart > hi)
      : false
  const listOverlap = listing !== null && listing >= lo && listing <= hi
  return subOverlap || listOverlap
}

export async function listIpos(params: ListParams = {}): Promise<{ items: IpoSummary[] }> {
  let items = summaries.slice()
  if (params.status) items = items.filter(it => it.verdict.status === params.status)
  if (params.from || params.to) {
    items = items.filter(it => rangeOverlap(it.subscription_start, it.subscription_end, it.listing_date, params.from, params.to))
  }
  items.sort((a, b) => (a.subscription_start ?? '').localeCompare(b.subscription_start ?? ''))
  return delay({ items })
}

export async function getIpo(id: string, shares = 10): Promise<IpoDetail> {
  const row = seed[id]
  if (!row) {
    throw new Error(`해당 종목을 찾을 수 없습니다 (id=${id}).`)
  }
  const detail: IpoDetail = {
    ...row,
    min_deposit: computeMinDeposit(row.final_price, shares),
    checklist: buildChecklist(row.indicators, row.final_price),
  }
  return delay(detail)
}

export async function getScoringConfig(): Promise<ScoringConfig> {
  return delay(CONFIG)
}

export async function getCollectStatus(): Promise<CollectStatus> {
  return delay(collectState)
}

export async function postCollect(key: string | null): Promise<CollectStartResult> {
  if (key === 'wrong-key-demo') {
    await delay(null, 150)
    throw new HttpError(401, '수집 키가 올바르지 않습니다. (목업)')
  }
  if (collectState.status === 'RUNNING') {
    return delay({ kind: 'RUNNING', data: collectState })
  }
  startMockCollect()
  return delay({ kind: 'STARTED', data: collectState })
}

export async function getHealth(): Promise<Health> {
  return delay({ status: 'ok', last_collected_at: collectState.last_collected_at })
}
