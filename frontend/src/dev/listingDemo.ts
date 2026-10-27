// v1.10 (#30): 「상장 알림 배너」 로컬 미리보기용 샘플.
//
// 호출부는 반드시 `import.meta.env.DEV` 로 감싸서 호출한다.
// Vite 가 prod 빌드에서 `import.meta.env.DEV` 를 `false` 로 치환 → 데드 코드로 제거.
// 그래도 혹시 남을 수 있으니 커밋/push 전 `grep -r "demo=listing" dist/` 로 교차 검증.

import type { IpoSummary } from '../types'
import type { Holding } from '../api/holdings'
import { toYmd } from '../utils/calendar'

export interface DemoItem {
  holding: Holding
  ipo: IpoSummary
  kind: 'today' | 'tomorrow'
}

export function isListingDemoActive(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const u = new URL(window.location.href)
    return u.searchParams.get('demo') === 'listing'
  } catch {
    return false
  }
}

function tomorrowKst(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  return toYmd(d)
}

export function pickDemoItems(ipos: IpoSummary[]): DemoItem[] {
  if (!ipos || ipos.length === 0) return []
  const today = toYmd(new Date())
  const tomorrow = tomorrowKst()
  const now = new Date().toISOString()

  // PASS 종목을 우선 사용. 2건이 없으면 전체에서 채움.
  const pass = ipos.filter(x => x.verdict.status === 'PASS')
  const pool = pass.length >= 2 ? pass : ipos
  const first = pool[0]
  const second = pool[1] ?? (pool[0] !== ipos[0] ? ipos[0] : ipos[1])
  if (!first) return []

  const items: DemoItem[] = []
  items.push({
    holding: makeHolding(first, 20, now),
    ipo: { ...first, listing_date: today },
    kind: 'today',
  })
  if (second && second.id !== first.id) {
    items.push({
      holding: makeHolding(second, 10, now),
      ipo: { ...second, listing_date: tomorrow },
      kind: 'tomorrow',
    })
  }
  return items
}

export function demoCorpCodes(ipos: IpoSummary[]): string[] {
  return pickDemoItems(ipos).map(x => x.ipo.id)
}

function makeHolding(ipo: IpoSummary, shares: number, now: string): Holding {
  return {
    corp_code: ipo.id,
    shares,
    price: ipo.final_price ?? 10000,
    memo: '',
    created_at: now,
    updated_at: now,
  }
}
