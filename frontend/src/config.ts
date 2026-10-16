// API 소스 전환은 이 한 곳에서 결정한다.
// 기본값은 실 API (안전 기본값). 명시적으로 'true' 일 때만 목업으로 돈다.
// - 로컬 개발 목업: `.env.development.local` 에 `VITE_USE_MOCK=true` (git 제외).
// - 운영 빌드: `.env.production` 과 `netlify.toml [build.environment]` 양쪽 모두 'false' 명시.
export const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
