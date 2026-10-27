# recommend_ipo

DART 공시(투자설명서·정정 증권신고서·증권발행실적보고서)를 수집·분석해 공모주 청약 추천(점수 100점 만점 → PASS S·A·B 등급 / REJECT) 과 종목별 체크리스트를 보여주는 웹 서비스.

이 파일은 루트와 하위 폴더에서 실행되는 모든 세션(pm/backend/frontend)이 함께 읽는다. 역할별 상세는 각 폴더의 `CLAUDE.md`에 둔다.

> **새 세션은 먼저 [docs/HANDOFF.md](docs/HANDOFF.md)(전체 인계)와 자기 역할의 `backend/HANDOFF.md`·`frontend/HANDOFF.md`를 읽는다.** 지금까지의 결정·이력·함정·남은 일이 정리되어 있다. `.claude/co-work/`(git 제외)가 없는 환경이면 `docs/decisions/` 사본으로 복원한다.

## 구조
```
recommend_ipo/
├── CLAUDE.md, README.md
├── docs/ipo-checklist-and-scoring-guide.md  # 점수·체크리스트 정본 (사용자 작성)
├── docs/dart-ipo-analysis-logic.md       # 데이터 출처·지표 정의 (3장 점수 체계는 폐기)
├── backend/                          # FastAPI, Turso(운영·개발)/SQLite(테스트) — backend 세션 소유
│   └── .env.local                    # DART_CERT_KEY, 개발용 TURSO_* (git 제외, 값 출력 금지)
├── frontend/                         # React + Vite + TS — frontend 세션 소유
└── .claude/co-work/                  # 세션 간 협업 공유 폴더 (git 제외)
    ├── tools/daily_check.py          # pm 일일 원문 대조 스크립트
    └── daily-check/                  # 대조 리포트(YYYY-MM-DD.md)·스냅샷·원문 캐시(cache/{rcept_no}.txt)
```

## 3세션 협업
| 역할 | 실행 위치 | 담당 | 수정 가능 영역 |
| --- | --- | --- | --- |
| pm | 루트 | 요구사항·API 계약 확정, 작업 지시, 검증, 사용자 보고 | 루트 문서, `.claude/co-work/` |
| backend | `backend/` | DART 수집·파싱, 판정 로직, API | `backend/` |
| frontend | `frontend/` | 웹 UI | `frontend/` |

- 다른 역할의 영역은 **열람만** 한다. 수정이 필요하면 질문 파일로 요청한다.
- 규약 정본은 `.claude/co-work/PROTOCOL.md`다. `PROTOCOL.md`와 `watch-cowork.sh`는 수정하지 않는다.
- 질문 파일은 `{받는쪽}-inquery-{uuid}.md`, 답변 파일은 `{물어본쪽}-answer-{uuid}.md`(같은 uuid)로 만든다. 파일 첫머리에 `from:` / `to:` / `subject:`를 적고, 한 파일에는 한 주제만 담는다.
- 각자 메모장(`.claude/co-work/{역할}.md`)에 보낸 질문의 대기 상태와 결정 로그를 남긴다.
- 사실 조회는 상대 코드를 직접 읽어서 해결한다. 결정과 계약 협상만 파일로 왕복한다. 추측에는 "추측"이라고 표기한다.

### 운영상 주의 (실측된 사항)
- **세션 간 메시지(SendMessage)는 쓸 수 없다.** backend와 frontend 세션에는 해당 도구가 없다. 통신은 파일로만 하고, 급한 신호는 사용자를 통해 전달한다.
- **감시기**: `ROLE={역할} bash /c/workspace/recommend_ipo/.claude/co-work/watch-cowork.sh`
  - 감시기를 켜기 전에 이미 있던 파일은 프라이밍되어 알림이 오지 않는다. 세션을 시작하면 자기 이름으로 된 미처리 파일이 있는지 `ls`로 먼저 확인한다.
  - **감시기는 반드시 Monitor 도구로 띄운다.** Bash `run_in_background`나 `&`로 띄우면 무한 루프라서 종료 알림이 오지 않는다. 그러면 새 파일을 감지해도 세션이 깨어나지 않는다.
  - Monitor는 최대 30분 뒤 만료된다. 만료 알림을 받으면 다시 띄운다.
  - **만료되거나 세션을 종료해도 실제 감시 프로세스(`bash watch-cowork.sh`)는 고아로 남는다(실측).** 다시 띄우기 전에 기존 프로세스를 확인해서 직접 종료한다. 남아 있으면 같은 역할 감시기가 두 개가 된다.
  - **같은 역할의 감시기는 하나만 띄운다.** 같은 역할의 감시기들은 기록 파일(`%TEMP%\cowork-seen-{역할}`)을 함께 쓴다. 그래서 먼저 감지한 쪽이 기록해 버리면 나머지는 알리지 않는다. 다시 띄우기 전에 `ps -ef | grep watch-cowork`로 기존 감시기를 확인하고 종료한다.
  - 알림이 누락된 사례가 있으므로 답을 기다리는 동안 폴더를 직접 확인한다.
- **uuid 생성**: Git Bash에는 `/proc/sys/kernel/random/uuid`가 없다. `powershell -NoProfile -Command "[guid]::NewGuid().ToString()"`을 쓰고, 값이 비어 있지 않은지 확인한 뒤 파일을 만든다.

## 정본 문서 (작업 전 확인)
| 문서 | 내용 |
| --- | --- |
| `docs/ipo-checklist-and-scoring-guide.md` | **점수 체계·체크리스트 정본** — 35/25/20/20, S80·A65·B50, 50 미만 REJECT |
| `docs/dart-ipo-analysis-logic.md` | 데이터 출처(DART 문서 3종)·지표 정의. 3장(하드 필터·점수)은 폐기 |
| `.claude/co-work/requirements.md` | 명세의 빈칸과 모순을 pm이 확정한 문서. 판정 상태, 기준값 초안 |
| `.claude/co-work/api-contract.md` | backend↔frontend API 계약. 변경은 협상을 거쳐 pm이 반영한다 |
| `.claude/co-work/pm.md` | 진행 중인 지시와 결정 로그 (재개할 때 가장 먼저 읽는다) |

## 개발 시 지켜야 할 것
- **Python**: 3.12가 `C:\Users\CHO\AppData\Local\Programs\Python\Python312\python.exe`에 설치되어 있다. PATH에서 `python`을 부르면 Microsoft Store 스텁이 잡힐 수 있으니, 이 경로로 `backend/.venv`를 만들고 venv 안의 python을 쓴다.
- **배포 대상**: frontend는 Netlify(`/api/*`를 Render로 프록시), backend는 Render Free(슬립, 휘발성 디스크), DB는 Turso(HTTP pipeline API)다. 운영(Render)은 운영 Turso DB, 로컬 개발은 개발용 Turso DB(`backend/.env.local`)를 쓴다. 테스트는 항상 임시 SQLite를 쓰고 Turso에 붙지 않는다. 스키마 변경은 마이그레이션(ADD COLUMN)으로만 하고, DROP·삭제는 하지 않는다. 상세는 `requirements.md` 12장에 있다. 계정 생성과 배포 설정은 사용자가 하고, push는 pm이 검증 후 한다.
- **스택과 포트**: backend는 FastAPI, `:8000`. frontend는 Vite, `:5173`이며 `/api` 요청을 8000으로 proxy한다. backend는 CORS로 5173을 허용한다.
- **MVP 범위**: 종목 목록·달력, 상세(지표·점수·등급·근거·체크리스트 4항목·원문 링크·주관사·일정). 균등 배정 최소 증거금은 제거했다(2026-10-20). 알림, 로그인, 백테스트, 예상 수익 예측은 제외한다.
- **판정 상태**: 수요예측 결과(경쟁률·공모가 위치) 미공시면 `PENDING`, 총점 50 이상 `PASS`(S≥80·A≥65·B), 50 미만 `REJECT`(점수는 있음). 지표가 빠져 점수 범위가 50을 걸치면 `INCOMPLETE`(범위가 한쪽이면 PASS/REJECT 확정, `score_range`), 금감원 정정 요구 미제출·정정 후 효력 발생 전이면 `CORRECTION`. 하드 필터 없음. 상세에는 체크리스트 4항목(경쟁률·공모가 위치·확약·유통, 만족/불만족/미공시)을 함께 준다.
- **판정 기준값**(점수 구간·배점·등급·체크리스트 기준)은 `requirements.md` 3·4·9·19장이 정본이다. 경쟁률 대형주 보완 가산(공모 금액 1,000억 원 이상 + 경쟁률 800:1 이상 → +5, 최대 35)은 사용자 결정, 체크리스트 확약·유통 기준은 pm 해석이다. backend는 이 값을 `backend/app/config_files/scoring.yaml`로 분리하고, 코드에 하드코딩하지 않는다.
- **API 값 규칙**: 미공시 값이나 파싱 실패 값은 `null`로 둔다. 0으로 채우지 않는다. 금액은 원 단위 정수, 비율은 0~100 퍼센트, 필드명은 snake_case로 쓴다.
- **화면 고지**: 모든 화면에 "투자 권유가 아니며 참고용 정보"라는 고지를 표시한다.
- **비밀값**: DART 키는 `backend/.env.local`의 `DART_CERT_KEY`에만 둔다. 로그, 응답, co-work 파일, 커밋 어디에도 키 값을 쓰지 않는다. 루트 `.gitignore`가 `.env`와 `.env.*`를 제외한다(`.env.example`은 허용).
- **git 작업**: push는 pm이 검증(테스트·빌드·비밀값 점검)한 뒤 한다(사용자 위임). backend와 frontend는 커밋·푸시하지 않는다.

## 원문 파싱·검증 원칙 (2026-10-21 원문 대조에서 실측한 오류)
- **정정 신고서**는 서두 정정표에 '정정전'/'정정후' 블록이 번갈아 나와 옛 값과 새 값이 섞여 있다. 일정·밴드처럼 정정으로 바뀌는 값은 **본문("대표이사 등의 확인" 이후)**에서 읽는다.
- **가정·조건 문장**("확정공모가액이 N원 이상으로 결정되는 경우")과 **가치평가 표**(신주모집유입자금 등 금액), **부분값**("기존 주주의 유통가능 물량")은 지표로 쓰지 않는다. 첫 매치를 그대로 쓰지 말고 문맥을 확인한다.
- 원문 오타(예: `37,68%`)처럼 값이 이상하면 다른 서술이나 주식 수로 검산한다. 음수, 0~100을 벗어난 비율, 신주+구주≠총공모는 `null`로 둔다.
- 저장 시 COALESCE(새 값이 null이면 기존 값 유지)는 다운로드·파싱 실패에 대비한 장치다. 대신 한 번 잘못 저장된 값이 영구히 남을 수 있으므로, 서로 묶인 값(확정가는 경쟁률과 함께 생긴다)은 함께 갱신한다.
- 파서 회귀 테스트는 합성 문자열이 아니라 **실제 원문**(`daily-check/cache/`)으로 고정한다. pm은 push 전에 수정된 파서를 실제 원문 캐시에 직접 돌려 기대값을 확인한다. 테스트만 통과하고 실제 원문에서 회귀한 사례가 있었다(v23).
- pm은 매일 09:00 `tools/daily_check.py`로 운영 수집 → 전 종목 원문 대조 → 점수·체크리스트 독립 재계산을 돌리고, 불일치는 원문을 직접 확인해 실제 오류만 backend에 묶어 요청한다.

## 연속 운영 (`.claude/co-work/WORKFLOW.md`)
- 각 세션은 시작하면 `/loop 10m …`으로 스스로 주기적으로 깨어난다. 감시기 알림만 믿지 않는다.
- 작업 하나가 끝나면 pm 검증을 기다리지 않고 대기열의 다음 작업으로 넘어간다. 결정이 필요한 작업만 보류하고 질문한다.
- `.claude/co-work/{역할}-status.md`(updated, state, current, next, blocked_on)를 작업 시작·종료·loop마다 갱신한다. pm은 20분 이상 갱신이 없거나 blocked인 세션을 사용자에게 알린다.
- 권한 확인 창은 세션을 멈춘다. 사용자가 각 세션에서 `/fewer-permission-prompts`를 직접 실행한다. 세션이 권한 설정을 스스로 바꾸지 않는다.

## 재개 체크리스트
1. 자기 역할을 확인한다. 실행 위치나 사용자 안내로 판단한다.
2. `.claude/co-work/WORKFLOW.md`, `{역할}.md`, `{역할}-status.md`, `requirements.md`, `api-contract.md`를 읽는다.
3. `ls .claude/co-work/{역할}-*`로 미처리 질문과 답변을 확인한다.
4. 기존 감시 프로세스를 정리하고 감시기를 하나만 띄운다. 그다음 `/loop 10m` 사이클을 시작하고 대기열부터 이어서 진행한다.
