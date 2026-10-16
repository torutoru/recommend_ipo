import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import type { IpoDetail } from '../types'
import {
  gradeExecGuide,
  gradeExecLabel,
  VerdictBadge,
} from '../components/Badge'
import { Checklist } from '../components/Checklist'
import { ErrorBox, Loading } from '../components/Loading'
import {
  competitionRateTypeLabel,
  docTypeLabel,
  fmtBand,
  fmtDate,
  fmtDateRange,
  fmtKrw,
  fmtKrwAbbrev,
  fmtOrNull,
  fmtPct,
  fmtRatio,
  fmtShares,
  lockupRatioBasisLabel,
  marketLabel,
  NULL_PLACEHOLDER,
  pricePositionLabel,
} from '../utils/format'

type IndicatorRow = {
  label: string
  value: string
  sub?: string
  scoreValue: number | null
  scoreMax: number
  indicatorMissing: boolean
}

function buildIndicatorRows(detail: IpoDetail): IndicatorRow[] {
  const { indicators: ind, scores: s } = detail
  return [
    {
      label: '① 기관 수요예측 경쟁률',
      value: `${fmtOrNull(ind.competition_rate, fmtRatio)}${
        ind.demand_amount_krw !== null
          ? ` · 신청 금액 ${fmtKrwAbbrev(ind.demand_amount_krw)} (참고)`
          : ''
      }`,
      sub: `집계 방식: ${competitionRateTypeLabel(ind.competition_rate_type)} · 가산 기준은 공모 금액`,
      scoreValue: s.comp,
      scoreMax: 35,
      indicatorMissing: ind.competition_rate === null,
    },
    {
      label: '② 확정 공모가 위치 (희망 밴드 대비)',
      value: pricePositionLabel(ind.price_position),
      scoreValue: s.price,
      scoreMax: 25,
      indicatorMissing: ind.price_position === null,
    },
    {
      label: '③ 기관 의무보유 확약 비율',
      value: fmtOrNull(ind.lockup_ratio, fmtPct),
      sub: `기준: ${lockupRatioBasisLabel(ind.lockup_ratio_basis)}`,
      scoreValue: s.lockup,
      scoreMax: 20,
      indicatorMissing: ind.lockup_ratio === null,
    },
    {
      label: '④ 상장일 유통가능 · 구주매출 비율',
      value: `유통 ${fmtOrNull(ind.tradable_ratio, fmtPct)} · 구주 ${fmtOrNull(ind.old_share_ratio, fmtPct)}`,
      scoreValue: s.flow,
      scoreMax: 20,
      indicatorMissing: ind.tradable_ratio === null || ind.old_share_ratio === null,
    },
  ]
}

function scoreLabel(row: IndicatorRow): string {
  if (row.scoreValue === null) return `${NULL_PLACEHOLDER} / ${row.scoreMax}`
  return `${row.scoreValue} / ${row.scoreMax}`
}

export function DetailPage() {
  const { id } = useParams<{ id: string }>()
  const [shares, setShares] = useState<number>(10)
  const [sharesInput, setSharesInput] = useState<string>('10')
  const [detail, setDetail] = useState<IpoDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    setDetail(null)
    setError(null)
    api
      .getIpo(id, shares)
      .then(d => { if (!cancelled) setDetail(d) })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [id, shares])

  function onSubmitShares(e: React.FormEvent) {
    e.preventDefault()
    const n = parseInt(sharesInput, 10)
    if (!Number.isFinite(n) || n <= 0) return
    setShares(n)
  }

  if (!id) return <p>잘못된 요청입니다.</p>
  if (error) return <ErrorBox message={error} />
  if (detail === null) return <Loading />

  const rows = buildIndicatorRows(detail)
  const scoreTotal = detail.scores.total
  const totalLine =
    scoreTotal === null
      ? NULL_PLACEHOLDER
      : `${scoreTotal} / 100`
  const execLabel = gradeExecLabel(detail.verdict.status, detail.verdict.grade)
  const execGuide = gradeExecGuide(detail.verdict.status, detail.verdict.grade)

  const ind = detail.indicators
  const md = detail.min_deposit

  return (
    <section className="page page-detail">
      <div className="back-link">
        <Link to="/">← 목록으로</Link>
      </div>

      <header className="detail-head">
        <h2>
          {detail.corp_name}
          <span className="verdict-wrap"><VerdictBadge verdict={detail.verdict} /></span>
        </h2>
        <dl className="meta">
          <div><dt>시장</dt><dd>{marketLabel(detail.market)}</dd></div>
          <div><dt>청약일</dt><dd>{fmtDateRange(detail.subscription_start, detail.subscription_end)}</dd></div>
          <div><dt>상장일</dt><dd>{fmtOrNull(detail.listing_date, fmtDate)}</dd></div>
          <div><dt>희망 밴드</dt><dd>{fmtBand(detail.band_low, detail.band_high)}</dd></div>
          <div><dt>확정 공모가</dt><dd>{fmtOrNull(detail.final_price, fmtKrw)}</dd></div>
          <div><dt>총점 · 등급</dt>
            <dd>
              {totalLine}
              {detail.verdict.grade && (
                <> · <strong>{detail.verdict.grade}</strong></>
              )}
            </dd>
          </div>
          <div><dt>기준 공시 접수번호</dt><dd>{fmtOrNull(ind.report_rcept_no, s => s)}</dd></div>
          <div><dt>갱신 시각</dt><dd>{detail.updated_at}</dd></div>
        </dl>
      </header>

      {execLabel && (
        <aside className={`grade-exec grade-exec-${detail.verdict.status.toLowerCase()}`}>
          <strong>{execLabel}</strong>
          <span> — {execGuide}</span>
        </aside>
      )}

      <Checklist items={detail.checklist} />

      <h3>지표 및 점수</h3>
      <div className="indicator-grid">
        {rows.map((r, i) => {
          const showMissing = r.indicatorMissing && r.scoreValue !== null
          return (
            <div className="indicator-card" key={i}>
              <div className="indicator-label">{r.label}</div>
              <div className="indicator-value">{r.value}</div>
              {r.sub && <div className="indicator-sub">{r.sub}</div>}
              <div className="indicator-score">
                점수 {scoreLabel(r)}
                {showMissing && (
                  <span className="indicator-missing" title="지표 미공시 — 0점 처리">
                    · 미공시
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <h3>공모 구조</h3>
      <dl className="meta meta-cols-4">
        <div><dt>신주모집 수량</dt><dd>{fmtOrNull(ind.new_share_count, fmtShares)}</dd></div>
        <div><dt>구주매출 수량</dt><dd>{fmtOrNull(ind.old_share_count, fmtShares)}</dd></div>
        <div><dt>총 공모 수량</dt><dd>{fmtOrNull(ind.total_offering_count, fmtShares)}</dd></div>
        <div>
          <dt>공모 금액 <span className="meta-badge">가산 기준</span></dt>
          <dd>{fmtOrNull(ind.offering_amount_krw, fmtKrwAbbrev)}</dd>
        </div>
      </dl>

      <h3>판정 근거</h3>
      {detail.reasons.length === 0 && detail.reject_reasons.length === 0 && (
        <p className="empty">판정 근거가 아직 없습니다.</p>
      )}
      {detail.reasons.length > 0 && (
        <ul className="reasons reasons-pass">
          {detail.reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
      {detail.reject_reasons.length > 0 && (
        <>
          <h4>REJECT 사유</h4>
          <ul className="reasons reasons-reject">
            {detail.reject_reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </>
      )}

      <h3>균등 배정 최소 증거금</h3>
      <form className="deposit-form" onSubmit={onSubmitShares}>
        <label>
          수량(주){' '}
          <input
            type="number"
            min={1}
            step={1}
            value={sharesInput}
            onChange={e => setSharesInput(e.target.value)}
          />
        </label>
        <button type="submit">다시 계산</button>
      </form>
      {md === null ? (
        <p className="empty">확정 공모가 미공시 — 계산 불가.</p>
      ) : (
        <dl className="deposit-breakdown">
          <div>
            <dt>증거금 ({md.shares}주 × {fmtOrNull(detail.final_price, fmtKrw)} × 50%)</dt>
            <dd>{fmtKrw(md.deposit_krw)}</dd>
          </div>
          <div>
            <dt>청약 수수료</dt>
            <dd>{fmtKrw(md.fee_krw)}</dd>
          </div>
          <div className="deposit-total">
            <dt>합계</dt>
            <dd><strong>{fmtKrw(md.total_krw)}</strong></dd>
          </div>
        </dl>
      )}

      <h3>원문 공시 (DART)</h3>
      {detail.sources.length === 0 ? (
        <p className="empty">연결된 공시 문서가 없습니다.</p>
      ) : (
        <ul className="sources">
          {detail.sources.map(s => (
            <li key={s.rcept_no}>
              <a href={s.url} target="_blank" rel="noopener noreferrer">
                {docTypeLabel(s.doc_type)} ({s.rcept_dt}) — 접수번호 {s.rcept_no}
              </a>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
