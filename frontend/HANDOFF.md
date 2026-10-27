# frontend 인계 문서

이 세션(frontend)이 지금까지 쌓은 작업과, 다음 세션/개발자가 이어가기 전에 알고 가면 좋은 함정·결정 배경을 모은다. 짝 문서는 루트 `docs/HANDOFF.md`(pm 작성). 코드 변경 없이 문서만.

> 이 문서는 2026-10-27 기준. 커밋 해시가 있는 변경은 그 시점의 것이며, 이후에 바뀌었을 수 있다. 추측은 "추측" 으로 표기한다.

---

## 1. 구조 지도

### 1-1. 디렉토리 트리 (운영에 쓰이는 파일만)

```
frontend/
├── index.html              # 진입 HTML. viewport·color-scheme·apple-* 메타·icons
├── vite.config.ts          # Vite + React + VitePWA + define(빌드 메타)
├── netlify.toml            # /api 프록시, SPA fallback, sw/manifest 캐시 헤더
├── tsconfig.json           # strict + ES2020 target
├── package.json            # 의존성(react 18.3·vite 5.4·vite-plugin-pwa 0.21.1)
├── public/
│   └── icons/              # icon-192.png·icon-512.png·icon-maskable-512.png
├── scripts/
│   └── gen-icons.mjs       # Node zlib 로 PNG 생성(외부 lib 없음)
└── src/
    ├── main.tsx            # React 진입(BrowserRouter + Routes)
    ├── App.tsx             # 레이아웃: 헤더 + UpdateBanner + OfflineBanner + ListingBanner + <Routes>
    ├── config.ts           # VITE_USE_MOCK 환경변수 토글
    ├── types.ts            # api-contract v1.8 과 1:1 매칭 TS 타입
    ├── styles.css          # 다크 토큰 + 전역 CSS(:root 에 모든 색 집중)
    ├── vite-env.d.ts       # vite·vite-plugin-pwa·__BUILD_* declare
    ├── api/
    │   ├── index.ts        # lazy proxy — USE_MOCK 로 real/mock 동적 import
    │   ├── real.ts         # 실제 /api/* 호출(fetch + 재시도 budget)
    │   ├── mock.ts         # 메모리 fixture(목업 모드). 10+ 종목 샘플
    │   └── holdings.ts     # 「내 공모주」 저장소(캐시 + async upsert/remove)
    ├── components/
    │   ├── Badge.tsx       # VerdictBadge, gradeExec*
    │   ├── Checklist.tsx   # 체크리스트 표(4항목·MET/NOT_MET/UNKNOWN)
    │   ├── CollectBar.tsx  # 「수집 및 분석하기」 + 폴링 + 수집 키 폼
    │   ├── Disclaimer.tsx  # "참고용 정보" + build 태그(#34)
    │   ├── HoldingForm.tsx # 수량·공모가·메모 입력(사용·추가·수정 공용)
    │   ├── ListingBanner.tsx  # 보유 종목 오늘/내일 상장 안내(헤더 하단, in-flow)
    │   ├── Loading.tsx     # 로딩/에러 공통
    │   ├── OfflineBanner.tsx  # navigator.onLine 기반 오프라인 안내
    │   └── UpdateBanner.tsx   # 플로팅 토스트(#35, 상단 중앙 fixed)
    ├── dev/
    │   ├── listingDemo.ts  # ?demo=listing (DEV 전용, prod tree-shake)
    │   └── updateDemo.ts   # ?demo=update (DEV 전용, prod tree-shake)
    ├── pages/
    │   ├── CalendarPage.tsx       # 메인 / . 월 그리드 + CollectBar
    │   ├── ListPage.tsx           # /list 보조 표 보기
    │   ├── DetailPage.tsx         # /ipos/:id 상세(지표·점수·체크리스트·data_notes·원문)
    │   ├── MyPage.tsx             # /my 「내 공모주」
    │   ├── ScoringConfigPage.tsx  # /scoring 판정 기준
    │   └── GuidePage.tsx          # /guide 가이드
    └── utils/
        ├── calendar.ts     # monthGrid·toYmd·parseYmd 등 KST Date 유틸
        ├── collectKey.ts   # localStorage 수집 키 저장(brbrowser only)
        ├── focus.ts        # scrollIntoViewOnMobile(#33)
        ├── format.ts       # fmtKrw·fmtPct·fmtDateTime·marketLabel 등
        ├── httpError.ts    # HttpError 클래스(status·message)
        └── wakeWatcher.ts  # Render 콜드스타트 "깨우는 중" 배너용
```

### 1-2. 데이터 경계

- **환경변수**: `VITE_USE_MOCK` 하나. `.env.development` 는 `true`(목업), `.env.production` 는 `false`(실 API) 로 커밋돼 있다. Netlify 는 `netlify.toml` `[build.environment]` 로 추가 보장.
- **환경 분기**: 운영 번들에 목업 코드가 섞이지 않도록 **동적 import** 로 `./mock` 또는 `./real` 만 로드(`src/api/index.ts`).
- **DEV 전용 코드**: `src/dev/*.ts` 는 전부 `import.meta.env.DEV` 가드 뒤에서만 호출. 운영 번들에서는 symbol 과 리터럴("미리보기", `demo=listing`, `demo=update`) 모두 tree-shake 로 제거(검증: `grep -r '...' dist/` → 0건).
- **localStorage 사용처**:
  - `recommend-ipo:collect-key` — 수집 키(X-Collect-Key)
  - `recommend-ipo:listing-banner-dismissed:YYYY-MM-DD` — 상장 알림 배너 하루 숨김
  - `recommend-ipo:holdings:v1` — **레거시**. backend 전환 후 자동 이전 → 제거(남아 있어도 다음 로드 때 재시도).
- 모든 localStorage 접근은 try/catch — 사파리 private·용량 초과·disabled 상태에서도 UI 가 동작.

---

## 2. 실행·테스트·빌드

### 2-1. 명령

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (strictPort), /api → :8000 proxy
npm run build      # tsc -b && vite build (PWA 산출물 포함)
npm run preview    # 빌드 결과물 로컬 미리보기 (서비스워커 실제 등록 확인용)
npm run typecheck  # tsc -b (noEmit)
```

- 테스트 러너는 **없다**. 변경 후 `npm run build` 로 타입체크 + 빌드 둘 다 통과하는지 확인하는 게 사실상의 CI.
- 실측 가이드: 변경 후 반드시 `npm run build` 를 돌리고 산출물 크기/파일 수를 pm 에게 보고(답변에 첨부). 돌리지 않고 "타입 체크로 대체" 같은 보고 금지(#2 에서 실제 사고).

### 2-2. 로컬 환경 주의점

- **Windows + Git Bash**: `python` PATH 가 Microsoft Store 스텁에 잡힐 수 있다. backend 가 아닌 frontend 세션은 python 안 쓰지만, scripts 는 Node 전용이므로 영향 없음.
- **포트 5173 고정**(`strictPort: true`). 다른 프로세스가 쓰면 Vite 가 실패한다.
- **backend 는 frontend 세션이 띄우지 않는다**(루트 CLAUDE.md 규칙, 가드레일로도 차단 경험 있음). backend 8000 꺼져 있으면 pm 에게 알림.
- **npm 설치는 네트워크 필요**. 최초 clone 또는 package.json 바꾼 뒤 `npm install` 한 번만 돌리면 그 뒤는 로컬.
- **vite-plugin-pwa 는 dev 에서 SW 비활성**(`devOptions.enabled: false`). 서비스워커 실제 동작은 `npm run preview` 또는 배포본에서 확인.

### 2-3. PWA 산출물 확인

```bash
npm run build
ls dist/
#  manifest.webmanifest      sw.js      workbox-*.js
#  index.html                assets/    icons/
```

- `grep -r 'demo=listing' dist/`·`grep -r 'demo=update' dist/` → 둘 다 `(no match)` 여야 함.
- precache 항목 수가 바뀌었다면 vite.config.ts `workbox.globPatterns` 영향.

---

## 3. 변경 이력 요약 (지시 번호 → 무엇을 왜)

(커밋 해시는 push 된 묶음만. 이번 세션 후반(#28 이후) 은 pm 가 묶어서 push.)

### 초기 뼈대
- **#1~#6**: React + Vite + TS 골격, 네 화면, 목업 데이터, Vite proxy, 실 API 전환(samples 모드). 반복 fail 사례: typecheck/빌드 로그 미첨부 → 재발 방지 규칙 생김.
- **#7**: 「수집 및 분석하기」 (CollectBar). 2.5s polling + 완료 시 달력 재조회.

### 체크리스트·데이터 모델
- **#8~#22**: v0.1 → v1.5 로 계약 반복 반영. 체크리스트 v1.5 에서 4항목(min_deposit·sell_timing 삭제).
- **#23**: 균등 배정 최소 증거금 **폐지**(사용자 결정).

### UI 다듬기
- **#24~#25**: 공모가 위치 라벨 통일("밴드 최상단"), README 개편.
- **#26 (32b21fd1)**: 코드 리뷰 8건 묶음 — ListPage score_range·Badge 「최소 B」·KST overdue·CollectStatus failures·INCOMPLETE 범위·needsInput 좁힘·CORRECTION 리스트 라벨·CalendarPage subscription_end 단독.

### 테마·칩
- **#27 (5d40e5bb)**: 상장 칩 **주황** #b45309, 보류 **보라** #6f42c1 + **항상 다크 모드** 전환. 하드코딩 색 전부 토큰화(.deposit-*·.chip-type/grade 삭제).
- **#28 (793fa619)**: 상장 칩 **금색** #c9a227 + 진한 글자 #1a1400(사용자 지적: 다크 바탕에서 눈부심). outline 데드코드 제거.

### 「내 공모주」 블록
- **#29**: 「내 공모주」 화면 신설(프론트만, localStorage). `/my` 라우트, 상세 「+ 청약 결과 입력」 트리거, 달력 ★ 접두, ListingBanner.
- **#30**: ListingBanner `?demo=listing` DEV 미리보기(prod tree-shake).
- **#31**: holdings → backend API 전환(계약 v1.7). sync 캐시 + async upsert/remove, 레거시 localStorage 자동 이전.

### PWA
- **#32**: PWA 1차 — vite-plugin-pwa, SW, 매니페스트, 자체 아이콘, OfflineBanner, UpdateBanner(배너형).
- **#33**: 모바일 입력 자동 확대 방지 — 입력 글자 ≥16px(`(pointer: coarse)` 매칭), `scrollIntoViewOnMobile`.
- **#34**: 업데이트 확인 트리거(visibility·focus·route) + 60s throttle + 빌드 메타 노출(`build XXX`).
- **#35**: UpdateBanner → **플로팅 토스트**(fixed top-center) + `?demo=update` DEV.
- **#36**: `IpoDetail.data_notes` 섹션(상세 전용). 목업 샘플 1건.
- **#37**: 달력 **청약 칩**에도 `(청약)` 접두.

### 「인계 작업」
- **인계**: 이 문서(`frontend/HANDOFF.md`) + `frontend/CLAUDE.md` 한 줄.

---

## 4. 함정·교훈 (이 세션이 겪은 것 위주)

### 4-1. 환경·빌드

- **목업↔실 API 분리**: `src/api/index.ts` 에서 동적 import 로 `./real` 또는 `./mock` 만 로드. 정적 import 로 바꾸면 운영 번들에 목업 코드가 섞인다. 바꿀 때마다 `grep -oE "..." dist/assets/index-*.js` 로 교차 검증.
- **운영 빌드에 DEV 코드 확인**: `?demo=listing`·`?demo=update`·`isListingDemoActive`·`pickDemoItems`·"미리보기" 모두 `import.meta.env.DEV` 가드 뒤에 두면 Rollup 이 tree-shake. 추가할 때마다 **반드시 grep 로 재검증**.
- **.env.production 커밋**: `.gitignore` 가 `.env.*` 를 제외하지만 `!.env.production` 로 **인버트** 해 둠. 벨트+멜빵으로 `netlify.toml [build.environment] VITE_USE_MOCK = "false"` 도 명시.
- **tsconfig.node.json 삭제됨**: 이전에 `tsc -b` 가 운영 번들에 .d.ts 를 뱉어서 tsconfig.node.json 과 reference 를 제거함. 되살리지 말 것.

### 4-2. 다크 테마

- 모든 색은 `styles.css :root` 의 토큰(`--bg`·`--panel`·`--surface`·`--surface-weak`·`--border`·`--fg`·`--fg-mute`·각 상태 `-weak`/`-border`·`--row-*`·`--result-*-bg/fg/border`). 하드코딩 금지.
- **등급 색은 브랜드 유지**: `.badge-grade-S/A/B/C` 는 `styles.css` 에 하드코딩. `--pass` 를 바꿔도 영향 받지 않도록 A 는 고정 `#137752`.
- **달력 칩 색**은 `--chip-*` 전용 토큰. S/A/B 파랑, REJECT 빨강, 대기/정정 회색, 상장 금색(#c9a227), 보류 보라(#6f42c1).
- `index.html` 에 `<meta name="color-scheme" content="dark">` 와 `:root { color-scheme: dark }` 둘 다 — 폼 컨트롤·스크롤바까지 다크.

### 4-3. 달력

- **7칸 균등**: `grid-template-columns: repeat(7, minmax(0, 1fr))` + 셀 `min-width: 0`. 자식 min-content 가 열을 밀지 못하게.
- **긴 영문 종목명 줄바꿈**: `.cal-chip .chip-name { overflow-wrap: anywhere; word-break: break-all }`. SimwonAmericaCorp 같은 케이스가 셀을 깨지 않게.
- **칩 우선순위**: `CHIP_PRIORITY` (S<A<B<INCOMPLETE<REJECT<PENDING<CORRECTION). 같은 순위는 입력 순(안정 정렬).
- **CORRECTION 숨김**: 셀에 non-correction 이벤트가 하나라도 있으면 CORRECTION 칩은 셀에서 숨기고 "+N 더보기" 에만 포함.
- **(청약)·(상장) 접두**: EventChip 안에서 처리. 상장 보유는 `★ (상장) ...`. 날짜 패널은 이미 `.cal-item-type` 로 유형 표시가 있어 접두 중복 금지.

### 4-4. 「내 공모주」

- **sync 캐시 + async mutate**: `holdings.list()/get()/subscribe()` 는 sync (화면 영향 최소화). `upsert()/remove()` 는 async. 서버 전환 때 UI 가 거의 안 바뀌었던 이유.
- **GET 404 는 조용히 empty**: backend 가 아직 holdings 안 보내는 상태(초기 배포)에서도 UI 가 깨지지 않게. 그 외 오류는 `loadError` 로 재시도 UI.
- **PUT/DELETE 는 재시도 금지**: 중복 업서트/삭제 위험. 실패는 폼의 `holding-err` 또는 MyPage 상단 `.error` 로.
- **레거시 localStorage 이전**: 모듈 로드 때 자동. 성공한 항목만 제거.
- **달력 ★**: `heldSet` (holdings subscribe) + `demoCorpCodes` (DEV 미리보기) 합집합 → `starSet` 으로 EventChip 에 전달.

### 4-5. PWA

- **registerType: 'prompt'**: 자동 활성화 금지. 사용자가 "새로고침" 눌러야 `updateServiceWorker(true)`. iOS 에서 특히 중요.
- **skipWaiting: false · clientsClaim: false**: 사용자 세션이 중간에 끊기지 않게.
- **holdings PUT/DELETE 캐시 금지**: runtimeCaching 에 `request.method === 'GET'` 조건 필수. 안 그러면 workbox 가 뭘 저장할지 모름.
- **GET /api/* NetworkFirst**: 15s timeout, 24h TTL, maxEntries 60. 오프라인이면 마지막 응답을 보여줌.
- **업데이트 확인 트리거(#34)**: 등록 1회 + 1h interval + visibilitychange(visible) + window focus + route change. **60s throttle** 로 과도 호출 억제.
- **배너 → 토스트(#35)**: `position: fixed`, `top: calc(env(safe-area-inset-top, 0px) + 12px)`. iOS 노치/Dynamic Island 아래. z-index 1000.
- **빌드 메타(#34)**: `vite.config.ts` `define` 으로 `__BUILD_COMMIT__`(Netlify `COMMIT_REF` 앞 7자)·`__BUILD_TIME__`(ISO) 주입. Disclaimer 끝에 `build XXX` 노출.
- **아이콘 생성**: `scripts/gen-icons.mjs` 가 Node builtin(zlib) 만 사용. 외부 lib 없음. **상표·로고 금지**(추상 "증가 바" 심볼만).
- **Netlify 캐시 헤더**: `/sw.js`·`/workbox-*.js`·`/manifest.webmanifest` 는 `max-age=0, must-revalidate`. 안 하면 신 버전 안 떠뜸.

### 4-6. iOS

- **입력 자동 확대 방지**: `@media (pointer: coarse), (max-width: 768px) { input, select, textarea { font-size: 16px } }`.
  - **(#38)** 이 블록은 `styles.css` **파일 끝** 에 두어야 한다. 파일 앞에 두면 뒤에 오는 class+attribute 규칙(e.g. `.holding-form input[type="text"] { font-size: 13px }`, specificity 0,2,1) 에 덮어씌워진다. 또한 **동등 이상 specificity 로 명시** — `.key-prompt input`·`.my-add-panel input[type="text"]`·`.holding-form input[type="text"]`·`.holding-form .holding-memo input[type="text"]` 전부 override 리스트에 포함.
  - 재발 방지: CSS 변경 뒤에는 반드시 **빌드 산출 CSS 안에서 override 가 원본 뒤에 있는지** `grep -boF` 로 오프셋 비교하고, 가능하면 DevTools 모바일 에뮬레이션에서 `getComputedStyle(el).fontSize` 로 확인.
- **viewport 에 `maximum-scale=1`·`user-scalable=no` 금지**(접근성). 핀치 줌은 허용.
- **포커스 시 중앙 스크롤**: `scrollIntoViewOnMobile` (매치미디어 try/catch 보호).
- **apple-touch-icon·apple-mobile-web-app-capable=yes·status-bar black-translucent**: `index.html`.

### 4-7. API·오류

- **GET 자동 재시도**: 90s budget, 3s backoff. 502/503/504 와 네트워크 오류. Render 콜드스타트(최대 30s+) 대응.
- **POST 자동 재시도 금지**: 중복 실행 위험. CollectBar 가 502/503/504 받으면 `getCollectStatus` 로 실제 시작 여부만 확인.
- **AbortController 65s timeout**: Netlify 외부 프록시 ~26s + Render 콜드스타트 여유.
- **wakeWatcher**: 3s 이상 지연되는 요청 감지 → "서버를 깨우는 중" 배너.

### 4-8. 세션 운영

- **inquery 는 끝까지 읽는다**(#35 에서 반성). 추가 사항 섹션을 자주 놓침.
- **빌드 로그·크기 교차 검증 첨부**. 사용자가 어떤 것이 반영됐는지 바로 봄.
- **커밋·push 는 pm 담당**. 요청받지 않으면 하지 않는다.
- **답변은 1회**. 긴 작업이어도 답변 파일은 하나로 정리.

---

## 5. 남은 일·알려진 한계

- **테스트 러너 없음**. 전역 테스트가 유용하면 vitest 고려(backend 전용). frontend 는 `npm run build` 로 타입+빌드 검증만.
- **Lighthouse PWA installable 자동 검증 없음**. 로컬에서 수동으로 돌려야 함. 빌드 시점 CI 통합은 미도입.
- **상장 종목 반영 자동 테스트 없음**. backend 가 `listing_date` 를 채워주면 ListingBanner·★ 가 자동 반영되지만, backend 쪽 테스트는 backend 세션 영역.
- **IPO 종목 이미지·로고 없음**. 추후 corp_name 옆 로고 넣고 싶으면 S3-식 CDN 설계 필요. 지금은 텍스트 only.
- **푸시 알림 없음**(MVP '알림 제외'). 상장 알림은 앱 열었을 때 `ListingBanner` 로만.
- **다국어 없음**. 한국어 전용. 혹시 다국어 추가 시 포맷 유틸(fmtDateTime 등) 분기 필요.
- **차트 없음**. ScoringConfig·DetailPage 모두 텍스트/표. 시각화가 필요하면 Recharts 등 추가 고려.
- **백테스트·수익률 없음**(MVP 제외). `MyPage` 는 보유 정보만, 매도/수익률 미노출.
- **ServiceWorker 캐시 스토리지 폭증 체크 없음**: 추측 — API 응답이 커지면 24h TTL · maxEntries 60 조정 필요.

---

## 6. 코드에서 바로 안 보이는 결정 배경

- **「내 공모주」가 왜 별도 저장소에 있는가**: 사용자가 "저렇게 가면 됨" 하기 전까지 `holdings.ts` 는 localStorage. 저장 방식 미정이었기 때문. 그 뒤 인증 없이 backend 단일 목록으로 결정(사용자 결정, requirements 24장).
- **왜 상장 칩이 금색인가**: 처음 초록(#2e7d32) → #27 에서 주황(#b45309) → #28 에서 금색(#c9a227). 사용자가 "다크 바탕에서 눈부시다" 피드백. 금색은 뉴스에서 쓰는 '증권' 톤 + B 등급 연한 파랑과 색상환상 반대.
- **왜 UpdateBanner 가 토스트인가**: #32 에서 처음 배너로 넣었지만 사용자가 7995260 배포 후에도 "안 보임" 보고. #34 에서 트리거 다중화 + visibility · focus · route 추가. 그래도 플로팅이 더 눈에 띈다는 사용자 요청으로 #35 에서 토스트.
- **왜 아이콘이 추상적인가**: 상표·로고 사용 금지(pm 지시). 자체 생성한 PNG(zlib 로 solid color + bar pattern)로 Lighthouse PWA 요구 충족.
- **왜 `(청약) 회사명`·`(상장) 회사명` 접두를 넣는가**: 처음(v1.6) 에는 칩에 회사명만. 사용자가 "청약인지 상장인지 색만으로 구분 안 됨" 피드백 → #37 에서 접두 추가. 날짜 패널은 이미 유형 라벨이 있어 접두 중복 금지.
- **왜 레거시 localStorage 이전 로직을 남겨두는가**: 사용자가 로컬 개발 중에 쌓은 holdings 가 유실되지 않게. 실패한 항목은 재시도되므로 안전. backend #51 이 배포돼야 실제 서버 저장 발생.
- **왜 PWA update interval 이 1시간인가**: 모바일 데이터 걱정보다 "안 뜸" 사용자 불만이 더 큰 비용. 60s throttle 이 과도 호출을 억제하므로 1h 간격은 cumulative 로도 안전.
- **왜 `.update-banner` → `.update-toast` 로 이름까지 바꿨는가**: 배너와 토스트는 behavior 가 완전히 다름(in-flow vs fixed). 이름을 유지하면 CSS 섞여서 사고 가능.
- **왜 iOS 입력 16px 를 `(pointer: coarse)` 로도 묶었는가**: `max-width` 만 쓰면 iPad 가로 모드처럼 pointer:coarse 지만 769px+ 인 경우를 놓침.

---

## 7. 외부 자원 요약 (키 없음)

- **Netlify**: 프론트 호스팅. `base = "frontend"`, `publish = "dist"`, `/api/*` → Render 프록시(URL 은 `netlify.toml` 참고).
- **Render Free**: backend 호스팅. 콜드스타트 30초+. frontend 가 들어오면 `/api/health` 1회 호출로 미리 깨움(`App.tsx`).
- **Turso**: SQLite(HTTP pipeline). frontend 는 직접 접근하지 않음(backend 전용).
- **DART**: 공시 원천. backend 전용. 키는 `backend/.env.local`.

---

## 8. 다음 세션이 가장 먼저 할 것

1. `root/CLAUDE.md` → `frontend/CLAUDE.md` → `frontend/HANDOFF.md` → `docs/HANDOFF.md` 순으로 읽기.
2. `.claude/co-work/{requirements.md, api-contract.md, frontend.md, frontend-status.md}` 읽기.
3. `ls .claude/co-work/frontend-*` 로 미처리 질문/답변 확인.
4. 자기 역할의 감시기(Monitor) 가 1개만 살아 있는지 `ps -ef | grep watch-cowork` 로 확인.
5. 그 뒤 `/loop 10m …` 사이클을 시작하거나, pm 지시가 있으면 그에 따라.
6. 변경 후에는 반드시 `npm run build` 실측 로그를 pm 에게 첨부.
