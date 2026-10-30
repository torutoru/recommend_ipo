// 네이티브 Date 기반 유틸 — 외부 의존성 없이 월 그리드 생성·날짜 포맷·비교.

export function toYmd(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function parseYmd(s: string): Date {
  // 로컬 자정 기준 생성 (YYYY-MM-DD).
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y!, (m ?? 1) - 1, d ?? 1)
}

export interface MonthCell {
  date: Date
  ymd: string
  isCurrentMonth: boolean
  isToday: boolean
  dayOfWeek: number // 0 = Sun
}

export function monthGrid(cursor: Date): MonthCell[] {
  const year = cursor.getFullYear()
  const month = cursor.getMonth()
  const first = new Date(year, month, 1)
  const startOffset = first.getDay()
  const todayYmd = toYmd(new Date())
  const cells: MonthCell[] = []
  for (let i = 0; i < 42; i++) {
    const d = new Date(year, month, 1 - startOffset + i)
    const ymd = toYmd(d)
    cells.push({
      date: d,
      ymd,
      isCurrentMonth: d.getMonth() === month,
      isToday: ymd === todayYmd,
      dayOfWeek: d.getDay(),
    })
  }
  return cells
}

export function monthLabel(cursor: Date): string {
  return `${cursor.getFullYear()}년 ${cursor.getMonth() + 1}월`
}

export function addMonths(cursor: Date, delta: number): Date {
  return new Date(cursor.getFullYear(), cursor.getMonth() + delta, 1)
}

export function firstDayOfMonth(cursor: Date): string {
  return toYmd(new Date(cursor.getFullYear(), cursor.getMonth(), 1))
}

export function lastDayOfMonth(cursor: Date): string {
  return toYmd(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0))
}

// v1.9 (#42): 달력 URL 쿼리·sessionStorage 동기화용 "YYYY-MM" 유틸.
const MONTH_RE = /^(\d{4})-(0[1-9]|1[0-2])$/

export function fmtMonth(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  return `${y}-${m}`
}

// 유효하지 않으면 null — 호출부에서 이번 달로 폴백한다.
export function parseMonth(raw: string | null | undefined): Date | null {
  if (!raw) return null
  const m = MONTH_RE.exec(raw)
  if (!m) return null
  const year = Number(m[1])
  const month = Number(m[2]) - 1
  if (year < 1900 || year > 2100) return null
  return new Date(year, month, 1)
}

export function enumerateDaysInclusive(startYmd: string, endYmd: string): string[] {
  const start = parseYmd(startYmd)
  const end = parseYmd(endYmd)
  if (start > end) return []
  const out: string[] = []
  const cur = new Date(start)
  while (cur <= end) {
    out.push(toYmd(cur))
    cur.setDate(cur.getDate() + 1)
  }
  return out
}
