import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// v1.11 (#32): PWA — 설치 + 오프라인. 푸시 알림 없음.
//   - 앱 셸(정적 자산) 프리캐시, SPA fallback 은 index.html.
//   - /api/* 는 NetworkFirst(실패 시 마지막 응답). 단, holdings PUT/DELETE 는 전혀 캐시하지 않음.
//   - skipWaiting 사용 안 함(강제 새로고침 금지). 새 버전은 UpdateBanner 가 안내.

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'prompt', // 자동 활성화 금지 — UpdateBanner 가 사용자 액션으로 적용
      includeAssets: ['icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-maskable-512.png'],
      manifest: {
        name: '공모주 청약 추천',
        short_name: '공모주',
        description: 'DART 공시 기반 공모주 청약 추천 (참고용)',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'any',
        background_color: '#0b121c', // :root --bg
        theme_color: '#141c28',       // :root --panel
        lang: 'ko',
        dir: 'ltr',
        categories: ['finance'],
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//],
        // 운영 번들의 모든 정적 자산을 프리캐시 — 오프라인 셸.
        globPatterns: ['**/*.{js,css,html,png,svg,webmanifest}'],
        cleanupOutdatedCaches: true,
        skipWaiting: false,
        clientsClaim: false,
        runtimeCaching: [
          {
            // GET /api/* 는 NetworkFirst. holdings PUT/DELETE 는 아예 매칭되지 않음.
            urlPattern: ({ url, request }) =>
              url.pathname.startsWith('/api/') && request.method === 'GET',
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-get',
              networkTimeoutSeconds: 15,
              expiration: { maxEntries: 60, maxAgeSeconds: 60 * 60 * 24 }, // 24h
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
