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

    # v1.1 (지시 #20): 공모 일정
    price_confirm_date: Optional[str] = None       # 공모가 확정공고일 (= [발행조건확정] 공시 공개일)
    demand_forecast_start: Optional[str] = None    # 수요예측 시작일
    demand_forecast_end: Optional[str] = None      # 수요예측 종료일

    # v1.2 (지시 #21): 주관사·인수회사 이름 목록 (대표→공동→인수 순, 중복 제거). 수량·금액 없음.
    underwriters: list[str] = field(default_factory=list)

    warnings: list[str] = field(default_factory=list)


# ---------- 유틸 ----------

_RE_TAG = re.compile(r"<[^>]+>")
_RE_SPACE = re.compile(r"\s+")


def _strip_tags(s: str) -> str:
    return _RE_SPACE.sub(" ", _RE_TAG.sub(" ", s)).strip()


# 지시 #42: 정정 신고서는 서두 정정표(약 2.5만 자) 안에 '정정전'/'정정후' 블록이 번갈아 나와
# "정정전 섹션만 제거" 방식(v22 greedy·v23 non-greedy 모두)으로는 안정적으로 분리 불가.
# **"대표이사 등의 확인" 첫 등장 이후 = 본문** — 본문에만 새 일정이 있음(pm 실측).
# 비정정 문서는 마커가 없거나 처음에 등장하므로 전체 텍스트 사용.
_RE_BODY_MARKER = re.compile(r"대표이사\s*등의\s*확인")


def _extract_body_text(text: str) -> str:
    """정정 신고서 서두 정정표를 skip 하고 본문만 반환.

    "대표이사 등의 확인" 첫 등장 이후 = 본문(새 일정만 포함).
    마커가 없으면 원문 전체 유지(비정정 문서).
    """
    m = _RE_BODY_MARKER.search(text)
    if m:
        return text[m.end():]
    return text


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
# 지시 #39: 어순 변형 "희망공모가액인 10,000원~13,000원" (씨앤엠) 수용.
_RE_BAND = re.compile(
    r"(?:공모희망가액|희망공모가액)[^0-9가-힣]{0,10}(?:인|범위|\(|\s)*\s*([0-9,]+)\s*원\s*~\s*([0-9,]+)\s*원"
)


def extract_band(xml: str) -> tuple[Optional[int], Optional[int]]:
    """공모희망가액 (low, high) 추출. 못 뽑으면 (None, None).

    지시 #42: 정정 신고서 서두 정정표는 제외하고 본문에서만 추출.
    """
    text = _extract_body_text(_strip_tags(xml))
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

# 지시 #40 (아델): "확정공모가액이 N원 이상으로 결정되어 … 경우" 같은 **가정·조건 문장**은 제외.
# 매치된 "N원" 바로 뒤 20자 안에 아래 접미가 오면 조건문으로 간주하고 skip.
_RE_FINAL_PRICE_ASSUMPTION_SUFFIX = re.compile(
    r"\s*(?:이상|이하|미만|초과|경우|되어|되는|이라면|이라고|기준으로\s*(?:산정|계산))"
)


def extract_final_price(xml: str) -> Optional[int]:
    """`[발행조건확정]` 공시 안의 확정공모가액. 결정 전 공시엔 없음.

    지시 #40: 조건문 "확정공모가액이 N원 이상으로 결정되어 … 경우" 는 가정 서술이므로 제외한다
    (아델 사례 — 상장주선인 의무보유 주석의 가정문을 확정가로 오인).
    """
    text = _strip_tags(xml)
    for pat in _RE_FINAL_PRICE_PATTERNS:
        # finditer 로 전수 탐색 — 가정문 접미사 window 검사 후 유효한 매치만 수용
        for m in pat.finditer(text):
            tail = text[m.end():m.end() + 20]
            if _RE_FINAL_PRICE_ASSUMPTION_SUFFIX.match(tail):
                continue  # 가정·조건문 — skip
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
    # 지시 #39: 정정 신고서 "정 정 전" 섹션 제거 — 최신 일정만 매치.
    text = _extract_body_text(_strip_tags(xml))
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
    """의무보유확약 비율(%) + 기준(신청/배정).

    라벨 변형 수용 (실측 — 지시 (정확도 보강 #3)):
    - "합계" / "합 계" (디티에스·티앤이·크리에이츠·엠에스바이오)
    - **"합"** 한 글자 (엘리스그룹)
    """
    m = _RE_LOCKUP_SECTION.search(xml)
    if not m:
        return None, None
    section = m.group(1)
    # 엘리스 등: COLSPAN 처리로 "합 계" 가 두 셀 "합" + "계" 로 분리되어 cells[0]="계" 로 들어옴
    total = _sum_large_cells_in_row(section, "합계")
    for alt in ("합", "계"):
        if total is None:
            total = _sum_large_cells_in_row(section, alt)
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
# 지시 #38: 숫자 캡처에 쉼표도 허용 — 원문 오타 "37,68%" (이에스티 사례) 수용 후 _parse_pct 가 소수점으로 변환.
# 지시 #39: "유통가능" / "유통 가능" 띄어쓰기 변형 수용 (씨앤엠 "유통 가능한 물량").
_RE_TRADABLE_RATIO_NARRATIVE = re.compile(
    r"(?:약\s*)?([\d.,]+)\s*%\s*에\s*해당하는\s*[\d,]+\s*주[^<]{0,40}유통\s*가능\s*물량"
)

# 지시 #26: 삼성증권 형식(크리에이츠) — 순서 반전 "N주는 상장 직후 ... 유통가능 ... %"
_RE_TRADABLE_RATIO_NARRATIVE_INVERTED = re.compile(
    r"상장\s*직후[^%<]{0,120}?유통\s*가능[^%<]{0,120}?([\d.,]+)\s*%"
)

# 정확도 보강 (#1): 엠에스바이오 형식 — "주식수 N주(N.NN%)는 상장 직후 시장에서 유통가능한 물량입니다"
# 지시 #39: 괄호 안에 "공모 후" 같은 라벨이 끼는 포맷(씨앤엠) 수용 — "N주(공모 후 N%)".
_RE_TRADABLE_RATIO_NARRATIVE_PAREN = re.compile(
    r"[\d,]+\s*주\s*\(\s*(?:[^0-9%)]{0,20})?([\d.,]+)\s*%\s*\)[^%<]{0,60}상장\s*직후[^%<]{0,40}유통\s*가능"
)

# 지시 #38: 이에스티 서술 — "상장일 유통가능 물량은 N주(상장일 기준 N,NN%)"
# "유통가능 물량은" 뒤 N주 + 괄호 안 % 표기. 쉼표가 소수점을 대신하는 오타 수용.
_RE_TRADABLE_RATIO_NARRATIVE_ESTAT = re.compile(
    r"상장일\s*유통\s*가능\s*물량[^<%]{0,20}?[\d,]+\s*주\s*\([^%<]{0,30}?([\d.,]+)\s*%\s*\)"
)

# fallback: 테이블 "유통가능물량(A-B)" 라벨 셀 뒤 300자 이내에서 "N.NN%" 매치 (첫 매치).
_RE_TRADABLE_RATIO_TABLE = re.compile(
    r"유통\s*가능물량[^가-힣%]{0,300}?([\d]+[.,]?\d+)\s*%"
)

# 지시 #39: 부분값 서술 라벨 — "기존 주주의 유통가능", "상장 전 유통가능", "공모주주 유통가능" 등은
# 전체 유통 비율이 아니라 부분값(씨앤엠 36.25% = 기존 주주의 유통가능 물량). 매치 window 안에
# 이런 라벨이 있으면 skip 하고 다음 매치 후보로 넘어간다.
_RE_PARTIAL_FLOW_HINT = re.compile(
    r"기존\s*주주|상장\s*전\s*유통|보호예수\s*제외|공모주주\s*유통"
)


def _parse_pct(s: Optional[str]) -> Optional[float]:
    """퍼센트 문자열 → float. 지시 #38: 쉼표가 소수점을 대신하는 오타("37,68") 수용.

    규칙:
    - "." 포함: 기존대로 쉼표(천 단위) 제거 후 float
    - "," 포함 + "." 없음: 쉼표를 소수점으로 간주 ("37,68" → 37.68)
    - 결과가 0~100 범위 밖이면 null (추정 금지)
    """
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    if "." in s:
        v = _to_float(s)
    elif "," in s:
        # 쉼표를 소수점으로 간주 (오타 수용)
        try:
            v = float(s.replace(",", "."))
        except ValueError:
            return None
    else:
        v = _to_float(s)
    if v is None:
        return None
    if 0 <= v <= 100:
        return v
    return None


def _tradable_match_valid(text: str, m: "re.Match") -> bool:
    """지시 #39: 매치 **직전 40자** 안에 부분값 라벨 ("기존 주주" 등) 이 있으면 부분값 서술로 간주, False.

    window 를 좁게 잡아 다른 매치 후보의 라벨이 끼지 않게 한다.
    """
    s = max(0, m.start() - 40)
    window = text[s:m.start()]
    return _RE_PARTIAL_FLOW_HINT.search(window) is None


def _first_valid_pct(text: str, pattern: "re.Pattern") -> Optional[float]:
    """pattern.finditer 로 전수 탐색 — 부분값 라벨 window 는 skip, 첫 유효 매치 반환."""
    for m in pattern.finditer(text):
        if _tradable_match_valid(text, m):
            v = _parse_pct(m.group(1))
            if v is not None:
                return v
    return None


def extract_tradable_ratio(xml: str) -> Optional[float]:
    """상장일 유통가능 비율(%). 서술형(4종) → 테이블 fallback 순.

    지시 #39: 매치 window 안에 "기존 주주" 등 부분값 라벨이 있으면 skip 하고
    다음 유효 매치를 찾는다. 씨앤엠(36.25% 부분값 → 45.75% 전체) 복구.
    """
    text = _strip_tags(xml)
    for pattern in (
        _RE_TRADABLE_RATIO_NARRATIVE,
        _RE_TRADABLE_RATIO_NARRATIVE_PAREN,
        _RE_TRADABLE_RATIO_NARRATIVE_INVERTED,
        _RE_TRADABLE_RATIO_NARRATIVE_ESTAT,
        _RE_TRADABLE_RATIO_TABLE,
    ):
        v = _first_valid_pct(text, pattern)
        if v is not None:
            return v
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
    # 지시 #39: 정정 신고서 "정 정 전" 섹션 제거.
    text = _extract_body_text(_strip_tags(xml))
    m = _RE_LISTING_DATE.search(text)
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


# ---------- 공모가 확정공고일 (지시 #20 / v1.1) ----------

# "공모가액 확정공고 YYYY년 M월 D일" / "모집 또는 매출가액 확정의 공고 YYYY년 M월 D일" 등.
# collect 가 명시 매치 실패 시 발행조건확정 접수일로 fallback.
_RE_PRICE_CONFIRM_DATE = re.compile(
    r"(?:공모가액|모집(?:\s*(?:또는|·|,)\s*매출)?\s*가액)"
    r"\s*확정(?:의)?\s*공고(?:일)?"
    r"[^\d]{0,20}"
    r"(\d{4})\s*[-\.년]\s*(\d{1,2})\s*[-\.월]\s*(\d{1,2})\s*일?"
)


def extract_price_confirm_date(xml: str) -> Optional[str]:
    """본문 명시 "공모가액 확정공고 YYYY-MM-DD" 등. 없으면 None."""
    # 지시 #39: 정정 신고서 "정 정 전" 섹션 제거.
    text = _extract_body_text(_strip_tags(xml))
    m = _RE_PRICE_CONFIRM_DATE.search(text)
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


# ---------- 주관사·인수회사 (지시 #21 / v1.2) ----------

# 공식 API estkRs 는 IPO 증권신고서를 반환하지 않음(실측 0건) → 원본 XML 서술 매치로.
# 매치 범위:
#   - "대표주관회사(인|는|로|가)? ○○증권(주식회사)?" / "...인 ㈜○○"
#   - "공동주관회사" / "공동대표주관회사" / "인수회사" (수량·금액은 쓰지 않음 — pm 지시)
_RE_UW_LEAD = re.compile(
    r"대표\s*주관\s*회사(?:인|는|로|가)?\s*(?:(?:㈜|주식회사)\s*)?([가-힣A-Za-z]{1,15}(?:증권))"
)
_RE_UW_JOINT = re.compile(
    r"(?:공동\s*대표\s*주관\s*회사|공동\s*주관\s*회사)(?:인|는|로|가)?\s*(?:(?:㈜|주식회사)\s*)?([가-힣A-Za-z]{1,15}(?:증권))"
)
_RE_UW_SUB = re.compile(
    r"인수\s*회사(?:인|는|로|가)?\s*(?:(?:㈜|주식회사)\s*)?([가-힣A-Za-z]{1,15}(?:증권))"
)


def _normalize_underwriter(name: str) -> str:
    name = re.sub(r"\s+", "", name).strip()
    # 꼬리 "주식회사" / "㈜" 제거
    name = re.sub(r"(?:주식회사|㈜)$", "", name)
    return name


def extract_underwriters(xml: str) -> list[str]:
    """지시 #21 (v1.2): 주관사·인수회사 이름 목록. 대표 → 공동 → 인수 순, 중복 제거.

    estkRs API 가 IPO 증권신고서를 반환하지 않아 원문 서술 매치로 추출(실측 결정).
    수량·금액은 쓰지 않는다(크리에이츠 udtcnt 1,400,000,000 이상값 사례).
    """
    text = _strip_tags(xml)
    leads = [_normalize_underwriter(m.group(1)) for m in _RE_UW_LEAD.finditer(text)]
    joints = [_normalize_underwriter(m.group(1)) for m in _RE_UW_JOINT.finditer(text)]
    subs = [_normalize_underwriter(m.group(1)) for m in _RE_UW_SUB.finditer(text)]
    seen: set[str] = set()
    out: list[str] = []
    for name in leads + joints + subs:
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


# ---------- 수요예측 기간 (지시 #20 / v1.1) ----------

# "수요예측 기간: 2026년 10월 15일 ~ 2026년 10월 16일" / "수요예측기간 ..." / "기관투자자 수요예측 기간 ..."
# 지시 (정확도 보강): "수요예측 일시 2026년 10월 12일(월) ~ 2026년 10월 16일(금)" — "일시" 라벨 + 요일 괄호 수용.
# 연도 반복 생략 포맷도 지원: "2026년 10월 15일 ~ 10월 16일".
_RE_DEMAND_FORECAST = re.compile(
    r"수요예측\s*(?:실시|일시)?\s*(?:기간)?"
    r"[^\d<]{0,40}"
    r"(\d{4})\s*[-\.년]\s*(\d{1,2})\s*[-\.월]\s*(\d{1,2})\s*일?"
    r"\s*(?:\(\s*[월화수목금토일]\s*\))?"       # 요일 괄호 선택
    r"\s*(?:~|부터|-)\s*"
    r"(?:(\d{4})\s*[-\.년]\s*)?(\d{1,2})\s*[-\.월]\s*(\d{1,2})\s*일?"
    r"\s*(?:\(\s*[월화수목금토일]\s*\))?"
)


def extract_demand_forecast_period(xml: str) -> tuple[Optional[str], Optional[str]]:
    """본문 명시 수요예측 시작·종료일. 없으면 (None, None)."""
    # 지시 #39: 정정 신고서 "정 정 전" 섹션 제거.
    text = _extract_body_text(_strip_tags(xml))
    m = _RE_DEMAND_FORECAST.search(text)
    if not m:
        return None, None
    y1, mo1, d1 = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y2 = int(m.group(4)) if m.group(4) else y1
    mo2, d2 = int(m.group(5)), int(m.group(6))
    start = f"{y1:04d}-{mo1:02d}-{d1:02d}"
    end = f"{y2:04d}-{mo2:02d}-{d2:02d}"
    return start, end


# ---------- 모집·매출 구성 (신주·구주) ----------

# 지시 #38: 라벨 뒤에 "유입자금|자금|총액|금액|금" (상대가치 평가표의 금액성 서술) 가 붙으면
# 매치를 **차단** 한다. 영광 오류("신주모집유입자금 (E) 32,589,200") 재발 방지.
# 수량 라벨(수량|주식(의) 수) 은 여전히 **optional** — "신주모집 1,000,000주" 같은 단순 표기 유지.
_RE_NEW_SHARES = re.compile(
    r"신주\s*모집(?!유입|자금|총액|금액|금)"
    r"(?:\s*(?:수량|주식(?:의)?\s*수))?[^0-9]{0,20}([0-9,]+)\s*주"
)
_RE_OLD_SHARES = re.compile(
    r"구주\s*매출(?!유입|자금|총액|금액|금)"
    r"(?:\s*(?:수량|주식(?:의)?\s*수))?[^0-9]{0,20}([0-9,]+)\s*주"
)
# 지시 #39: 구주매출 없음 서술 — 매치되면 old=0 으로 간주.
# "구주매출 없이", "구주매출 해당사항 없음", "구주매출 없음".
_RE_NO_OLD_SHARES = re.compile(
    r"구주\s*매출\s*(?:없이|없음|해당\s*(?:사항)?\s*없)"
)
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
    """신주·구주·총 공모 주식 수 best-effort. 라벨이 다양해 fail-soft.

    지시 #38: 범위 검증을 수행한다 — 음수·total 초과·합 불일치는 추정 금지(null).
    지시 #39: "구주매출 없이" 등 명시 서술이 있으면 old=0 강제 (regex 오매치 보호).
    """
    text = _strip_tags(xml)
    new = old = total = None
    warnings: list[str] = []

    # 지시 #39: 구주매출 없음 서술 → old=0 (명시 신호 — regex 오매치보다 신뢰도 높음)
    no_old_hint = bool(_RE_NO_OLD_SHARES.search(text))

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

    # 지시 #39: 구주매출 없음 명시 — 기존 regex old 값 폐기, 0 으로 설정
    if no_old_hint:
        if old is not None and old != 0:
            warnings.append(f"구주매출 없음 명시 — regex old({old}) 폐기 → 0")
        old = 0

    # 보완: new+old 가 있고 total 없으면 합산, 반대도 가능
    if total is None and new is not None and old is not None:
        total = new + old
    if new is None and total is not None and old is not None:
        new = total - old
    if old is None and total is not None and new is not None:
        old = total - new

    # 지시 #38: 범위 검증. 음수·total 초과·합 불일치는 **null + warning**.
    if new is not None and new < 0:
        warnings.append(f"신주 수 음수({new}) — 평가표 등 잘못된 매치 가능성, null")
        new = None
    if old is not None and old < 0:
        warnings.append(f"구주 수 음수({old}) — null")
        old = None
    if total is not None and total <= 0:
        warnings.append(f"총 공모 주식 수 비정상({total}) — null")
        total = None
    if new is not None and total is not None and new > total:
        warnings.append(f"신주 수({new}) > 총 공모 주식 수({total}) — 라벨 매치 오류, null")
        new = None
    if old is not None and total is not None and old > total:
        warnings.append(f"구주 수({old}) > 총 공모 주식 수({total}) — null")
        old = None
    if new is not None and old is not None and total is not None and new + old != total:
        warnings.append(
            f"신주({new}) + 구주({old}) = {new + old} ≠ 총({total}) — 둘 중 잘못 매치, 신주·구주 null"
        )
        new = None
        old = None

    return {"new": new, "old": old, "total": total, "warnings": warnings}


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
    # 지시 #38: 범위 검증 warning 전파
    for w in off.get("warnings", []):
        out.warnings.append(w)
    if out.total_offering_count:
        if out.old_share_count is not None:
            ratio = round(out.old_share_count / out.total_offering_count * 100, 2)
            # 지시 #38: 비율 범위 검증 — 0~100 외는 null
            if 0 <= ratio <= 100:
                out.old_share_ratio = ratio
            else:
                out.warnings.append(f"구주매출 비율({ratio}%) 범위 밖 — null")
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
    # 지시 #75aebc23 + #29: 공모 금액 산출 규칙
    # 1) final_price 없음 → **null** (band_low 추정·"최저가액 기준(예정)" 명시 모두 거부)
    # 2) final_price 있고 total_offering_count 있으면 → **total × final_price 우선**
    #    (원문 "모집(매출)총액" 매치가 신고서의 '최저가액 기준 예정 총액' 을 확정 후에도 담고 있어 신뢰 불가)
    # 3) final_price 있고 total 없으면 → explicit_amount (최후 수단)
    if out.final_price is None:
        out.offering_amount_krw = None
        if explicit_amount is not None:
            out.warnings.append(
                f"공모 금액 원문 매치값 {explicit_amount:,}원 이 '최저가액 기준(예정)' 가능성 — "
                "확정가 전이라 null 유지"
            )
        else:
            out.warnings.append("공모 금액: 확정가 전이라 null (band_low 추정 제거)")
    elif out.total_offering_count is not None:
        # 재계산 우선 — 원문 explicit 는 "최저가액 기준(예정)" 가능성이 있어 신뢰 안 함(지시 #29)
        out.offering_amount_krw = out.total_offering_count * out.final_price
        if explicit_amount is not None and explicit_amount != out.offering_amount_krw:
            out.warnings.append(
                f"공모 금액: 원문 명시 {explicit_amount:,}원 과 total×final "
                f"{out.offering_amount_krw:,}원 불일치 — 재계산값 채택(지시 #29)"
            )
    elif explicit_amount is not None:
        out.offering_amount_krw = explicit_amount
        out.warnings.append("공모 금액: total 없이 원문 명시값 사용 — 신뢰도 낮음")
    else:
        out.offering_amount_krw = None
        out.warnings.append("공모 금액: 확정가 있으나 원문·총수량 모두 없음 — null")

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

    # 지시 #20 / v1.1: 공모가 확정공고일 + 수요예측 기간 (명시 매치, 없으면 null)
    out.price_confirm_date = extract_price_confirm_date(xml)
    ds, de = extract_demand_forecast_period(xml)
    out.demand_forecast_start = ds
    out.demand_forecast_end = de

    # 지시 #21 / v1.2: 주관사·인수회사 이름
    out.underwriters = extract_underwriters(xml)

    # 메타 보조 로그
    if rcept_no:
        out.warnings = [f"[{rcept_no} {corp_name}] " + w for w in out.warnings]

    return out
