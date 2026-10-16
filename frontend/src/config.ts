// API 소스 전환은 이 한 곳에서 결정한다.
// backend 샘플 응답이 준비되면 .env.development 에서 VITE_USE_MOCK=false 로 바꾼다.
export const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false'
