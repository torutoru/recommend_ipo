<!-- 스냅샷 2026-10-27: 정본은 .claude/co-work/api-contract.md (git 제외). 이 사본은 새 환경 인계용. -->
# API 계약 (정본 — pm 관리, 변경은 협상 후 pm 이 반영)

버전: v1.8 (2026-10-27)

## 변경 이력
- v1.6: 균등 배정 최소 증거금 기능 제거(사용자 결정) — `IpoDetail.min_deposit`·`MinDeposit` 타입·`GET /api/ipos/{id}` 의 `shares` 쿼리·scoring-config `deposit` 블록 삭제
- v1.5: 체크리스트에서 `min_deposit`·`sell_timing` 제거(사용자 결정) — 판정 4항목만, 항상 4개. `INFO` 결과는 더 이상 쓰지 않음. `/api/health` 에 `parser_version`·`commit` 추가(backend #31)
- v1.4: 판정 보류 보완(사용자 결정, requirements 15-1장) — 미확인 지표의 최소·최대로도 결과가 같으면 PASS/REJECT 확정. `Verdict.score_range` 추가
- v1.3: `CollectStatus.failures: {corp_code, corp_name, reason}[]` 추가(backend #22) — 실패 종목별 사유, 비밀값·경로 제거
- v1.2: `IpoDetail.underwriters` 추가(사용자 요청) — 주관사·인수회사 이름 목록. 상세 화면에만 표시
- v1.1: 공모 일정 필드 추가(사용자 요청) — `price_confirm_date`(공모가 확정공고일 = 기관 데이터 공개일), `demand_forecast_start`·`demand_forecast_end`(수요예측 기간). PENDING·CORRECTION 종목에 표시
- v1.0: 상태 `INCOMPLETE`("판정 보류 · 데이터 확인 필요") 추가(사용자 결정) — 수요예측 결과는 있으나 확약·유통 지표를 확정 못 하면 PASS/REJECT 대신 보류. 미공시 0점 처리 규칙 폐지
- v0.9: 체크리스트 경쟁률 기준 변경(사용자 결정) — ≥1,000:1 MET "좋음", ≥1,500:1 MET "아주 좋음". `ChecklistItem.level` 추가
- v0.8: 상태 `CORRECTION` 추가(사용자 요청) — 금감원 정정신고서 제출요구가 있고 그 뒤 발행조건확정이 없으면 "정정 요구 · 일정 변경 가능". PENDING 으로 보이지 않게. `Verdict.correction` 추가
- v0.7: 배포 대비(사용자 결정, requirements 12장) — `POST /api/collect` 에 수집 키 헤더 `X-Collect-Key`, 401 응답 추가
- v0.6: 가산점 기준 교체(사용자 결정) — "신청 금액 ≥ 5조" → "공모 금액 ≥ 1,000억 AND 경쟁률 ≥ 800:1" 대형주 보완. `Indicators.offering_amount_krw` 추가, scoring-config `comp.demand_bonus` → `comp.large_cap_bonus`
- v0.5: 수집 실행 API(사용자 결정, requirements 11장) — `POST /api/collect`, `GET /api/collect/status` 추가. `last_collected_at` = 마지막 성공 수집 완료 시각
- v0.4: 달력 화면(사용자 요청) — `GET /api/ipos` 의 `from`/`to` 를 "청약 기간 또는 상장일이 범위와 겹치는 종목" 으로 변경, `market`·`listing_date` 는 DART 원문 파싱값(못 찾으면 null)
- v0.3: **점수 체계 교체**(사용자 결정 — `docs/ipo-checklist-and-scoring-guide.md`, `requirements.md` 2~4·6장)
  - 하드 필터 폐지. REJECT = 총점 < 50 → REJECT 도 `score`/`scores` 를 가진다
  - `Grade` 에서 `C` 삭제 (S/A/B)
  - `PricePosition`: `BELOW_TOP` 삭제 → `WITHIN_BAND`, `BELOW_BAND` 추가
  - 점수 만점: comp 35 / price 25 / lockup 20 / flow 20
  - `min_deposit` 에 `fee_krw`, `total_krw` 추가
  - `/api/scoring-config` 구조 변경
  - `IpoDetail.checklist` 추가 (사용자 요청 — 상세 화면 체크리스트 표)
- v0.2: backend·frontend 제안 반영(Indicators 필드 추가, `IpoSummary.updated_at`, `PROSPECTUS_AMENDED`, 판정 불변식)
- v0.1: 초안

## 공통
- Base URL: `http://localhost:8000` (backend), frontend 개발 서버 `http://localhost:5173` 에서 Vite proxy `/api` → 8000.
- backend 는 CORS 로 `http://localhost:5173` 허용.
- JSON, 필드명 snake_case. 금액은 원(KRW) 정수. 비율은 0~100 의 퍼센트 숫자(소수 허용). 날짜 `YYYY-MM-DD`, 시각 ISO 8601(+09:00).
- 아직 공시되지 않았거나 파싱 실패한 값은 `null` (0 으로 채우지 않는다).
- 에러: HTTP 상태코드 + `{ "detail": "메시지" }` (FastAPI 기본 형식).

## 타입
```ts
type Status = "PENDING" | "PASS" | "REJECT" | "CORRECTION" | "INCOMPLETE";   // v0.8 CORRECTION = 정정 요구·일정 변경 가능, v1.0 INCOMPLETE = 판정 보류·데이터 확인 필요
type Grade = "S" | "A" | "B";                       // v0.3: C 삭제
type PricePosition =
  | "ABOVE_BAND"     // 확정가 > 밴드 상단
  | "TOP_OF_BAND"    // 확정가 = 밴드 상단
  | "WITHIN_BAND"    // 밴드 하단 ≤ 확정가 < 밴드 상단   (v0.3)
  | "BELOW_BAND";    // 확정가 < 밴드 하단               (v0.3)

interface Verdict {
  status: Status;
  grade: Grade | null;        // PASS 일 때만
  score: number | null;       // PASS·REJECT 일 때, 0~100. 항상 scores.total 과 같은 값
  score_range: { min: number; max: number } | null;  // v1.4 — 미확인 지표가 있을 때의 총점 범위. 범위로 확정된 PASS/REJECT 와 INCOMPLETE 에 값(이때 score·scores.total 은 null, PASS 등급은 min 기준). 모든 지표 확인 시·PENDING 은 null
  correction: {               // v0.8 — 정정 요구 정보. 해당 없으면 null
    requested_at: string;     // 정정신고서 제출요구일 (YYYY-MM-DD)
    amended_at: string | null;// 그 이후 정정신고서 제출일, 아직 없으면 null
  } | null;
}

interface IpoSummary {
  id: string;                 // DART corp_code
  corp_name: string;
  market: "KOSPI" | "KOSDAQ" | "KONEX" | null;   // v0.4 DART 원문 파싱, 못 찾으면 null (requirements 10장)
  subscription_start: string | null;  // 청약 시작일
  subscription_end: string | null;
  listing_date: string | null;        // v0.4 DART 원문 파싱(상장 예정일), 못 찾으면 null
  band_low: number | null;
  band_high: number | null;
  final_price: number | null;
  verdict: Verdict;
  price_confirm_date: string | null;     // v1.1 공모가 확정공고일(YYYY-MM-DD). 이날 [발행조건확정] 공시로 기관 데이터 공개. 원문 공모 일정 표에서 파싱, 없으면 null
  demand_forecast_start: string | null;  // v1.1 수요예측 시작일
  demand_forecast_end: string | null;    // v1.1 수요예측 종료일
  updated_at: string;         // 이 종목 데이터 마지막 갱신 시각
}

interface Indicators {
  competition_rate: number | null;     // 기관 수요예측 경쟁률 (예: 1523.4 → 1523.4:1)
  competition_rate_type: "simple" | "weighted" | null;
  demand_amount_krw: number | null;    // 기관 신청 금액. 원문에 금액이 없으면 신청 수량 × 확정가(파생값)
  price_position: PricePosition | null;
  lockup_ratio: number | null;         // %
  lockup_ratio_basis: "allocated" | "applied" | null;
  tradable_ratio: number | null;       // 상장일 유통가능 비율 %
  old_share_ratio: number | null;      // 구주매출 비율 %
  new_share_count: number | null;
  old_share_count: number | null;
  total_offering_count: number | null;
  offering_amount_krw: number | null;  // v0.6 공모 금액. 원문 모집(매출) 총액 우선, 없으면 total_offering_count × final_price. 둘 다 없으면 null
  report_rcept_no: string | null;      // 지표 값의 기준 공시 접수번호
}

interface Scores {
  comp: number | null;   // 0~35 (대형주 보완 가산 포함, 최대 35)
  price: number | null;  // 0~25
  lockup: number | null; // 0~20
  flow: number | null;   // 0~20
  total: number | null;  // 0~100
}

interface SourceDoc {
  doc_type: "PROSPECTUS" | "PROSPECTUS_AMENDED" | "REGISTRATION_AMENDED" | "ISSUANCE_REPORT";
  rcept_no: string;
  rcept_dt: string;
  url: string;                // https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}
}

interface MinDeposit {
  shares: number;
  deposit_krw: number;        // shares × final_price × margin_rate
  fee_krw: number;            // v0.3 청약 수수료 (설정값, 기본 2000)
  total_krw: number;          // v0.3 deposit_krw + fee_krw
}

interface IpoDetail extends IpoSummary {
  indicators: Indicators;
  scores: Scores;
  reasons: string[];          // 판정 근거 (한국어 문장). 빈 배열 가능
  reject_reasons: string[];   // REJECT 일 때 비추천 사유(예: "종합 점수 42점 — 50점 미만"). 그 외 빈 배열
  // v1.6 min_deposit 삭제(사용자 결정)
  sources: SourceDoc[];
  checklist: ChecklistItem[];      // v1.5 — 판정 4항목, 항상 4개, 순서 competition → price_position → lockup → flow
  underwriters: string[];          // v1.2 — 주관사·인수회사 이름(대표 → 공동 → 인수 순, 중복 제거). OpenDART estkRs 인수인정보. 모르면 빈 배열
}

type ChecklistKey = "competition" | "price_position" | "lockup" | "flow";   // v1.5 min_deposit·sell_timing 제거
type ChecklistResult =
  | "MET"        // 만족 → 화면 ✓
  | "NOT_MET"    // 불만족 → 화면 ✗
  | "UNKNOWN"    // 값 미공시 → 화면 "미공시"
  | "INFO";      // 판정 대상 아님(증거금·매도 타이밍) → 정보만 표시

interface ChecklistItem {
  key: ChecklistKey;
  label: string;        // 예: "기관 경쟁률"
  indicator: string;    // 예: "기관 수요예측 경쟁률"
  criterion: string;    // 사람이 읽는 만족 기준, 예: "1,500:1 이상"
  actual: string | null;// 이 종목의 실제 값 표시 문자열, 예: "983.98:1". 미공시면 null
  result: ChecklistResult;
  level: "VERY_GOOD" | "GOOD" | null;  // v0.9 — MET 일 때 단계. 현재 competition 만 사용(≥1500 VERY_GOOD, ≥1000 GOOD). 그 외 항목·결과는 null
}
```
- 체크리스트 만족 기준의 정본은 `requirements.md` 9장. 기준 수치는 `/api/scoring-config` 의 `checklist` 에도 노출.

## 판정 규칙 (v0.3 — 상태와 값의 불변식)
| status | 조건 | score / scores | grade | reject_reasons |
| --- | --- | --- | --- | --- |
| `CORRECTION` (v0.8) | 정정신고서 제출요구가 있고 그 이후 [발행조건확정] 공시가 없음 (PENDING 보다 우선) | 모두 null | null | 빈 배열 |
| `PENDING` | `competition_rate` 또는 `price_position` 중 하나라도 null | 모두 null | null | 빈 배열 |
| `INCOMPLETE` (v1.0) | 수요예측 결과(경쟁률·가격 위치)는 있으나 S_lockup 또는 S_flow 를 확정할 수 없음(아래) | `scores` 는 확정된 지표만 값, 나머지 null. `score`·`scores.total` null | null | 빈 배열 |
| `PASS` | 총점 ≥ `grade.pass_min`(50) | 모두 값, `verdict.score == scores.total` | S(≥80) / A(≥65) / B | 빈 배열 |
| `REJECT` | 총점 < 50 | 모두 값, `verdict.score == scores.total` | null | 1개 이상 |

- (v1.0) **미공시 0점 처리 폐지.** S_lockup 확정 불가 = `lockup_ratio` null. S_flow 확정 불가 = `tradable_ratio` null, 또는 `tradable_ratio` ≤ 35 인데 `old_share_ratio` null(구주 값에 따라 0/12/20 이 갈림). 둘 중 하나라도 확정 불가면 `INCOMPLETE`, `reasons` 에 "○○ 확인 필요 — 판정 보류" 문장. 우선순위: 철회 → CORRECTION → PENDING → INCOMPLETE → PASS/REJECT. `offering_amount_krw` 또는 `competition_rate` 가 기준 미달·null 이면 가산점 없음. 가산 시 `reasons` 에 "대형주 보완 +5점" 문장.
- 점수 계산 규칙의 정본은 `requirements.md` 3장.

## 엔드포인트
### `GET /api/ipos`
- query: `status` (선택, Status), `from` / `to` (선택, `YYYY-MM-DD`) — v0.4: **청약 기간(subscription_start~end) 또는 listing_date 가 [from, to] 와 겹치는 종목**. 달력 월 단위 조회용
- 응답: `{ "items": IpoSummary[] }` — 청약 시작일 오름차순

### `GET /api/ipos/{id}`
- (v1.6) `shares` 쿼리 삭제
- 응답: `IpoDetail`, 없으면 404

### `GET /api/scoring-config`
- 응답: 현재 적용 중인 기준값(임계값·배점만, 설명 문구는 frontend 소유). backend 설정 파일과 같은 구조.
```jsonc
{
  "score": {
    "comp": {
      "max": 35,
      "tiers": [ { "gte": 1500, "points": 35 }, { "gte": 1000, "points": 25 }, { "gte": 500, "points": 15 } ],
      "default": 0,
      "large_cap_bonus": { "min_offering_amount_krw": 100000000000, "min_competition_rate": 800, "points": 5 }
    },
    "price": {
      "max": 25,
      "points": { "ABOVE_BAND": 25, "TOP_OF_BAND": 20, "WITHIN_BAND": 10, "BELOW_BAND": 0 }
    },
    "lockup": {
      "max": 20,
      "tiers": [ { "gte": 20, "points": 20 }, { "gte": 10, "points": 15 }, { "gte": 5, "points": 10 } ],
      "default": 0
    },
    "flow": {
      "max": 20,
      "zero_if": { "tradable_gt": 35, "old_share_gte": 30 },          // 둘 중 하나라도 → 0
      "top_if":  { "tradable_lt": 25, "old_share_eq": 0, "points": 20 }, // 둘 다 → 20
      "otherwise": 12
    }
  },
  "grade":   { "pass_min": 50, "s_min": 80, "a_min": 65 },
  "deposit": { "default_shares": 10, "margin_rate": 0.5, "fee_krw": 2000 },
  "checklist": {
    "competition_good_min": 1000, "competition_very_good_min": 1500,   // v0.9
    "price_positions_met": ["TOP_OF_BAND", "ABOVE_BAND"],
    "lockup_min": 10,
    "flow_tradable_max": 35, "flow_old_share_lt": 30
  }
}
```
- `tiers` 는 `gte` 내림차순, 처음 만족하는 구간의 점수. 없으면 `default`.

### `GET /api/health` (v1.5: parser_version·commit 추가 예정)
- 응답: `{ "status": "ok", "last_collected_at": string | null }`

### `POST /api/collect` (v0.5)
- 수집·분석 작업 시작. body 없음.
- (v0.7) 서버에 수집 키가 설정되어 있으면 요청 헤더 `X-Collect-Key` 가 일치해야 함. 누락·불일치 → **401** `{ "detail": "수집 키가 올바르지 않습니다." }`. 키 미설정(로컬 개발)이면 검사 없음. `GET /api/collect/status` 는 키 불필요.
- 응답 **202**: `CollectStatus` (status = `RUNNING`)
- 이미 실행 중이면 **409** + `CollectStatus`(현재 실행 중인 작업)를 body 로 반환. frontend 는 409 도 "진행 중" 으로 처리.
- 샘플 데이터 모드에서는 **409** + `{ "detail": "샘플 데이터 모드에서는 수집할 수 없습니다." }`.

### `GET /api/collect/status` (v0.5)
- 응답: `CollectStatus`
```ts
interface CollectStatus {
  status: "IDLE" | "RUNNING" | "SUCCEEDED" | "FAILED";  // IDLE = 서버 기동 후 실행 이력 없음
  started_at: string | null;
  finished_at: string | null;
  progress: { done: number; total: number | null } | null;   // 처리한 공시 수 / 대상 공시 수(모르면 null)
  summary: {
    new_count: number;        // 신규 추가 종목
    updated_count: number;    // 갱신 종목(새 문서·재판정)
    unchanged_count: number;  // 변화 없음
    failed_count: number;     // 실패 종목(파싱·다운로드 오류)
    withdrawn_count: number;  // 철회로 제외된 종목
  } | null;                   // 완료(SUCCEEDED/FAILED) 시
  error: string | null;       // FAILED 사유(사람이 읽는 한국어). 키·내부 경로 노출 금지
  last_collected_at: string | null;  // 마지막 성공 수집 완료 시각 (/api/health 와 같은 값)
  failures: { corp_code: string; corp_name: string; reason: string }[];  // v1.3 실패 종목별 사유(키·URL·경로 제거, 300자 이내). 없으면 빈 배열
}
```
- frontend 는 RUNNING 동안 2~3초 간격 폴링, 완료 시 달력 재조회.

## v1.7 (2026-10-27) — 내 공모주 `holdings` (requirements 24장)
```ts
type Holding = {
  corp_code: string;        // ipos.corp_code (종목당 1건)
  shares: number;           // 배정 수량, 정수 ≥ 1
  price: number;            // 공모가(원), 정수 ≥ 1
  memo: string;             // 0~60자, 없으면 ""
  created_at: string;       // ISO +09:00
  updated_at: string;
  // 응답 전용(수집 데이터에서 결합, 저장 안 함)
  corp_name: string | null;
  listing_date: string | null;   // YYYY-MM-DD
  amount_krw: number;            // shares × price
};
```
- `GET /api/holdings` → `{ items: Holding[] }` (정렬은 frontend)
- `PUT /api/holdings/{corp_code}` body `{shares, price, memo}` → 200 `Holding` (없으면 생성, 있으면 수정 = upsert). corp_code 가 ipos 에 없으면 404, 값 검증 실패 422
- `DELETE /api/holdings/{corp_code}` → 204 (없어도 204)
- 인증 없음(사용자 결정). 응답·로그에 비밀값 없음

## v1.8 (2026-10-27) — `IpoDetail.data_notes: string[]`
- 상세에만. 수집 중 정해진 방식으로 처리한 알려진 상황(본문 없는 [첨부정정]으로 직전 공시 사용, 기준 공시 없음 등)을 사용자용 문장으로. 없으면 `[]`. 수집 요약·목록에는 노출하지 않음(requirements 27장)
