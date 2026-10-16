import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { IpoSummary, Verdict } from '../types'
import { CollectBar } from '../components/CollectBar'
import { ErrorBox, Loading } from '../components/Loading'
import {
  addMonths,
  enumerateDaysInclusive,
  firstDayOfMonth,
  lastDayOfMonth,
  monthGrid,
  monthLabel,
} from '../utils/calendar'
import { marketLabel } from '../utils/format'

type EventType = 'SUBSCRIPTION' | 'LISTING'
interface CalEvent {
  item: IpoSummary
  type: EventType
}

const WEEK_HEADER = ['일', '월', '화', '수', '목', '금', '토']

const VERDICT_CLS: Record<string, string> = {
  'PASS-S':   'event-pass-s',
  'PASS-A':   'event-pass-a',
  'PASS-B':   'event-pass-b',
  'REJECT':   'event-reject',
  'PENDING':  'event-pending',
}

const VERDICT_TEXT: Record<string, string> = {
  'PASS-S':  'S',
  'PASS-A':  'A',
  'PASS-B':  'B',
  'REJECT':  'REJECT',
  'PENDING': '대기',
}

function verdictKey(v: Verdict): string {
  if (v.status === 'PASS' && v.grade) return `PASS-${v.grade}`
  return v.status
}

function buildEventMap(items: IpoSummary[]): Map<string, CalEvent[]> {
  const m = new Map<string, CalEvent[]>()
  const push = (ymd: string, ev: CalEvent) => {
    const list = m.get(ymd) ?? []
    list.push(ev)
    m.set(ymd, list)
  }
  for (const it of items) {
    if (it.subscription_start && it.subscription_end) {
      for (const d of enumerateDaysInclusive(it.subscription_start, it.subscription_end)) {
        push(d, { item: it, type: 'SUBSCRIPTION' })
      }
    } else if (it.subscription_start) {
      push(it.subscription_start, { item: it, type: 'SUBSCRIPTION' })
    }
    if (it.listing_date) {
      push(it.listing_date, { item: it, type: 'LISTING' })
    }
  }
  return m
}

const MAX_CHIPS_PER_CELL = 3

export function CalendarPage() {
  const [cursor, setCursor] = useState<Date>(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const [passOnly, setPassOnly] = useState(false)
  const [items, setItems] = useState<IpoSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedDay, setSelectedDay] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const from = firstDayOfMonth(cursor)
  const to = lastDayOfMonth(cursor)

  // 달력 데이터
  useEffect(() => {
    let cancelled = false
    setItems(null)
    setError(null)
    api
      .listIpos({ from, to })
      .then(res => { if (!cancelled) setItems(res.items) })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [from, to, refreshKey])

  const onCollectSucceeded = useCallback(() => {
    setRefreshKey(k => k + 1)
  }, [])

  const filteredItems = useMemo(() => {
    if (!items) return items
    return passOnly ? items.filter(it => it.verdict.status === 'PASS') : items
  }, [items, passOnly])

  const eventMap = useMemo(
    () => filteredItems ? buildEventMap(filteredItems) : new Map<string, CalEvent[]>(),
    [filteredItems],
  )
  const grid = useMemo(() => monthGrid(cursor), [cursor])
  const dayEvents = selectedDay ? eventMap.get(selectedDay) ?? [] : []

  function goToday() {
    const t = new Date()
    setCursor(new Date(t.getFullYear(), t.getMonth(), 1))
    setSelectedDay(null)
  }

  return (
    <section className="page page-calendar">
      <CollectBar onSucceeded={onCollectSucceeded} />

      <div className="cal-head">
        <div className="cal-nav">
          <button onClick={() => setCursor(c => addMonths(c, -1))} aria-label="이전 달">◀</button>
          <button className="cal-today" onClick={goToday}>오늘</button>
          <button onClick={() => setCursor(c => addMonths(c, 1))} aria-label="다음 달">▶</button>
          <h2 className="cal-month">{monthLabel(cursor)}</h2>
        </div>
        <div className="cal-tools">
          <label className="cal-passonly">
            <input
              type="checkbox"
              checked={passOnly}
              onChange={e => setPassOnly(e.target.checked)}
            />
            추천(PASS)만 보기
          </label>
          <Link to="/list" className="cal-switch">목록 보기 →</Link>
        </div>
      </div>

      <Legend />

      {error && <ErrorBox message={error} />}
      {!error && items === null && <Loading />}
      {!error && items !== null && (
        <>
          <div className="cal-grid" role="grid" aria-label={monthLabel(cursor)}>
            <div className="cal-weekheader" role="row">
              {WEEK_HEADER.map((w, i) => (
                <div key={w} role="columnheader" className={`cal-wh ${i === 0 ? 'wh-sun' : ''} ${i === 6 ? 'wh-sat' : ''}`}>{w}</div>
              ))}
            </div>
            <div className="cal-body">
              {grid.map(cell => {
                const events = eventMap.get(cell.ymd) ?? []
                const visible = events.slice(0, MAX_CHIPS_PER_CELL)
                const overflow = events.length - visible.length
                return (
                  <div
                    key={cell.ymd}
                    className={[
                      'cal-cell',
                      cell.isCurrentMonth ? '' : 'off-month',
                      cell.isToday ? 'today' : '',
                      selectedDay === cell.ymd ? 'selected' : '',
                      cell.dayOfWeek === 0 ? 'is-sun' : '',
                      cell.dayOfWeek === 6 ? 'is-sat' : '',
                    ].filter(Boolean).join(' ')}
                    role="gridcell"
                    tabIndex={events.length > 0 ? 0 : -1}
                    onClick={() => events.length > 0 ? setSelectedDay(cell.ymd) : undefined}
                  >
                    <div className="cal-date">{cell.date.getDate()}</div>
                    <div className="cal-chips">
                      {visible.map((ev, i) => (
                        <EventChip key={`${ev.item.id}-${ev.type}-${i}`} ev={ev} />
                      ))}
                      {overflow > 0 && (
                        <button
                          className="cal-more"
                          onClick={e => { e.stopPropagation(); setSelectedDay(cell.ymd) }}
                        >
                          +{overflow} 더보기
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {selectedDay !== null && (
            <aside className="cal-detail">
              <div className="cal-detail-head">
                <h3>{selectedDay} 일정 ({dayEvents.length})</h3>
                <button onClick={() => setSelectedDay(null)} aria-label="닫기">✕</button>
              </div>
              {dayEvents.length === 0 ? (
                <p className="empty">선택한 날짜에 일정이 없습니다.</p>
              ) : (
                <ul className="cal-detail-list">
                  {dayEvents.map((ev, i) => (
                    <li key={`${ev.item.id}-${ev.type}-${i}`}>
                      <Link to={`/ipos/${ev.item.id}`}>
                        <span className={`cal-chip ${VERDICT_CLS[verdictKey(ev.item.verdict)]}`}>
                          {VERDICT_TEXT[verdictKey(ev.item.verdict)]}
                        </span>
                        <span className="cal-item-type">{ev.type === 'LISTING' ? '상장' : '청약'}</span>
                        <span className="cal-item-name">{ev.item.corp_name}</span>
                        <span className="cal-item-market">{marketLabel(ev.item.market)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </aside>
          )}

          {filteredItems !== null && filteredItems.length === 0 && (
            <p className="empty">이 달에 조건에 맞는 종목이 없습니다.</p>
          )}
        </>
      )}
    </section>
  )
}

function EventChip({ ev }: { ev: CalEvent }) {
  const key = verdictKey(ev.item.verdict)
  const label = ev.type === 'LISTING' ? '상장' : '청약'
  const title = `${ev.item.corp_name} — ${label} (${VERDICT_TEXT[key]})`
  return (
    <Link
      to={`/ipos/${ev.item.id}`}
      className={`cal-chip ${VERDICT_CLS[key]} ${ev.type === 'LISTING' ? 'chip-listing' : ''}`}
      title={title}
      onClick={e => e.stopPropagation()}
    >
      <span className="chip-type">{label}</span>
      <span className="chip-grade">{VERDICT_TEXT[key]}</span>
      <span className="chip-name">{ev.item.corp_name}</span>
    </Link>
  )
}

function Legend() {
  const items = [
    { key: 'PASS-S', label: 'S 강력 추천' },
    { key: 'PASS-A', label: 'A 청약 유망' },
    { key: 'PASS-B', label: 'B 중립·주의' },
    { key: 'REJECT', label: 'REJECT 비추천' },
    { key: 'PENDING', label: '판정 대기' },
  ]
  return (
    <div className="cal-legend" role="list" aria-label="범례">
      <span className="legend-head">범례</span>
      {items.map(it => (
        <span key={it.key} className={`legend-item ${VERDICT_CLS[it.key]}`} role="listitem">
          <span className="legend-swatch" aria-hidden /> {it.label}
        </span>
      ))}
      <span className="legend-sep">·</span>
      <span className="legend-note">칩에 "청약" / "상장" 라벨 표기 — <strong>상장</strong> 칩은 테두리 강조.</span>
    </div>
  )
}
