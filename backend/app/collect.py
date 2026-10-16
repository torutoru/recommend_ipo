"""수집기 CLI — `python -m app.collect --days 90`.

파이프라인:
  1. list.json(C001, 최근 N일, last_reprt_at=Y) → 공시 메타
  2. 종목 그룹핑(corp_code)
  3. IPO 식별: corp_cls='E' AND stock_code 없음 AND corp_name NOT LIKE '%기업인수목적%'
  4. 보고서명 분류: PROSPECTUS / PROSPECTUS_AMENDED / REGISTRATION_AMENDED / ISSUANCE_REPORT / WITHDRAWN
  5. 철회신고서 있는 종목 제외
  6. 종목별로 문서 유형마다 최신 접수본만 유지
  7. "정본" 선정: 발행조건확정 > 기재정정 > 최초 신고서 (지분증권) 순. 없으면 PENDING.
  8. 정본 ZIP 다운로드 + 캐시 + 파일 매직 검사(ZIP 서명) + 압축 해제 후 단일 XML 추출
  9. parser.parse() → store 저장
  오류는 종목 단위로 격리.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

from .config import BACKEND_DIR, get_settings
from .dart_client import download_document_zip, list_disclosures
from .parser import parse
from .store import (
    connect,
    finish_collect_run,
    init_db,
    replace_sources,
    replace_warnings,
    start_collect_run,
    upsert_ipo,
)


CACHE_DIR = BACKEND_DIR / "data" / "dart_cache"
ZIP_MAGIC = b"PK\x03\x04"

DART_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


# ---------- 분류 ----------

DOC_TYPE_RULES: list[tuple[re.Pattern, str]] = [
    # 우선순위: 특수 접두사 먼저
    (re.compile(r"철회신고서"), "WITHDRAWN"),
    (re.compile(r"\[기재정정\]투자설명서"), "PROSPECTUS_AMENDED"),
    (re.compile(r"\[기재정정\]증권발행실적보고서"), "ISSUANCE_REPORT"),
    (re.compile(r"증권발행실적보고서"), "ISSUANCE_REPORT"),
    (re.compile(r"투자설명서"), "PROSPECTUS"),
    (re.compile(r"\[발행조건확정\]증권신고서\(지분증권\)"), "REGISTRATION_AMENDED"),
    (re.compile(r"\[기재정정\]증권신고서\(지분증권\)"), "REGISTRATION_AMENDED"),
    (re.compile(r"\[정정제출요구\]증권신고서\(지분증권\)"), "REGISTRATION_AMENDED"),
    (re.compile(r"증권신고서\(지분증권\)"), "REGISTRATION_AMENDED"),
]


def classify_report(report_nm: str) -> Optional[str]:
    for pat, doc_type in DOC_TYPE_RULES:
        if pat.search(report_nm):
            return doc_type
    return None


def is_ipo_candidate(disclosure: dict) -> bool:
    """공시 하나의 메타만 보고 IPO 후보 여부 판정."""
    if disclosure.get("corp_cls") != "E":
        return False
    if (disclosure.get("stock_code") or "").strip():
        return False
    name = disclosure.get("corp_name") or ""
    if "기업인수목적" in name:
        return False
    return True


def is_final_release(report_nm: str) -> bool:
    """발행조건확정이 '정본' — 수요예측 결과·확정 공모가 모두 담긴다."""
    return "[발행조건확정]" in report_nm


# ---------- 수집 ----------

def fetch_all_c001(days: int) -> list[dict]:
    """지난 N일 치 C001 공시 메타(pagination 포함)."""
    end = datetime.now()
    bgn = end - timedelta(days=days)
    fmt = "%Y%m%d"
    all_items: list[dict] = []
    page_no = 1
    while True:
        resp = list_disclosures(
            bgn_de=bgn.strftime(fmt),
            end_de=end.strftime(fmt),
            pblntf_detail_ty="C001",
            last_reprt_at="N",
            page_count=100,
            page_no=page_no,
        )
        if resp.get("status") != "000":
            if resp.get("status") == "013":  # 조회 결과 없음
                break
            raise RuntimeError(f"OpenDART list.json 실패: status={resp.get('status')} msg={resp.get('message')}")
        all_items.extend(resp.get("list", []))
        total_page = resp.get("total_page") or 1
        if page_no >= int(total_page):
            break
        page_no += 1
    return all_items


def _cache_zip_path(rcept_no: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"document_{rcept_no}.zip"


def get_document_zip_cached(rcept_no: str) -> bytes:
    """ZIP 바이트를 캐시 포함으로 반환. 파일 매직 검사."""
    p = _cache_zip_path(rcept_no)
    if p.exists():
        data = p.read_bytes()
    else:
        data = download_document_zip(rcept_no=rcept_no)
        p.write_bytes(data)
    if not data.startswith(ZIP_MAGIC):
        raise RuntimeError(f"파일 매직 불일치 — ZIP 아님(rcept_no={rcept_no})")
    return data


def extract_single_xml(zip_bytes: bytes) -> bytes:
    """ZIP 내부에서 단일 XML 파일을 추출. 그 외 형식은 예외."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
        if not names:
            raise RuntimeError("ZIP 내부에 XML 없음 (HWP 임베디드 가능성)")
        # 하나만 사용 — dart4.xsd 양식은 단일 XML
        with zf.open(names[0]) as f:
            return f.read()


# ---------- 종목별 집계 ----------

def group_by_corp(items: list[dict]) -> dict[str, list[dict]]:
    """corp_code → 공시 리스트(접수일 오름차순)."""
    out: dict[str, list[dict]] = {}
    for it in items:
        if not is_ipo_candidate(it):
            continue
        out.setdefault(it["corp_code"], []).append(it)
    for v in out.values():
        v.sort(key=lambda d: d.get("rcept_dt", ""))
    return out


def choose_core_disclosure(disclosures: list[dict]) -> tuple[Optional[dict], list[dict]]:
    """
    (정본 공시, 모든 유효 공시(sources 용)).
    정본 우선순위: [발행조건확정] > 가장 최근 [기재정정]/[정정제출요구] 증권신고서 > 최초 증권신고서.
    철회신고서 있으면 (None, [])  — 호출자가 전체 종목을 스킵하도록.
    """
    classified = []
    for d in disclosures:
        t = classify_report(d.get("report_nm", ""))
        if t == "WITHDRAWN":
            return None, []
        if t is None:
            continue
        classified.append((d, t))

    # 발행조건확정 우선 (가장 최근)
    finals = [c for c in classified if is_final_release(c[0].get("report_nm", ""))]
    if finals:
        core = max(finals, key=lambda c: c[0].get("rcept_dt", ""))[0]
    else:
        # 모든 지분증권 증권신고서(기재정정/정정제출요구/신규) 중 최신
        regs = [c for c in classified if c[1] == "REGISTRATION_AMENDED"]
        if regs:
            core = max(regs, key=lambda c: c[0].get("rcept_dt", ""))[0]
        else:
            core = None

    sources = [{"disclosure": d, "doc_type": t} for d, t in classified]
    return core, sources


# ---------- 1 종목 처리 ----------

def process_corp(
    corp_code: str,
    disclosures: list[dict],
    *,
    log: list[str],
) -> dict:
    """1 종목을 처리. 저장까지 수행. 반환: 이 종목 요약."""
    core, raw_sources = choose_core_disclosure(disclosures)

    corp_name = disclosures[-1].get("corp_name", corp_code)  # 최신 공시의 이름 사용

    sources_payload = [
        {
            "doc_type": s["doc_type"],
            "rcept_no": s["disclosure"]["rcept_no"],
            "rcept_dt": _dash_date(s["disclosure"]["rcept_dt"]),
            "url": DART_URL + s["disclosure"]["rcept_no"],
        }
        for s in raw_sources
    ]

    status = "PENDING"
    parsed_warnings: list[str] = []
    row: dict = {
        "corp_code": corp_code,
        "corp_name": corp_name,
        "market": None,
        "subscription_start": None,
        "subscription_end": None,
        "listing_date": None,
        "band_low": None,
        "band_high": None,
        "final_price": None,
        "price_position": None,
        "competition_rate": None,
        "competition_rate_type": None,
        "demand_quantity": None,
        "demand_amount_krw": None,
        "lockup_ratio": None,
        "lockup_ratio_basis": None,
        "tradable_ratio": None,
        "old_share_ratio": None,
        "new_share_count": None,
        "old_share_count": None,
        "total_offering_count": None,
        "offering_amount_krw": None,
        "report_rcept_no": None,
    }

    if core is None:
        # 철회 또는 분류 가능한 공시 없음 — raw_sources 비면 저장하지 않음
        if not raw_sources:
            log.append(f"[SKIP] {corp_code} {corp_name} — 분류 가능한 공시 없음(철회신고서 포함)")
            return {"corp_code": corp_code, "status": "SKIPPED", "warnings": []}
        parsed_warnings.append("정본 공시(발행조건확정/증권신고서) 없음 — PENDING 유지")
    else:
        rcept_no = core["rcept_no"]
        try:
            zip_bytes = get_document_zip_cached(rcept_no)
            xml_bytes = extract_single_xml(zip_bytes)
        except Exception as e:
            parsed_warnings.append(f"원문 다운로드/압축해제 실패({rcept_no}): {type(e).__name__}: {e}")
            xml_bytes = None

        if xml_bytes:
            parsed = parse(
                xml_bytes,
                rcept_no=rcept_no,
                corp_name=corp_name,
                rcept_dt=_dash_date(core.get("rcept_dt", "")),
            )
            row.update(
                market=parsed.market,
                subscription_start=parsed.subscription_start,
                subscription_end=parsed.subscription_end,
                listing_date=parsed.listing_date,
                band_low=parsed.band_low,
                band_high=parsed.band_high,
                final_price=parsed.final_price,
                price_position=parsed.price_position,
                competition_rate=parsed.competition_rate,
                competition_rate_type=parsed.competition_rate_type,
                demand_quantity=parsed.demand_quantity,
                demand_amount_krw=parsed.demand_amount_krw,
                lockup_ratio=parsed.lockup_ratio,
                lockup_ratio_basis=parsed.lockup_ratio_basis,
                tradable_ratio=parsed.tradable_ratio,
                old_share_ratio=parsed.old_share_ratio,
                new_share_count=parsed.new_share_count,
                old_share_count=parsed.old_share_count,
                total_offering_count=parsed.total_offering_count,
                offering_amount_krw=parsed.offering_amount_krw,
                report_rcept_no=rcept_no,
            )
            parsed_warnings.extend(parsed.warnings)

    # 저장
    with connect() as conn:
        upsert_ipo(conn, **row)
        replace_sources(conn, corp_code, sources_payload)
        replace_warnings(conn, corp_code, parsed_warnings)

    return {
        "corp_code": corp_code,
        "corp_name": corp_name,
        "status": "collected",
        "warnings_count": len(parsed_warnings),
        "has_core_release": core is not None,
    }


def _dash_date(d: str) -> str:
    """YYYYMMDD → YYYY-MM-DD. 이미 대시면 그대로."""
    if len(d) == 8 and d.isdigit():
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return d


# ---------- 엔트리 ----------

def run(days: int, *, verbose: bool = True) -> dict:
    init_db()
    all_items = fetch_all_c001(days)
    grouped = group_by_corp(all_items)

    log: list[str] = []
    results: list[dict] = []
    errors = 0

    with connect() as conn:
        run_id = start_collect_run(conn, days)

    for corp_code, disclosures in grouped.items():
        try:
            r = process_corp(corp_code, disclosures, log=log)
            results.append(r)
            if verbose and r.get("status") == "collected":
                log.append(
                    f"[OK] {corp_code} {r['corp_name']} "
                    f"warnings={r['warnings_count']} core={'YES' if r['has_core_release'] else 'NO'}"
                )
        except Exception as e:
            errors += 1
            log.append(f"[ERR] {corp_code}: {type(e).__name__}: {e}")

    collected = sum(1 for r in results if r.get("status") == "collected")

    with connect() as conn:
        finish_collect_run(conn, run_id, collected=collected, errors=errors,
                           note=f"days={days} candidates={len(grouped)} items={len(all_items)}")

    summary = {
        "candidates": len(grouped),
        "collected": collected,
        "errors": errors,
        "total_c001_items": len(all_items),
    }
    if verbose:
        for line in log:
            print(line)
        print("---")
        print(f"요약: candidates={summary['candidates']} collected={summary['collected']} "
              f"errors={summary['errors']} C001총={summary['total_c001_items']}")
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="app.collect")
    ap.add_argument("--days", type=int, default=90, help="지난 N 일 공시 수집 (기본 90)")
    ap.add_argument("--quiet", action="store_true")
    ns = ap.parse_args(argv)
    try:
        run(ns.days, verbose=not ns.quiet)
    except httpx.HTTPError as e:
        print(f"[FATAL] HTTP 오류: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(f"[FATAL] {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
