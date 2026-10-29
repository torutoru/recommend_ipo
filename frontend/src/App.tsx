import { useEffect, useRef, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import { CalendarPage } from './pages/CalendarPage'
import { ListPage } from './pages/ListPage'
import { DetailPage } from './pages/DetailPage'
import { MyPage } from './pages/MyPage'
import { ScoringConfigPage } from './pages/ScoringConfigPage'
import { GuidePage } from './pages/GuidePage'
import { Disclaimer } from './components/Disclaimer'
import { ListingBanner } from './components/ListingBanner'
import { OfflineBanner } from './components/OfflineBanner'
import { UpdateBanner } from './components/UpdateBanner'
import { USE_MOCK } from './config'
import { subscribeSlow } from './utils/wakeWatcher'

// v1.9 (#41): 라우트 이동마다 /api/wake fire-and-forget — 짧은 간격 연속 이동 억제.
const WAKE_ROUTE_THROTTLE_MS = 30_000

export default function App() {
  const [waking, setWaking] = useState(false)
  useEffect(() => subscribeSlow(setWaking), [])

  // 앱 진입 시 /api/health 를 한 번 호출해 Render 콜드스타트를 미리 깨운다.
  // 결과는 사용하지 않음(에러도 조용). 응답 지연은 wake 배너로 자동 노출.
  useEffect(() => { api.getHealth().catch(() => { /* noop */ }) }, [])

  // v1.9 (#41): 라우트 이동마다 /api/wake 를 fire-and-forget 으로 호출.
  //   - 목업 모드에서는 건너뜀(실 API 호출 없음 원칙).
  //   - 30초 throttle 로 짧은 연속 이동 억제.
  //   - 응답/오류/재시도/로그 모두 무시 — 서버가 깨어나는 신호만 던진다.
  //   - #40 수집 버튼 wake(응답 기다림)와는 독립.
  const location = useLocation()
  const lastWakeRouteRef = useRef<number>(0)
  useEffect(() => {
    if (USE_MOCK) return
    const now = Date.now()
    if (now - lastWakeRouteRef.current < WAKE_ROUTE_THROTTLE_MS) return
    lastWakeRouteRef.current = now
    try {
      void fetch('/api/wake', { method: 'GET', cache: 'no-store' }).catch(() => {})
    } catch { /* ignore */ }
  }, [location.pathname])

  return (
    <div className="app">
      {waking && (
        <div className="wake-banner" role="status">
          서버를 깨우는 중입니다 (최대 1분). 처음 호출일 수 있으니 잠시만 기다려 주세요.
        </div>
      )}
      <header className="site-header">
        <div className="site-title">
          <h1>공모주 청약 추천</h1>
          <span className="subtitle">DART 공시 기반 — PENDING / PASS(S·A·B) / REJECT / 판정 보류 / 정정 요구</span>
        </div>
        <nav className="site-nav">
          <NavLink to="/" end>달력</NavLink>
          <NavLink to="/list">목록</NavLink>
          <NavLink to="/my">내 공모주</NavLink>
          <NavLink to="/scoring">판정 기준</NavLink>
          <NavLink to="/guide">안내</NavLink>
        </nav>
        {USE_MOCK && (
          <div className="mock-banner" role="status">
            목업 데이터 모드 (<code>VITE_USE_MOCK=true</code>) — 실제 API 미호출
          </div>
        )}
      </header>
      <UpdateBanner />
      <OfflineBanner />
      <ListingBanner />
      <main className="site-main">
        <Routes>
          <Route path="/" element={<CalendarPage />} />
          <Route path="/list" element={<ListPage />} />
          <Route path="/ipos/:id" element={<DetailPage />} />
          <Route path="/my" element={<MyPage />} />
          <Route path="/scoring" element={<ScoringConfigPage />} />
          <Route path="/guide" element={<GuidePage />} />
          <Route path="*" element={<p>페이지를 찾을 수 없습니다.</p>} />
        </Routes>
      </main>
      <footer className="site-footer">
        <Disclaimer />
      </footer>
    </div>
  )
}
