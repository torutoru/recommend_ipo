# recommend_ipo

DART 전자공시를 수집·분석해 공모주 청약 여부를 판단하도록 돕는 웹 서비스입니다.
종목마다 100점 만점 점수와 등급(PASS S·A·B / REJECT), 판정 근거, 체크리스트 4항목, 공모 일정, 원문 링크를 보여 줍니다.

> 투자 권유가 아니며 참고용 정보입니다. 모든 값은 DART 원문에서 자동으로 추출하므로 청약 전에 원문을 함께 확인하세요.

## 주요 기능
- **달력·목록**: 수요예측·확정공고·청약·상장 일정을 달력과 목록으로 보여 줍니다. 칩 색은 판정 등급별로 다릅니다.
- **상세**: 지표, 항목별 점수, 등급, 판정 근거, 체크리스트, 주관사, 일정, 기준 공시 원문 링크를 보여 줍니다.
- **수집**: 화면의 수집 버튼이나 `POST /api/collect`로 DART를 다시 조회합니다. 마지막 수집 시각을 표시합니다.

## 판정 기준
기준값은 [docs/ipo-checklist-and-scoring-guide.md](docs/ipo-checklist-and-scoring-guide.md)가 정본입니다. 코드에서는 [backend/app/config_files/scoring.yaml](backend/app/config_files/scoring.yaml)로 분리되어 있습니다.

| 항목 | 배점 | 기준 |
| --- | --- | --- |
| 기관 경쟁률 | 35 | 1,500:1 이상 35 · 1,000:1 이상 25 · 500:1 이상 15. 공모 금액 1,000억 원 이상이면서 800:1 이상이면 +5(최대 35) |
| 공모가 위치 | 25 | 밴드 초과 25 · 최상단 20 · 밴드 내 10 · 하단 미만 0 |
| 의무보유 확약 | 20 | 20% 이상 20 · 10% 이상 15 · 5% 이상 10 |
| 유통 물량 | 20 | 유통 25% 미만이고 구주매출 0%면 20 · 유통 35% 초과 또는 구주매출 30% 이상이면 0 · 그 외 12 |

등급은 S 80점 이상, A 65점 이상, B 50점 이상이고 50점 미만은 REJECT입니다.

| 상태 | 뜻 |
| --- | --- |
| `PENDING` 판정 대기 | 수요예측 결과(경쟁률·확정 공모가)가 아직 공시되지 않음 |
| `PASS` / `REJECT` | 총점으로 판정. 일부 지표가 없어도 가능한 점수 범위만으로 결과가 정해지면 확정 |
| `INCOMPLETE` 판정 보류 | 지표가 빠져 점수 범위가 50점을 걸침 |
| `CORRECTION` 정정 | 금감원 정정 요구 후 미제출이거나, 정정 제출 뒤 효력 발생 전(일정이 바뀔 수 있음) |

체크리스트는 경쟁률(1,000:1 좋음 · 1,500:1 아주 좋음), 공모가 최상단 이상, 확약 10% 이상, 유통 35% 이하이면서 구주매출 30% 미만의 4항목입니다.

## 데이터 출처
OpenDART의 공시 목록, 공시 원문, 인수인 정보 API만 씁니다. 원문 종류별 용도는 [docs/dart-ipo-analysis-logic.md](docs/dart-ipo-analysis-logic.md)에 정리되어 있습니다.
- 정정 증권신고서·투자설명서: 공모 일정, 희망 밴드, 공모 주식 수, 유통 가능 물량
- `[발행조건확정]` 정정 증권신고서: 기관 경쟁률, 확정 공모가, 의무보유 확약
- 증권발행실적보고서: 상장일, 시장 구분

## 구조와 배포
```
recommend_ipo/
├── backend/    FastAPI · Python 3.12 — DART 수집·파싱, 판정, API (Render)
├── frontend/   React · Vite · TypeScript — 웹 UI (Netlify)
└── docs/       점수 가이드, 데이터 출처·지표 정의
```
- **frontend**: Netlify에서 서비스합니다. `/api/*` 요청은 Render 백엔드로 프록시합니다([frontend/netlify.toml](frontend/netlify.toml)).
- **backend**: Render Free 플랜에서 돌고, `main`에 push하면 자동 배포됩니다. 요청이 없으면 슬립하므로 첫 요청이 느릴 수 있습니다. `GET /api/health`의 `parser_version`·`commit`으로 배포 버전을 확인합니다.
- **DB**: Turso(HTTP API)를 씁니다. 운영과 로컬 개발은 DB를 분리하고, 테스트는 임시 SQLite를 씁니다.

## 로컬 실행
backend 상세는 [backend/README.md](backend/README.md), frontend 상세는 [frontend/README.md](frontend/README.md)를 보세요.
```bash
# backend — backend/.env.local 에 DART_CERT_KEY 등 설정(git 제외)
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
.venv/Scripts/python -m pytest -q

# frontend — /api 를 localhost:8000 으로 프록시
cd frontend
npm install
npm run dev        # http://localhost:5173
```

## API
| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/api/health` | 상태, 마지막 수집 시각, `parser_version`, `commit` |
| GET | `/api/ipos` | 종목 목록(`status`, `from`, `to` 필터) |
| GET | `/api/ipos/{corp_code}` | 상세(지표·점수·근거·체크리스트·주관사·원문 링크) |
| GET | `/api/scoring-config` | 현재 판정 기준값 |
| POST | `/api/collect` | 수집 시작(202), 진행 중이면 409 |
| GET | `/api/collect/status` | 수집 진행 상태·결과 요약·실패 종목 |

미공시 값과 파싱 실패 값은 `null`로 줍니다(0으로 채우지 않음). 금액은 원 단위 정수, 비율은 0~100 퍼센트, 시각은 KST(+09:00)입니다.

## 품질 관리
- 매일 오전 운영 서버에서 수집한 뒤 전 종목의 일정·밴드·확정가·경쟁률·확약·유통 비율·점수·체크리스트를 DART 원문과 대조합니다.
- 불일치가 나오면 원문을 확인해 파서를 고치고, 실제 원문으로 회귀 테스트를 추가합니다.

## 비밀값
DART 인증키와 Turso 접속 정보는 `backend/.env.local`(로컬)과 Render 환경변수(운영)에만 둡니다. 저장소에는 변수 이름만 적힌 [backend/.env.example](backend/.env.example)만 있습니다.
