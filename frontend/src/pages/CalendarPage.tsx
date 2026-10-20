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
  'PASS-S':     'event-pass-s',
  'PASS-A':     'event-pass-a',
  'PASS-B':     'event-pass-b',
  'REJECT':     'event-reject',
  'PENDING':    'event-pending',
  'CORRECTION': 'event-correction',
  'INCOMPLETE': 'event-incomplete',
}

// v1.8 (#21 추가 4번): 칩에는 회사명만 표시 — 이 라벨은 title/aria-label 전용.
const VERDICT_LABEL: Record<string, string> = {
  'PASS-S':     '추천 S',
  'PASS-A':     '추천 A',
  'PASS-B':     '추천 B',
  'INCOMPLETE': '판정 보류',
  'REJECT':     '비추천',
  'PENDING':    '판정 대기',
  'CORRECTION': '정정 요구',
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

// v1.5 — 셀 안 칩 정렬 우선순위 (낮을수록 먼저).
// 요구: S > A > B > INCOMPLETE > REJECT > PENDING > CORRECTION
const CHIP_PRIORITY: Record<string, number> = {
  'PASS-S':     1,
  'PASS-A':     2,
  'PASS-B':     3,
  'INCOMPLETE': 4,
  'REJECT':     5,
  'PENDING':    6,
  'CORRECTION': 7,
}

function priorityOf(ev: CalEvent): number {
  return CHIP_PRIORITY[verdictKey(ev.item.verdict)] ?? 999
}

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
  // 선택 날짜 상세 패널은 CORRECTION 포함 전체 이벤트, 우선순위 정렬.
  const dayEvents = (selectedDay ? eventMap.get(selectedDay) ?? [] : [])
    .slice()
    .sort((a, b) => priorityOf(a) - priorityOf(b))

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
                // v1.5: CORRECTION 은 non-correction 이벤트가 하나라도 있으면 셀에서 숨긴다.
                // CORRECTION 만 있는 날짜(nonCorrection === 0)는 그대로 노출.
                const nonCorrection = events.filter(e => e.item.verdict.status !== 'CORRECTION')
                const chipPool = nonCorrection.length > 0 ? nonCorrection : events
                // 우선순위 안정 정렬 (Array.prototype.sort 는 안정 — 같은 우선순위면 입력 순서 유지).
                const sorted = chipPool.slice().sort((a, b) => priorityOf(a) - priorityOf(b))
                const visible = sorted.slice(0, MAX_CHIPS_PER_CELL)
                // +N 더보기: CORRECTION 숨김 포함 전체 이벤트 수 기준.
                const overflow = events.length - visible.length
                const hasEvents = events.length > 0
                const isSelected = selectedDay === cell.ymd
                return (
                  <div
                    key={cell.ymd}
                    className={[
                      'cal-cell',
                      cell.isCurrentMonth ? '' : 'off-month',
                      cell.isToday ? 'today' : '',
                      isSelected ? 'selected' : '',
                      cell.dayOfWeek === 0 ? 'is-sun' : '',
                      cell.dayOfWeek === 6 ? 'is-sat' : '',
                      hasEvents ? 'has-events' : '',
                    ].filter(Boolean).join(' ')}
                    role={hasEvents ? 'button' : 'gridcell'}
                    aria-pressed={hasEvents ? isSelected : undefined}
                    aria-label={hasEvents ? `${cell.ymd} 일정 ${events.length}건` : undefined}
                    tabIndex={hasEvents ? 0 : -1}
                    onClick={() => hasEvents ? setSelectedDay(cell.ymd) : undefined}
                    onKeyDown={e => {
                      if (hasEvents && (e.key === 'Enter' || e.key === ' ')) {
                        e.preventDefault()
                        setSelectedDay(cell.ymd)
                      }
                    }}
                  >
                    <div className="cal-date">{cell.date.getDate()}</div>
                    <div className="cal-chips">
                      {visible.map((ev, i) => (
                        <EventChip key={`${ev.item.id}-${ev.type}-${i}`} ev={ev} />
                      ))}
                      {overflow > 0 && (
                        <span className="cal-more">+{overflow} 더보기</span>
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
                          {VERDICT_LABEL[verdictKey(ev.item.verdict)]}
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
  const isListing = ev.type === 'LISTING'
  const label = isListing ? '상장' : '청약'
  const roleLabel = VERDICT_LABEL[key]
  const warn = ev.item.verdict.status === 'CORRECTION'
  // title/aria-label: "회사명 · 청약 · 추천 A" (+ 정정 종목은 "· 일정 변경 가능")
  const title = `${ev.item.corp_name} · ${label} · ${roleLabel}${warn ? ' · 일정 변경 가능' : ''}`
  // v1.8 (#21 4·5번) + v1.9 (⚠ 제거):
  //   - 칩에는 회사명만. 라벨·등급·경고 아이콘 모두 제거.
  //   - 정정 종목의 "일정 변경 가능" 안내는 title/aria-label·날짜 패널·상세 배너에만 유지.
  //   - 상장 칩은 상태 색 대신 초록, 본문 "(상장) 회사명" 접두사.
  const cls = isListing
    ? 'cal-chip chip-listing'
    : `cal-chip ${VERDICT_CLS[key]}`
  return (
    <span className={cls} title={title} aria-label={title}>
      <span className="chip-name">
        {isListing ? `(상장) ${ev.item.corp_name}` : ev.item.corp_name}
      </span>
    </span>
  )
}

function Legend() {
  const items = [
    { key: 'PASS-S',     cls: VERDICT_CLS['PASS-S'],     label: 'S 강력 추천' },
    { key: 'PASS-A',     cls: VERDICT_CLS['PASS-A'],     label: 'A 청약 유망' },
    { key: 'PASS-B',     cls: VERDICT_CLS['PASS-B'],     label: 'B 중립·주의' },
    { key: 'INCOMPLETE', cls: VERDICT_CLS['INCOMPLETE'], label: '판정 보류' },
    { key: 'REJECT',     cls: VERDICT_CLS['REJECT'],     label: 'REJECT 비추천' },
    { key: 'NEUTRAL',    cls: 'event-pending',           label: '판정 대기 · 정정 요구' },
    // v1.8 (#21 5번): 상장은 상태와 무관한 초록 단색 — 별도 범례 항목.
    { key: 'LISTING',    cls: 'event-listing',           label: '상장' },
  ]
  return (
    <div className="cal-legend" role="list" aria-label="범례">
      <span className="legend-head">범례</span>
      {items.map(it => (
        <span key={it.key} className={`legend-item ${it.cls}`} role="listitem">
          <span className="legend-swatch" aria-hidden /> {it.label}
        </span>
      ))}
      <span className="legend-sep">·</span>
      <span className="legend-note">칩은 <strong>회사명만</strong> 표기. 상장은 <strong>초록 단색</strong>으로 구분.</span>
    </div>
  )
}
