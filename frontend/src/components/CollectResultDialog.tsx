import { useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import type { CollectCorpRef } from '../types'

// v1.9 (#40): 수집 결과 요약 항목(신규/갱신/변화없음/실패)을 눌렀을 때 뜨는 간이 다이얼로그.
// - ESC·바깥 클릭·닫기 버튼으로 닫힘.
// - 회사명 클릭 → /ipos/:id 이동(다이얼로그 닫힘).
// - 0건 항목은 "없음" 안내만.

interface Props {
  title: string
  items: CollectCorpRef[]
  onClose: () => void
}

export function CollectResultDialog({ title, items, onClose }: Props) {
  const panelRef = useRef<HTMLDivElement | null>(null)
  const closeBtnRef = useRef<HTMLButtonElement | null>(null)

  // ESC → 닫기.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.stopPropagation(); onClose() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // 포커스를 닫기 버튼으로.
  useEffect(() => {
    closeBtnRef.current?.focus()
  }, [])

  function onBackdropClick(e: React.MouseEvent) {
    if (e.target === e.currentTarget) onClose()
  }

  return (
    <div className="result-dialog-backdrop" onClick={onBackdropClick} role="presentation">
      <div
        className="result-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="result-dialog-title"
        ref={panelRef}
      >
        <div className="result-dialog-head">
          <h3 id="result-dialog-title">{title} <span className="muted">({items.length})</span></h3>
          <button type="button" ref={closeBtnRef} onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </div>
        {items.length === 0 ? (
          <p className="result-dialog-empty">없음</p>
        ) : (
          <ul className="result-dialog-list">
            {items.map(c => (
              <li key={c.corp_code}>
                <Link to={`/ipos/${c.corp_code}`} onClick={onClose}>
                  <span className="result-dialog-name">{c.corp_name}</span>
                  <code className="result-dialog-code">{c.corp_code}</code>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
