import { Fragment, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { holdings, type Holding, type HoldingsStatus } from '../api/holdings'
import type { IpoSummary } from '../types'
import { parseYmd, toYmd } from '../utils/calendar'
import { fmtDate, fmtKrw, NULL_PLACEHOLDER } from '../utils/format'
import { Loading } from '../components/Loading'
import { HoldingForm } from '../components/HoldingForm'
import { scrollIntoViewOnMobile } from '../utils/focus'

type Bucket = 'today' | 'future' | 'undated' | 'past'

interface Row {
  holding: Holding
  ipo: IpoSummary | null
  bucket: Bucket
  daysUntil: number | null
}

function classify(ipo: IpoSummary | null, todayYmd: string): { bucket: Bucket; days: number | null } {
  if (!ipo || !ipo.listing_date) return { bucket: 'undated', days: null }
  if (ipo.listing_date === todayYmd) return { bucket: 'today', days: 0 }
  if (ipo.listing_date > todayYmd) {
    const dt = parseYmd(ipo.listing_date).getTime() - parseYmd(todayYmd).getTime()
    return { bucket: 'future', days: Math.round(dt / 86400000) }
  }
  return { bucket: 'past', days: null }
}

function StatusCell({ row }: { row: Row }) {
  switch (row.bucket) {
    case 'today':
      return <strong className="status-today">오늘 상장</strong>
    case 'future':
      return <span>D-{row.daysUntil}</span>
    case 'undated':
      return (
        <span className="status-undated" title="증권발행실적보고서 제출 후 자동 표시">
          상장일 미정
        </span>
      )
    case 'past':
      return <span className="status-past">상장 완료</span>
  }
}

const BUCKET_ORDER: Bucket[] = ['today', 'future', 'undated', 'past']

export function MyPage() {
  const [list, setList] = useState<Holding[]>(() => holdings.list())
  const [status, setStatus] = useState<HoldingsStatus>(() => holdings.getStatus())
  const [ipos, setIpos] = useState<IpoSummary[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [searchQ, setSearchQ] = useState('')
  const [pickedCorp, setPickedCorp] = useState<string | null>(null)
  const [editingCorp, setEditingCorp] = useState<string | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.listIpos()
      .then(res => { if (!cancelled) setIpos(res.items) })
      .catch(() => { if (!cancelled) setIpos([]) })
    return () => { cancelled = true }
  }, [])

  useEffect(() => holdings.subscribe(() => {
    setList(holdings.list())
    setStatus(holdings.getStatus())
  }), [])

  const todayYmd = toYmd(new Date())

  const rows: Row[] = useMemo(() => {
    const byCode = new Map((ipos ?? []).map(x => [x.id, x]))
    return list
      .map(h => {
        const ipo = byCode.get(h.corp_code) ?? null
        const { bucket, days } = classify(ipo, todayYmd)
        return { holding: h, ipo, bucket, daysUntil: days }
      })
      .sort((a, b) => {
        const oa = BUCKET_ORDER.indexOf(a.bucket)
        const ob = BUCKET_ORDER.indexOf(b.bucket)
        if (oa !== ob) return oa - ob
        if (a.bucket === 'future' && b.bucket === 'future') {
          return (a.daysUntil ?? 0) - (b.daysUntil ?? 0)
        }
        const an = a.ipo?.corp_name ?? a.holding.corp_code
        const bn = b.ipo?.corp_name ?? b.holding.corp_code
        return an.localeCompare(bn, 'ko')
      })
  }, [list, ipos, todayYmd])

  const totalInvestment = rows.reduce((s, r) => s + r.holding.shares * r.holding.price, 0)

  const addable = useMemo(() => {
    if (!ipos) return []
    const owned = new Set(list.map(h => h.corp_code))
    const q = searchQ.trim().toLowerCase()
    const candidates = ipos.filter(x => !owned.has(x.id))
    const filtered = q
      ? candidates.filter(x => x.corp_name.toLowerCase().includes(q))
      : candidates
    // 상장 완료 종목은 뒤로, 그 외는 subscription_end 가까운 순(미래 우선, null 은 뒤).
    return filtered.slice().sort((a, b) => {
      const aPast = a.listing_date !== null && a.listing_date < todayYmd
      const bPast = b.listing_date !== null && b.listing_date < todayYmd
      if (aPast !== bPast) return aPast ? 1 : -1
      const ae = a.subscription_end ?? '9999-12-31'
      const be = b.subscription_end ?? '9999-12-31'
      return ae.localeCompare(be)
    }).slice(0, 50)
  }, [ipos, list, searchQ, todayYmd])

  // v1.11 (#31): 초기 로딩은 holdings.loading 또는 IPO 목록 둘 중 하나라도 로딩 중이면 표시.
  if (ipos === null || (status.loading && rows.length === 0 && !status.loadError)) return (
    <section className="page page-my">
      <div className="page-head"><h2>내 공모주</h2></div>
      <Loading />
    </section>
  )

  async function onRemove(corpCode: string, name: string) {
    if (!confirm(`「${name}」을/를 내 공모주에서 삭제할까요?`)) return
    setRemoveError(null)
    try {
      await holdings.remove(corpCode)
    } catch (e) {
      setRemoveError(e instanceof Error ? `삭제 실패: ${e.message}` : '삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.')
    }
  }

  return (
    <section className="page page-my">
      <div className="page-head">
        <h2>내 공모주</h2>
        <button type="button" className="my-add-btn"
          onClick={() => { setAdding(a => !a); setSearchQ(''); setPickedCorp(null) }}>
          {adding ? '추가 창 닫기' : '+ 추가'}
        </button>
      </div>

      {status.loadError && (
        <div className="error" role="alert">
          <strong>목록을 불러오지 못했습니다.</strong> {status.loadError}
          <button type="button" className="my-retry-btn"
            onClick={() => { void holdings.reload() }}>
            다시 시도
          </button>
        </div>
      )}

      {removeError && (
        <div className="error" role="alert">{removeError}</div>
      )}

      {adding && (
        <div className="my-add-panel">
          <h3>종목 추가</h3>
          <input type="text" value={searchQ} onChange={e => setSearchQ(e.target.value)}
            placeholder="회사명 검색" aria-label="회사명 검색"
            onFocus={scrollIntoViewOnMobile} />
          <ul className="my-add-list">
            {addable.map(x => (
              <li key={x.id}>
                <button type="button" onClick={() => setPickedCorp(x.id)}
                  className={pickedCorp === x.id ? 'picked' : ''}>
                  <strong>{x.corp_name}</strong>
                  <span className="muted"> · 청약 {x.subscription_end ?? '미정'} · 상장 {x.listing_date ?? '미정'}</span>
                </button>
              </li>
            ))}
            {addable.length === 0 && <li className="muted">검색 결과가 없습니다.</li>}
          </ul>
          {pickedCorp && (() => {
            const picked = ipos.find(x => x.id === pickedCorp) ?? null
            return (
              <HoldingForm
                corpCode={pickedCorp}
                defaultPrice={picked?.final_price ?? null}
                onSaved={() => { setAdding(false); setPickedCorp(null); setSearchQ('') }}
                onCancel={() => { setPickedCorp(null) }}
              />
            )
          })()}
        </div>
      )}

      {rows.length === 0 && !adding ? (
        <div className="my-empty">
          <p>아직 등록된 공모주가 없습니다.</p>
          <p className="muted">「+ 추가」로 종목을 선택하거나, 종목 상세 화면의 「+ 청약 결과 입력」을 눌러 기록하세요.</p>
          <button type="button" className="my-add-btn" onClick={() => setAdding(true)}>+ 추가</button>
        </div>
      ) : rows.length > 0 ? (
        <div className="my-table-wrap">
          <table className="my-table">
            <thead>
              <tr>
                <th>종목</th>
                <th>상장일</th>
                <th className="num">수량</th>
                <th className="num">공모가</th>
                <th className="num">투자금액</th>
                <th>상태</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(r => {
                const isEditing = editingCorp === r.holding.corp_code
                return (
                  <Fragment key={r.holding.corp_code}>
                    <tr>
                      <td>
                        {r.ipo ? (
                          <Link to={`/ipos/${r.holding.corp_code}`}>{r.ipo.corp_name}</Link>
                        ) : (
                          <code>{r.holding.corp_code}</code>
                        )}
                      </td>
                      <td>{r.ipo?.listing_date ? fmtDate(r.ipo.listing_date) : NULL_PLACEHOLDER}</td>
                      <td className="num">{r.holding.shares.toLocaleString('ko-KR')}주</td>
                      <td className="num">{fmtKrw(r.holding.price)}</td>
                      <td className="num"><strong>{fmtKrw(r.holding.shares * r.holding.price)}</strong></td>
                      <td><StatusCell row={r} /></td>
                      <td className="my-actions">
                        <button type="button"
                          onClick={() => setEditingCorp(c => c === r.holding.corp_code ? null : r.holding.corp_code)}>
                          {isEditing ? '닫기' : '수정'}
                        </button>
                        <button type="button" className="holding-danger"
                          onClick={() => {
                            const name = r.ipo?.corp_name ?? r.holding.corp_code
                            void onRemove(r.holding.corp_code, name)
                          }}>
                          삭제
                        </button>
                      </td>
                    </tr>
                    {r.holding.memo && !isEditing && (
                      <tr className="my-memo-row">
                        <td colSpan={7}>메모: <em>{r.holding.memo}</em></td>
                      </tr>
                    )}
                    {isEditing && (
                      <tr className="my-edit-row">
                        <td colSpan={7}>
                          <HoldingForm
                            corpCode={r.holding.corp_code}
                            defaultPrice={r.ipo?.final_price ?? null}
                            onSaved={() => setEditingCorp(null)}
                            onCancel={() => setEditingCorp(null)}
                            onDeleted={() => setEditingCorp(null)}
                          />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={4}>합계 투자금액</td>
                <td className="num"><strong>{fmtKrw(totalInvestment)}</strong></td>
                <td colSpan={2}></td>
              </tr>
            </tfoot>
          </table>
        </div>
      ) : null}
    </section>
  )
}
