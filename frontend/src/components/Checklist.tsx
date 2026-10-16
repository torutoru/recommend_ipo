import type { ChecklistItem, ChecklistResult } from '../types'

type ResultCfg = { icon: string; label: string; cls: string }

const RESULT_CFG: Record<ChecklistResult, ResultCfg> = {
  MET:     { icon: '✓', label: '만족',   cls: 'result-met' },
  NOT_MET: { icon: '✗', label: '불만족', cls: 'result-notmet' },
  UNKNOWN: { icon: '—', label: '미공시', cls: 'result-unknown' },
  INFO:    { icon: '',  label: '정보',   cls: 'result-info' },
}

export function Checklist({ items }: { items: ChecklistItem[] }) {
  const judged = items.filter(it => it.result === 'MET' || it.result === 'NOT_MET' || it.result === 'UNKNOWN')
  const metCount = judged.filter(it => it.result === 'MET').length
  const totalJudged = judged.length

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
            {items.map(item => {
              const cfg = RESULT_CFG[item.result]
              return (
                <tr key={item.key} className={cfg.cls}>
                  <td>{item.label}</td>
                  <td>{item.indicator}</td>
                  <td>{item.criterion}</td>
                  <td>{item.actual ?? '미공시'}</td>
                  <td>
                    {item.result === 'INFO' ? (
                      <span className="result-badge result-info" title="정보 항목">—</span>
                    ) : (
                      <span className={`result-badge ${cfg.cls}`} role="status">
                        <span className="result-icon" aria-hidden>{cfg.icon}</span>
                        <span>{cfg.label}</span>
                      </span>
                    )}
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
