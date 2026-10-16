import type {
  CompetitionRateType,
  DocType,
  LockupRatioBasis,
  Market,
  PricePosition,
} from '../types'

export const NULL_PLACEHOLDER = '미공시'

export function fmtOrNull<T>(v: T | null | undefined, fmt: (x: T) => string): string {
  return v === null || v === undefined ? NULL_PLACEHOLDER : fmt(v)
}

const krwFormatter = new Intl.NumberFormat('ko-KR')

export function fmtKrw(n: number): string {
  return `${krwFormatter.format(n)}원`
}

// 금액을 억/조 단위로 요약 (대형 수요 금액 가독성)
export function fmtKrwAbbrev(n: number): string {
  if (n >= 1_0000_0000_0000) {
    return `${(n / 1_0000_0000_0000).toFixed(1)}조 원`
  }
  if (n >= 1_0000_0000) {
    return `${(n / 1_0000_0000).toFixed(1)}억 원`
  }
  return fmtKrw(n)
}

export function fmtPct(n: number): string {
  return `${n.toFixed(1)}%`
}

export function fmtRatio(n: number): string {
  return `${krwFormatter.format(Math.round(n * 10) / 10)}:1`
}

export function fmtDate(s: string): string {
  return s // YYYY-MM-DD
}

// ISO 8601 → "YYYY-MM-DD HH:mm" (로컬 타임존). 실패 시 입력 그대로.
export function fmtDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function fmtDateRange(start: string | null, end: string | null): string {
  if (start === null && end === null) return NULL_PLACEHOLDER
  if (start === end) return start ?? end ?? NULL_PLACEHOLDER
  return `${start ?? NULL_PLACEHOLDER} ~ ${end ?? NULL_PLACEHOLDER}`
}

export function fmtBand(low: number | null, high: number | null): string {
  if (low === null && high === null) return NULL_PLACEHOLDER
  return `${low !== null ? fmtKrw(low) : NULL_PLACEHOLDER} ~ ${high !== null ? fmtKrw(high) : NULL_PLACEHOLDER}`
}

export function marketLabel(m: Market | null): string {
  if (m === null) return NULL_PLACEHOLDER
  return m
}

const PRICE_POSITION_LABEL: Record<PricePosition, string> = {
  ABOVE_BAND: '밴드 상단 초과',
  TOP_OF_BAND: '밴드 상단',
  WITHIN_BAND: '밴드 내',
  BELOW_BAND: '밴드 하단 미만',
}

export function pricePositionLabel(p: PricePosition | null): string {
  return p === null ? NULL_PLACEHOLDER : PRICE_POSITION_LABEL[p]
}

const DOC_TYPE_LABEL: Record<DocType, string> = {
  PROSPECTUS: '투자설명서',
  PROSPECTUS_AMENDED: '투자설명서(정정)',
  REGISTRATION_AMENDED: '증권신고서(정정)',
  ISSUANCE_REPORT: '증권발행실적보고서',
}

export function docTypeLabel(t: DocType): string {
  return DOC_TYPE_LABEL[t]
}

const COMP_RATE_TYPE_LABEL: Record<CompetitionRateType, string> = {
  simple: '단순 경쟁률',
  weighted: '가중 경쟁률',
}

export function competitionRateTypeLabel(t: CompetitionRateType | null): string {
  return t === null ? NULL_PLACEHOLDER : COMP_RATE_TYPE_LABEL[t]
}

const LOCKUP_BASIS_LABEL: Record<LockupRatioBasis, string> = {
  allocated: '배정 수량 기준',
  applied: '신청 수량 기준',
}

export function lockupRatioBasisLabel(b: LockupRatioBasis | null): string {
  return b === null ? NULL_PLACEHOLDER : LOCKUP_BASIS_LABEL[b]
}

const sharesFormatter = new Intl.NumberFormat('ko-KR')

export function fmtShares(n: number): string {
  return `${sharesFormatter.format(n)}주`
}
