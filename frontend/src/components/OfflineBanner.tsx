import { useEffect, useState } from 'react'
import { api } from '../api'
import { fmtDateTime } from '../utils/format'

// v1.11 (#32): 오프라인일 때 상단에 "마지막 수집" 기준을 안내.
// 상태 소스:
//   - navigator.onLine + 'online'/'offline' 이벤트
//   - last_collected_at 은 /api/health 로 1회 조회(그 후는 세션 캐시).

export function OfflineBanner() {
  const [online, setOnline] = useState<boolean>(() => {
    try { return navigator.onLine } catch { return true }
  })
  const [lastCollectedAt, setLastCollectedAt] = useState<string | null>(null)

  useEffect(() => {
    function onOnline() { setOnline(true) }
    function onOffline() { setOnline(false) }
    window.addEventListener('online', onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    api.getHealth()
      .then(h => { if (!cancelled) setLastCollectedAt(h.last_collected_at) })
      .catch(() => { /* 오프라인이면 조용히 무시 — 캐시가 있으면 이후 재시도 때 채워짐 */ })
    return () => { cancelled = true }
  }, [])

  if (online) return null

  return (
    <div className="offline-banner" role="status" aria-live="polite">
      <span className="offline-banner-icon" aria-hidden>⚠</span>
      오프라인입니다.
      {lastCollectedAt
        ? <> 표시 중인 데이터는 <strong>{fmtDateTime(lastCollectedAt)}</strong> 수집 기준입니다.</>
        : <> 캐시된 마지막 응답을 보여줍니다.</>}
    </div>
  )
}
