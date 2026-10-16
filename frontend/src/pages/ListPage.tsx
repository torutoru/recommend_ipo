import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import type { IpoSummary, Status } from '../types'
import { VerdictBadge } from '../components/Badge'
import { ErrorBox, Loading } from '../components/Loading'
import {
  fmtBand,
  fmtDate,
  fmtKrw,
  fmtOrNull,
  marketLabel,
  NULL_PLACEHOLDER,
} from '../utils/format'

const STATUS_OPTIONS: { value: '' | Status; label: string }[] = [
  { value: '', label: '전체' },
  { value: 'PENDING', label: '판정 대기 (PENDING)' },
  { value: 'PASS', label: 'PASS' },
  { value: 'REJECT', label: 'REJECT' },
]

export function ListPage() {
  const [params, setParams] = useSearchParams()
  const status = (params.get('status') as Status | null) ?? ''
  const [items, setItems] = useState<IpoSummary[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const query = useMemo(() => (status ? { status } : {}), [status])

  useEffect(() => {
    let cancelled = false
    setItems(null)
    setError(null)
    api
      .listIpos(query)
      .then(res => { if (!cancelled) setItems(res.items) })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [query])

  function onStatusChange(next: string) {
    const nextParams = new URLSearchParams(params)
    if (next) nextParams.set('status', next)
    else nextParams.delete('status')
    setParams(nextParams, { replace: true })
  }

  return (
    <section className="page page-list">
      <div className="page-head">
        <h2>청약 예정 종목</h2>
        <label className="filter">
          <span>status</span>
          <select
            value={status}
            onChange={e => onStatusChange(e.target.value)}
          >
            {STATUS_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </label>
      </div>

      {error && <ErrorBox message={error} />}
      {!error && items === null && <Loading />}
      {!error && items !== null && items.length === 0 && (
        <p className="empty">조건에 맞는 종목이 없습니다.</p>
      )}
      {!error && items !== null && items.length > 0 && (
        <div className="table-wrap">
          <table className="ipo-table">
            <thead>
              <tr>
                <th>종목명</th>
                <th>시장</th>
                <th>청약일</th>
                <th>상장일</th>
                <th>밴드 / 확정가</th>
                <th>판정</th>
                <th>점수</th>
              </tr>
            </thead>
            <tbody>
              {items.map(it => (
                <tr key={it.id}>
                  <td>
                    <Link to={`/ipos/${it.id}`}>{it.corp_name}</Link>
                  </td>
                  <td>{marketLabel(it.market)}</td>
                  <td>
                    {fmtOrNull(it.subscription_start, fmtDate)}
                    {it.subscription_end && it.subscription_end !== it.subscription_start
                      ? ` ~ ${fmtDate(it.subscription_end)}`
                      : ''}
                  </td>
                  <td>{fmtOrNull(it.listing_date, fmtDate)}</td>
                  <td className="band-cell">
                    <div>{fmtBand(it.band_low, it.band_high)}</div>
                    <div className="band-final">
                      확정 {fmtOrNull(it.final_price, fmtKrw)}
                    </div>
                  </td>
                  <td><VerdictBadge verdict={it.verdict} /></td>
                  <td className="score-cell">
                    {it.verdict.score === null
                      ? NULL_PLACEHOLDER
                      : `${it.verdict.score} / 100`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
