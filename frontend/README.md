# recommend_ipo — frontend

React + Vite + TypeScript. DART 공시 기반 공모주 청약 추천 웹 UI.

## 실행

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc -b && vite build (운영 번들)
npm run typecheck  # tsc -b
npm run preview    # 빌드 결과물 로컬 미리보기
```

Vite 가 `/api` 요청을 `http://localhost:8000` (backend FastAPI) 로 프록시합니다. backend 는 `localhost:5173` 을 CORS 허용해야 합니다.

## 테마 — 항상 다크 (v1.9, #27)

- 라이트 모드·전환 UI 없음. `index.html` 의 `<meta name="color-scheme" content="dark">` 로 폼 컨트롤·스크롤바까지 다크.
- 모든 밝은 색은 `styles.css` 의 `:root` 토큰(`--bg`·`--panel`·`--surface`·`--surface-weak`·`--border`·`--fg`·`--fg-mute`·각 상태 `-weak`/`-border`·체크리스트 `--row-*`/`--result-*-bg/fg/border`)으로 집중. 하드코딩 금지.
- 본문·보조 글자·결과 배지·링크 전부 WCAG AA(4.5:1) 이상 대비.
- 칩·등급 색은 브랜드 유지(S/A/B 파랑·REJECT 빨강·대기/정정 회색·상장 주황·판정 보류 보라).

## 화면 구성

| 경로 | 화면 |
| --- | --- |
| `/` | **달력**(CalendarPage) — 메인 |
| `/list` | 목록(ListPage) — 보조 보기 |
| `/ipos/:id` | 상세(DetailPage) |
| `/scoring` | 판정 기준 안내(ScoringConfigPage) |
| `/guide` | 매도 전략·계좌 개설 안내(GuidePage) |

### 달력 칩 규칙 (requirements 18장)

- **본문은 회사명만** — "청약"·"상장"·등급(S/A/B/보류/비추천/대기/정정) 글자는 넣지 않음. 접근성은 `title`/`aria-label` 에 "회사명 · 청약 · 추천 A" 로 제공.
- **상장 칩**: 판정과 무관하게 **주황 단색** + 본문 접두사 `(상장) 회사명`. 점선 테두리 없음.
- **상태별 색** (칩 배경, WCAG AA 이상 대비):
  - PASS S — 진한 파랑 `#1a5fb4`
  - PASS A — 파랑 `#1c71d8`
  - PASS B — 연한 파랑 `#a4c8ff` + 어두운 글자
  - INCOMPLETE — 보라 `#6f42c1`
  - REJECT — 빨강 `#a3251b`
  - PENDING·CORRECTION — 짙은 회색 `#5f6b7a` + 흰 글자
  - 상장 — 차분한 금색 `#c9a227` + 진한 글자 `#1a1400` (대비 ~9:1, 다크 바탕에서 눈부시지 않게)
- **셀 내 정렬 우선순위**: S > A > B > INCOMPLETE > REJECT > PENDING > CORRECTION. 같은 등급 안에서는 입력 순(안정 정렬).
- **CORRECTION 숨김**: 셀에 non-correction 이벤트가 하나라도 있으면 CORRECTION 칩은 셀에서 숨기고 "+N 더보기" 에만 포함. 셀에 CORRECTION 만 있으면 그대로 노출.
- **클릭**: 칩은 non-interactive(span). 날짜 셀 어디를 눌러도 하단 **선택 날짜 패널**이 열림. 패널의 종목 항목만 상세 페이지로 이동. 키보드 Tab/Enter·Space 로 셀 포커스 선택 가능.
- **7칸 폭 균등 고정**: `repeat(7, minmax(0, 1fr))` + 셀·칩 `min-width: 0` + 칩 `overflow-wrap: anywhere; word-break: break-all` 로 긴 영문 종목명(`SimwonAmericaCorp.`)도 칸 안에서 줄바꿈.

### 상태 5종

| status | 표시 (상세) |
| --- | --- |
| `PENDING` | "총점 : 미공시 / 100" — 수요예측 결과 미공시 |
| `PASS` | "N / 100 · 등급 S/A/B" — 범위 확정 (`score_range`) 시 "min~max점 · 최소 B" |
| `REJECT` | "N / 100" — 범위 확정 시 "최대 M점" |
| `INCOMPLETE` | "**판정 보류 · 데이터 확인 필요**" — 지표 null 셀에 "확인 필요" 라벨 |
| `CORRECTION` | 상단 `⚠ 금융감독원 정정신고서 제출요구` 경고 배너 + 등급 배너 없음 |

### 체크리스트 (4항목)

상세에 가이드 2장 체크리스트를 표로 노출. **v1.5 에서 `min_deposit`/`sell_timing` 제거 — 4항목만**:
1. 기관 경쟁률 — ≥1,000:1 "좋음" (초록), ≥1,500:1 "아주 좋음" (진한 초록)
2. 공모가 위치 — "밴드 최상단"/"밴드 최상단 초과" 통일 라벨
3. 의무보유 확약 — ≥10%
4. 유통 가능 물량 — 유통 ≤35% 그리고 구주 <30%

결과: `MET`/`NOT_MET`/`UNKNOWN` 3종. backend 가 아직 6항목을 보내도 UI 가 걸러서 4개만 노출.

### 균등 배정 최소 증거금 — **v1.6 에서 폐지**

- `MinDeposit` 타입·`IpoDetail.min_deposit`·`ScoringConfig.deposit` 전부 삭제.
- 상세의 증거금 영역(수량 입력·분해 표)·안내 화면 공식·판정 기준 설정 모두 폐지.
- 매도 전략·계좌 사전 개설 안내는 `/guide` 에 유지.

## 목업 ↔ 실 API 전환

**기본값은 실 API** (`src/config.ts` 가 `VITE_USE_MOCK === 'true'` 일 때만 목업).

로컬 개발에서 목업을 쓰고 싶다면 **git 제외 파일**에 명시적으로 켭니다:

```
# frontend/.env.development.local  (git 제외)
VITE_USE_MOCK=true
```

전환 후 `npm run dev` 를 재시작합니다 (Vite env 는 기동 시 로드).

운영 빌드는 **벨트+멜빵**으로 두 곳에서 `false` 를 보장합니다:
- `frontend/.env.production` (저장소에 커밋)
- `frontend/netlify.toml` 의 `[build.environment]`

Vite 는 USE_MOCK 이 false 로 평가되면 **운영 메인 번들에서 목업 코드를 완전히 제거** 합니다 (동적 import — `src/api/index.ts` 참조). 종목명·fixture 등 샘플 데이터가 번들에 들어가지 않습니다.

## 디렉토리

```
src/
├── main.tsx, App.tsx            # 엔트리·라우터·레이아웃·전역 "서버 깨우는 중" 배너
├── config.ts                    # USE_MOCK 토글 (명시적 'true' 외엔 실 API)
├── types.ts                     # api-contract.md 와 1:1 매칭되는 TS 타입
├── api/
│   ├── index.ts                 # mock | real 선택 (동적 import — 운영 번들에서 mock 제거)
│   ├── mock.ts                  # 목업 응답 (19종목: PASS S/A/B·INCOMPLETE·REJECT·PENDING·CORRECTION·범위 확정·달력 fixtures)
│   └── real.ts                  # fetch 기반 클라이언트 + 재시도 + 타임아웃 + X-Collect-Key
├── utils/
│   ├── format.ts                # null → "미공시", 금액·비율·날짜 포맷, PricePosition 라벨
│   ├── calendar.ts              # 월 그리드·날짜 범위 유틸
│   ├── collectKey.ts            # 수집 키 localStorage wrapper (try/catch)
│   ├── httpError.ts             # HttpError 공유 class (status 보존)
│   └── wakeWatcher.ts           # 전역 느림 감지 pub/sub + trackRequest
├── components/
│   ├── Badge.tsx                # VerdictBadge · 등급 라벨 유틸
│   ├── CollectBar.tsx           # 수집 버튼·마지막 수집 시각·수집 키 UI (401 처리)
│   ├── Checklist.tsx            # 체크리스트 4항목 테이블
│   ├── Disclaimer.tsx           # "투자 권유 아님" 고지
│   └── Loading.tsx              # Loading · ErrorBox
└── pages/
    ├── CalendarPage.tsx         # 달력 (메인)
    ├── ListPage.tsx             # 목록 (보조)
    ├── DetailPage.tsx           # 상세
    ├── ScoringConfigPage.tsx    # 판정 기준 안내
    └── GuidePage.tsx            # 매도 전략·계좌 사전 개설 안내
```

## 규칙

- 모든 화면 하단에 "투자 권유가 아니며 참고용 정보" 고지 표시.
- 숫자 `null` 은 "미공시" 로 표시 (0 으로 그리지 않음).
- backend 미반영 응답(필드 자체가 undefined) 도 crash 없이 degraded — `??` / `!= null` 로 전부 방어.
- 지표 이름·필드명은 `.claude/co-work/api-contract.md` 기준. 변경이 필요하면 `pm` 에게 질문.

## 배포 (Netlify)

frontend 는 Netlify, backend 는 Render (별도 세션). 실제 계정 연결·배포는 사용자가 수행.

### Netlify 세팅

1. 저장소(`recommend_ipo`) 를 Netlify 사이트에 연결.
2. **Base directory**: `frontend` 로 지정.
3. 그 외는 `frontend/netlify.toml` 이 자동 로드 — `command = "npm run build"`, `publish = "dist"`, Node 20.
4. SPA fallback(`/* → /index.html 200`) 과 `/api/*` 프록시가 함께 설정됨.

### Render 호스트

현재 target: `https://recommend-ipo-api.onrender.com`. `netlify.toml` 에 반영돼 있습니다:

```toml
[[redirects]]
  from = "/api/*"
  to = "https://recommend-ipo-api.onrender.com/api/:splat"
  status = 200
  force = true
```

- 같은 오리진 프록시이므로 **CORS 설정이 불필요**하고, 백엔드 호스트가 **브라우저 네트워크에 노출되지 않습니다**.
- `/api/*` 리다이렉트가 SPA fallback 보다 **위**에 와야 함 (파일에 이미 그렇게 돼 있음).
- 호스트가 바뀌면 위 한 줄만 수정 후 커밋.

### 환경 변수

- frontend 번들에 들어가는 비밀값 없음. `VITE_USE_MOCK` 은 `.env.production` 에서 `false` (실 API 가 기본).
- backend 비밀값(`DART_CERT_KEY`, `COLLECT_KEY`, `TURSO_*`) 은 Render 환경변수에만 둡니다. frontend 와 무관.

### 수집 키 UI 흐름

- Render 에 `COLLECT_KEY` 가 설정돼 있으면 `POST /api/collect` 가 `X-Collect-Key` 헤더 일치 시에만 실행됩니다.
- frontend 는 저장된 키가 있으면 자동 포함, 없으면 처음엔 헤더 없이 호출 → **401** 을 받으면 입력창을 띄웁니다.
- 사용자가 입력한 키는 `localStorage` 에 저장 (브라우저 단위). "변경"·"삭제" 버튼으로 수정 가능.
- 로컬 개발(키 미설정 backend)에서는 **입력 없이도 수집 버튼이 동작**합니다.

### 서버 깨우기 안내 + 재시도

- Render Free 플랜은 15분 무요청 시 슬립, 기동 30초+. frontend 는 모든 API 요청의 응답이 **3초를 넘기면 상단에 "서버를 깨우는 중" 배너**를 띄웁니다 (`src/utils/wakeWatcher.ts`).
- **GET 자동 재시도**: 502/503/504/네트워크 오류 → 3초 간격 재시도, 총 90초 budget (`src/api/real.ts`).
- **각 시도 타임아웃 65초** (`AbortController`).
- **POST `/api/collect` 는 재시도 금지** (중복 실행 방지). 502/503/504 를 받으면 `GET /api/collect/status` 로 실제 시작 여부 확인 후 안내.
- 앱 진입 시 `/api/health` 를 fire-and-forget 으로 호출해 Render 를 미리 깨움.
