# 인계 문서 (HANDOFF) — recommend_ipo

작성: 2026-10-27, pm 세션. 다음에 이 저장소에서 개발을 이어갈 세션이나 개발자가 **가장 먼저** 읽는 문서다.
역할별 상세는 [backend/HANDOFF.md](../backend/HANDOFF.md), [frontend/HANDOFF.md](../frontend/HANDOFF.md)에 있다.

## 1. 서비스 한눈에 보기
- DART 공시(증권신고서·투자설명서·증권발행실적보고서)를 수집·파싱해서 공모주마다 100점 만점 점수와 판정(PASS S·A·B / REJECT / 판정 대기 / 판정 보류 / 정정)을 매기고, 달력·목록·상세 화면으로 보여 준다.
- 사용자 1인 전용 서비스다. 로그인이 없고, 「내 공모주」도 인증 없이 서버 단일 목록으로 저장한다(사용자 결정).
- 배포 구성
  - frontend: Netlify, `main` push 시 자동 배포. `/api/*`는 Render로 프록시한다([frontend/netlify.toml](../frontend/netlify.toml)).
  - backend: Render Free(`recommend-ipo-api`), `main` push 시 자동 배포. 요청이 없으면 슬립하므로 첫 요청이 느리다.
  - DB: Turso(HTTP pipeline). 운영·개발 DB가 분리되어 있고 테스트는 임시 SQLite만 쓴다.
- 배포 확인: `GET https://recommend-ipo-api.onrender.com/api/health` 응답의 `parser_version`·`commit`으로 확인한다.
- 2026-10-27 기준 운영: `commit f5ed1c0`, `parser_version v36`, 31종목, 수집 실패 0, 원문 대조 실제 오류 0.

## 2. 문서 지도 (정본)
| 문서 | 내용 |
| --- | --- |
| [docs/ipo-checklist-and-scoring-guide.md](ipo-checklist-and-scoring-guide.md) | 점수·체크리스트 정본(사용자 작성) |
| [docs/dart-ipo-analysis-logic.md](dart-ipo-analysis-logic.md) | 데이터 출처·지표 정의(3장 점수 체계는 폐기) |
| [docs/decisions/requirements.md](decisions/requirements.md) | 사용자 결정 전체(1~27장). **정본은 `.claude/co-work/requirements.md`**(git 제외). 이 파일은 2026-10-27 스냅샷 |
| [docs/decisions/api-contract.md](decisions/api-contract.md) | backend↔frontend API 계약 v1.8. 정본은 `.claude/co-work/api-contract.md` |
| [docs/decisions/WORKFLOW.md](decisions/WORKFLOW.md) | 3세션 연속 운영 규칙 |
| [backend/app/config_files/scoring.yaml](../backend/app/config_files/scoring.yaml) | 판정 기준값(코드에 하드코딩 금지) |
| [tools/daily_check.py](../tools/daily_check.py) | 일일 운영 수집 + 전 종목 원문 대조 스크립트(사본. 실행본은 `.claude/co-work/tools/`) |

> `.claude/co-work/`는 git에서 제외된다. 새 PC나 새 클론에서는 `docs/decisions/` 사본으로 `.claude/co-work/`를 다시 만든다.

## 3. 판정 규칙 요약 (상세는 requirements 3·4·9·15·19장)
- 배점: 경쟁률 35 · 공모가 위치 25 · 확약 20 · 유통 20. 등급: S≥80, A≥65, B≥50, 50 미만 REJECT.
- 대형주 가산: 공모 금액 1,000억 원 이상 **그리고** 경쟁률 800:1 이상이면 +5(최대 35).
- 상태
  - `PENDING`: 수요예측 결과([발행조건확정] 공시)가 아직 없음.
  - `INCOMPLETE`: 지표가 비어 점수 범위가 50을 걸침. 범위가 한쪽에 있으면 PASS/REJECT로 확정(`score_range`).
  - `CORRECTION`: 정정 요구 미제출이거나 정정 후 효력 발생 전.
- 확약 비율은 **수요예측 신청 수량 기준**이다(사용자 결정, 배정 기준 아님).
- 체크리스트는 4항목이다(경쟁률 1,000:1 좋음 / 1,500:1 아주 좋음, 공모가 최상단 이상, 확약 10% 이상, 유통 35% 이하이면서 구주 30% 미만). 증거금 기능은 없앴다.
- 상장일은 **증권발행실적보고서에서만** 가져온다(보통 상장 6~7일 전 제출). KIND는 쓰지 않기로 했다(10/26 결정).

## 4. 지금까지 한 일 (2026-10-16 ~ 10-27)
| 시기 | 주요 작업 |
| --- | --- |
| 10/16 | MVP(목록·상세·점수), 수집 API, Render·Netlify·Turso 연결(HTTP pipeline 어댑터) |
| 10/19 | 판정 보류·정정 상태, 확정공고일·수요예측 기간, 상장일·시장(실적보고서), 데이터 보호, 점수 범위 판정 |
| 10/20 | 달력 칩 규칙(우선순위·색·회사명만), 주관사(estkRs 교차검증), 체크리스트 4항목·증거금 제거, `/api/health`에 버전·커밋, 연속 운영(WORKFLOW) |
| 10/21 | **원문 대조 체계 도입**(매일 09:00). 파싱 오류 대량 수정(정정전/정정후 블록, 가정문, 평가표, 부분 유통, 쉼표 소수점), DART 키 노출 경로 차단, 저장 정책을 "정상 파싱이면 교체"로 변경 |
| 10/22 | 래블업 "경쟁률(주2)" 각주 라벨, 영광 부분 유통값(6.75%→31.75%) 수정 |
| 10/23 | 항상 다크 모드, 상장 칩 금색·판정 보류 보라 |
| 10/27 | 「내 공모주」(holdings API·화면·상장 배너·달력 ★), PWA(설치·오프라인·업데이트 토스트), 모바일 입력 확대 방지, 증분 수집 2단계(v34), 비IPO 45행 삭제, [첨부정정] 처리, 실패 정의 정리, 상세 「데이터 안내」(data_notes), 달력 "(청약)" 접두 |

전체 커밋은 `git log`에서 볼 수 있다(61개, 커밋 메시지에 이유를 적어 두었다).

## 5. 반드시 알아야 할 함정과 교훈
**원문 파싱 (가장 많이 틀린 곳)**
- 정정 신고서 앞부분의 정정표에는 '정정전'/'정정후' 블록이 섞여 있다. 일정·밴드·유통처럼 정정되는 값은 **본문("대표이사 등의 확인" 이후)**에서 읽는다.
- 다음 값들은 지표로 쓰면 안 된다.
  - 가정 문장("확정공모가액이 N원 이상으로 결정되는 경우")
  - 가치평가 표의 금액(신주모집유입자금)
  - 특정 주주의 부분값("벤처금융 보유분 610,800주(6.75%)")
- 같은 항목에 후보가 여럿이면 문맥과 주식 수로 검산한다.
- 표 라벨에 각주가 붙는 경우가 있다("경쟁률(주2)"). 원문 오타도 있다("37,68%").
- **회귀 테스트는 실제 원문으로 한다.** 합성 문자열 테스트는 통과했는데 실제 원문에서 회귀한 사례가 있다(v23).
- push 전에는 수정된 파서를 원문 캐시(`.claude/co-work/daily-check/cache/`) 전체에 돌려서, 이전 버전과 결과 차이를 비교한다.

**수집**
- 증분 수집은 2단계다(v34).
  1. 새 종목 발견은 `pblntf_detail_ty=C001`(지분증권 신고서)만 사용한다.
  2. 전 유형 조회 결과는 **이미 DB에 있는 종목**에만 받아들인다. 실적보고서는 이 경로로 들어온다.
- 전 유형을 그대로 받으면 펀드·증권사 공시가 IPO로 유입된다. 실제로 v33에서 45개사가 들어와 revert했다.
- [첨부정정] 공시는 본문 원문이 없어서 DART가 014를 응답한다. 기준 공시에서 제외한다.
- 금감원 공지(접수번호 9~10번째 자리가 "10")는 메타데이터로만 쓰고 원문은 내려받지 않는다.
- `PARSER_VERSION`을 올리면 다음 수집에서 전 종목을 재처리한다. 파서나 추출 로직을 바꾸면 반드시 올린다.
- **"실패"는 예상하지 못한 오류만 센다.** 알려진 처리 상황은 실패로 세지 않고, 종목 상세의 `data_notes`로만 보여 준다(requirements 27장).
- 저장 정책: 정상적으로 파싱하면 값을 교체한다(null 포함). 다운로드나 파싱이 실패하면 기존 값을 유지한다. 상장일·시장·주관사는 별도 출처라서 기존 값을 유지한다.

**운영·보안**
- 운영 DB는 Render 환경변수로만 접속한다. backend 세션은 운영 DB에 직접 쓰지 않는다.
- 운영 데이터를 고칠 일이 있으면 기동 시 한 번 실행되는 정리 코드로 처리한다. 예: [backend/app/maintenance.py](../backend/app/maintenance.py). 이 파일은 다음 릴리스에서 제거할 예정이다.
- DART 키가 HTTP 오류 메시지(URL)에 섞여 저장될 수 있다. 오류 문자열은 항상 `security.mask_secrets`를 거친다.
- 운영 빌드에서 개발용 코드(`?demo=listing`, `?demo=update`)가 빠졌는지 `dist/`를 grep해서 확인한다.

**협업 운영**
- 세션 간 통신은 `.claude/co-work/` 파일로만 한다. 감시기(watch-cowork.sh)는 Monitor로 띄우고, 30분마다 만료되며, 고아 프로세스가 남는다.
- inquery를 보낸 **뒤에** 내용을 덧붙이면 상대가 이미 답변을 쓴 뒤라 누락된다(#34, #55에서 실제로 발생). 추가 요청은 새 inquery로 보낸다.
- pm 세션은 하나만 띄운다. 두 개가 떠서 요청 번호가 겹친 적이 있다.
- PC가 절전에 들어가면 `/loop`, 예약 작업, 감시기가 모두 멈춘다. 세션 상태는 상태 파일의 **수정 시각**으로 판단한다(파일 안의 updated 값은 틀린 적이 있다).
- 예약 작업(CronCreate)은 세션 안에서만 살아 있고 7일 뒤 만료된다. 현재 일일 대조 `b8644753`, 10분 사이클 `65e13080`은 11/3에 만료된다.

## 6. 남은 일·알려진 한계
- `backend/app/maintenance.py`(비IPO 45행 삭제 코드)는 이미 실행됐다. 다음 배포 때 제거한다.
- `data_notes`는 [첨부정정]만 다룬다. "기준 공시 없음(preserved)" 안내는 아직 구현하지 않았다.
- 검증 스크립트의 정규식 한계 3건이 매일 표시된다. 엘리스·티앤이코리아 확약(표 형식), SimwonAmericaCorp 청약일(해외 기업)이다. 값 자체는 원문에서 확인했다.
- 확약 집계의 100만 주 미만 셀 필터(#45 ②-7), Turso 트랜잭션 원자성(②-6)은 점검만 하고 수정하지 않았다(지금까지 실제 영향 없음).
- 티앤이코리아 유통 31.27%(본문 31.29%)는 같은 점수 구간이라 그대로 두었다.
- 「내 공모주」는 인증이 없다. 사이트 주소를 아는 사람은 보고 고칠 수 있다(사용자가 수용).
- 푸시 알림, 로그인, 백테스트, 수익 예측, 매도·수익률 기록은 범위 밖이다.

## 7. 새 세션 시작 순서
1. 이 문서, [CLAUDE.md](../CLAUDE.md), 자기 역할의 `HANDOFF.md`를 읽는다.
2. `.claude/co-work/`가 없으면 `docs/decisions/` 사본으로 다시 만든다(requirements.md, api-contract.md, WORKFLOW.md, `tools/daily_check.py` → `.claude/co-work/tools/`).
3. `/api/health`로 운영 버전을 확인하고, `tools/daily_check.py --no-collect`로 현재 운영 데이터를 원문과 대조한다.
4. pm이면 일일 대조(매일 09:00)와 10분 사이클 예약을 다시 등록한다.
