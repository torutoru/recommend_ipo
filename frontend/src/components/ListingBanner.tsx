import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { holdings, type Holding } from '../api/holdings'
import type { IpoSummary } from '../types'
import { toYmd } from '../utils/calendar'
import { fmtKrw } from '../utils/format'
// v1.10 (#30): 로컬 미리보기(demo=listing) — 모든 호출을 `import.meta.env.DEV` 로 감싸 prod 번들에서 제거.
import { isListingDemoActive, pickDemoItems } from '../dev/listingDemo'

const DISMISS_PREFIX = 'recommend-ipo:listing-banner-dismissed:'

interface Item { holding: Holding; ipo: IpoSummary; kind: 'today' | 'tomorrow' }

function todayKst(): string { return toYmd(new Date()) }
function tomorrowKst(): string {
  const d = new Date(); d.setDate(d.getDate() + 1); return toYmd(d)
}

function readDismissed(ymd: string): boolean {
  try { return localStorage.getItem(DISMISS_PREFIX + ymd) === '1' }
  catch { return false }
}

export function ListingBanner() {
  const [list, setList] = useState<Holding[]>(() => holdings.list())
  const [ipos, setIpos] = useState<IpoSummary[] | null>(null)
  const [today, setToday] = useState(() => todayKst())
  const [dismissed, setDismissed] = useState(() => readDismissed(today))

  useEffect(() => {
    let cancelled = false
    api.listIpos().then(res => { if (!cancelled) setIpos(res.items) }).catch(() => { /* ignore */ })
    return () => { cancelled = true }
  }, [])

  useEffect(() => holdings.subscribe(() => setList(holdings.list())), [])

  // 자정 넘어가면 today·dismissed 를 재평가. 간단히 5분 간격 체크.
  useEffect(() => {
    const t = setInterval(() => {
      const ymd = todayKst()
      if (ymd !== today) {
        setToday(ymd)
        setDismissed(readDismissed(ymd))
      }
    }, 5 * 60 * 1000)
    return () => clearInterval(t)
  }, [today])

  // v1.10 (#30): DEV + ?demo=listing 이면 실제 보유·상장일 대신 샘플 2건.
  const preview = import.meta.env.DEV && isListingDemoActive()

  const items: Item[] = useMemo(() => {
    if (preview) {
      return ipos ? pickDemoItems(ipos) : []
    }
    if (!ipos || list.length === 0) return []
    const tm = tomorrowKst()
    const result: Item[] = []
    for (const h of list) {
      const ipo = ipos.find(x => x.id === h.corp_code)
      if (!ipo || !ipo.listing_date) continue
      if (ipo.listing_date === today) result.push({ holding: h, ipo, kind: 'today' })
      else if (ipo.listing_date === tm) result.push({ holding: h, ipo, kind: 'tomorrow' })
    }
    // 오늘 상장 우선, 그 다음 내일.
    return result.sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === 'today' ? -1 : 1
      return a.ipo.corp_name.localeCompare(b.ipo.corp_name)
    })
  }, [preview, ipos, list, today])

  // 미리보기는 닫기 상태를 무시(항상 표시).
  if (!preview && dismissed) return null
  if (items.length === 0) return null

  function dismiss() {
    try { localStorage.setItem(DISMISS_PREFIX + today, '1') } catch { /* ignore */ }
    setDismissed(true)
  }

  return (
    <div className="listing-banner" role="status">
      <span className="listing-banner-icon" aria-hidden>🔔</span>
      <ul className="listing-banner-list">
        {items.map(({ holding, ipo, kind }) => (
          <li key={holding.corp_code}>
            {kind === 'today' ? (
              <>오늘 <strong>{ipo.corp_name}</strong> 상장일 — 보유 <strong>{holding.shares.toLocaleString('ko-KR')}주</strong>
                {ipo.final_price !== null && <> (공모가 {fmtKrw(ipo.final_price)})</>}
              </>
            ) : (
              <>내일 <strong>{ipo.corp_name}</strong> 상장 — 보유 <strong>{holding.shares.toLocaleString('ko-KR')}주</strong></>
            )}
          </li>
        ))}
      </ul>
      {preview && <span className="listing-banner-tag" aria-label="미리보기 모드">(미리보기)</span>}
      <div className="listing-banner-actions">
        <Link to="/my" className="listing-banner-link">내 공모주 보기</Link>
        {!preview && (
          <button type="button" onClick={dismiss} aria-label="오늘 하루 숨김">닫기</button>
        )}
      </div>
    </div>
  )
}
