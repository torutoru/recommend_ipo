import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { useRegisterSW } from 'virtual:pwa-register/react'

// v1.11 (#32·#34): 새 서비스 워커가 대기 중이면 안내 배너.
//   - 자동 새로고침 금지(사용자가 눌러야 적용).
//   - offlineReady 는 조용히 무시(토스트 없이).
//   - 업데이트 체크 트리거: 등록 시 1회, 1시간 interval, visibilitychange(visible),
//     window focus, 라우트 이동. 60초 간격 미만은 skip(과도 호출 방지).
//   - 배너 '닫기' 후 다음 방문·라우트 이동·visibility 복귀 등으로 다시 감지되면 재표시.

const CHECK_THROTTLE_MS = 60_000
const CHECK_INTERVAL_MS = 60 * 60 * 1000

export function UpdateBanner() {
  const registrationRef = useRef<ServiceWorkerRegistration | null>(null)
  const lastCheckRef = useRef<number>(0)
  const location = useLocation()

  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      if (!registration) return
      registrationRef.current = registration
      // 등록 직후 1회 확인(캐시 TTL 영향 없이 네트워크로).
      void tryUpdate()
      try {
        setInterval(() => { void tryUpdate() }, CHECK_INTERVAL_MS)
      } catch { /* ignore */ }
    },
  })

  async function tryUpdate() {
    const reg = registrationRef.current
    if (!reg) return
    const now = Date.now()
    if (now - lastCheckRef.current < CHECK_THROTTLE_MS) return
    lastCheckRef.current = now
    try { await reg.update() } catch { /* 네트워크 실패는 조용히 무시 */ }
  }

  // visibilitychange + window focus → tryUpdate.
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState === 'visible') void tryUpdate()
    }
    function onFocus() { void tryUpdate() }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onFocus)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onFocus)
    }
  }, [])

  // 라우트 이동 때마다 tryUpdate(60초 throttle 로 과도 호출 자동 억제).
  useEffect(() => {
    void tryUpdate()
  }, [location.pathname])

  if (!needRefresh) return null

  function onRefresh() {
    void updateServiceWorker(true)
  }
  function onDismiss() {
    setNeedRefresh(false)
  }

  return (
    <div className="update-banner" role="status">
      <span>새 버전이 있습니다.</span>
      <div className="update-banner-actions">
        <button type="button" className="update-banner-primary" onClick={onRefresh}>
          새로고침
        </button>
        <button type="button" onClick={onDismiss} aria-label="닫기">닫기</button>
      </div>
    </div>
  )
}
