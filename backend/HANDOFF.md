# backend 세션 인계 문서

이 문서는 **처음 이 코드베이스를 여는 Claude 세션/개발자** 가 backend 를 이어서 개발할 때 참고하는 지도다.
루트 `docs/HANDOFF.md`(pm 작성) 와 짝. 이 파일은 **`backend/` 디렉터리에 한정**된 것만 다룬다.

- 프로젝트 전체 규약은 루트 `../CLAUDE.md`, 상세 요구사항은 `../.claude/co-work/requirements.md`, API 계약은 `../.claude/co-work/api-contract.md`.
- backend 세션 전용 규약은 `backend/CLAUDE.md`.
- 공모주 판정 로직 정본은 `docs/ipo-checklist-and-scoring-guide.md`, 데이터 정의는 `docs/dart-ipo-analysis-logic.md`.

---

## 1. 구조 지도

### 디렉터리
```
backend/
├── app/                      # FastAPI 애플리케이션
│   ├── main.py               # 진입점. CORS, 라우터 등록, 시작 시 maintenance 호출
│   ├── config.py             # pydantic-settings. .env.local 로드
│   ├── config_files/
│   │   └── scoring.yaml      # 점수·등급·체크리스트 기준값(코드에 하드코딩 금지)
│   ├── schemas.py            # 응답 모델(Pydantic). IpoDetail/IpoSummary/Indicators/Verdict/Checklist/Holding
│   ├── routers/
│   │   ├── health.py         # /api/health (parser_version, commit, last_collected_at)
│   │   ├── ipos.py           # /api/ipos, /api/ipos/{id}
│   │   ├── collect.py        # POST /api/collect, GET /api/collect/status
│   │   ├── scoring_config.py # /api/scoring-config (설정 그대로 반환)
│   │   └── holdings.py       # /api/holdings (내 청약 기록)
│   ├── collect.py            # 파서·classify + process_corp. PARSER_VERSION 상수 보유
│   ├── collect_service.py    # 수집 서비스. 2단계 조회(C001 + 전 유형×existing) + stale 재처리
│   ├── parser.py             # DART 원문에서 지표/일정 추출. 함수당 1지표 원칙
│   ├── dart_client.py        # OpenDART HTTP 호출(list.xml, document.xml, estkRs.xml)
│   ├── store.py              # SQLite/Turso 저장소. init_db / 마이그레이션 / upsert / replace_sources
│   ├── turso_adapter.py      # Turso Hrana /v2/pipeline 어댑터(SQLite 인터페이스 흉내)
│   ├── repository.py         # row dict ↔ IpoDetail 변환, data_notes 생성
│   ├── scoring.py            # evaluate(점수·등급·상태) + build_checklist + build_verdict
│   ├── maintenance.py        # 시작 시 1회 정리 (지시 #54 — v33 유입 비IPO 45개 삭제)
│   ├── security.py           # 비밀값 sanitize (DART 키 로그 유출 방지)
│   ├── sample_data.py        # use_sample_data=True 분기용 (PENDING/PASS/REJECT 각 1건+)
│   └── time_utils.py         # KST ISO 포맷 + now_iso_kst
├── tests/                    # pytest. conftest 가 tmp SQLite 강제
├── data/                     # 로컬 SQLite (운영 로컬 파일 — 쓰기 금지, mtime 보존)
├── .env.local                # DART_CERT_KEY, TURSO_* (git 제외, 값 출력 금지)
├── .env.example              # 변수명만, 값 비움
├── requirements.txt
├── README.md                 # 설치·실행·테스트·엔드포인트 요약
├── CLAUDE.md                 # backend 세션 규약
└── HANDOFF.md                # (이 파일)
```

### 핵심 데이터 흐름
```
OpenDART (list.xml C001)
     ↓
collect_service._run()       # 2단계 조회 (지시 #53)
     ↓
collect.process_corp()       # classify_report → 파싱 → store upsert
     ↓
store.upsert_ipo + replace_sources (COALESCE/파생값 교체 규칙)
     ↓
repository._detail_from_row  # 점수 재계산 + 체크리스트 + data_notes
     ↓
GET /api/ipos/{id}
```

---

## 2. 실행·테스트·빌드

### 설치
```bash
cd backend
# Microsoft Store python 스텁 회피 — 전체 경로 지정
C:/Users/CHO/AppData/Local/Programs/Python/Python312/python.exe -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

### 실행 (로컬)
```bash
cd backend
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
# http://localhost:8000/docs
```

### 수집 1회 (최초 기동 전)
```bash
.venv/Scripts/python -m app.collect --days 90 --quiet
# 또는 서버 띄우고
curl -X POST http://localhost:8000/api/collect
```

### 테스트
```bash
.venv/Scripts/python -m pytest -q
# 303 passed  (2026-10-27 기준)
```
- `tests/conftest.py` 의 autouse `_force_tmp_sqlite_path` 가 `TURSO_*=""` 를 강제하고 임시 SQLite 를 쓴다 → **운영 DB 에 절대 안 붙음**.
- 실원문 회귀 fixture: `tests/test_parser.py::TestRealCorpus` 가 `../.claude/co-work/daily-check/cache/{rcept_no}.txt` 를 참조. 캐시 없으면 skip (pm 세션 daily_check 이 생성).

### 로컬 환경 주의점
- **Python**: PATH 의 `python` 은 Microsoft Store 스텁일 수 있다. 반드시 `C:\Users\CHO\AppData\Local\Programs\Python\Python312\python.exe` 로 venv 생성.
- **Git Bash 특수성**:
  - `/proc/sys/kernel/random/uuid` 없음 → `powershell -NoProfile -Command "[guid]::NewGuid().ToString()"` 로 UUID 생성.
  - 셸 상태(변수, 함수) 는 명령 간 보존 안 됨 — 긴 작업은 Python 스크립트로.
- **포트**: backend `:8000`, frontend `:5173`. CORS 는 `http://localhost:5173` 허용.
- **운영 로컬 DB**: `backend/data/recommend_ipo.sqlite` — **쓰기 금지**. mtime 보존.

---

## 3. 변경 이력 요약 (지시 번호별)

### 파서 버전 (`PARSER_VERSION` 상수)
현재 **v36**. 버전은 `/api/health.parser_version` 으로 노출. stale 재처리의 트리거.

| v | 지시 | 요약 |
| --- | --- | --- |
| v2 | #16 | 티앤이코리아 확약·유통 regex 일반화 |
| v3 | #19 | INCOMPLETE 상태 도입 |
| v4 | #24 | 재파싱 시 종목 전체 이력 조회 |
| v5 | #25 | 실적보고서 상장일(매매개시일) 파싱 |
| v6 | #26 | 삼성증권 확약 형식 수용 |
| v7 | #20 | 공모가 확정공고일·수요예측 기간 파싱 |
| v8 | #17 | CORRECTION 상태 도입 |
| v9 | #28 | 공지 다운로드 가드 + stale-only 재처리 |
| v10 | #21+#75aebc23 | estkRs 주관사 + 확정가 전 공모금액 null |
| v11 | #29 | 공모금액 total×final + 파생필드 COALESCE 예외 |
| v12-v13 | 정확도 보강 | 요일 괄호·신주/구주 라벨 변형·엠에스바이오 유통 |
| v14-v15 | #30+#32 | CORRECTION 해제 조건 확장 + 메타 COALESCE 예외 |
| v16-v17 | 보강 | 엘리스 "합/계" COLSPAN, estkRs 교차검증, Turso 트랜잭션 |
| v18-v20 | #35-#37 | 상장 완료 종목 재처리 + 메인 for 루프 필터 완화 |
| v21-v22 | #38+#39 | 신주/구주 strict + 정정 "정 정 전" 섹션 제거 |
| v23 | #40+#41 | 아델 가정 확정가 거부 + flow 한쪽 조건 NOT_MET |
| v24 | #42 | 정정 신고서 서두 정정표 skip ("대표이사 등의 확인" 이후만) |
| v25 | #43 | final_price 조건부 COALESCE (competition_rate null 이면 교체) |
| v26 | #46 ① | COALESCE 축소 — 정상 파싱이면 excluded 교체 (전용 출처는 보호) |
| v27-v30 | #45 묶음 | INCOMPLETE 한글 라벨, flow 범위, 다중 확정가 후보 등 |
| v31 | #48 | extract_offering_amount_krw 본문 추출 원복 (1주가격 오매치) |
| v32 | #49 | 각주 "(주N)" 수용 + 유통 부분값 힌트 확장 |
| v34 | #53 | 증분 조회 2단계 (C001 신규 + 전 유형×existing) |
| v35 | #55 | [첨부정정] core 후보 제외 (document.xml 014 해소) |
| v36 | #56 | sources.report_nm + IpoDetail.data_notes + 014 사유 문구 |

### 지시 #57 (2026-10-27, v36 유지)
- `_data_notes_from_row` 비교를 날짜(>) → **rcept_no(>)** 로 변경. 같은 날 공시(제논) 사례 해소.
- core report_nm 에서 `[기재정정]` / `[발행조건확정]` 접두 추출해 안내 문구에 포함.
- 날짜 포맷 `10/26` → `10월 26일`.
- 소스 payload 변경 없음 → PARSER_VERSION bump 없음.

### 지시 #54 (startup cleanup)
- `app/maintenance.py` 신규. 시작 시 1회, v33 수집으로 유입된 비IPO 45개 corp_code 삭제.
- 배치 IN 쿼리 3개로 처리 (개별 DELETE 135개면 subprocess 타임아웃 초과).
- `holdings` 테이블은 **절대 안 건드림** (사용자 데이터).

### 지시 #dd93b259 (holdings)
- `/api/holdings` CRUD. 내 청약 기록 저장(배정 주식 수, 상장일 플래그).
- DELETE 응답: `Response(status_code=204)` (FastAPI 는 `@router.delete(status_code=204)` + return 조합을 거부).

---

## 4. 함정·교훈 (**이게 가장 중요하다**)

### 4.1 원문 파싱
- **정정 신고서**: 서두에 "정정전/정정후" 블록이 번갈아 나와 옛 값과 새 값이 섞여 있다. **"대표이사 등의 확인" 첫 등장 이후** 의 본문에서만 일정·밴드·확정가를 읽는다 (지시 #42, v24).
- **가정·조건 문장 거부**: "확정공모가액이 N원 이상으로 결정되는 경우" 같은 문장을 파싱 결과로 쓰면 안 된다. 접미사 `[경우|될|라면|가정|이상|이하]` 를 확인 (지시 #40, v23).
- **가치평가 표 금지**: "신주모집유입자금 N억원" 같은 금액은 공모금액이 아니라 자본 조달 추정. 공모금액은 `total_offering_count × final_price` 로만 계산 (지시 #48 — 본문 추출 회귀 원복).
- **부분값 거부**: "기존 주주의 유통가능 물량" 같은 부분 비율은 전체 유통비율이 아니다. 명시 서술만 수용 (지시 #39, #49).
- **원문 오타 검산**: `37,68%` 같은 쉼표 소수점 수용(이에스티, v21), 음수·0~100 범위 벗어남·신주+구주≠총공모 는 null (지시 #38).

### 4.2 저장 정책 (store.upsert_ipo)
- **COALESCE 패턴**: 다운로드·파싱 실패 시 **기존 값 보존**. 지표 전체가 null 이면 DB 는 이전 값 유지.
- **파생값은 excluded 교체**: `price_position`, `demand_amount_krw`, `old_share_ratio`, `offering_amount_krw` 는 null 포함 교체 (지시 #29, #32, #43).
  - 이유: `final_price` 가 바뀌면 `price_position` 재계산 결과가 null 이어야 하는데 COALESCE 로 보존되면 **옛 가격 기준 값이 영구히 남는다**.
- **correction 메타도 excluded 교체** (지시 #32): CORRECTION 해제 시 null 로 바꿔야 한다.
- **final_price 조건부 COALESCE** (지시 #43, v25): `competition_rate` 가 새·기존 모두 null 이면 excluded 교체. **가정문 오파싱(아델) 영구 저장 방지**.
- **전용 출처 보호** (지시 #46, v26): `listing_date`, `market`, `underwriters` 는 ISSUANCE_REPORT / estkRs 전용. REGISTRATION 파싱 결과로 덮지 않는다.

### 4.3 증분 조회 (collect_service._run)
- **2단계 조회** (지시 #53, v34):
  1. `pblntf_detail_ty=C001` (지분증권 발행) → **신규 종목 발견**.
  2. `pblntf_detail_ty=None` + 기존 종목(`existing_corp_codes`) 필터 → 이미 수집된 종목의 **전 유형 이력** 수집.
- **왜**: v33 이 2단계 없이 전 유형을 돌려서 `classify_report` 가 집합투자증권·사채·SPAC 등을 PROSPECTUS 로 오인 → 비IPO 45개가 유입됨 (c176c7a 가 복구).
- **lesson**: 신규 corp 발견 경로는 반드시 좁은 필터로. 넓은 필터는 **이미 검증된 corp_code** 에만 적용.

### 4.4 [첨부정정] 공시 (지시 #55, v35)
- 접수번호에 `[첨부정정]` 이 붙은 증권신고서는 **본문 document.xml 이 없다** (`<status>014</status> 파일이 존재하지 않습니다`).
- `choose_core_disclosure()` 가 `finals` / `regs` 양쪽에서 **[첨부정정] 을 제외** → 다운로드 자체가 발생하지 않음.
- 다른 유형에서 014 가 나면 dart_client 가 자동으로 `"DART 014 파일 없음"` 문구로 표시 (지시 #56).

### 4.5 실패 정의 (지시 #56)
- `failures` / `failed_count` 는 **예상 못한 오류만** 집계: timeout·5xx 반복, ZIP 아님, 파싱 예외, DB 오류.
- 알려진 처리 상황은 실패 아님: 본문 없는 공시 skip, preserved 보존, 비IPO·FSS 공지 제외.
- 014 가 `[첨부정정]` 외 공시에서 나면 **"DART 014 파일 없음"** — 원인이 드러나는 문구.

### 4.6 테스트 — 실원문 회귀 (지시 #42, v24 사고)
- 합성 문자열 테스트만 통과하고 실제 원문에서 회귀한 사례 있음(v23).
- **파서 수정 후 반드시 `../.claude/co-work/daily-check/cache/{rcept_no}.txt` 에 직접 돌려** 기대값 확인.
- 테스트 fixture 가 상대 경로로 캐시를 참조하므로 pm 세션이 daily_check 를 돌릴 때만 캐시가 생성됨 → 로컬 테스트 환경에서 fixture 는 자동 skip.

### 4.7 PARSER_VERSION bump 규칙
- **코드 변경이 저장된 값에 영향**을 주면 bump → stale 재처리로 전 종목 반영.
- **응답 생성 로직만 변경** (예: 지시 #57) 은 bump 안 함 → 다음 요청부터 즉시 반영.
- bump 후 pm 이 Render 재기동으로 stale 트리거.

### 4.8 Turso 어댑터 특성
- Hrana `/v2/pipeline` API, `turso_adapter.py` 가 SQLite 인터페이스 흉내.
- **FK CASCADE 는 Turso 가 서버에서 처리** — 로컬 SQLite 와 결과 다를 수 있어 테스트는 임시 SQLite 로.
- 타입 변환: float 는 `{"type": "float", "value": "0.5"}` 가 아니라 **JSON 숫자** 로 보내야 함 (지시 #23 fix).
- 에러 바디는 Turso 가 그대로 반환 → 500/400 시 `turso_adapter.py` 가 **본문을 로그에 노출** (지시 #23).

### 4.9 비밀값
- `DART_CERT_KEY` 는 `.env.local` 에서만 로드.
- `app/security.py` 의 `sanitize_url_for_log` 가 쿼리스트링의 `crtfc_key` 를 제거.
- 저장된 warnings 에도 키가 들어가지 않도록 `collect.py` 가 로그 생성 전 sanitize (1e2a174).
- **로그·응답·협업 파일·커밋 어디에도 키 값 쓰지 말 것**.
- `~/.ssh`, `~/.aws/credentials` 등 **다른 자격증명 파일 내용 출력 금지** (조직 정책).

---

## 5. 남은 일·알려진 한계

### 미구현 inquery (오래된 orphan — 2026-10-27 기준)
- `backend-inquery-75aebc23` (2026-10-19) — 다비오 fallback 제거, 확정가 전 null. 이후 지시 #43(v25) 로 대체되었을 가능성 (추측).
- `backend-inquery-637ea895` (2026-10-16) — 트랜잭션 묶음, 구주/신주 파서, 유통 포맷. 이후 보강 묶음 v17 과 지시 #38(v21) 로 대체 (추측).
- 그 외 8개 (Oct 16-22 날짜) — pm 이 후속 지시로 대체했거나 결정 파기. 그대로 열지 말고 pm 확인 필요.

### `data_notes` 미구현 사례
- **preserved 안내** (지시 #56 에서 다음 라운드로): 지표가 전부 null 인데 `report_rcept_no` 는 있는 경우(정본 공시 없음). 현재 preserved 판정이 응답 레벨에서 복잡해서 보류 중.
- **report_nm NULL 폴백** (지시 #57 에서 다음 라운드): ADD COLUMN 이전 수집된 sources 행은 report_nm null → `[첨부정정]` 판정 못 함 → 안내 생략. 재처리로 자동 복구 되지만 그때까지는 안내 없음.

### 구조적 한계
- **classify_report 는 doc_type 레벨만** (REGISTRATION_AMENDED / EFFECTIVENESS_NOTICE 등). `[첨부정정]` 같은 세부 브래킷은 `report_nm` 에서만 읽을 수 있음.
- **Render Free 플랜 슬립**: 15분 유휴 후 콜드 스타트. 첫 요청 ~30초. frontend 의 timeout UI 는 그에 맞춰 설정.
- **Turso 쓰기 지연**: 운영 Turso 는 edge replication 이 있어 쓰기 후 즉시 read 가 stale 할 수 있음(실측).

---

## 6. 세션이 기억하는 결정 배경 (코드에 안 보이는 것)

### 6.1 균등 배정 최소 증거금 제거 (2026-10-20)
- 초기 요구사항에 있었으나 사용자 결정으로 제거.
- backend 는 `shares` 쿼리를 받되 **무시** (422 아님 — frontend 구버전 호환).
- 체크리스트도 6항목 → 4항목으로 축소 (deposit, sell_timing 제거).

### 6.2 하드 필터 폐지 (requirements 3장)
- 초기 설계의 "경쟁률 100:1 미만이면 즉시 REJECT" 같은 하드 필터는 폐기.
- 모든 종목이 점수를 가지고, 50 미만이 REJECT. 하드 필터 없음.

### 6.3 체크리스트 재구성 (지시 #33, v1.5)
- 4항목: competition / price_position / lockup / flow.
- 결과는 3값: MET / NOT_MET / UNKNOWN (NO가 아님).

### 6.4 PENDING vs INCOMPLETE vs CORRECTION
- **PENDING**: 수요예측 결과 미공시 (경쟁률 null). 판정 유보.
- **INCOMPLETE**: 지표가 빠져서 점수 범위가 50을 걸침 (범위가 한쪽이면 PASS/REJECT 확정).
- **CORRECTION**: 정정요구 공시 수신 후 발행조건확정 전. 판정 보류.
- **PASS/REJECT**: 50 기준.

### 6.5 왜 `/api/health.commit` 이 있나 (지시 #31)
- Render 는 커밋 해시를 빌드 시 env 로 주입 가능. frontend 가 health 응답에서 commit 과 parser_version 을 보고 **배포 지연 확인** 가능.
- `commit` 은 `RENDER_GIT_COMMIT` 환경변수에서 가져옴 (없으면 null).

### 6.6 왜 운영 로컬 DB(`backend/data/recommend_ipo.sqlite`) 쓰기 금지
- 과거 세션이 테스트 실행으로 운영 로컬 DB 를 덮어쓴 사고 발생 (추측).
- 현재는 `conftest.py` autouse 로 tmp SQLite 강제. mtime(`90112 Oct 16 14:55`) 는 **그 사고 이전 상태 보존 중**.
- 새 세션은 이 파일을 절대 열거나 쓰지 말 것 (읽기도 지양).

### 6.7 Autonomous loop 운영 (지시 #40 교훈)
- backend 세션은 `/loop 10m` 으로 돌아간다. 10분마다 스스로 깨어남.
- **감시기 알림 누락 사례** 있음 (2026-10-21): 매 사이클 시작 시 `ls backend-inquery-*` 로 전수 확인 **필수**.
- Monitor 는 30분 만료 — 재무장 전에 `ps -ef | grep watch-cowork` 로 좀비 확인 (실측: 세션 종료 후에도 bash 프로세스가 고아로 남음).
- 좀비 2개 쌓이면 알림 중복/누락 발생.

### 6.8 왜 `.claude/co-work/pm.md`, `pm-status.md`, `requirements.md`, `api-contract.md`, `WORKFLOW.md`, `watch-cowork.sh`, `PROTOCOL.md` 는 변경 금지인가
- pm 세션 소유.
- 수정 필요 시 `pm-inquery-{uuid}.md` 로 협상.

### 6.9 데이터 제보 받을 때 (unchanged_corps 로그 — 지시 #36)
- 수집 후 "변경 없음" 인 종목을 `unchanged_corps` 로 반환 → pm 이 preserved 사고 조기 발견.
- 로그 포맷: `{corp_name}:{reason}` (예: `엘리스:preserved:정본-공시-없음-...`).

### 6.10 Turso 트랜잭션 묶음 (지시 #보강-C, v17)
- `process_corp` 안의 upsert + replace_sources 를 **원자적으로**. 이전엔 중간 실패 시 sources 만 남는 유령 상태 발생.
- Turso 어댑터가 `BEGIN/COMMIT` 지원.

---

**이 문서를 읽은 다음**:
1. 루트 `../CLAUDE.md` 와 `backend/CLAUDE.md` 를 읽는다.
2. `.claude/co-work/requirements.md`, `api-contract.md`, `WORKFLOW.md` 를 읽는다.
3. `ls .claude/co-work/backend-inquery-*.md` 로 미처리 inquery 확인.
4. 감시기 재무장 → `/loop 10m` 시작.

좋은 작업 되기를.
