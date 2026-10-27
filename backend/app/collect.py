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
from . import dart_client  # 테스트 격리 위해 모듈 참조 (`dart_client.download_document_zip` 로 호출)
from .parser import parse
from .security import mask_secrets as _mask  # 지시 #45 ①: 모든 외부 노출 문자열에 적용
from .store import (
    ensure_ipo_stub,
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

# 파서 버전 — 코드가 바뀔 때마다 bump. store.ipos.parser_version 에 저장.
# 수집기가 DB 저장값과 다르면 "변화 없음" 분기에서 빼내 재파싱.
# 버전 bump 사례:
#   v2 — 지시 #16 (티앤이코리아 확약·유통 regex 일반화, 두 표 합산)
#   v3 — 지시 #19 (INCOMPLETE 상태 도입, "미공시 0점" 폐지)
#   v4 — 지시 #24 (재파싱 시 종목 전체 이력 조회, core=None 보호, sources 보존)
#   v5 — 지시 #25 (실적보고서 상장일(매매개시일)·상장구분 파싱 + ISSUANCE_REPORT 보강)
#   v6 — 지시 #26 (삼성증권 형식 — 확약 섹션 "의무보유 확약 신청내역" 수용 + 유통 서술형 역순)
#   v7 — 지시 #20 (공모가 확정공고일·수요예측 기간 — 명시 매치 + 발행조건확정 접수일 fallback)
#   v8 — 지시 #17 (CORRECTION 상태 — 정정요구/기재정정 접수일 추적)
#   v9 — 지시 #28 (공지 다운로드 가드 + DB stale-only 재처리 + 투자설명서 수요예측 보강)
#   v10 — 지시 #21(주관사 서술 추출) + #75aebc23 (확정가 전 공모 금액 null)
#   v11 — 지시 #29 (공모 금액 total×final 우선 + 파생 필드 COALESCE 예외)
#   v12 — 정확도 보강 배치1 (수요예측 요일 괄호·"일시" 라벨 + 신주/구주 라벨 변형)
#   v13 — 정확도 보강 #1 (엠에스바이오 유통 — 괄호 % 서술 + 투자설명서 tradable_ratio 보강)
#   v14 — 지시 #30 (CORRECTION 해제: 효력발생안내 또는 투자설명서가 요구일 이후 있으면 정상 판정)
#   v15 — 지시 #32 (correction 메타 COALESCE 예외 — 해제 조건 성립 시 null 로 교체)
#   v16 — 정확도 보강 #정확도-배치3 (엘리스그룹 확약 — 라벨 "합/계" COLSPAN 분리 수용)
#   v17 — 보강 묶음 (D: estkRs 교차검증 + C: Turso transaction 묶음)
#   v18 — 지시 #35 (상장 완료 종목 재처리 — stale-only + 메인 루프 필터 완화 + ABOVE_BAND 라벨 교체)
#   v19 — 지시 #36 (unchanged_corps 로그 + 강제 재처리 bump — 엘리스 운영 null 재검증)
#   v20 — 지시 #37 (메인 for 루프 filtered_full 완화 — stale-only 와 동일 — 엘리스 preserved 사고 해소)
#   v21 — 지시 #38 (신주/구주 라벨 strict + 범위 검증 — 영광 음수 사고 해소 / 유통 쉼표 소수점 수용 — 이에스티)
#   v22 — 지시 #39 (정정 "정 정 전" 섹션 제거 + 밴드 어순 변형 + "구주매출 없음" 명시 + 유통 부분값 skip + "유통 가능" 띄어쓰기)
#   v23 — 지시 #40+#41 (아델 가정 확정가 거부 + 정정 블록 상한 제거 + flow 한쪽 조건 NOT_MET)
#   v24 — 지시 #42 (정정 신고서 서두 정정표 skip — "대표이사 등의 확인" 이후 본문에서만 일정·밴드 추출)
#   v25 — 지시 #43 (final_price 저장 조건부 COALESCE — competition_rate 미공시면 excluded 교체, 아델 오파싱 보존 해소)
#   v26 — 지시 #46 ① (COALESCE 축소 — 정상 파싱이면 지표/일정 excluded 교체, listing_date·market·underwriters 는 전용 출처 보호)
#   v27 — 지시 #45 ② 묶음1 (쉼표 단독 매치 방지·청약 종료 연도 생략·INCOMPLETE 한글 라벨·_is_incomplete 삭제)
#   v28 — 지시 #45 ②-4 (flow 범위 좁힘 — tradable null 이어도 구주 확정이면 좁은 범위 반환)
#   v29 — 지시 #45 ②-3 (확정가 다중 후보 수집 + 가정문 접미사 확장[경우|될|라면|가정|이상|이하] + 유효 다중 상이값 null)
#   v30 — 지시 #45 ②-1 (본문 추출 확대: tradable·offering counts·offering amount·final_price. lockup 는 HTML 구조 유지로 미적용)
#   v31 — 지시 #48 (extract_offering_amount_krw 본문 추출 회귀 원복 — 1주 가격 오매치 사고 해소)
#   v32 — 지시 #49 (수요예측 라벨 각주 "(주N)" 수용 — 래블업 / 유통 부분값 힌트 확장 — 영광)
#   v34 — 지시 #53 (증분 조회 2단계 — C001 신규 발견 + 전 유형은 existing corp 만 수용. v33 비IPO 유입 회귀 해소)
PARSER_VERSION = "v34"


# ---------- 분류 ----------

DOC_TYPE_RULES: list[tuple[re.Pattern, str]] = [
    # 우선순위: 특수 접두사 먼저
    (re.compile(r"철회신고서"), "WITHDRAWN"),
    (re.compile(r"\[기재정정\]투자설명서"), "PROSPECTUS_AMENDED"),
    (re.compile(r"\[기재정정\]증권발행실적보고서"), "ISSUANCE_REPORT"),
    (re.compile(r"증권발행실적보고서"), "ISSUANCE_REPORT"),
    (re.compile(r"투자설명서"), "PROSPECTUS"),
    # 지시 #17 수정 (pm 피드백): 금감원 "정정신고서제출요구( ... )" 공지는 접두 괄호 없이 "정정신고서제출요구" 로 시작.
    # (주의: "[정정제출요구]" 접두가 붙은 문서는 **회사가 낸 원 신고서** 로서 정본 후보.)
    (re.compile(r"^정정신고서제출요구"), "CORRECTION_REQUEST"),
    # 지시 #30: 금감원 "효력발생안내( ... )" 공지. CORRECTION 해제 트리거.
    (re.compile(r"^효력발생안내"), "EFFECTIVENESS_NOTICE"),
    (re.compile(r"\[발행조건확정\]증권신고서\(지분증권\)"), "REGISTRATION_AMENDED"),
    (re.compile(r"\[기재정정\]증권신고서\(지분증권\)"), "REGISTRATION_AMENDED"),
    # 지시 #17 수정: "[정정제출요구]증권신고서" 는 회사가 낸 원 신고서 → 정본 후보로 유지(REGISTRATION_AMENDED)
    (re.compile(r"\[정정제출요구\]증권신고서\(지분증권\)"), "REGISTRATION_AMENDED"),
    (re.compile(r"증권신고서\(지분증권\)"), "REGISTRATION_AMENDED"),
]


def classify_report(report_nm: str) -> Optional[str]:
    for pat, doc_type in DOC_TYPE_RULES:
        if pat.search(report_nm):
            return doc_type
    return None


def _is_fss_notice_rcept_no(rcept_no: str) -> bool:
    """지시 #28: 금감원 발행 공시 접수번호 식별 — 9~10번째 자리가 '10'.

    예: 20260916**10**0012 (효력발생안내, 정정신고서제출요구 등). 원문이 없어 다운로드 실패.
    메타는 raw_sources 에 남기되 **정본 후보에서 제외**.
    """
    return len(rcept_no) >= 10 and rcept_no[8:10] == "10"


def is_ipo_candidate(disclosure: dict) -> bool:
    """공시 하나의 메타만 보고 IPO 후보 여부 판정.

    v0.7+ (지시 #15): 스팩 제외 키워드는 설정값(`SPAC_EXCLUSION_KEYWORDS` CSV).
    기본값: "기업인수목적,스팩" — 회사명에 둘 중 하나라도 포함되면 제외.
    """
    if disclosure.get("corp_cls") != "E":
        return False
    if (disclosure.get("stock_code") or "").strip():
        return False
    name = disclosure.get("corp_name") or ""
    from .config import get_settings
    for kw in get_settings().spac_keywords():
        if kw and kw in name:
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
        resp = dart_client.list_disclosures(
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
        data = dart_client.download_document_zip(rcept_no=rcept_no)
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

    # 지시 #28: 금감원 공지 접수번호(9~10번째 '10')는 원문이 없어 다운로드 실패 → 정본 후보에서 제외
    def _is_company_doc(d: dict) -> bool:
        return not _is_fss_notice_rcept_no(d.get("rcept_no", ""))

    # 발행조건확정 우선 (가장 최근) — 금감원 공지는 제외
    finals = [c for c in classified
              if is_final_release(c[0].get("report_nm", "")) and _is_company_doc(c[0])]
    if finals:
        core = max(finals, key=lambda c: c[0].get("rcept_dt", ""))[0]
    else:
        # 모든 지분증권 증권신고서(기재정정/정정제출요구/신규) 중 최신 — 금감원 공지는 제외
        regs = [c for c in classified
                if c[1] == "REGISTRATION_AMENDED" and _is_company_doc(c[0])]
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

    # 지시 #17 (pm 수정 피드백 반영): 정정요구 추적 — 두 단계 소스.
    # 1차: "정정신고서제출요구( ... )" **공지** 접수일(CORRECTION_REQUEST).
    # 2차 fallback: 공지 공시가 못 잡혔으면(조회 안 됨) 접두 "[정정제출요구]" 가 붙은 **원 신고서** 접수일.
    #   접두 '[정정제출요구]' 는 회사가 낸 원 신고서이므로 정본 후보로 유지되고 분류는 REGISTRATION_AMENDED,
    #   정정요구 '발생' 자체는 이 접두가 증거.
    # 이후 발행조건확정이 그 날짜 이후면 correction 상태 아님(정상 평가).
    correction_requested_at: Optional[str] = None
    correction_amended_at: Optional[str] = None
    correction_warning: Optional[str] = None

    corr_notices = [s for s in raw_sources if s["doc_type"] == "CORRECTION_REQUEST"]
    corr_req_date_raw: Optional[str] = None
    corr_source_label: Optional[str] = None   # "notice" 또는 "bracket"
    if corr_notices:
        latest = max(corr_notices, key=lambda s: s["disclosure"].get("rcept_dt", ""))
        corr_req_date_raw = latest["disclosure"].get("rcept_dt", "")
        corr_source_label = "notice"
    else:
        # 2차 fallback: 접두 '[정정제출요구]' 를 가진 회사 신고서
        bracket_regs = [
            s for s in raw_sources
            if s["doc_type"] == "REGISTRATION_AMENDED"
            and "[정정제출요구]" in s["disclosure"].get("report_nm", "")
        ]
        if bracket_regs:
            latest = max(bracket_regs, key=lambda s: s["disclosure"].get("rcept_dt", ""))
            corr_req_date_raw = latest["disclosure"].get("rcept_dt", "")
            corr_source_label = "bracket"

    if corr_req_date_raw:
        # 지시 #30: CORRECTION 해제 트리거 — 요구일 이후에 다음 중 하나라도 있으면 정상 판정
        #   (1) 발행조건확정 공시
        #   (2) 금감원 "효력발생안내" 공지(EFFECTIVENESS_NOTICE)
        #   (3) 회사의 투자설명서(PROSPECTUS / PROSPECTUS_AMENDED)
        has_release_after = any(
            (
                is_final_release(s["disclosure"].get("report_nm", ""))
                or s["doc_type"] == "EFFECTIVENESS_NOTICE"
                or s["doc_type"] in ("PROSPECTUS", "PROSPECTUS_AMENDED")
            )
            and (s["disclosure"].get("rcept_dt", "") or "") > corr_req_date_raw
            for s in raw_sources
        )
        if not has_release_after:
            correction_requested_at = _dash_date(corr_req_date_raw) or None
            if corr_source_label == "bracket":
                correction_warning = (
                    f"정정요구 공지 공시 미발견 — 접두 '[정정제출요구]' 신고서 접수일 "
                    f"({correction_requested_at}) 기준"
                )
            # 그 이후 기재정정(발행사 재제출) 중 최신
            amends_after = [
                s for s in raw_sources
                if s["doc_type"] == "REGISTRATION_AMENDED"
                and "[기재정정]" in s["disclosure"].get("report_nm", "")
                and (s["disclosure"].get("rcept_dt", "") or "") > corr_req_date_raw
            ]
            if amends_after:
                latest_amend = max(amends_after, key=lambda s: s["disclosure"].get("rcept_dt", ""))
                correction_amended_at = _dash_date(latest_amend["disclosure"].get("rcept_dt", "")) or None

    status = "PENDING"
    parsed_warnings: list[str] = []
    if correction_warning:
        parsed_warnings.append(correction_warning)
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
        "parser_version": PARSER_VERSION,
        # v1.1 (지시 #20): 공모 일정
        "price_confirm_date": None,
        "demand_forecast_start": None,
        "demand_forecast_end": None,
        # v0.8 (지시 #17): 정정요구 정보 — CORRECTION 상태 판정 데이터
        "correction_requested_at": correction_requested_at,
        "correction_amended_at": correction_amended_at,
        # v1.2 (지시 #21): 주관사·인수회사 목록 (JSON 문자열로 저장)
        "underwriters_json": None,
    }

    if core is None:
        # 철회 또는 분류 가능한 공시 없음 — raw_sources 비면 저장하지 않음
        if not raw_sources:
            log.append(f"[SKIP] {corp_code} {corp_name} — 분류 가능한 공시 없음(철회신고서 포함)")
            return {"corp_code": corp_code, "status": "SKIPPED", "warnings": []}
        # 지시 #24: 정본 공시(발행조건확정/증권신고서)가 없고 ISSUANCE_REPORT 만 있는 경우.
        # 기존 레코드가 있으면 지표를 null 로 덮지 말고 그대로 보존.
        # sources·warnings 는 업데이트해 두되 upsert_ipo 는 skip → parser_version 도 안 바뀜(다음 수집에서 또 체크).
        with connect() as conn:
            existing = conn.execute(
                "SELECT corp_code FROM ipos WHERE corp_code = ? AND withdrawn_rcept_no IS NULL",
                (corp_code,),
            ).fetchone()
            if existing is not None:
                parsed_warnings.append(
                    "정본 공시(발행조건확정/증권신고서) 없음 — 기존 지표 보존(ISSUANCE_REPORT 만으로는 덮어쓰지 않음)"
                )
                replace_sources(conn, corp_code, sources_payload)
                replace_warnings(conn, corp_code, parsed_warnings)
            else:
                # 신규 종목인데 core 가 없음 — PENDING 메타만 저장(지표는 전부 null)
                parsed_warnings.append("정본 공시(발행조건확정/증권신고서) 없음 — PENDING 유지")
                _save_atomic(conn, corp_code=corp_code, row=row,
                             sources_payload=sources_payload, parsed_warnings=parsed_warnings)
                return {
                    "corp_code": corp_code,
                    "corp_name": corp_name,
                    "status": "collected",
                    "warnings_count": len(parsed_warnings),
                    "has_core_release": False,
                }
        return {
            "corp_code": corp_code,
            "corp_name": corp_name,
            "status": "preserved",
            "reason": "정본 공시 없음 — 기존 지표 보존",
            "has_core_release": False,
        }
    else:
        rcept_no = core["rcept_no"]
        xml_bytes: Optional[bytes] = None
        download_error: Optional[str] = None
        try:
            zip_bytes = get_document_zip_cached(rcept_no)
            xml_bytes = extract_single_xml(zip_bytes)
        except Exception as e:
            download_error = _mask(f"원문 다운로드/압축해제 실패({rcept_no}): {type(e).__name__}: {e}")
            parsed_warnings.append(download_error)

        if xml_bytes is None:
            # 지시 #22: 다운로드/압축해제 실패 → 기존 데이터 **덮어쓰지 않음**.
            # upsert_ipo 호출 skip, parser_version 도 갱신 안 함 → 다음 수집에서 재시도.
            # sources·warnings 는 참고용이므로 업데이트해 둠(기존 데이터와 충돌 없음).
            # 지시 #47: 신규 종목이면 ipos 가 없어 sources FK 실패 → stub row 로 선 보장.
            with connect() as conn:
                ensure_ipo_stub(conn, corp_code, corp_name)
                replace_sources(conn, corp_code, sources_payload)
                replace_warnings(conn, corp_code, parsed_warnings)
            return {
                "corp_code": corp_code,
                "corp_name": corp_name,
                "status": "download_failed",
                "reason": download_error or "unknown",
                "has_core_release": True,
            }

        parsed = parse(
            xml_bytes,
            rcept_no=rcept_no,
            corp_name=corp_name,
            rcept_dt=_dash_date(core.get("rcept_dt", "")),
        )
        # 지시 #22: **핵심 지표(parse 결과)** 가 전부 null 이면 저장소를 덮지 않음.
        # 핵심 = band_low · final_price · competition_rate · lockup_ratio · tradable_ratio 중 **하나라도** 추출됐으면 유효한 파싱.
        core_signals = (
            parsed.band_low, parsed.final_price, parsed.competition_rate,
            parsed.lockup_ratio, parsed.tradable_ratio,
            parsed.subscription_start,  # 신고서 1차에는 이것만 있어도 OK
        )
        if all(v is None for v in core_signals):
            msg = f"파싱 결과 핵심 지표 전부 null({rcept_no}) — 저장 skip"
            parsed_warnings.append(msg)
            # 지시 #47: 신규 종목이면 ipos 가 없어 sources FK 실패 → stub row 로 선 보장.
            with connect() as conn:
                ensure_ipo_stub(conn, corp_code, corp_name)
                replace_sources(conn, corp_code, sources_payload)
                replace_warnings(conn, corp_code, parsed_warnings)
            return {
                "corp_code": corp_code,
                "corp_name": corp_name,
                "status": "parse_empty",
                "reason": msg,
                "has_core_release": True,
            }

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
            price_confirm_date=parsed.price_confirm_date,
            demand_forecast_start=parsed.demand_forecast_start,
            demand_forecast_end=parsed.demand_forecast_end,
        )
        # v1.2 (지시 #21) + 보강 (estkRs 교차검증): 서술형 추출 결과 + estkRs group[].list "인수인정보" merge.
        # 서술형이 못 잡는 공동주관사·인수회사가 estkRs 에 있으면 보강(이름만, 수량/금액 사용 금지).
        combined = list(parsed.underwriters)
        estk_names: list[str] = []
        try:
            core_dt_raw = core.get("rcept_dt", "")
            if len(core_dt_raw) >= 4:
                yr = int(core_dt_raw[:4])
                bgn_de = f"{yr-1:04d}0101"
                end_de = f"{yr+1:04d}1231"
                estk_resp = dart_client.get_estk_rs(corp_code=corp_code, bgn_de=bgn_de, end_de=end_de)
                estk_names = _extract_underwriters_from_estk_rs(estk_resp)
        except Exception as e:
            parsed_warnings.append(_mask(f"estkRs 교차검증 호출 실패: {type(e).__name__}: {e}"))
        if estk_names:
            seen = set(combined)
            for name in estk_names:
                if name not in seen:
                    seen.add(name)
                    combined.append(name)
            if combined != parsed.underwriters:
                added = [n for n in estk_names if n not in parsed.underwriters]
                parsed_warnings.append(
                    f"주관사 estkRs 보강: 서술형={parsed.underwriters}, estkRs={estk_names}, 추가={added}"
                )
        if combined:
            import json as _json
            row["underwriters_json"] = _json.dumps(combined, ensure_ascii=False)
        # 지시 #20: price_confirm_date 는 발행조건확정 공시 접수일로 fallback.
        # 명세: "확정공고일 = 이날 [발행조건확정] 공시로 기관 데이터 공개" → core 가 [발행조건확정] 이면 접수일 == 공고일.
        if row["price_confirm_date"] is None and is_final_release(core.get("report_nm", "")):
            row["price_confirm_date"] = _dash_date(core.get("rcept_dt", "")) or None
        parsed_warnings.extend(parsed.warnings)

        # 지시 #25: ISSUANCE_REPORT 로 상장일·시장 보강.
        # - 발행조건확정 XML 에서 listing_date 또는 market 이 null 이고
        # - raw_sources 에 ISSUANCE_REPORT 가 있으면
        # - 가장 최근 실적보고서를 다운로드·파싱해 두 값만 보완(경쟁률·가격 등 기존 지표는 건드리지 않음).
        if row.get("listing_date") is None or row.get("market") is None:
            _supplement_from_issuance_report(
                corp_code=corp_code, corp_name=corp_name, core_rcept=rcept_no,
                raw_sources=raw_sources, row=row, parsed_warnings=parsed_warnings,
            )

        # 지시 #28 + 정확도 보강: 투자설명서로 수요예측 기간 + 유통가능 비율 보강.
        # 발행조건확정에는 "수요예측 기간"·"유통가능 서술" 명시가 거의 없음 — 투자설명서에 있음(엠에스바이오 사례).
        if (
            row.get("demand_forecast_start") is None
            or row.get("demand_forecast_end") is None
            or row.get("tradable_ratio") is None
        ):
            _supplement_from_prospectus(
                corp_code=corp_code, corp_name=corp_name, core_rcept=rcept_no,
                raw_sources=raw_sources, row=row, parsed_warnings=parsed_warnings,
            )

    # 저장 (지시 보강 #C: Turso 는 transaction()으로 한 pipeline 묶음, SQLite 는 context manager 가 자연 원자)
    with connect() as conn:
        _save_atomic(conn, corp_code=corp_code, row=row,
                     sources_payload=sources_payload, parsed_warnings=parsed_warnings)

    return {
        "corp_code": corp_code,
        "corp_name": corp_name,
        "status": "collected",
        "warnings_count": len(parsed_warnings),
        "has_core_release": core is not None,
    }


def _supplement_from_issuance_report(
    *,
    corp_code: str,
    corp_name: str,
    core_rcept: str,
    raw_sources: list[dict],
    row: dict,
    parsed_warnings: list[str],
) -> None:
    """지시 #25: ISSUANCE_REPORT 로 listing_date / market 보강.

    발행조건확정에서 못 뽑은 값만 채운다. 실패는 경고로만 남기고 진행.
    """
    issuance = [s for s in raw_sources
                if s.get("doc_type") == "ISSUANCE_REPORT"
                and not _is_fss_notice_rcept_no(s["disclosure"].get("rcept_no", ""))]
    if not issuance:
        return
    # 가장 최근 실적보고서 선택
    latest = max(issuance, key=lambda s: s["disclosure"].get("rcept_dt", ""))
    issue_rcept = latest["disclosure"]["rcept_no"]
    if issue_rcept == core_rcept:
        # 정본이 이미 실적보고서인 특수 케이스 — 중복 파싱 skip
        return
    try:
        zip_bytes = get_document_zip_cached(issue_rcept)
        xml_bytes = extract_single_xml(zip_bytes)
    except Exception as e:
        parsed_warnings.append(
            _mask(f"ISSUANCE_REPORT({issue_rcept}) 보강 다운로드/압축해제 실패: {type(e).__name__}: {e}")
        )
        return
    try:
        issue_parsed = parse(
            xml_bytes,
            rcept_no=issue_rcept,
            corp_name=corp_name,
            rcept_dt=_dash_date(latest["disclosure"].get("rcept_dt", "")),
        )
    except Exception as e:
        parsed_warnings.append(
            _mask(f"ISSUANCE_REPORT({issue_rcept}) 보강 파싱 실패: {type(e).__name__}: {e}")
        )
        return
    changed: list[str] = []
    if row.get("listing_date") is None and issue_parsed.listing_date:
        row["listing_date"] = issue_parsed.listing_date
        changed.append(f"listing_date={issue_parsed.listing_date}")
    if row.get("market") is None and issue_parsed.market:
        row["market"] = issue_parsed.market
        changed.append(f"market={issue_parsed.market}")
    if changed:
        parsed_warnings.append(
            f"ISSUANCE_REPORT({issue_rcept}) 보강 적용 — {', '.join(changed)}"
        )


def _extract_underwriters_from_estk_rs(response: dict) -> list[str]:
    """지시 (보조): estkRs 응답의 group[]."인수인정보" list → 이름 리스트 (대표/공동/인수 순 정렬).

    actsen: 역할(대표/공동/인수), actnmn: 이름. 수량/금액(udtcnt, udtamt)은 쓰지 않음(pm 지시).
    """
    role_order = {"대표": 0, "공동대표": 1, "공동": 2, "인수": 3}
    pairs: list[tuple[int, str]] = []
    for g in response.get("group", []) or []:
        if g.get("title") == "인수인정보":
            for it in g.get("list", []) or []:
                name = (it.get("actnmn") or "").strip()
                if not name:
                    continue
                role = (it.get("actsen") or "").strip()
                pairs.append((role_order.get(role, 9), name))
            break
    pairs.sort(key=lambda t: t[0])
    seen: set[str] = set()
    out: list[str] = []
    for _, n in pairs:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _save_atomic(
    conn,
    *,
    corp_code: str,
    row: dict,
    sources_payload: list[dict],
    parsed_warnings: list[str],
) -> None:
    """지시 보강 #C: 종목 1건 저장(ipo + sources + warnings)을 원자적으로 묶는다.

    - Turso HTTP: `conn.transaction()` 가 BEGIN + 세 그룹 쿼리 + COMMIT 를 한 pipeline 으로 전송
    - SQLite 로컬: `connect()` context manager 가 종료 시 commit, 중간 예외 시 rollback → 이미 자연 원자
    """
    if hasattr(conn, "transaction"):
        with conn.transaction():
            upsert_ipo(conn, **row)
            replace_sources(conn, corp_code, sources_payload)
            replace_warnings(conn, corp_code, parsed_warnings)
    else:
        upsert_ipo(conn, **row)
        replace_sources(conn, corp_code, sources_payload)
        replace_warnings(conn, corp_code, parsed_warnings)


def _supplement_from_prospectus(
    *,
    corp_code: str,
    corp_name: str,
    core_rcept: str,
    raw_sources: list[dict],
    row: dict,
    parsed_warnings: list[str],
) -> None:
    """지시 #28: 투자설명서(PROSPECTUS/PROSPECTUS_AMENDED)로 수요예측 기간 보강.

    발행조건확정 공시는 "수요예측 기간" 명시가 거의 없고 투자설명서에 있다 — pm 실측(크리에이츠).
    null 자리만 채운다. 공지 접수번호는 다운로드 대상에서 제외.
    """
    pros = [
        s for s in raw_sources
        if s.get("doc_type") in ("PROSPECTUS", "PROSPECTUS_AMENDED")
        and not _is_fss_notice_rcept_no(s["disclosure"].get("rcept_no", ""))
    ]
    if not pros:
        return
    # 가장 최근 투자설명서 (PROSPECTUS_AMENDED 우선)
    latest = max(
        pros,
        key=lambda s: (
            1 if s.get("doc_type") == "PROSPECTUS_AMENDED" else 0,
            s["disclosure"].get("rcept_dt", ""),
        ),
    )
    pros_rcept = latest["disclosure"]["rcept_no"]
    if pros_rcept == core_rcept:
        return
    try:
        zip_bytes = get_document_zip_cached(pros_rcept)
        xml_bytes = extract_single_xml(zip_bytes)
    except Exception as e:
        parsed_warnings.append(
            _mask(f"PROSPECTUS({pros_rcept}) 보강 다운로드/압축해제 실패: {type(e).__name__}: {e}")
        )
        return
    try:
        pros_parsed = parse(
            xml_bytes,
            rcept_no=pros_rcept,
            corp_name=corp_name,
            rcept_dt=_dash_date(latest["disclosure"].get("rcept_dt", "")),
        )
    except Exception as e:
        parsed_warnings.append(
            _mask(f"PROSPECTUS({pros_rcept}) 보강 파싱 실패: {type(e).__name__}: {e}")
        )
        return
    changed: list[str] = []
    if row.get("demand_forecast_start") is None and pros_parsed.demand_forecast_start:
        row["demand_forecast_start"] = pros_parsed.demand_forecast_start
        changed.append(f"demand_forecast_start={pros_parsed.demand_forecast_start}")
    if row.get("demand_forecast_end") is None and pros_parsed.demand_forecast_end:
        row["demand_forecast_end"] = pros_parsed.demand_forecast_end
        changed.append(f"demand_forecast_end={pros_parsed.demand_forecast_end}")
    # 정확도 보강: 유통가능 비율도 보완(발행조건확정에 서술 없는 엠에스바이오 사례)
    if row.get("tradable_ratio") is None and pros_parsed.tradable_ratio is not None:
        row["tradable_ratio"] = pros_parsed.tradable_ratio
        changed.append(f"tradable_ratio={pros_parsed.tradable_ratio}")
    if changed:
        parsed_warnings.append(
            f"PROSPECTUS({pros_rcept}) 보강 적용 — {', '.join(changed)}"
        )


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
            log.append(_mask(f"[ERR] {corp_code}: {type(e).__name__}: {e}"))

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
        print(_mask(f"[FATAL] HTTP 오류: {e}"), file=sys.stderr)
        return 2
    except RuntimeError as e:
        print(_mask(f"[FATAL] {e}"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
