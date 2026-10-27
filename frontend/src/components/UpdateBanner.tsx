import { useRegisterSW } from 'virtual:pwa-register/react'

// v1.11 (#32): 새 서비스 워커가 대기 중이면 안내 배너.
//   - 자동 새로고침 금지(사용자가 눌러야 적용).
//   - offlineReady 는 조용히 무시(토스트 없이).

export function UpdateBanner() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    // 디폴트: 설치/업데이트 이벤트는 자동으로 활성화하지 않는다.
    onRegisteredSW(_swUrl, registration) {
      if (!registration) return
      // 1시간마다 서버에 업데이트 체크(사용자가 앱을 계속 열어둔 경우에도 안내 가능).
      try {
        setInterval(() => { void registration.update() }, 60 * 60 * 1000)
      } catch { /* ignore */ }
    },
  })

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
