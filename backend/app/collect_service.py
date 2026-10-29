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
from typing import Any, Optional

from . import collect as collect_mod
from . import dart_client, store
from .config import get_settings
from .parser import parse
from .schemas import (
    CollectCorpEntry,
    CollectCorps,
    CollectFailure,
    CollectProgress,
    CollectStatus,
    CollectSummary,
)
from .time_utils import KST, kst_days_ago, now_iso_kst, now_kst


_lock = threading.Lock()
_state: dict = {
    "status": "IDLE",
    "started_at": None,
    "finished_at": None,
    "progress": None,
    "summary": None,
    "corps": None,   # v1.9 (지시 #59): 가장 최근 수집의 분기별 종목 목록
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
        failures=s.get("failures") or [],
        corps=s.get("corps"),   # v1.9 (지시 #59)
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
        failures=[],
        corps=CollectCorps(),   # v1.9 (지시 #59): 이번 수집 분기별 목록 초기화
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


def _fetch_list(
    bgn: str, end: str,
    corp_code: Optional[str] = None,
    pblntf_detail_ty: Optional[str] = "C001",
) -> list[dict]:
    """OpenDART 공시 전체(pagination). corp_code 가 주어지면 그 종목만 조회(#24).
    pblntf_detail_ty=None 이면 유형 필터 없이 조회(#17 수정: 금감원 요구 공지 포함)."""
    all_items: list[dict] = []
    page_no = 1
    while True:
        resp = dart_client.list_disclosures(
            bgn_de=bgn, end_de=end,
            pblntf_detail_ty=pblntf_detail_ty,
            last_reprt_at="N",
            page_count=100,
            page_no=page_no,
            corp_code=corp_code,
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


def _fetch_corp_history(corp_code: str) -> list[dict]:
    """지시 #24: 종목의 전체 공시 이력(최근 full_history_days 일) 조회.

    증분 범위 안 문서만 보면 발행조건확정이 과거라 빠지고 ISSUANCE_REPORT 만 보여서 지표가 null 로
    바뀌는 사고 방지. corp_code 를 OpenDART list.json 에 넘겨 그 종목만 받아 온다.
    지시 #17 수정: 유형 필터 없이 조회 — "정정신고서제출요구( ... )" 공지도 포함.
    """
    s = get_settings()
    end = now_kst()
    bgn = end - timedelta(days=s.full_history_days)
    fmt = "%Y%m%d"
    return _fetch_list(bgn.strftime(fmt), end.strftime(fmt),
                       corp_code=corp_code, pblntf_detail_ty=None)


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

    # 기존 접수번호 집합 — 신규 판별 (조회 전략 결정에 필요하므로 먼저 로드)
    # parser_version 이 현재 코드 버전과 다른 종목은 "변화 없음" 분기에서 빼내 재파싱 (지시 #16)
    with store.connect() as conn:
        known = store.known_rcept_nos(conn)
        run_id = store.start_collect_run(conn, days=(datetime.strptime(end, "%Y%m%d") - datetime.strptime(bgn, "%Y%m%d")).days)
        existing_corp_codes = set()
        stale_corp_codes = set()
        for r in conn.execute(
            "SELECT corp_code, parser_version FROM ipos WHERE withdrawn_rcept_no IS NULL"
        ):
            existing_corp_codes.add(r["corp_code"])
            if (r["parser_version"] or "") != collect_mod.PARSER_VERSION:
                stale_corp_codes.add(r["corp_code"])

    # 지시 #53: 2단계 조회 전략.
    # 1) 메인 조회는 C001(지분증권 증권신고서) — 신규 corp 를 **IPO 후보로만 발견** (펀드·SPAC·채권 유입 방지).
    # 2) 기존 종목(existing_corp_codes) 에 한해 전 유형 조회 — 증권발행실적보고서 등 수용 (이에스티 사례).
    disclosures = _fetch_list(bgn, end)   # pblntf_detail_ty="C001" 기본값
    if existing_corp_codes:
        full_disclosures = _fetch_list(bgn, end, pblntf_detail_ty=None)
        seen_rcept = {d.get("rcept_no") for d in disclosures}
        for d in full_disclosures:
            if (
                d.get("corp_code") in existing_corp_codes
                and d.get("rcept_no") not in seen_rcept
                and collect_mod.classify_report(d.get("report_nm", "")) is not None
            ):
                disclosures.append(d)
                seen_rcept.add(d.get("rcept_no"))

    # IPO 후보 그룹핑
    grouped = collect_mod.group_by_corp(disclosures)
    # 지시 #35 pm 추가: 메인 루프에도 is_ipo_candidate 완화 — 상장 완료된 **기존 종목**의 증분 공시도 포함.
    # group_by_corp 는 is_ipo_candidate 로 필터 → 엘리스처럼 상장 후 corp_cls='K' 종목이 빠짐.
    # DB 에 있던 종목이면 분류 가능한 공시는 재파싱 대상으로 추가.
    for d in disclosures:
        corp_code = d.get("corp_code")
        if not corp_code or corp_code not in existing_corp_codes:
            continue
        if collect_mod.classify_report(d.get("report_nm", "")) is None:
            continue
        bucket = grouped.setdefault(corp_code, [])
        if not any(it.get("rcept_no") == d.get("rcept_no") for it in bucket):
            bucket.append(d)
    for cc in grouped:
        grouped[cc].sort(key=lambda it: it.get("rcept_dt", ""))
    total_disclosures = sum(len(v) for v in grouped.values())
    _set(progress=CollectProgress(done=0, total=total_disclosures))

    summary = CollectSummary()
    failures: list[CollectFailure] = []
    corps = CollectCorps()   # v1.9 (지시 #59)
    done = 0

    def _add_failure(corp_code: str, corp_name: str, reason: str) -> None:
        reason = _sanitize_error_text(reason)
        failures.append(CollectFailure(corp_code=corp_code, corp_name=corp_name, reason=reason))
        corps.failed.append(CollectCorpEntry(corp_code=corp_code, corp_name=corp_name))

    def _add_corp(bucket: str, corp_code: str, corp_name: str) -> None:
        """v1.9 (지시 #59): corps.{new,updated,unchanged} 에 기록. failed 는 _add_failure 전용."""
        entry = CollectCorpEntry(corp_code=corp_code, corp_name=corp_name)
        getattr(corps, bucket).append(entry)

    for corp_code, items in grouped.items():
        corp_name = items[-1].get("corp_name", corp_code)
        try:
            new_items = [it for it in items if it["rcept_no"] not in known]
            is_stale = corp_code in stale_corp_codes
            is_existing = corp_code in existing_corp_codes
            if not new_items and not is_stale:
                # 완전히 새로운 공시가 없고 파서 버전도 최신 — unchanged
                if is_existing:
                    summary.unchanged_count += 1
                    summary.unchanged_corps.append(f"{corp_name}({corp_code})")
                    _add_corp("unchanged", corp_code, corp_name)
                continue
            # is_stale 이면 new_items 가 비어도 process_corp 로 재파싱 진행 (버전 bump 시 자동 재적용)

            # 지시 #24: 재파싱/갱신 시 종목의 **전체 공시 이력**(최근 full_history_days 일)을 다시 받아 와서
            # 정본(발행조건확정)이 증분 조회 범위 밖에 있어도 선정되게 한다.
            # 신규 종목(is_existing=False) 은 증분 범위에서 발견된 공시만으로 처리(어차피 그게 전부).
            items_for_process = items
            if is_stale or is_existing:
                try:
                    full_items = _fetch_corp_history(corp_code)
                except Exception as fe:
                    # 종목별 조회 실패해도 치명적이지 않음 — 증분 items 로 fallback (경고로 보고)
                    full_items = []
                    _add_failure(
                        corp_code, corp_name,
                        f"종목 전체 이력 조회 실패 — {_sanitize_error(fe)} / 증분 범위로 fallback",
                    )
                if full_items:
                    # 지시 #37 (pm 원인 특정): 메인 for 루프의 필터도 stale-only 루프와 **동일 완화**.
                    # 상장 후 엘리스처럼 corp_cls='K' + stock_code 할당된 종목은 is_ipo_candidate=False.
                    # 분류 가능한 공시(발행조건확정 포함) 전부 포함해야 core 가 선정됨 — 그렇지 않으면 preserved 로 떨어짐.
                    filtered_full = [
                        it for it in full_items
                        if collect_mod.is_ipo_candidate(it)
                        or collect_mod.classify_report(it.get("report_nm", "")) is not None
                    ]
                    if filtered_full:
                        items_for_process = sorted(
                            filtered_full, key=lambda d: d.get("rcept_dt", "")
                        )

            # 철회신고서가 포함되면 종목 제외 (전체 이력 기준)
            if any(collect_mod.classify_report(x.get("report_nm", "")) == "WITHDRAWN" for x in items_for_process):
                with store.connect() as conn:
                    for w in items_for_process:
                        if collect_mod.classify_report(w.get("report_nm", "")) == "WITHDRAWN":
                            store.mark_withdrawn(conn, corp_code, w["rcept_no"])
                            break
                summary.withdrawn_count += 1
                continue

            is_new = not is_existing
            r = collect_mod.process_corp(corp_code, items_for_process, log=[])
            # 지시 #22/#24: 다운로드/파싱 실패·core 없음(기존 보존) → upsert skip 반환값으로 처리
            if r.get("status") in ("download_failed", "parse_empty"):
                summary.failed_count += 1
                _add_failure(corp_code, corp_name, r.get("reason") or r["status"])
            elif r.get("status") == "preserved":
                # 지시 #24: core 없음(ISSUANCE_REPORT 만) + 기존 레코드 있음 → 지표 보존 (unchanged 로 계수)
                summary.unchanged_count += 1
                # 지시 #37: preserved 사유 포함 — 다음 라운드 특정 쉬움
                _reason = (r.get("reason") or "").replace(" ", "-")[:40] or "no-core"
                summary.unchanged_corps.append(f"{corp_name}({corp_code}) preserved:{_reason}")
                _add_corp("unchanged", corp_code, corp_name)
            elif is_new:
                summary.new_count += 1
                _add_corp("new", corp_code, corp_name)
            else:
                summary.updated_count += 1
                _add_corp("updated", corp_code, corp_name)
        except Exception as e:  # 종목 단위 오류 격리
            summary.failed_count += 1
            _add_failure(corp_code, corp_name, _sanitize_error(e))
        finally:
            # continue/정상/예외 모두 여기 한 번만 가산
            done += len(items)
            _set(progress=CollectProgress(done=done, total=total_disclosures),
                 summary=summary, failures=failures, corps=corps)

    # 지시 #28: 증분 조회에 안 잡혔지만 DB 에 있고 parser_version 이 낡은 종목도 재처리.
    # (다비오/유캐스트처럼 최근 공시 없는 종목이 stale 로 남으면 CORRECTION/지표 갱신이 안 됨)
    unprocessed_stale = stale_corp_codes - set(grouped.keys())
    for corp_code in unprocessed_stale:
        corp_name = corp_code
        try:
            try:
                full_items = _fetch_corp_history(corp_code)
            except Exception as fe:
                _add_failure(
                    corp_code, corp_name,
                    f"stale 종목 전체 이력 조회 실패 — {_sanitize_error(fe)}",
                )
                continue
            # 지시 #35: 상장 완료된 기존 종목은 corp_cls='K' + stock_code 할당되어 is_ipo_candidate=False.
            # 하지만 DB 에 있던 종목(엘리스 사례)이면 **분류 가능한 공시 전부** 포함해 재파싱 지속.
            filtered_full = [
                it for it in full_items
                if collect_mod.is_ipo_candidate(it)
                or collect_mod.classify_report(it.get("report_nm", "")) is not None
            ]
            if not filtered_full:
                # 조회됐으나 분류 가능한 공시가 없음 — unchanged 로 계수
                summary.unchanged_count += 1
                summary.unchanged_corps.append(f"{corp_name}({corp_code}) stale-only:no-filtered")
                _add_corp("unchanged", corp_code, corp_name)
                continue
            items_for_process = sorted(filtered_full, key=lambda d: d.get("rcept_dt", ""))
            if items_for_process:
                corp_name = items_for_process[-1].get("corp_name", corp_code)

            # 철회신고서 포함 체크
            if any(collect_mod.classify_report(x.get("report_nm", "")) == "WITHDRAWN" for x in items_for_process):
                with store.connect() as conn:
                    for w in items_for_process:
                        if collect_mod.classify_report(w.get("report_nm", "")) == "WITHDRAWN":
                            store.mark_withdrawn(conn, corp_code, w["rcept_no"])
                            break
                summary.withdrawn_count += 1
                continue

            r = collect_mod.process_corp(corp_code, items_for_process, log=[])
            if r.get("status") in ("download_failed", "parse_empty"):
                summary.failed_count += 1
                _add_failure(corp_code, corp_name, r.get("reason") or r["status"])
            elif r.get("status") == "preserved":
                summary.unchanged_count += 1
                _reason = (r.get("reason") or "").replace(" ", "-")[:40] or "no-core"
                summary.unchanged_corps.append(
                    f"{corp_name}({corp_code}) stale-only:preserved:{_reason}"
                )
                _add_corp("unchanged", corp_code, corp_name)
            else:
                summary.updated_count += 1
                _add_corp("updated", corp_code, corp_name)
        except Exception as e:
            summary.failed_count += 1
            _add_failure(corp_code, corp_name, _sanitize_error(e))
        finally:
            _set(progress=CollectProgress(done=done, total=total_disclosures),
                 summary=summary, failures=failures, corps=corps)

    # 완료
    with store.connect() as conn:
        store.finish_collect_run(
            conn, run_id,
            collected=summary.new_count + summary.updated_count,
            errors=summary.failed_count,
            note=f"bgn={bgn} end={end} new={summary.new_count} updated={summary.updated_count} "
                 f"unchanged={summary.unchanged_count} failed={summary.failed_count} withdrawn={summary.withdrawn_count}",
        )

    # 쓰기 검증 (지시 #14): 쓰기가 실제로 영속됐는지 **새 커넥션**으로 확인
    # "성공했다고 보고했는데 데이터 없음" 재발 방지
    expected_min_rows = summary.new_count + summary.updated_count
    if expected_min_rows > 0:
        try:
            with store.connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM ipos WHERE withdrawn_rcept_no IS NULL"
                ).fetchone()
                actual = int(row["c"]) if row is not None else 0
        except Exception as e:
            _set(
                status="FAILED",
                finished_at=now_iso_kst(),
                summary=summary,
                error=f"쓰기 검증 실패 (COUNT 조회 자체 실패) — {_sanitize_error(e)}",
                progress=CollectProgress(done=done, total=total_disclosures),
            )
            return
        if actual < expected_min_rows:
            _set(
                status="FAILED",
                finished_at=now_iso_kst(),
                summary=summary,
                error=(
                    f"쓰기 검증 실패 — 보고된 new+updated={expected_min_rows} 건이지만 "
                    f"COUNT(ipos)={actual} 건. Turso 영속성 문제 의심."
                ),
                progress=CollectProgress(done=done, total=total_disclosures),
            )
            return

    _set(
        status="SUCCEEDED",
        finished_at=now_iso_kst(),
        summary=summary,
        failures=failures,
        progress=CollectProgress(done=done, total=total_disclosures),
    )


# ---------- 보안: 에러 메시지에서 키·내부 경로 제거 (지시 #45 ①: app/security.py 로 공통화) ----------

from .security import mask_exception as _sanitize_error  # noqa: E402
from .security import mask_secrets as _sanitize_error_text  # noqa: E402


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
            "corps": None,   # v1.9 (지시 #59)
            "error": None,
        })
        # 테스트 간 failures 가 남아 다음 테스트에서 보이는 문제 방지 (현재는 failures 미기록)
        _state.pop("failures", None)
    _lock = threading.Lock()
