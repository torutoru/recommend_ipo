import type { Grade, Status, Verdict } from '../types'

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  if (verdict.status === 'PENDING') {
    return <span className="badge badge-pending" title="수요예측 미공시">판정 대기</span>
  }
  if (verdict.status === 'REJECT') {
    return <span className="badge badge-reject" title="청약 비추천">REJECT</span>
  }
  const grade = verdict.grade ?? '-'
  return (
    <span className={`badge badge-pass badge-grade-${grade}`}>
      PASS · {grade}
    </span>
  )
}

export const GRADE_LABEL: Record<Grade, string> = {
  S: '강력 추천',
  A: '청약 유망',
  B: '중립 · 주의',
}

export const REJECT_LABEL = '청약 비추천'

export function gradeExecLabel(status: Status, grade: Grade | null): string {
  if (status === 'REJECT') return REJECT_LABEL
  if (grade === null) return ''
  return GRADE_LABEL[grade]
}

export function gradeExecGuide(status: Status, grade: Grade | null): string {
  if (status === 'REJECT') {
    return '원금 손실 위험이 큰 종목으로 분류됩니다. 청약 보류 / 패스를 권장합니다.'
  }
  switch (grade) {
    case 'S':
      return '균등 배정 필수 참여. 자금 여력이 있다면 비례 배정 청약까지 적극 검토.'
    case 'A':
      return '균등 배정 참여 추천. 소액 현금(증거금) 을 활용해 안전한 시초가 차익 실현 목표.'
    case 'B':
      return '공모주 시장 분위기와 주관사 경쟁률 추이를 관망한 뒤 제한적 균등 참여.'
    default:
      return ''
  }
}
