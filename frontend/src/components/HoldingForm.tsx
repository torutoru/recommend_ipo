import { useState } from 'react'
import { holdings, type Holding } from '../api/holdings'
import { fmtKrw } from '../utils/format'
import { scrollIntoViewOnMobile } from '../utils/focus'

interface Props {
  corpCode: string
  defaultPrice: number | null
  onSaved?: (h: Holding) => void
  onCancel?: () => void
  onDeleted?: () => void
}

function parseIntOrNull(s: string): number | null {
  const trimmed = s.replace(/[,\s]/g, '')
  if (!/^\d+$/.test(trimmed)) return null
  const n = Number(trimmed)
  return Number.isFinite(n) && n >= 1 ? n : null
}

export function HoldingForm({ corpCode, defaultPrice, onSaved, onCancel, onDeleted }: Props) {
  const existing = holdings.get(corpCode)
  const [sharesStr, setSharesStr] = useState(existing ? String(existing.shares) : '')
  const [priceStr, setPriceStr] = useState(
    existing ? String(existing.price) : (defaultPrice !== null ? String(defaultPrice) : '')
  )
  const [memo, setMemo] = useState(existing?.memo ?? '')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const shares = parseIntOrNull(sharesStr)
  const price = parseIntOrNull(priceStr)
  const total = shares !== null && price !== null ? shares * price : null

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (shares === null) { setErr('배정 수량은 1 이상의 정수여야 합니다.'); return }
    if (price === null) { setErr('공모가는 1 이상의 정수(원)여야 합니다.'); return }
    setErr(null)
    setBusy(true)
    try {
      // v1.11 (#31): 서버 저장. 실패 시 입력값은 유지하고 오류만 표시.
      const saved = await holdings.upsert({ corp_code: corpCode, shares, price, memo: memo.slice(0, 60) })
      onSaved?.(saved)
    } catch (e) {
      setErr(e instanceof Error ? `저장 실패: ${e.message}` : '저장에 실패했습니다. 잠시 후 다시 시도해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  async function onDelete() {
    if (!existing) return
    if (!confirm('이 종목을 「내 공모주」에서 삭제할까요?')) return
    setErr(null)
    setBusy(true)
    try {
      await holdings.remove(corpCode)
      onDeleted?.()
    } catch (e) {
      setErr(e instanceof Error ? `삭제 실패: ${e.message}` : '삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="holding-form" onSubmit={onSubmit}>
      <label>
        <span>배정 수량 (주)</span>
        <input type="text" inputMode="numeric" pattern="[0-9]*" value={sharesStr}
          onChange={e => setSharesStr(e.target.value)} placeholder="예: 10" required autoFocus
          onFocus={scrollIntoViewOnMobile} disabled={busy} />
      </label>
      <label>
        <span>공모가 (원)</span>
        <input type="text" inputMode="numeric" pattern="[0-9]*" value={priceStr}
          onChange={e => setPriceStr(e.target.value)} placeholder="확정 공모가" required
          onFocus={scrollIntoViewOnMobile} disabled={busy} />
      </label>
      <div className="holding-total">
        투자금액: <strong>{total !== null ? fmtKrw(total) : '—'}</strong>
      </div>
      <label className="holding-memo">
        <span>메모 (선택, 최대 60자)</span>
        <input type="text" maxLength={60} value={memo}
          onChange={e => setMemo(e.target.value)} placeholder="예: 균등 10주, 비례 미참여"
          onFocus={scrollIntoViewOnMobile} disabled={busy} />
      </label>
      {err && <p className="holding-err" role="alert">{err}</p>}
      <div className="holding-actions">
        <button type="submit" disabled={busy}>
          {busy ? '저장 중…' : (existing ? '변경 저장' : '저장')}
        </button>
        {existing && (
          <button type="button" onClick={onDelete} className="holding-danger" disabled={busy}>
            삭제
          </button>
        )}
        {onCancel && (
          <button type="button" onClick={onCancel} disabled={busy}>취소</button>
        )}
      </div>
    </form>
  )
}
