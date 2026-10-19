"""증권신고서(지분증권) 원문 XML 파서.

전제: 입력은 OpenDART `document.xml` ZIP 안의 단일 XML(dart4.xsd 양식). HWP 임베디드는 호출자가 걸러낸다.
설계 원칙(requirements.md 8장, api-contract v0.2):
- 파싱 못 한 값은 None 반환. **추정 금지.**
- 각 항목 실패마다 warnings 에 간단한 사유 기록(한국어).
- 섹션별로 함수 분리. 디티에스 fixture 로 TDD.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Optional

from .schemas import Market, PricePosition


# 지원 가능 범위를 명시한 결과
@dataclass
class ParsedIpo:
    band_low: Optional[int] = None
    band_high: Optional[int] = None
    final_price: Optional[int] = None
    price_position: Optional[PricePosition] = None

    competition_rate: Optional[float] = None
    competition_rate_type: Optional[Literal["simple", "weighted"]] = None
    demand_quantity: Optional[int] = None
    demand_amount_krw: Optional[int] = None

    lockup_ratio: Optional[float] = None
    lockup_ratio_basis: Optional[Literal["allocated", "applied"]] = None

    tradable_ratio: Optional[float] = None

    new_share_count: Optional[int] = None
    old_share_count: Optional[int] = None
    total_offering_count: Optional[int] = None
    old_share_ratio: Optional[float] = None
    offering_amount_krw: Optional[int] = None   # v0.6 공모 금액

    subscription_start: Optional[str] = None  # YYYY-MM-DD
    subscription_end: Optional[str] = None

    market: Optional[Market] = None           # v0.4 (requirements 10장)
    listing_date: Optional[str] = None        # v0.4 — 원문에 명시 없으면 null (추정 금지)

    warnings: list[str] = field(default_factory=list)


# ---------- 유틸 ----------

_RE_TAG = re.compile(r"<[^>]+>")
_RE_SPACE = re.compile(r"\s+")


def _strip_tags(s: str) -> str:
    return _RE_SPACE.sub(" ", _RE_TAG.sub(" ", s)).strip()


def _to_int(s: str) -> Optional[int]:
    try:
        return int(s.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


# ---------- 밴드 (공모희망가액) ----------

# 두 패턴을 OR: 괄호형(디티에스) 또는 조사형(다비오 "공모희망가액인 12,300원 ~ 16,600원")
_RE_BAND = re.compile(
    r"공모희망가액[^0-9가-힣]{0,10}(?:인|범위|\(|\s)*\s*([0-9,]+)\s*원\s*~\s*([0-9,]+)\s*원"
)


def extract_band(xml: str) -> tuple[Optional[int], Optional[int]]:
    """공모희망가액 (low, high) 추출. 못 뽑으면 (None, None)."""
    text = _strip_tags(xml)
    m = _RE_BAND.search(text)
    if not m:
        return None, None
    return _to_int(m.group(1)), _to_int(m.group(2))


# ---------- 확정 공모가 ----------

_RE_FINAL_PRICE_PATTERNS = [
    re.compile(r"확정공모가액[이에은]?\s*([0-9,]+)\s*원"),
    re.compile(r"확정공모가액\s*:\s*([0-9,]+)\s*원"),
    re.compile(r"확정\s*공모가\s*:\s*([0-9,]+)\s*원"),
]


def extract_final_price(xml: str) -> Optional[int]:
    """`[발행조건확정]` 공시 안의 확정공모가액. 결정 전 공시엔 없음."""
    text = _strip_tags(xml)
    # 최상위 매치만 (가장 먼저 나오는 명시적 선언 사용)
    for pat in _RE_FINAL_PRICE_PATTERNS:
        m = pat.search(text)
        if m:
            return _to_int(m.group(1))
    return None


def classify_price_position(
    band_low: Optional[int],
    band_high: Optional[int],
    final: Optional[int],
) -> Optional[PricePosition]:
    """v0.3: 4값. 밴드 하단도 사용한다. band_low 가 null 이면 하단 비교 불가 → null 반환."""
    if band_high is None or band_low is None or final is None:
        return None
    if final > band_high:
        return "ABOVE_BAND"
    if final == band_high:
        return "TOP_OF_BAND"
    if final >= band_low:
        return "WITHIN_BAND"
    return "BELOW_BAND"


# ---------- 수요예측 결과 (경쟁률·신청수량) ----------

# 테이블 패턴: "건수" / "수량" / "경쟁률" 세 행이 USERMARK 로 하이라이트된 수요예측 결과 표.
# 각 행은 <TR>...<TD>라벨</TD>...<TD>마지막=합계</TD></TR> 구조.
_RE_ROW = re.compile(
    r"<TR[^>]*>(?P<body>.*?)</TR>",
    re.DOTALL | re.IGNORECASE,
)
_RE_CELL = re.compile(
    r"<T[DH][^>]*>(?P<content>.*?)</T[DH]>",
    re.DOTALL | re.IGNORECASE,
)


def _rows_with_label(xml: str, label: str) -> list[list[str]]:
    """첫 셀 텍스트가 label 과 같은 모든 행의 셀 배열."""
    out: list[list[str]] = []
    for tr in _RE_ROW.finditer(xml):
        cells_raw = _RE_CELL.findall(tr.group("body"))
        if not cells_raw:
            continue
        cells = [_strip_tags(c) for c in cells_raw]
        if cells[0] == label:
            out.append(cells)
    return out


def extract_demand_result(xml: str) -> dict:
    """
    수요예측 결과 표에서 (경쟁률, 신청수량 합계) 추출.

    확정 공모가 공시의 "수요예측 결과" 표 구조:
      <TR> 건수 | <건수 10개> | 합계 </TR>
      <TR> 수량 | <수량 10개> | 합계 </TR>
      <TR> 경쟁률 | <경쟁률 10개> | 합계 </TR>

    라벨이 "수량"이 아니고 "참여수량" 등으로 다른 공시가 있을 수 있으나,
    1차 샘플(디티에스) 기준으로는 "수량"·"경쟁률" 고정 라벨.
    """
    result = {
        "competition_rate": None,
        "competition_rate_type": None,
        "demand_quantity": None,
    }

    for cells in _rows_with_label(xml, "경쟁률"):
        last = cells[-1]
        rate = _to_float(last)
        if rate and rate > 0:
            result["competition_rate"] = rate
            # 수요예측 결과 라벨은 단순 수량 경쟁률(건수×1 아님). 실측(디티에스) 기준 simple.
            result["competition_rate_type"] = "simple"
            break

    for cells in _rows_with_label(xml, "수량"):
        last = cells[-1]
        q = _to_int(last)
        if q and q > 0:
            result["demand_quantity"] = q
            break

    return result


# ---------- 청약기간 ----------

_RE_SUBSCRIPTION = re.compile(
    r"청약(?:\s*| )?(?:기간|기일)[^0-9]*"
    r"(\d{4})\s*[-\.년]\s*(\d{1,2})\s*[-\.월]\s*(\d{1,2})\s*일?"
    r"[^0-9]*?"
    r"(\d{4})\s*[-\.년]\s*(\d{1,2})\s*[-\.월]\s*(\d{1,2})"
)


def extract_subscription_dates(xml: str) -> tuple[Optional[str], Optional[str]]:
    text = _strip_tags(xml)
    m = _RE_SUBSCRIPTION.search(text)
    if not m:
        return None, None

    def _d(y, mo, da):
        return f"{int(y):04d}-{int(mo):02d}-{int(da):02d}"

    return _d(m.group(1), m.group(2), m.group(3)), _d(m.group(4), m.group(5), m.group(6))


# ---------- 의무보유확약 비율 (v0.5 보강 — 테이블 집계) ----------

# "(다) 의무보유확약기간별 수요예측 참여내역" 섹션에서:
# - "합계" TR 의 수량 셀 합 = 전체 신청 수량
# - "미확약" TR 의 수량 셀 합 = 미확약 신청 수량
# - 확약 비율(applied) = (전체 - 미확약) / 전체 × 100
# 각 TR 안의 셀은 (건수, 수량, 신청가격) × N기관 → 큰 수(>=1,000,000)만 수량으로 간주해 합산.

# 섹션 끝: (라)/(마)/(바) 또는 "USERMARK=\"0X" + 색상 코드 SPAN(다른 섹션 시작). 티앤이코리아는 "B 0X1814FF" 로 다름.
# 지시 #26: 발행사·주관사마다 섹션 이름이 다름 — 공통 접두 "(다) 의무보유" + 임의 꼬리 + "내역".
#   디티에스(대신): "(다) 의무보유확약기간별 수요예측 참여내역"
#   티앤이코리아(신한): "(다) 의무보유확약기간별 수요예측 참여내역"
#   크리에이츠(삼성): "(다) 의무보유 확약 신청내역"
_RE_LOCKUP_SECTION = re.compile(
    r"\(다\)\s*의무보유[^(]{0,40}?내역(.*?)"
    r"(?=\(라\)|\(마\)|\(바\)|<SPAN\s+USERMARK=\"[^\"]*0X[0-9A-Fa-f]+\"[^>]*>\s*\([가-힣]\))",
    re.DOTALL,
)


def _sum_large_cells_in_row(section: str, label: str, min_value: int = 1_000_000) -> Optional[int]:
    """섹션 안에서 첫 셀 텍스트가 label 과 같은 TR 들의 큰 수(>=min_value) 를 **모두** 합산.

    티앤이코리아처럼 (다) 섹션이 **두 표로 분할**(국내 + 외국)된 경우 두 표의 "미확약"/"합계" TR
    모두를 더해야 한다. 디티에스처럼 1개 표인 경우도 동일하게 동작.
    라벨 매칭은 "번호 접두" 허용: "1. 미확약" / "미확약" / "미 확약" 전부 매치.
    """
    import re as _re
    norm_pat = _re.compile(r"^\s*(?:\d+\.\s*)?(.+?)\s*$")

    total = 0
    found_any = False
    for tr in _RE_ROW.finditer(section):
        cells = [_strip_tags(c) for c in _RE_CELL.findall(tr.group("body"))]
        if not cells:
            continue
        first = cells[0]
        m = norm_pat.match(first)
        if not m or m.group(1).replace(" ", "") != label.replace(" ", ""):
            continue
        for c in cells[1:]:
            n = _to_int(c)
            if n is None or n < min_value:
                continue
            total += n
            found_any = True
    return total if found_any else None


def extract_lockup(xml: str) -> tuple[Optional[float], Optional[Literal["allocated", "applied"]]]:
    """의무보유확약 비율(%) + 기준(신청/배정)."""
    m = _RE_LOCKUP_SECTION.search(xml)
    if not m:
        return None, None
    section = m.group(1)
    total = _sum_large_cells_in_row(section, "합계")
    unlocked = _sum_large_cells_in_row(section, "미확약")
    if total is None or unlocked is None or total <= 0:
        return None, None
    locked = total - unlocked
    if locked < 0:
        return None, None
    return round(locked / total * 100, 2), "applied"


# ---------- 유통가능 비율 (v0.5 — 서술형) ----------

# 예1(디티에스): "약 15.15%에 해당하는 2,250,787주는 상장 직후 유통가능물량입니다"
# 예2(티앤이코리아): "11,357,737주 중 31.27%에 해당하는 3,551,856주는 상장직후 유통가능 물량에 해당됩니다"
# → "약" 선택, "유통가능" 뒤 공백 허용.
_RE_TRADABLE_RATIO_NARRATIVE = re.compile(
    r"(?:약\s*)?([\d.]+)\s*%\s*에\s*해당하는\s*[\d,]+\s*주[^<]{0,40}유통가능\s*물량"
)

# 지시 #26: 삼성증권 형식(크리에이츠) — 순서 반전 "N주는 상장 직후 ... 유통가능 ... %"
# "상기의 의무보유 수량을 제외한 주식수 5,176,832주는 상장 직후 시장에서 유통가능한 물량이며,
#  상장예정주식수 기준으로 39.47%에 해당합니다"
# 핵심 신호: "상장 직후" 근처 + "유통가능" + 그 뒤 N%. 상장 후 N개월 뒤 유통가능 섹션은 "상장 직후" 가 없음.
_RE_TRADABLE_RATIO_NARRATIVE_INVERTED = re.compile(
    r"상장\s*직후[^%<]{0,120}?유통가능[^%<]{0,120}?([\d.]+)\s*%"
)

# fallback: 테이블 "유통가능물량(A-B)" 라벨 셀 뒤 300자 이내에서 "N.NN%" 매치 (첫 매치).
# 중간에 한글 라벨(최대주주/벤처금융 등)이 끼면 다른 섹션이므로 거부.
_RE_TRADABLE_RATIO_TABLE = re.compile(
    r"유통가능물량[^가-힣%]{0,300}?([\d]+\.?\d+)\s*%"
)


def extract_tradable_ratio(xml: str) -> Optional[float]:
    """상장일 유통가능 비율(%). 서술형(2종) → 테이블 fallback 순."""
    text = _strip_tags(xml)
    m = _RE_TRADABLE_RATIO_NARRATIVE.search(text)
    if m:
        return _to_float(m.group(1))
    m_inv = _RE_TRADABLE_RATIO_NARRATIVE_INVERTED.search(text)
    if m_inv:
        return _to_float(m_inv.group(1))
    m2 = _RE_TRADABLE_RATIO_TABLE.search(text)
    if m2:
        return _to_float(m2.group(1))
    return None


# ---------- 시장 구분 (v0.4 / 지시 #25) ----------

_MARKET_NAMES: list[tuple[Market, str]] = [
    ("KOSDAQ", "코스닥"),
    ("KOSPI",  "유가증권"),
    ("KONEX",  "코넥스"),
]

# 지시 #25: 증권발행실적보고서 기업개요 "상장구분" 칸의 값을 **최우선** 명시 신호로 사용.
# 예: "상장구분 기업규모 업종구분 / 코스닥 중소기업 …" 또는 "상장구분 … 코스닥".
# "코스피" 는 "유가증권" 과 같은 KOSPI 로 매핑.
_LISTING_CLASS_TO_MARKET: dict[str, Market] = {
    "코스닥": "KOSDAQ",
    "유가증권": "KOSPI",
    "코스피":  "KOSPI",
    "코넥스": "KONEX",
}
_RE_MARKET_LISTING_CLASS = re.compile(
    r"상장\s*구분[^\n]{0,200}?(코스닥|유가증권|코스피|코넥스)"
)


# 1순위-b: 이번 공모의 상장 대상 시장을 선언하는 서술형.
# 보수적으로 좁게 — "○○시장에 (신규)상장" 서술만 인정.
#   비매치: "코스닥시장 상장규정", "코넥스시장 상장예정법인", "상장일부터"
# 매치 뒤 즉시 "법인/주식/기업/회사/일" 처럼 명사가 이어지면 공모 선언이 아니므로 lookahead 로 제외.
def _explicit_market_patterns() -> list[tuple[Market, re.Pattern]]:
    pats: list[tuple[Market, re.Pattern]] = []
    for market, kor in _MARKET_NAMES:
        pats.append((
            market,
            re.compile(
                rf"{kor}시장에\s*(?:신규\s*)?상장(?!\s*(?:법인|주식|기업|회사|일|예정법인))"
            ),
        ))
    return pats


def extract_market(xml: str, *, dominance_ratio: float = 3.0) -> Optional[Market]:
    """시장 구분 판별. 명시 패턴 1순위, 빈도 fallback(3배 이상 지배적일 때만).

    1순위 명시 패턴은 두 가지:
    - (a) 지시 #25: "상장구분 … (코스닥|유가증권|코스피|코넥스)" (실적보고서·공시명세 테이블).
    - (b) "○○시장에 (신규)상장" 서술 (투자설명서·발행조건확정 본문).

    둘 중 어느 하나라도 **단일 시장**을 가리키면 그 시장. 서로 다른 시장을 가리키면 상충(None).
    1순위가 비면 빈도 fallback 으로 — 단 **1위가 2위의 dominance_ratio 배 이상**일 때만 채택.
    """
    # 1) 명시 패턴 (상장구분 + 서술형)
    hit: set[Market] = set()
    text = _strip_tags(xml)
    m_class = _RE_MARKET_LISTING_CLASS.search(text)
    if m_class:
        kw = m_class.group(1)
        mapped = _LISTING_CLASS_TO_MARKET.get(kw)
        if mapped:
            hit.add(mapped)
    for market, pat in _explicit_market_patterns():
        if pat.search(xml):
            hit.add(market)
    if len(hit) == 1:
        return next(iter(hit))
    if len(hit) >= 2:
        return None   # 상충 — null

    # 2) 빈도 fallback (단순 "○○시장" 전체 매칭)
    counts = [(m, len(re.findall(f"{kor}시장", xml))) for m, kor in _MARKET_NAMES]
    counts.sort(key=lambda c: c[1], reverse=True)
    top_market, top_cnt = counts[0]
    second_cnt = counts[1][1] if len(counts) > 1 else 0
    if top_cnt == 0:
        return None
    if second_cnt == 0 and top_cnt > 0:
        return top_market
    if top_cnt >= second_cnt * dominance_ratio:
        return top_market
    return None


# ---------- 상장일 (v0.4 / 지시 #25) ----------

# 명시적 "상장(예정)일" 선언만 매칭한다. "상장일부터 6개월" 같은 상대 참조는 매칭하지 않는다.
# 지시 #25: 증권발행실적보고서는 "상장일(매매개시일) YYYY년 M월 D일 (예정)" 형식.
# "상장일" 매치 뒤 선택적 "(매매개시일)" 를 흡수해야 날짜가 바로 뒤에서 잡힌다.
_RE_LISTING_DATE = re.compile(
    r"상장\s*"
    r"(?:"
    r"(?:예정)?\s*일(?:자)?\s*(?:\(\s*매매개시일\s*\))?"   # "상장일[자][(매매개시일)?]"
    r"|"
    r"\(\s*매매개시일\s*\)"                                 # "상장(매매개시일)" 단독
    r")"
    r"\s*[:：은는]?\s*"
    r"(\d{4})\s*[-\.년]\s*(\d{1,2})\s*[-\.월]\s*(\d{1,2})\s*일?"
)


def extract_listing_date(xml: str) -> Optional[str]:
    """원문에 "상장(예정)일 YYYY-MM-DD" 또는 "상장일(매매개시일) YYYY-MM-DD" 명시가 있을 때만 반환. 추정 금지.

    주의: 과거 상장일 참조(예: 모회사 상장일, 기준 시점)가 섞여 들어오므로
    호출자(parse)가 rcept_dt / subscription_end 와 비교해 미래 날짜만 수용한다.
    """
    text = _strip_tags(xml)
    m = _RE_LISTING_DATE.search(text)
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


# ---------- 모집·매출 구성 (신주·구주) ----------

_RE_NEW_SHARES = re.compile(r"신주\s*모집[^0-9]{0,20}([0-9,]+)\s*주")
_RE_OLD_SHARES = re.compile(r"구주\s*매출[^0-9]{0,20}([0-9,]+)\s*주")
# 라벨 바로 뒤의 선언형 숫자만 매치. 설명문 안 "공모주식수는..." 같은 조사형은 lookahead 로 차단.
# 다비오("모집 또는 매출주식의 수" / "기명식 보통주 1,000,000주") 패턴도 추가.
_RE_TOTAL_OFFERING = re.compile(
    r"(?:모집\(매출\)\s*주식수|총\s*공모\s*주식\s*수|공모\s*주식\s*총수)"
    r"[^0-9]{0,10}([0-9,]+)\s*주"
    r"|공모주식수(?!\s*(?:는|을|를|이|가|의|에))\s*[:：]?\s*([0-9,]+)\s*주"
    r"|모집\s*(?:또는|및)\s*매출주식의\s*수[^0-9]{0,30}(?:기명식\s*보통주\s*)?([0-9,]+)\s*주"
)
# v0.6 공모 금액 (원문 "모집(매출) 총액" 명시가 있을 때만)
_RE_OFFERING_AMOUNT = re.compile(
    r"(?:모집\(매출\)\s*총액|공모\s*총액)[^0-9]{0,20}([0-9,]+)\s*원"
)


def extract_offering_amount_krw(xml: str) -> Optional[int]:
    """원문의 '모집(매출) 총액' 명시 값만 반환. 추정 금지 — 호출자가 fallback 처리."""
    m = _RE_OFFERING_AMOUNT.search(_strip_tags(xml))
    if not m:
        return None
    return _to_int(m.group(1))


def extract_offering_counts(xml: str) -> dict:
    """신주·구주·총 공모 주식 수 best-effort. 라벨이 다양해 fail-soft."""
    text = _strip_tags(xml)
    new = old = total = None

    mn = _RE_NEW_SHARES.search(text)
    if mn:
        new = _to_int(mn.group(1))
    mo = _RE_OLD_SHARES.search(text)
    if mo:
        old = _to_int(mo.group(1))
    mt = _RE_TOTAL_OFFERING.search(text)
    if mt:
        # alternation 중 매치된 group 선택 (group 1/2/3 OR)
        for g in mt.groups():
            if g is not None:
                total = _to_int(g)
                break

    # 보완: new+old 가 있고 total 없으면 합산, 반대도 가능
    if total is None and new is not None and old is not None:
        total = new + old
    if new is None and total is not None and old is not None:
        new = total - old
    if old is None and total is not None and new is not None:
        old = total - new

    return {"new": new, "old": old, "total": total}


# ---------- 통합 파서 ----------

def parse(
    xml_bytes: bytes,
    *,
    rcept_no: str = "",
    corp_name: str = "",
    rcept_dt: Optional[str] = None,
) -> ParsedIpo:
    """원문 XML(bytes) 을 받아 ParsedIpo 반환. 실패는 warnings 로 집약."""
    try:
        xml = xml_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ParsedIpo(warnings=["원문 XML 인코딩이 UTF-8 아님 — 파싱 중단"])

    out = ParsedIpo()

    # 밴드
    low, high = extract_band(xml)
    out.band_low, out.band_high = low, high
    if low is None or high is None:
        out.warnings.append("공모희망가액(밴드) 패턴을 찾지 못함")

    # 확정 공모가 (발행조건확정 공시에만 있음)
    out.final_price = extract_final_price(xml)
    if out.final_price is None:
        out.warnings.append("확정공모가액을 찾지 못함 (발행조건확정 단계 전일 수 있음)")

    # 공모가 위치
    out.price_position = classify_price_position(low, high, out.final_price)

    # 수요예측 결과
    demand = extract_demand_result(xml)
    out.competition_rate = demand["competition_rate"]
    out.competition_rate_type = demand["competition_rate_type"]
    out.demand_quantity = demand["demand_quantity"]
    if out.competition_rate is None:
        out.warnings.append("기관 수요예측 경쟁률을 찾지 못함")
    if out.demand_quantity is None:
        out.warnings.append("기관 수요예측 신청수량을 찾지 못함")

    # 신청 금액(원) = 신청 수량(주) × 확정가 (확정가 없으면 band_high 로 추정하지 않고 null)
    if out.demand_quantity is not None and out.final_price is not None:
        out.demand_amount_krw = out.demand_quantity * out.final_price
    else:
        out.demand_amount_krw = None
        out.warnings.append(
            "기관 신청 금액은 OpenDART 원문에 별도 명시가 없어 '수량 × 확정가' 로만 산출 — "
            "수량 또는 확정가 미공시로 null"
        )

    # 청약기간
    s, e = extract_subscription_dates(xml)
    out.subscription_start, out.subscription_end = s, e
    if s is None or e is None:
        out.warnings.append("청약기간 날짜를 찾지 못함")

    # 시장 구분 (v0.4) — Settings 의 지배 비율 사용
    from .config import get_settings
    out.market = extract_market(xml, dominance_ratio=get_settings().market_dominance_ratio)
    if out.market is None:
        out.warnings.append(
            "시장 구분 미결정 — 명시 패턴 상충/부재이거나 빈도 지배 비율 미달 (null 유지, 추정 금지)"
        )

    # 상장일 (v0.4 + v0.5 fix) — 명시 없으면 null, 과거 날짜(접수일/청약종료일 이전)도 null
    raw_listing = extract_listing_date(xml)
    if raw_listing is None:
        out.warnings.append(
            "상장(예정)일 명시 문구를 찾지 못함 — null 유지 (추정 금지)"
        )
    else:
        min_date_candidates = [d for d in (rcept_dt, out.subscription_end) if d]
        min_date = max(min_date_candidates) if min_date_candidates else None
        if min_date and raw_listing < min_date:
            out.warnings.append(
                f"상장일 후보 {raw_listing} 가 기준일 {min_date} 이전 — 과거 참조로 간주하여 null"
            )
            raw_listing = None
    out.listing_date = raw_listing

    # 모집·매출 구성
    off = extract_offering_counts(xml)
    out.new_share_count = off["new"]
    out.old_share_count = off["old"]
    out.total_offering_count = off["total"]
    if out.total_offering_count:
        if out.old_share_count is not None:
            out.old_share_ratio = round(out.old_share_count / out.total_offering_count * 100, 2)
    else:
        out.warnings.append("모집(매출) 주식 수 구성을 찾지 못함")

    # 공모 금액 (v0.6 + 다비오 수정):
    # (1) 원문 "모집(매출) 총액" 매치 → 타당성 검사(수량×밴드하단의 min_ratio, 또는 min_absolute 이상)
    # (2) 거부 또는 미매치 시 total_offering_count × final_price
    # (3) 둘 다 없으면 null
    from .config import get_settings as _get_settings
    _s = _get_settings()
    explicit_amount = extract_offering_amount_krw(xml)
    if explicit_amount is not None:
        min_abs = _s.offering_amount_min_absolute_krw
        min_rel = None
        if out.total_offering_count is not None and out.band_low is not None:
            min_rel = int(out.total_offering_count * out.band_low * _s.offering_amount_min_ratio_vs_band_low)
        min_required = max(min_abs, min_rel or 0)
        if explicit_amount < min_required:
            out.warnings.append(
                f"원문 매치 공모 금액 {explicit_amount:,}원 이 타당성 기준({min_required:,}원) 미달 "
                f"— 명시값 거부, fallback 산출로 전환"
            )
            explicit_amount = None
    if explicit_amount is not None:
        out.offering_amount_krw = explicit_amount
    elif out.total_offering_count is not None and out.final_price is not None:
        out.offering_amount_krw = out.total_offering_count * out.final_price
    elif out.total_offering_count is not None and out.band_low is not None:
        # 확정가 전 단계라도 밴드 하단으로 하한 추정 — pm 가산 기준(≥1000억) 판단은 **하한** 쪽이 보수적
        out.offering_amount_krw = out.total_offering_count * out.band_low
        out.warnings.append(
            "공모 금액: 확정가 전이라 band_low × total_offering_count 로 보수 추정 (가산 판단은 하한 기준)"
        )
    else:
        out.offering_amount_krw = None
        out.warnings.append("공모 금액(모집 총액)을 산출하지 못함 — 원문 명시도, 총수량·확정가/밴드도 없음")

    # 유통가능 비율 (v0.5 — 서술형 추출)
    out.tradable_ratio = extract_tradable_ratio(xml)
    if out.tradable_ratio is None:
        out.warnings.append(
            "유통가능 비율 서술형 패턴을 찾지 못함 — null 유지 (테이블 추출은 보강 과제)"
        )

    # 의무보유확약 비율 (v0.5 보강) — (다) 섹션 합계·미확약 TR 집계
    lockup_r, lockup_basis = extract_lockup(xml)
    out.lockup_ratio = lockup_r
    out.lockup_ratio_basis = lockup_basis
    if lockup_r is None:
        out.warnings.append(
            "의무보유확약 비율 테이블(다)에서 합계/미확약 수량을 집계하지 못함 — null 유지"
        )

    # 메타 보조 로그
    if rcept_no:
        out.warnings = [f"[{rcept_no} {corp_name}] " + w for w in out.warnings]

    return out
