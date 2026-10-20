import type { ChecklistItem, ChecklistLevel, ChecklistResult } from '../types'

type ResultCfg = { icon: string; label: string; cls: string }

// MET 은 level 에 따라 세 가지 표시 — 아이콘·텍스트·색 병기.
function metCfg(level: ChecklistLevel | null): ResultCfg {
  if (level === 'VERY_GOOD') return { icon: '✓✓', label: '아주 좋음', cls: 'result-met result-met-very-good' }
  if (level === 'GOOD')      return { icon: '✓',  label: '좋음',       cls: 'result-met result-met-good' }
  return                            { icon: '✓',  label: '만족',       cls: 'result-met' }
}

const BASE_CFG: Record<Exclude<ChecklistResult, 'MET'>, ResultCfg> = {
  NOT_MET: { icon: '✗', label: '불만족', cls: 'result-notmet' },
  UNKNOWN: { icon: '—', label: '미공시', cls: 'result-unknown' },
}

function cfgFor(item: ChecklistItem): ResultCfg {
  // v0.9 backend 미반영 응답은 level 필드 자체가 없을 수 있음 → ?? null 로 default 경로.
  if (item.result === 'MET') return metCfg(item.level ?? null)
  return BASE_CFG[item.result] ?? BASE_CFG.UNKNOWN
}

// v1.5 (#22): 화면 표시 대상 key. backend 가 아직 6개(min_deposit·sell_timing 포함) 를 보내도
// 모르는 key 는 걸러서 UI 가 깨지지 않도록 한다.
const DISPLAY_KEYS = new Set<string>(['competition', 'price_position', 'lockup', 'flow'])

export function Checklist({ items }: { items: ChecklistItem[] }) {
  // 알 수 없는 key / 레거시 INFO 결과는 화면에서 제거.
  const visibleItems = items.filter(
    it => DISPLAY_KEYS.has(it.key) && (it.result === 'MET' || it.result === 'NOT_MET' || it.result === 'UNKNOWN'),
  )
  const metCount = visibleItems.filter(it => it.result === 'MET').length
  const totalJudged = visibleItems.length

  return (
    <section className="checklist">
      <h3>종목 체크리스트</h3>
      <p className="checklist-summary">
        판정 항목 <strong>{totalJudged}</strong>개 중{' '}
        <strong className="checklist-met-count">{metCount}개 만족</strong>
      </p>
      <div className="table-wrap">
        <table className="checklist-table">
          <thead>
            <tr>
              <th>평가 항목</th>
              <th>지표</th>
              <th>만족 기준</th>
              <th>이 종목 값</th>
              <th>결과</th>
            </tr>
          </thead>
          <tbody>
            {visibleItems.map(item => {
              const cfg = cfgFor(item)
              return (
                <tr key={item.key} className={cfg.cls}>
                  <td>{item.label}</td>
                  <td>{item.indicator}</td>
                  <td>{item.criterion}</td>
                  <td>{item.actual ?? '미공시'}</td>
                  <td>
                    <span className={`result-badge ${cfg.cls}`} role="status">
                      <span className="result-icon" aria-hidden>{cfg.icon}</span>
                      <span>{cfg.label}</span>
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
