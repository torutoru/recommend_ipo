# recommend_ipo — frontend

React + Vite + TypeScript. 공모주 청약 추천 웹 UI.

## 실행

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Vite 가 `/api` 요청을 `http://localhost:8000` (backend FastAPI) 로 프록시합니다. backend 는 `localhost:5173` 을 CORS 허용해야 합니다.

## 목업 ↔ 실 API 전환

API 소스는 **한 곳**에서 토글합니다. `.env.development` 의 `VITE_USE_MOCK` 값으로 전환:

```
VITE_USE_MOCK=true   # 목업 데이터 (기본값)
VITE_USE_MOCK=false  # 실제 /api 호출
```

전환 후에는 `npm run dev` 를 재시작합니다 (Vite env 는 기동 시 로드).

## 디렉토리

```
src/
├── main.tsx, App.tsx       # 엔트리·라우터·레이아웃
├── config.ts               # USE_MOCK 토글
├── types.ts                # api-contract.md 와 1:1 매칭되는 TS 타입
├── api/
│   ├── index.ts            # mock | real 선택
│   ├── mock.ts             # 목업 응답 (세 종목: PENDING·PASS·REJECT)
│   └── real.ts             # fetch 기반 클라이언트
├── utils/format.ts         # null → "미공시", 금액·비율 포맷
├── components/             # Badge, Disclaimer 등 공용 UI
└── pages/
    ├── ListPage.tsx        # 목록
    ├── DetailPage.tsx      # 상세
    ├── ScoringConfigPage.tsx  # 판정 기준 안내
    └── GuidePage.tsx       # 매도 전략 안내 + 투자 권유 아님
```

## 규칙

- 모든 화면 하단에 "투자 권유가 아니며 참고용 정보" 고지 표시.
- 숫자 `null` 은 "미공시" 로 표시 (0 으로 그리지 않음).
- 지표 이름·필드명은 `.claude/co-work/api-contract.md` 기준. 변경이 필요하면 `pm` 에게 질문.

## 배포 (Netlify)

frontend 는 Netlify, backend 는 Render (별도 세션). 실제 계정 연결·배포는 사용자가 수행.

### Netlify 세팅

1. 저장소(`recommend_ipo`) 를 Netlify 사이트에 연결.
2. **Base directory**: `frontend` 로 지정.
3. 그 외는 `frontend/netlify.toml` 이 자동 로드 — `command = "npm run build"`, `publish = "dist"`, Node 20.
4. SPA fallback(`/* → /index.html 200`) 과 `/api/*` 프록시가 함께 설정됨.

### Render 호스트 교체

`netlify.toml` 의 다음 줄에서 `RENDER_HOST` 를 실제 Render 호스트로 바꿔 커밋합니다 (예: `recommend-ipo-api.onrender.com`):

```toml
[[redirects]]
  from = "/api/*"
  to = "https://RENDER_HOST/api/:splat"
  status = 200
  force = true
```

- 같은 오리진 프록시이므로 **CORS 설정이 불필요**하고, 백엔드 호스트가 **브라우저 네트워크에 노출되지 않습니다**.
- `/api/*` 리다이렉트가 SPA fallback 보다 **위**에 와야 함 (파일에 이미 그렇게 돼 있음).

### 환경 변수

- frontend 번들에 들어가는 비밀값 없음. `VITE_USE_MOCK` 은 `.env.production` 에서 `false` (실 API 가 기본).
- backend 비밀값(`DART_CERT_KEY`, `COLLECT_KEY`, `TURSO_*`) 은 Render 환경변수에만 둡니다. frontend 와 무관.

### 수집 키 UI 흐름

- Render 에 `COLLECT_KEY` 가 설정돼 있으면 `POST /api/collect` 가 `X-Collect-Key` 헤더 일치 시에만 실행됩니다.
- frontend 는 저장된 키가 있으면 자동 포함, 없으면 처음엔 헤더 없이 호출 → **401** 을 받으면 입력창을 띄웁니다.
- 사용자가 입력한 키는 `localStorage` 에 저장 (브라우저 단위). "변경"·"삭제" 버튼으로 수정 가능.
- 로컬 개발(키 미설정 backend)에서는 **입력 없이도 수집 버튼이 동작**합니다.

### 서버 깨우기 안내

- Render Free 플랜은 15분 무요청 시 슬립, 기동 30초+. frontend 는 모든 API 요청의 응답이 3초를 넘기면 상단에 **"서버를 깨우는 중" 배너**를 띄우고, 65초 타임아웃 뒤 실패 처리합니다.
