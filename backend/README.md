# recommend_ipo backend

DART 공시 기반 공모주 청약 추천 API. FastAPI + SQLite(로컬) / Turso(운영).

## 필수 환경
- Python 3.11+ (3.12 권장)
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
| `CORS_ORIGINS` | 선택 | CSV, 기본 `http://localhost:5173` (Vite dev). 운영에서는 Netlify 도메인 추가 |
| `TURSO_DATABASE_URL` | 운영 | 설정되면 Turso 사용(현재 어댑터 미구현 — 로컬 SQLite 전용). 로컬·테스트는 비워 둘 것 |
| `TURSO_AUTH_TOKEN` | 운영 | 상동 |
| `COLLECT_KEY` | 선택 | 설정되면 `POST /api/collect` 는 `X-Collect-Key` 헤더 요구(상수 시간 비교). 미설정이면 보호 없음 |

- 테스트는 `tests/conftest.py` 가 **모든 테스트에서 운영 경로·Turso 변수를 비움** — 환경에 뭐가 있어도 안전.

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
# 110 passed
```
- autouse fixture 로 각 테스트가 tmp SQLite 를 쓰고 use_sample_data=True / TURSO_* = "" 를 강제.
- 운영 DB(`data/recommend_ipo.sqlite`) 는 테스트 영향 없음.

## 엔드포인트 (api-contract v0.7)
| Method | Path | 요약 |
| --- | --- | --- |
| GET  | `/api/health` | 상태 + 마지막 수집 시각(KST) |
| GET  | `/api/ipos` | 목록. `status`, `from`, `to`(겹침 로직) |
| GET  | `/api/ipos/{id}` | 상세. `shares`(기본 10) |
| GET  | `/api/scoring-config` | 판정 기준값 |
| POST | `/api/collect` | 수집 시작(202) · 중복 409 · 샘플 모드 409 · 키 오류 401 |
| GET  | `/api/collect/status` | 상태 머신 폴링 |

응답 시각은 모두 ISO 8601 **+09:00(KST)**. Render(UTC) 에서도 보장.

## Render 배포 절차 (requirements 12장)

### 1. Turso DB 생성 (사용자가)
1. https://turso.tech/ 가입, CLI 설치: `brew install tursodatabase/tap/turso` (또는 OS 별 방법)
2. `turso db create recommend-ipo` → DB URL 획득
3. `turso db tokens create recommend-ipo` → 토큰 획득
4. **스키마 적용**: `turso db shell recommend-ipo < app/schema.sql`
   (현재는 `app/store.py:SCHEMA` 를 참조. 필요 시 `python -c "from app.store import SCHEMA; print(SCHEMA)" > schema.sql` 로 추출)

### 2. Render Blueprint 등록 (사용자가)
1. 레포를 Render 에 연결 (`https://render.com/`)
2. "New +" → "Blueprint" → `backend/render.yaml` 자동 감지
3. 환경변수 **값 입력**:
   - `DART_CERT_KEY` — OpenDART 발급 키
   - `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN` — 위 1 결과
   - `CORS_ORIGINS` — 예: `https://<netlify-site>.netlify.app`
   - (선택) `COLLECT_KEY` — frontend 수집 버튼 보호용. 현재 사용 안 함

### 3. 첫 수집
- 배포 완료 후 Render 콘솔에서 health check 통과 확인: `curl https://<render-service>.onrender.com/api/health`
- 첫 수집 요청: `curl -X POST https://<render-service>.onrender.com/api/collect`
- 15분 무요청 시 슬립(Free 플랜). 다음 호출 시 30초+ 콜드스타트 → `/api/health` 응답에 지연이 생길 수 있음

### 4. Netlify (frontend) 는 별도 프로젝트
- `netlify.toml` 에서 `/api/*` → `<render-service>` 프록시. CORS 설정 불필요(같은 오리진으로 보임)
- `CORS_ORIGINS` 는 **직접 호출** 되는 경우에만 사용

## 디렉토리 구조
```
backend/
├── app/
│   ├── main.py                 FastAPI 앱 생성·CORS·라우터·DB init
│   ├── config.py               pydantic-settings + YAML 로더 + use_turso()
│   ├── time_utils.py           KST 시간 중앙화 (zoneinfo("Asia/Seoul"))
│   ├── schemas.py              Pydantic 응답 모델 (api-contract v0.7)
│   ├── scoring.py              하드필터 없음, 점수+등급+체크리스트
│   ├── parser.py               XML → Indicators (밴드/확정가/경쟁률/확약/유통/시장)
│   ├── store.py                SQLite 저장소 + 마이그레이션 (Turso 어댑터 미구현)
│   ├── collect.py              수집 파이프라인 (CLI 와 collect_service 공용)
│   ├── collect_service.py      백그라운드 수집(Thread + Lock + 상태 머신)
│   ├── dart_client.py          OpenDART httpx 래퍼 (throttle 0.4s)
│   ├── repository.py           store(row) → IpoDetail(점수 재계산)
│   ├── sample_data.py          개발용 샘플 (use_sample_data=True 일 때)
│   ├── config_files/scoring.yaml
│   └── routers/{health,ipos,scoring_config,collect}.py
├── tests/
│   ├── conftest.py             autouse — tmp DB·샘플모드·TURSO 비움
│   ├── test_scoring.py / test_parser.py / test_endpoints.py / test_collect_api.py / test_time_utils.py
│   └── fixtures/document_20261012000308.xml (디티에스 공시)
├── .env.example / .env.local(gitignored)
├── render.yaml                 Render Blueprint
├── requirements.txt
└── README.md
```

## 알려진 미구현
- **Turso 어댑터**: `TURSO_DATABASE_URL`·`TURSO_AUTH_TOKEN` 설정 시 `store.connect()` 가 명시적으로 `RuntimeError` — `libsql-client` 가 async-first 라서 sync FastAPI 와 어댑터 작업이 별도 라운드 필요. 현재는 로컬 SQLite 전용.
- 유통가능·확약 테이블 파서는 디티에스·엠에스바이오 기준 추출 성공, 다른 종목 포맷은 추가 fixture 로 확장 필요
- `_MIGRATIONS` 리스트는 비어 있음 — 새 컬럼 추가 시 `("table","col","col TYPE")` 튜플만 추가하면 운영에도 자동 적용(DROP 금지)
