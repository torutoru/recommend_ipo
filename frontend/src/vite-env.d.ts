/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />
/// <reference types="vite-plugin-pwa/react" />

// v1.11 (#34): vite.config.ts 의 define 으로 주입되는 빌드 메타.
declare const __BUILD_COMMIT__: string  // Netlify COMMIT_REF 의 앞 7자 (로컬 빌드는 빈 문자열)
declare const __BUILD_TIME__: string    // 빌드 시각 ISO 8601
