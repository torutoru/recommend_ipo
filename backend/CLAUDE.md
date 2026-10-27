# backend 세션

루트 `../CLAUDE.md` 가 프로젝트 전체 규약(구조·협업·감시기·공통 규칙·연속 운영)을 담당한다. 이 파일은 **backend 전용 상세**만 적는다.

## 담당 영역
- 소유 워킹트리: `backend/` **만** (루트·`frontend/`·`.claude/` 는 열람만, 수정 금지)
- 책무: DART 수집·파싱, 판정 로직(점수·등급·체크리스트), FastAPI 엔드포인트, Turso/SQLite 저장소

## 스택과 실행
- Python 3.12 + FastAPI, Turso(/v2/pipeline, 운영) / SQLite(로컬·테스트)
- 포트: `:8000`
- CORS 허용: `http://localhost:5173` (frontend Vite dev)
- 실행·테스트 명령은 `backend/README.md` 참고

## 설정값 분리 (요구사항 1장 "설정 파일로 분리")
- 점수·등급·체크리스트 기준값은 **코드에 하드코딩하지 않는다**
- YAML 설정(`app/config_files/scoring.yaml`) + pydantic-settings 로 로드
- `/api/scoring-config` 엔드포인트가 현재 적용값을 그대로 반환
- (**균등 배정 최소 증거금은 제거됨 — 2026-10-20**)

## 비밀값
- DART 키: `backend/.env.local` 의 `DART_CERT_KEY` 에서만 읽는다
- pydantic-settings `env_file=".env.local"` 로 로더 구성
- Turso 변수(`TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`) 도 동일 경로
- `.env.example` 에 변수명만 적어 둔다 (값은 비움)
- 로그·응답·co-work 파일·커밋 어디에도 키 값을 출력하지 않는다

## API 값 규칙 (api-contract v1.6 반영)
- 미공시/파싱 실패 값은 `null`. 0 으로 채우지 않는다.
- 금액은 원(KRW) 정수, 비율은 0~100 퍼센트 숫자, 필드명 snake_case
- 에러 응답은 FastAPI 기본 `{ "detail": "메시지" }` 형식
- 체크리스트는 4항목 (`competition`, `price_position`, `lockup`, `flow`), 결과 3값 (`MET`, `NOT_MET`, `UNKNOWN`)

## 상태 (5종)
- `PENDING` — 수요예측 결과 미공시
- `PASS` — 총점 50 이상 (S≥80 / A≥65 / B)
- `REJECT` — 총점 50 미만 (점수 보유)
- `CORRECTION` — 정정 요청 공시 수신 후 발행조건확정 전 (판정 보류)
- `INCOMPLETE` — 필수 지표 다수 결측

## 저장소 (지시 #22·#29·#32·#43)
- 운영은 Turso HTTP pipeline, 로컬은 SQLite, 테스트는 임시 SQLite(`_force_tmp_sqlite_path`)
- 스키마 변경은 **ADD COLUMN 마이그레이션** 만 (DROP·DELETE 금지)
- COALESCE 패턴: 다운로드·파싱 실패 시 기존 값 보존
- 파생값(`price_position`, `demand_amount_krw`, `old_share_ratio`, `offering_amount_krw`)은 excluded 로 교체 (null 포함)
- `correction_requested_at`, `correction_amended_at` 도 excluded 로 교체 (지시 #32)
- `final_price` 는 **competition_rate 가 새·기존 모두 null 이면** excluded 값으로 교체 (지시 #43 — 가정문 오파싱 보존 방지)

## 수집 실패 정의 (지시 #56, requirements 27장)
- `failures` / `failed_count` 에는 **예상하지 못한 오류만** 집계 (timeout·5xx 반복, 본문이 있어야 할 공시가 ZIP 아님, 파싱 예외, DB 오류)
- 알려진 처리 상황은 실패가 아니다 (**본문 없는 공시 skip**, preserved 지표 보존, 비IPO·FSS 공지 제외)
- 014 가 다른 유형에서 나면 **"DART 014 파일 없음"** 처럼 **원인이 드러나는 문구**로 표기 (dart_client 가 자동 식별)

## 샘플 데이터 요구
- `use_sample_data=True` 시 `/api/ipos` 응답에 PENDING / PASS / REJECT 가 **각각 1건 이상**
- frontend 가 즉시 UI 를 붙일 수 있어야 한다

## 연속 운영 (중요)
- **매 /loop 사이클 시작 시 `ls .claude/co-work/backend-inquery-*` 로 미처리 inquery 전수 확인**. 감시기 알림만 믿지 않는다 — 지시 #40 가 알림 누락으로 놓치는 사례 발생(2026-10-21).
- 처리 완료된 inquery 는 같은 UUID 로 `pm-answer-{uuid}.md` 생성 → 그 UUID 는 미처리 목록에서 제외.
- 작업 시작·종료 시마다 `backend-status.md` 를 `date +%Y-%m-%dT%H:%M%z` 로 갱신.
- Monitor 는 30분 후 만료 — 재무장 전에 `ps -ef | grep watch-cowork` 로 좀비 확인.

## 변경 금지 영역
- `../CLAUDE.md`, `../.claude/co-work/PROTOCOL.md`, `../.claude/co-work/watch-cowork.sh`
- `../.claude/co-work/api-contract.md`, `../.claude/co-work/requirements.md`, `../.claude/co-work/WORKFLOW.md` (pm 소유)
- 수정 필요 시 → `pm-inquery-{uuid}.md` 로 협상
- **운영 로컬 DB**(`backend/data/recommend_ipo.sqlite`) 는 쓰기 금지 (`mtime: 90112 Oct 16 14:55` 보존)
