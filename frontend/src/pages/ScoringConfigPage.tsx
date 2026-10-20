import { useEffect, useState } from 'react'
import { api } from '../api'
import { ErrorBox, Loading } from '../components/Loading'
import type { ScoringConfig } from '../types'
import { fmtKrwAbbrev, pricePositionLabel } from '../utils/format'

export function ScoringConfigPage() {
  const [cfg, setCfg] = useState<ScoringConfig | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getScoringConfig()
      .then(c => { if (!cancelled) setCfg(c) })
      .catch(e => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
  }, [])

  return (
    <section className="page page-scoring">
      <h2>판정 기준 안내</h2>
      <p>
        <code>GET /api/scoring-config</code> 로부터 받은 현재 적용 기준입니다.
        backend 의 설정 파일과 같은 구조로, 코드 수정 없이 조정됩니다.
      </p>
      <p className="rule-note">
        v0.3 에서 하드 필터는 폐지됐습니다. 모든 종목은 네 지표의 합산 점수로만 판정되며,
        <strong> 총점 ≥ {' '}50점이면 PASS(S/A/B), 미만이면 REJECT</strong> 입니다. 수요예측 결과가 미공시이면 PENDING 으로 분류됩니다.
      </p>

      {error && <ErrorBox message={error} />}
      {!error && cfg === null && <Loading />}
      {!error && cfg !== null && <ScoringConfigView cfg={cfg} />}
    </section>
  )
}

function ScoringConfigView({ cfg }: { cfg: ScoringConfig }) {
  // v1.6 (#23): deposit 필드 폐지.
  const { score: sc, grade: gr, checklist: ck } = cfg
  return (
    <>
      <h3>1. 점수 (100점 만점)</h3>
      <div className="score-grid">
        <ScoreCard
          title={`① 기관 경쟁률 (최대 ${sc.comp.max})`}
          rows={[
            ...sc.comp.tiers.map(t => ({ cond: `≥ ${t.gte.toLocaleString()}:1`, pts: t.points })),
            { cond: '그 외', pts: sc.comp.default },
          ]}
          footer={
            <p className="score-footer">
              <strong>대형주 보완</strong>: 공모 금액 ≥{' '}
              <strong>{fmtKrwAbbrev(sc.comp.large_cap_bonus.min_offering_amount_krw)}</strong>{' '}
              이면서 경쟁률 ≥{' '}
              <strong>{sc.comp.large_cap_bonus.min_competition_rate.toLocaleString()}:1</strong>{' '}
              이면 <strong>+{sc.comp.large_cap_bonus.points}점</strong> (최대 {sc.comp.max}점 캡).
              기관 신청 금액은 가산 기준이 아닙니다.
            </p>
          }
        />
        <ScoreCard
          title={`② 확정 공모가 위치 (최대 ${sc.price.max})`}
          rows={(Object.keys(sc.price.points) as Array<keyof typeof sc.price.points>).map(k => ({
            cond: pricePositionLabel(k),
            pts: sc.price.points[k],
          }))}
        />
        <ScoreCard
          title={`③ 의무보유 확약 비율 (최대 ${sc.lockup.max})`}
          rows={(() => {
            const minTier = sc.lockup.tiers[sc.lockup.tiers.length - 1]
            return [
              ...sc.lockup.tiers.map(t => ({ cond: `≥ ${t.gte}%`, pts: t.points })),
              { cond: `< ${minTier?.gte ?? 0}%`, pts: sc.lockup.default },
            ]
          })()}
        />
        <ScoreCard
          title={`④ 유통가능 · 구주매출 (최대 ${sc.flow.max})`}
          rows={[
            {
              cond: `유통 > ${sc.flow.zero_if.tradable_gt}% 또는 구주 ≥ ${sc.flow.zero_if.old_share_gte}%`,
              pts: 0,
            },
            {
              cond: `유통 < ${sc.flow.top_if.tradable_lt}% 그리고 구주 = ${sc.flow.top_if.old_share_eq}%`,
              pts: sc.flow.top_if.points,
            },
            { cond: '그 외', pts: sc.flow.otherwise },
          ]}
          footer={<p className="score-footer">판정 순서: 0점 조건 먼저 평가 → 20점 조건 → 그 외는 중간 점수.</p>}
        />
      </div>

      <p className="rule-note">
        ※ 지표 값이 미공시이면 해당 지표 점수는 <strong>0점으로 계산</strong>되고,
        상세 화면 "판정 근거" 에 "미공시 — 0점 처리" 문장이 포함됩니다.
      </p>

      <h3>2. 등급</h3>
      <table className="grade-table">
        <thead>
          <tr><th>등급</th><th>점수</th><th>표기</th></tr>
        </thead>
        <tbody>
          <tr><td>S</td><td>≥ {gr.s_min}</td><td>강력 추천</td></tr>
          <tr><td>A</td><td>{gr.a_min} ~ {gr.s_min - 1}</td><td>청약 유망</td></tr>
          <tr><td>B</td><td>{gr.pass_min} ~ {gr.a_min - 1}</td><td>중립 · 주의</td></tr>
          <tr><td>REJECT</td><td>&lt; {gr.pass_min}</td><td>청약 비추천</td></tr>
        </tbody>
      </table>

      {/* v1.6 (#23): 균등 배정 최소 증거금 섹션 폐지. */}

      <h3>3. 체크리스트 만족 기준</h3>
      <table className="grade-table">
        <tbody>
          <tr>
            <td>기관 경쟁률</td>
            <td>
              ≥ {ck.competition_good_min.toLocaleString()}:1 <strong>좋음</strong>,{' '}
              ≥ {ck.competition_very_good_min.toLocaleString()}:1 <strong>아주 좋음</strong>
            </td>
          </tr>
          <tr><td>공모가 위치</td><td>{ck.price_positions_met.map(pricePositionLabel).join(' / ')}</td></tr>
          <tr><td>의무보유 확약</td><td>≥ {ck.lockup_min}%</td></tr>
          <tr><td>유통/구주</td><td>유통 ≤ {ck.flow_tradable_max}% 그리고 구주 &lt; {ck.flow_old_share_lt}%</td></tr>
        </tbody>
      </table>
    </>
  )
}

function ScoreCard({
  title,
  rows,
  footer,
}: {
  title: string
  rows: Array<{ cond: string; pts: number }>
  footer?: React.ReactNode
}) {
  return (
    <div className="score-card">
      <h4>{title}</h4>
      <table className="score-table">
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.cond}</td>
              <td className="score-pts">{r.pts}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {footer}
    </div>
  )
}
