import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { CollectStatus } from '../types'
import { fmtDateTime } from '../utils/format'
import { HttpError } from '../utils/httpError'
import { clearCollectKey, loadCollectKey, saveCollectKey } from '../utils/collectKey'
import { scrollIntoViewOnMobile } from '../utils/focus'

interface Props {
  onSucceeded: () => void
}

const POLL_MS = 2500

export function CollectBar({ onSucceeded }: Props) {
  const [collect, setCollect] = useState<CollectStatus | null>(null)
  const [key, setKey] = useState<string | null>(() => loadCollectKey())
  const [showKeyPrompt, setShowKeyPrompt] = useState(false)
  const [keyInput, setKeyInput] = useState('')
  const [blocked, setBlocked] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [keyError, setKeyError] = useState<string | null>(null)
  const prevLastRef = useRef<string | null>(null)

  // 진입 시 상태 1회 조회 (다른 탭에서 이미 RUNNING 인 경우 대비).
  useEffect(() => {
    let cancelled = false
    api
      .getCollectStatus()
      .then(s => {
        if (cancelled) return
        setCollect(s)
        prevLastRef.current = s.last_collected_at
      })
      .catch(() => { /* backend 미지원이면 조용히 */ })
    return () => { cancelled = true }
  }, [])

  // RUNNING 폴링. 완료 시 달력 재조회 트리거.
  useEffect(() => {
    if (collect?.status !== 'RUNNING') return
    const id = setInterval(() => {
      api
        .getCollectStatus()
        .then(s => {
          setCollect(s)
          if (s.status === 'SUCCEEDED' && s.last_collected_at !== prevLastRef.current) {
            prevLastRef.current = s.last_collected_at
            onSucceeded()
          }
        })
        .catch(() => { /* ignore */ })
    }, POLL_MS)
    return () => clearInterval(id)
  }, [collect?.status, onSucceeded])

  async function tryCollect(withKey: string | null) {
    setBlocked(null)
    setError(null)
    setKeyError(null)
    try {
      const res = await api.postCollect(withKey)
      if (res.kind === 'BLOCKED') {
        setBlocked(res.detail)
        return
      }
      setCollect(res.data)
      setShowKeyPrompt(false)
    } catch (e) {
      if (e instanceof HttpError && e.status === 401) {
        setKeyError(e.message)
        setShowKeyPrompt(true)
        return
      }
      // Netlify 프록시 ~26s vs Render 콜드스타트 30s+ 간극 보완.
      // POST 는 자동 재시도 금지(중복 실행 위험) — 대신 getCollectStatus 로 실제 시작 여부 확인.
      if (e instanceof HttpError && (e.status === 502 || e.status === 503 || e.status === 504)) {
        try {
          const s = await api.getCollectStatus()
          setCollect(s)
          if (s.status === 'RUNNING') {
            // 다른 경로에서 이미 시작됐거나 요청이 결국 서버에 전달됨.
            setShowKeyPrompt(false)
            return
          }
          setError(`수집 요청이 서버에 전달되지 못했습니다 (HTTP ${e.status}). 다시 시도해 주세요.`)
        } catch {
          setError(`수집 서버 응답 없음 (HTTP ${e.status}). 서버가 아직 깨어나는 중일 수 있습니다. 다시 시도해 주세요.`)
        }
        return
      }
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  function onSubmitKey(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = keyInput.trim()
    if (!trimmed) return
    saveCollectKey(trimmed)
    setKey(trimmed)
    setKeyInput('')
    tryCollect(trimmed)
  }

  function onClearKey() {
    clearCollectKey()
    setKey(null)
    setShowKeyPrompt(false)
    setKeyError(null)
  }

  const running = collect?.status === 'RUNNING'
  const btnLabel = running
    ? `수집 중…${collect?.progress ? ` (${collect.progress.done}${collect.progress.total ? ' / ' + collect.progress.total : ''})` : ''}`
    : collect?.status === 'FAILED' ? '다시 시도' : '수집 및 분석하기'
  const lastLabel = collect?.last_collected_at
    ? `마지막 수집: ${fmtDateTime(collect.last_collected_at)}`
    : '수집 이력 없음'

  return (
    <>
      <div className="collect-bar">
        <button
          type="button"
          className="collect-btn"
          onClick={() => tryCollect(key)}
          disabled={running}
          aria-busy={running}
        >
          {btnLabel}
        </button>
        <span className="last-collected">{lastLabel}</span>

        {collect?.status === 'SUCCEEDED' && collect.summary && (
          <span className="collect-summary">
            신규 {collect.summary.new_count} · 갱신 {collect.summary.updated_count} · 변화 없음 {collect.summary.unchanged_count} · 실패 {collect.summary.failed_count}
            {collect.summary.withdrawn_count > 0 && ` · 철회 ${collect.summary.withdrawn_count}`}
          </span>
        )}
        {collect?.status === 'FAILED' && collect.error && (
          <span className="collect-error" role="alert">실패: {collect.error}</span>
        )}
        {blocked && <span className="collect-blocked" role="status">⚠ {blocked}</span>}
        {error && <span className="collect-error" role="alert">⚠ {error}</span>}

        <span className="key-state">
          {key ? (
            <>
              키 <code>저장됨 ({key.length}자)</code>
              <button type="button" className="key-link" onClick={() => { setKeyInput(''); setShowKeyPrompt(true) }}>변경</button>
              <button type="button" className="key-link" onClick={onClearKey}>삭제</button>
            </>
          ) : (
            <button type="button" className="key-link" onClick={() => { setKeyInput(''); setShowKeyPrompt(true) }}>수집 키 설정</button>
          )}
        </span>
      </div>

      {/* v1.3 (#26-3): 수집 완료 후 실패 종목·사유 접이식 목록 */}
      {(collect?.status === 'SUCCEEDED' || collect?.status === 'FAILED') &&
        collect.failures != null && collect.failures.length > 0 && (
          <details className="collect-failures">
            <summary>실패 종목 {collect.failures.length}건 보기</summary>
            <ul>
              {collect.failures.map((f, i) => (
                <li key={i}>
                  <strong>{f.corp_name}</strong>
                  <code> ({f.corp_code})</code>
                  <span> — {f.reason}</span>
                </li>
              ))}
            </ul>
          </details>
        )}

      {showKeyPrompt && (
        <form className="key-prompt" onSubmit={onSubmitKey}>
          <p className="key-prompt-head">
            {keyError
              ? `${keyError} 다시 입력해 주세요.`
              : '서버에 수집 키가 설정돼 있으면 입력해 주세요. 로컬 개발 등 키 미설정 서버에서는 입력 없이도 수집 버튼이 동작합니다.'}
          </p>
          <label>
            <span>수집 키</span>
            <input
              type="password"
              autoComplete="off"
              value={keyInput}
              onChange={e => setKeyInput(e.target.value)}
              placeholder="X-Collect-Key"
              autoFocus
              onFocus={scrollIntoViewOnMobile}
            />
          </label>
          <div className="key-prompt-actions">
            <button type="submit" disabled={!keyInput.trim()}>저장 후 수집 시작</button>
            <button type="button" onClick={() => setShowKeyPrompt(false)}>닫기</button>
          </div>
          <p className="key-prompt-note">
            이 키는 브라우저 로컬 저장소(<code>localStorage</code>)에 보관되며, 서버로는{' '}
            <code>X-Collect-Key</code> 헤더로만 전송됩니다.
          </p>
        </form>
      )}
    </>
  )
}
