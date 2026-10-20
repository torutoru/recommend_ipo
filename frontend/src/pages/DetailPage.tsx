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

// v1.6 (#24): 공모가 위치 카드의 짧은 기준 힌트.
const PRICE_HINT = '최상단 초과 시 25점'

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
      // v1.6 (#24): 카드 하단에 짧은 기준 힌트.
      sub: PRICE_HINT,
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
  const [detail, setDetail] = useState<IpoDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  // v1.6 (#23): shares 쿼리 제거 — 증거금 영역 폐지.
  useEffect(() => {
    if (!id) return
    let cancelled = false
    setDetail(null)
    setError(null)
    api
      .getIpo(id)
      .then(d => { if (!cancelled) setDetail(d) })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [id])

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
          <div>
            <dt>수요예측 기간</dt>
            <dd>{fmtDateRange(detail.demand_forecast_start ?? null, detail.demand_forecast_end ?? null)}</dd>
          </div>
          <div>
            <dt>확정공고일 (기관 결과 공개 예정)</dt>
            <dd>{fmtOrNull(detail.price_confirm_date ?? null, fmtDate)}</dd>
          </div>
          <div><dt>희망 밴드</dt><dd>{fmtBand(detail.band_low, detail.band_high)}</dd></div>
          <div><dt>확정 공모가</dt><dd>{fmtOrNull(detail.final_price, fmtKrw)}</dd></div>
          <div><dt>총점 · 등급</dt>
            <dd>
              {(() => {
                if (detail.verdict.status === 'INCOMPLETE') {
                  return <strong className="verdict-incomplete">판정 보류 · 데이터 확인 필요</strong>
                }
                const range = detail.verdict.score_range
                // v1.4 — PASS: "min~max점 · 최소 등급". REJECT: "최대 max점".
                if (range && detail.verdict.status === 'PASS') {
                  return (
                    <>
                      <strong>{range.min}~{range.max}점</strong>
                      {detail.verdict.grade && (
                        <> · <strong>최소 {detail.verdict.grade}</strong></>
                      )}
                    </>
                  )
                }
                if (range && detail.verdict.status === 'REJECT') {
                  return <><strong>최대 {range.max}점</strong></>
                }
                // 기존 단일 점수 표시 (score_range null 또는 그 외 상태).
                return (
                  <>
                    {totalLine}
                    {detail.verdict.grade && (
                      <> · <strong>{detail.verdict.grade}</strong></>
                    )}
                  </>
                )
              })()}
            </dd>
          </div>
          <div>
            <dt>주관사</dt>
            <dd>
              {(() => {
                // backend 미반영 상태에서 응답에 필드 자체가 없을 수 있음 (undefined).
                const list = detail.underwriters ?? []
                return list.length === 0 ? NULL_PLACEHOLDER : list.join(', ')
              })()}
            </dd>
          </div>
          <div><dt>기준 공시 접수번호</dt><dd>{fmtOrNull(ind.report_rcept_no, s => s)}</dd></div>
          <div><dt>갱신 시각</dt><dd>{detail.updated_at}</dd></div>
        </dl>
      </header>

      {/* v1.1 — PENDING 인데 확정공고일이 이미 지났으면 "다시 수집" 유도
          (backend 미반영 응답은 price_confirm_date 가 undefined 일 수 있음 — `!= null` 로 둘 다 처리) */}
      {detail.verdict.status === 'PENDING' &&
        detail.price_confirm_date != null &&
        detail.price_confirm_date < new Date().toISOString().slice(0, 10) && (
          <aside className="overdue-banner" role="status">
            확정공고일({detail.price_confirm_date})이 지났지만 아직 수요예측 결과가 수집되지 않았습니다.
            홈에서 <strong>"수집 및 분석하기"</strong> 를 눌러 다시 시도해 주세요.
          </aside>
        )}

      {detail.verdict.status === 'CORRECTION' && detail.verdict.correction && (
        <aside className="correction-banner" role="alert">
          <h3><span aria-hidden>⚠</span> 금융감독원 정정신고서 제출요구</h3>
          <p>
            제출요구일: <strong>{detail.verdict.correction.requested_at}</strong>
            {detail.verdict.correction.amended_at
              ? <> · 정정신고서 제출일: <strong>{detail.verdict.correction.amended_at}</strong></>
              : <> · <strong>정정신고서 아직 미제출</strong></>}
          </p>
          <p>
            청약 일정이 바뀔 수 있습니다. 증권사 공지를 반드시 확인하세요.
          </p>
        </aside>
      )}

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
          // v1.0: 미공시 0점 처리 폐지. 지표 null + 점수 null 인 INCOMPLETE 종목에서
          // 해당 지표 셀에 "확인 필요" 라벨을 붙여 판정 보류 사유를 바로 보이게.
          // v1.4: score_range 로 PASS/REJECT 확정된 종목도 미확인 지표에 "확인 필요".
          const needsInput =
            r.indicatorMissing &&
            (
              (detail.verdict.status === 'INCOMPLETE' && r.scoreValue === null) ||
              (detail.verdict.score_range != null)
            )
          return (
            <div className="indicator-card" key={i}>
              <div className="indicator-label">{r.label}</div>
              <div className="indicator-value">{r.value}</div>
              {r.sub && <div className="indicator-sub">{r.sub}</div>}
              <div className="indicator-score">
                점수 {scoreLabel(r)}
                {needsInput && (
                  <span className="indicator-missing" title="데이터 확인 필요 — 판정 보류">
                    · 확인 필요
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

      {/* v1.6 (#23): 균등 배정 최소 증거금 섹션 폐지. 안내 매도 전략 문구는 /guide 로 이동 유지. */}

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
