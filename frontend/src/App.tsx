import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { api } from './api'
import { CalendarPage } from './pages/CalendarPage'
import { ListPage } from './pages/ListPage'
import { DetailPage } from './pages/DetailPage'
import { ScoringConfigPage } from './pages/ScoringConfigPage'
import { GuidePage } from './pages/GuidePage'
import { Disclaimer } from './components/Disclaimer'
import { USE_MOCK } from './config'
import { subscribeSlow } from './utils/wakeWatcher'

export default function App() {
  const [waking, setWaking] = useState(false)
  useEffect(() => subscribeSlow(setWaking), [])

  // 앱 진입 시 /api/health 를 한 번 호출해 Render 콜드스타트를 미리 깨운다.
  // 결과는 사용하지 않음(에러도 조용). 응답 지연은 wake 배너로 자동 노출.
  useEffect(() => { api.getHealth().catch(() => { /* noop */ }) }, [])

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
          <NavLink to="/scoring">판정 기준</NavLink>
          <NavLink to="/guide">안내</NavLink>
        </nav>
        {USE_MOCK && (
          <div className="mock-banner" role="status">
            목업 데이터 모드 (<code>VITE_USE_MOCK=true</code>) — 실제 API 미호출
          </div>
        )}
      </header>
      <main className="site-main">
        <Routes>
          <Route path="/" element={<CalendarPage />} />
          <Route path="/list" element={<ListPage />} />
          <Route path="/ipos/:id" element={<DetailPage />} />
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
