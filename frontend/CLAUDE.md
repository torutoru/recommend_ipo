# frontend 세션 안내

**새 세션은 먼저 `frontend/HANDOFF.md` 와 루트 `docs/HANDOFF.md` 를 읽는다.**

이 폴더에서 돌아가는 세션은 **frontend** 역할이며, 수정 가능 영역은 `frontend/` 아래뿐이다. backend·pm 영역은 열람만 하고, 수정이 필요하면 질문 파일로 요청한다.

## 요점

- 스택: React 18 + Vite 5 + TypeScript 5.5 strict, react-router-dom v6, PWA(vite-plugin-pwa 0.21.1).
- 포트: dev `:5173`(strictPort). `/api/*` → `http://localhost:8000` proxy.
- 테마: **항상 다크** — 모든 색은 `styles.css :root` 토큰. 하드코딩 금지.
- 목업↔실 API: `.env.*` 의 `VITE_USE_MOCK` 토글. 운영은 `false`.
- 커밋·push 는 **pm 담당**. frontend 는 코드 변경 후 `npm run build` 실측 로그를 답변에 첨부.
- 자세한 배경·함정·결정 로그: `frontend/HANDOFF.md`.

## 재개 체크리스트

1. 루트 `CLAUDE.md` 와 `frontend/HANDOFF.md`·`docs/HANDOFF.md` 읽기.
2. `.claude/co-work/requirements.md`·`api-contract.md`·`frontend.md`·`frontend-status.md` 읽기.
3. `ls .claude/co-work/frontend-*` 로 미처리 질문·답변 확인.
4. 기존 감시 프로세스 정리 후 Monitor 1개만 띄우기 (`ROLE=frontend bash .claude/co-work/watch-cowork.sh`).
5. 대기열의 다음 작업을 진행하거나 신규 inquery 를 기다림.
