# backend 세션

루트 `../CLAUDE.md` 가 프로젝트 전체 규약(구조·협업·감시기·공통 규칙)을 담당한다. 이 파일은 **backend 전용 상세**만 적는다.

## 담당 영역
- 소유 워킹트리: `backend/` **만** (루트·`frontend/`·`.claude/` 는 열람만, 수정 금지)
- 책무: DART 수집·파싱, 판정 로직(하드 필터·점수·등급·증거금), FastAPI 엔드포인트, SQLite 저장소

## 스택과 실행
- Python + FastAPI, SQLite
- 포트: `:8000`
- CORS 허용: `http://localhost:5173` (frontend Vite dev)
- 실행 명령 / 테스트 명령은 구현 완료 시 `backend/README.md` 에 기록한다

## 설정값 분리 (요구사항 1장 "설정 파일로 분리")
- 하드 필터·점수·등급·증거금 계산 상수는 **코드에 하드코딩하지 않는다**
- YAML 또는 TOML 설정 파일로 분리하고 pydantic-settings 로 로드
- `/api/scoring-config` 엔드포인트가 현재 적용값을 그대로 반환

## 비밀값
- DART 키: `backend/.env.local` 의 `DART_CERT_KEY` 에서만 읽는다
- pydantic-settings `env_file=".env.local"` 로 로더 구성
- `.env.example` 에 변수명만 적어 둔다 (값은 비움)
- 로그·응답·co-work 파일·커밋 어디에도 키 값을 출력하지 않는다

## API 값 규칙 (api-contract 반영)
- 미공시/파싱 실패 값은 `null`. 0 으로 채우지 않는다.
- 금액은 원(KRW) 정수, 비율은 0~100 퍼센트 숫자, 필드명 snake_case
- 에러 응답은 FastAPI 기본 `{ "detail": "메시지" }` 형식

## 샘플 데이터 요구 (지시 #1-B)
- `/api/ipos` 응답에 PENDING / PASS / REJECT 가 **각각 1건 이상**
- frontend 가 즉시 UI 를 붙일 수 있어야 한다

## 변경 금지 영역
- `../CLAUDE.md`, `../.claude/co-work/PROTOCOL.md`, `../.claude/co-work/watch-cowork.sh`
- `../.claude/co-work/api-contract.md`, `../.claude/co-work/requirements.md` (pm 소유)
- 수정 필요 시 → `pm-inquery-{uuid}.md` 로 협상
