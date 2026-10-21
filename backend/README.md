# recommend_ipo backend

DART 공시 기반 공모주 청약 추천 API. FastAPI + Turso(운영) / SQLite(로컬·테스트).

## 필수 환경
- Python 3.11+ (3.12 권장, 개발 환경은 `C:\Users\CHO\AppData\Local\Programs\Python\Python312\python.exe`)
- `tzdata` 패키지 자동 설치 (Windows 에서 `ZoneInfo("Asia/Seoul")` 보장용)

## 설치
```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate      # Git Bash
# .\.venv\Scripts\Activate.ps1     # PowerShell
pip install -r requirements.txt
```

## 환경변수 (`backend/.env.local` — git 제외)

| 변수 | 필수 | 설명 |
| --- | --- | --- |
| `DART_CERT_KEY` | ✅ | OpenDART 인증키. 로그·응답·협업 파일에 값 출력 금지 |
| `CORS_ORIGINS` | 선택 | CSV, 기본 `http://localhost:5173` (Vite dev). 운영은 Netlify 도메인 추가 |
| `TURSO_DATABASE_URL` | 운영 | Turso HTTP pipeline(/v2/pipeline) URL. 로컬 개발용 DB 또는 운영 DB |
| `TURSO_AUTH_TOKEN` | 운영 | 상동 |

- 로컬 개발은 **개발용 Turso DB**(별도 생성), 운영은 **운영 Turso DB** 를 쓴다.
- 테스트는 **임시 SQLite** 사용. `tests/conftest.py` 의 autouse fixture `_force_tmp_sqlite_path` 가 Turso 변수를 비우고 tmp 경로를 강제한다.
- `COLLECT_KEY` 는 사용자 결정으로 사용하지 않음(설정 금지).

## 실행 (로컬)
```bash
cd backend
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
# http://localhost:8000/docs
```
- 기본값: `use_sample_data=False` (DB 조회). 샘플 응답으로 돌리려면 `USE_SAMPLE_DATA=true`
- 처음 기동 전 수집 1회 필요: `.venv/Scripts/python -m app.collect --days 90 --quiet`
- 또는 서버 띄우고 `curl -X POST http://localhost:8000/api/collect`

## 테스트
```bash
cd backend
.venv/Scripts/python -m pytest -q
# 249 passed
```
- autouse fixture 로 각 테스트가 tmp SQLite 를 쓰고 `use_sample_data=True` / `TURSO_*=""` 를 강제.
- 운영 로컬 DB(`data/recommend_ipo.sqlite`) 는 테스트 영향 없음 (mtime 보존).

### 실원문 회귀 fixture
- `tests/test_parser.py::TestRealCorpus` 는 pm 의 daily_check 캐시(`.claude/co-work/daily-check/cache/{rcept_no}.txt`) 를 상대 경로로 참조해 실제 DART 원문 7종목 × 13개 extract 결과를 고정한다.
- 캐시가 없으면 `pytest.mark.skipif` 로 스킵. 로컬에서는 pm 세션이 동시에 돌 때만 캐시가 생성된다.

## 엔드포인트 (api-contract v1.6)
| Method | Path | 요약 |
| --- | --- | --- |
| GET  | `/api/health` | 상태 + 마지막 수집 시각(KST) + `parser_version` + `commit` |
| GET  | `/api/ipos` | 목록. `status`, `from`, `to`(겹침 로직) |
| GET  | `/api/ipos/{id}` | 상세 (지표·점수·등급·근거·체크리스트 4항목·주관사·일정) |
| GET  | `/api/scoring-config` | 판정 기준값(설정 파일 그대로) |
| POST | `/api/collect` | 수집 시작(202) · 중복 409 · 샘플 모드 409 |
| GET  | `/api/collect/status` | 상태 머신 폴링 |

- 응답 시각은 모두 ISO 8601 **+09:00(KST)**. Render(UTC) 에서도 보장.
- 균등 배정 최소 증거금(`shares` 쿼리·`MinDeposit` 모델)은 **제거됨(2026-10-20)**. 호환성을 위해 `?shares=…` 는 받되 무시 (422 아님).
- 체크리스트 4항목: `competition` / `price_position` / `lockup` / `flow`. (deposit·sell_timing 제거)

## 수집 동작 요약
- **증분 조회**: C001 (지분증권 발행) + 상장 완료 종목(`existing_corp_codes`) 의 전체 이력 → `is_ipo_candidate(corp_cls='E' + stock_code='')` 또는 `classify_report(…) is not None` 로 필터
- **stale 재처리**: 저장된 `parser_version` 이 현재 `PARSER_VERSION` 과 다르면 전 종목 재처리 (parser 업그레이드 반영)
- **FSS 공지**: 접수번호 9~10번째 자리가 `"10"` 이면 메타만 저장(다운로드 skip)
- **다운로드·파싱 실패**: 기존 값 **보존** (COALESCE). 단 `final_price` 는 수요예측 결과(`competition_rate`) 가 새·기존 모두 null 이면 excluded 값(null)으로 교체 (지시 #43 — 가정문 오파싱 보존 방지)
- **파생값**(`price_position`, `demand_amount_krw`, `old_share_ratio`, `offering_amount_krw`): excluded 로 교체 (null 포함, 지시 #29·#32·#43)
- **CollectSummary**: `failures`, `unchanged_corps` (분기별 라벨), `withdrawn_rcept_nos` 포함

## 파싱 원칙
루트 `../CLAUDE.md` 의 "원문 파싱·검증 원칙" 과 `docs/dart-ipo-analysis-logic.md` 참조. 요약:
- 명시 서술만 수용. **추정 금지** → null 반환 + warning 기록.
- 가정·조건문 거부 (예: "확정공모가액이 N원 이상으로 결정되어" — 지시 #40).
- 정정 신고서는 **"대표이사 등의 확인" 첫 등장 이후** 본문에서만 일정·밴드 추출 (지시 #42).
- 부분값 서술 skip (예: "기존 주주의 유통가능 N%" — 지시 #39).

## Render 배포 절차 (requirements 12장)

### 1. Turso DB 생성 (사용자가)
1. https://turso.tech/ 가입, CLI 설치
2. `turso db create recommend-ipo` → DB URL 획득
3. `turso db tokens create recommend-ipo` → 토큰 획득
4. 스키마 적용: 운영은 첫 서비스 기동 시 `store.init_db()` 가 CREATE 수행

### 2. Render Blueprint 등록 (사용자가)
1. 레포를 Render 에 연결, `backend/render.yaml` 자동 감지
2. 환경변수 **값 입력**: `DART_CERT_KEY`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `CORS_ORIGINS`

### 3. 첫 수집
- 배포 완료 후 `/api/health` 확인
- `curl -X POST https://<render-service>.onrender.com/api/collect`
- 15분 무요청 시 슬립(Free 플랜). 다음 호출 시 30초+ 콜드스타트.

### 4. Netlify (frontend) 는 별도 프로젝트
- `netlify.toml` 에서 `/api/*` → Render 프록시. CORS 설정 불필요.
- `CORS_ORIGINS` 는 **직접 호출** 되는 경우에만 사용.

## 디렉토리 구조
```
backend/
├── app/
│   ├── main.py                 FastAPI 앱 생성·CORS·라우터·DB init
│   ├── config.py               pydantic-settings + YAML 로더
│   ├── time_utils.py           KST 시간 중앙화 (zoneinfo("Asia/Seoul"))
│   ├── schemas.py              Pydantic 응답 모델 (api-contract v1.6)
│   ├── scoring.py              점수+등급+체크리스트 (하드 필터 없음)
│   ├── parser.py               XML → Indicators (밴드/확정가/경쟁률/확약/유통/시장)
│   ├── store.py                SQLite + Turso 어댑터 (sync + HTTP pipeline)
│   ├── turso_adapter.py        /v2/pipeline 트랜잭션 버퍼
│   ├── collect.py              수집 파이프라인 (CLI 와 collect_service 공용)
│   ├── collect_service.py      백그라운드 수집(Thread + Lock + 상태 머신)
│   ├── dart_client.py          OpenDART httpx 래퍼 (throttle 0.4s)
│   ├── repository.py           store(row) → IpoDetail(점수 재계산)
│   ├── sample_data.py          개발용 샘플 (use_sample_data=True 일 때)
│   ├── config_files/scoring.yaml
│   └── routers/{health,ipos,scoring_config,collect}.py
├── tests/
│   ├── conftest.py             autouse — tmp DB·샘플모드·TURSO 비움
│   ├── test_scoring.py / test_parser.py / test_endpoints.py / test_collect_api.py / test_time_utils.py / test_turso_adapter.py / test_ipo_identification.py
│   └── fixtures/document_20261012000308.xml (디티에스 공시)
├── .env.example / .env.local(gitignored)
├── render.yaml                 Render Blueprint
├── requirements.txt
└── README.md
```

## 상태 (5종)
- `PENDING` — 수요예측 결과 미공시 (경쟁률 또는 공모가 위치 null)
- `PASS` — 총점 50 이상, S≥80 / A≥65 / B<65
- `REJECT` — 총점 50 미만 (점수 유지)
- `CORRECTION` — 정정 요청 공시 수신 후 발행조건확정 전 (판정 보류)
- `INCOMPLETE` — 필수 지표 다수 결측 (지시 #19)

## 알려진 미구현/제약
- `_MIGRATIONS` 리스트는 비어 있음 — 새 컬럼 추가 시 `("table","col","col TYPE")` 튜플만 추가하면 운영에도 자동 적용(DROP 금지)
- 유통가능·확약 테이블 파서는 서술형 패턴 다수 수용, 테이블 포맷 미지원 종목은 추가 fixture 로 확장 필요
