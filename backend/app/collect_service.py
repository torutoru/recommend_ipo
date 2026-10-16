"""백그라운드 수집 서비스 (requirements 11장 + api-contract v0.5).

- POST /api/collect 가 호출하면 Thread 하나로 수집을 돌리고, 상태는 인메모리로 관리.
- 동시에 하나만 실행(threading.Lock). 중복 호출 → 409.
- 증분 로직:
    조회 시작일 = (last_collected_at - overlap_days) 또는 (최초면 initial_days 전)
    조회 끝일   = 오늘
    DB 에 없는 접수번호만 신규 → 종목에 새 공시가 있으면 재파싱·재판정.
    철회신고서 발견 → mark_withdrawn (종목 제외).
    변화 없는 종목은 건드리지 않음.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Optional

from . import collect as collect_mod
from . import dart_client, store
from .config import get_settings
from .parser import parse
from .schemas import CollectProgress, CollectStatus, CollectSummary
from .time_utils import KST, kst_days_ago, now_iso_kst, now_kst


_lock = threading.Lock()
_state: dict = {
    "status": "IDLE",
    "started_at": None,
    "finished_at": None,
    "progress": None,
    "summary": None,
    "error": None,
}
_state_lock = threading.Lock()


def current_status() -> CollectStatus:
    with _state_lock:
        s = dict(_state)
    return CollectStatus(
        status=s["status"],
        started_at=s["started_at"],
        finished_at=s["finished_at"],
        progress=s["progress"],
        summary=s["summary"],
        error=s["error"],
        last_collected_at=store.last_collected_at(),
    )


def _set(**kw) -> None:
    with _state_lock:
        _state.update(kw)


def is_running() -> bool:
    with _state_lock:
        return _state["status"] == "RUNNING"


def try_start() -> tuple[bool, CollectStatus]:
    """(실행 시작 여부, 현재 상태). 이미 실행 중이면 (False, 현재 상태)."""
    if not _lock.acquire(blocking=False):
        return False, current_status()
    now = now_iso_kst()
    _set(
        status="RUNNING",
        started_at=now,
        finished_at=None,
        progress=CollectProgress(done=0, total=None),
        summary=CollectSummary(),
        error=None,
    )
    thread = threading.Thread(target=_run_safely, name="collect-worker", daemon=True)
    thread.start()
    return True, current_status()


# ---------- 실제 수집 ----------

def _date_range() -> tuple[str, str]:
    """YYYYMMDD(KST 기준) 포맷의 (bgn_de, end_de).

    마지막 성공 시각 - overlap_days(최초면 initial_days 전) ~ 오늘(KST).
    Render 가 UTC 라도 조회 범위는 서울 날짜로 통일.
    """
    s = get_settings()
    end = now_kst()
    last = store.last_collected_at()
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=KST)
            bgn = last_dt.astimezone(KST) - timedelta(days=s.incremental_overlap_days)
        except ValueError:
            bgn = kst_days_ago(s.initial_days)
    else:
        bgn = kst_days_ago(s.initial_days)
    fmt = "%Y%m%d"
    return bgn.strftime(fmt), end.strftime(fmt)


def _fetch_list(bgn: str, end: str) -> list[dict]:
    all_items: list[dict] = []
    page_no = 1
    while True:
        resp = dart_client.list_disclosures(
            bgn_de=bgn, end_de=end,
            pblntf_detail_ty="C001",
            last_reprt_at="N",
            page_count=100,
            page_no=page_no,
        )
        if resp.get("status") == "013":  # 조회 결과 없음
            break
        if resp.get("status") != "000":
            raise RuntimeError(
                f"OpenDART list.json 실패 (status={resp.get('status')})"
            )
        all_items.extend(resp.get("list", []))
        total_page = int(resp.get("total_page") or 1)
        if page_no >= total_page:
            break
        page_no += 1
    return all_items


def _run_safely() -> None:
    try:
        _run()
    except Exception as e:  # 전역 실패
        msg = _sanitize_error(e)
        _set(
            status="FAILED",
            finished_at=now_iso_kst(),
            error=msg,
        )
    finally:
        try:
            _lock.release()
        except RuntimeError:
            pass


def _run() -> None:
    store.init_db()
    bgn, end = _date_range()
    disclosures = _fetch_list(bgn, end)

    # 기존 접수번호 집합 — 신규 판별
    with store.connect() as conn:
        known = store.known_rcept_nos(conn)
        run_id = store.start_collect_run(conn, days=(datetime.strptime(end, "%Y%m%d") - datetime.strptime(bgn, "%Y%m%d")).days)
        existing_corp_codes = {
            r["corp_code"] for r in conn.execute(
                "SELECT corp_code FROM ipos WHERE withdrawn_rcept_no IS NULL"
            )
        }

    # IPO 후보 그룹핑
    grouped = collect_mod.group_by_corp(disclosures)
    total_disclosures = sum(len(v) for v in grouped.values())
    _set(progress=CollectProgress(done=0, total=total_disclosures))

    summary = CollectSummary()
    done = 0

    for corp_code, items in grouped.items():
        try:
            new_items = [it for it in items if it["rcept_no"] not in known]
            if not new_items:
                # 완전히 새로운 공시가 없다 — unchanged
                if corp_code in existing_corp_codes:
                    summary.unchanged_count += 1
                continue

            # 철회신고서가 포함되면 종목 제외
            if any(collect_mod.classify_report(x.get("report_nm", "")) == "WITHDRAWN" for x in items):
                with store.connect() as conn:
                    for w in items:
                        if collect_mod.classify_report(w.get("report_nm", "")) == "WITHDRAWN":
                            store.mark_withdrawn(conn, corp_code, w["rcept_no"])
                            break
                summary.withdrawn_count += 1
                continue

            is_new = corp_code not in existing_corp_codes
            collect_mod.process_corp(corp_code, items, log=[])
            if is_new:
                summary.new_count += 1
            else:
                summary.updated_count += 1
        except Exception as e:  # 종목 단위 오류 격리
            summary.failed_count += 1
            _ = _sanitize_error(e)
        finally:
            # continue/정상/예외 모두 여기 한 번만 가산
            done += len(items)
            _set(progress=CollectProgress(done=done, total=total_disclosures),
                 summary=summary)

    # 완료
    with store.connect() as conn:
        store.finish_collect_run(
            conn, run_id,
            collected=summary.new_count + summary.updated_count,
            errors=summary.failed_count,
            note=f"bgn={bgn} end={end} new={summary.new_count} updated={summary.updated_count} "
                 f"unchanged={summary.unchanged_count} failed={summary.failed_count} withdrawn={summary.withdrawn_count}",
        )
    _set(
        status="SUCCEEDED",
        finished_at=now_iso_kst(),
        summary=summary,
        progress=CollectProgress(done=done, total=total_disclosures),
    )


# ---------- 보안: 에러 메시지에서 키·내부 경로 제거 ----------

def _sanitize_error(e: Exception) -> str:
    msg = f"{type(e).__name__}: {e}"
    key = get_settings().dart_cert_key
    if key:
        msg = msg.replace(key, "***")
    collect_key = get_settings().collect_key
    if collect_key:
        msg = msg.replace(collect_key, "***")
    # Windows/Linux 경로 토큰 제거
    import re
    msg = re.sub(r"[A-Za-z]:[\\/][^\s'\"]+", "<path>", msg)
    msg = re.sub(r"/[^\s'\"]*/[^\s'\"]+", "<path>", msg)
    return msg[:500]


# 테스트용 리셋
def _reset_for_tests() -> None:
    global _lock
    with _state_lock:
        _state.update({
            "status": "IDLE",
            "started_at": None,
            "finished_at": None,
            "progress": None,
            "summary": None,
            "error": None,
        })
    _lock = threading.Lock()
