# recommend_ipo backend

DART 공시 기반 공모주 청약 추천 API. FastAPI + SQLite(예정).

> 지금은 **MVP 골격** 상태 — 모든 응답이 샘플 데이터이며, PENDING / PASS / REJECT 각 1건 이상을 포함한다. 실제 DART 수집·파싱은 조사 결과(`.claude/co-work/pm-answer-79cd21e2-...md`)를 바탕으로 다음 지시에서 붙인다.

## 필수 환경
- Python 3.11+ (3.12 권장)
- 패키지 설치는 `pip` 또는 `uv` 사용 가능

> Windows 에서 `python` 명령이 Microsoft Store 로 리다이렉트되는 경우: 공식 Python 설치 후 "Add python.exe to PATH" 체크, 또는 [python.org/downloads](https://www.python.org/downloads/) 에서 설치.

## 설치
```bash
cd backend
python -m venv .venv
source .venv/Scripts/activate       # Git Bash
# .\.venv\Scripts\Activate.ps1     # PowerShell
pip install -r requirements.txt
```

## 비밀값
- `backend/.env.local` 에 `DART_CERT_KEY=...` 를 둔다 (git 제외).
- 설정 로더는 pydantic-settings 가 `.env.local` 을 자동 로드한다.
- 로그·응답·협업 파일·커밋 어디에도 키 값을 출력하지 않는다.

## 실행
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```
- 포트 **8000**
- CORS 허용 Origin: `http://localhost:5173` (frontend Vite dev)
- OpenAPI 스펙: `http://localhost:8000/docs`

## 테스트
```bash
cd backend
pytest -q
```
- 샘플 데이터만 사용. 외부(DART) 호출은 없다.
- `tests/test_scoring.py` — 판정 로직(하드 필터·점수·등급·증거금)
- `tests/test_endpoints.py` — HTTP 엔드포인트 응답 형태·CORS

## 엔드포인트 (api-contract v0.1 반영)
| Method | Path | 요약 |
| --- | --- | --- |
| GET | `/api/health` | 상태 + 마지막 수집 시각 |
| GET | `/api/ipos` | 청약 예정 목록. query: `status`, `from`, `to` |
| GET | `/api/ipos/{id}` | 종목 상세. query: `shares` (기본 10) |
| GET | `/api/scoring-config` | 현재 적용 중인 판정 기준값 (하드 필터·점수·등급·증거금) |

## 디렉토리 구조
```
backend/
├── app/
│   ├── main.py              FastAPI 앱 생성·라우터 등록·CORS
│   ├── config.py            pydantic-settings + scoring.yaml 로더
│   ├── schemas.py           Pydantic 응답 모델 (api-contract 반영)
│   ├── scoring.py           하드 필터·점수·등급·증거금 계산
│   ├── sample_data.py       MVP 샘플 (PENDING/PASS/REJECT/예외통과)
│   ├── config_files/
│   │   └── scoring.yaml     판정 기준값 (코드 수정 없이 조정)
│   └── routers/
│       ├── health.py
│       ├── ipos.py
│       └── scoring_config.py
├── tests/
│   ├── conftest.py
│   ├── test_scoring.py
│   └── test_endpoints.py
├── .env.example
├── .env.local               (git 제외, DART_CERT_KEY)
├── .gitignore
├── requirements.txt
└── README.md
```

## 샘플 데이터 (디버그용)
| corp_code | 상태 | 설명 |
| --- | --- | --- |
| 00990001 | PENDING | 수요예측 전 — 지표 null, 증거금 null |
| 00990002 | PASS (S) | 경쟁률 2214:1, 상단 초과, 확약 38.5%, 유통 22%/구주 0% |
| 00990003 | REJECT | 경쟁률 612:1 하드 필터 미달 + 밴드 상단 미만 |
| 00990004 | PASS (B/A) | 예외 통과(경쟁률 1180:1, 신청 금액 6.1조) |

## 다음 작업
- DART 수집 파이프라인 (`list.json` + 보고서명 라우팅 → `estkRs` 정형 + `document.xml` 원문 파싱)
- SQLite 스키마 설계·마이그레이션
- `/api/scoring-config` 구조 검증 (frontend 요구에 맞춰 보완)
