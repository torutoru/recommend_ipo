"""pm 일일 검증: 운영 수집 실행 → 전 종목 API 값을 DART 원문과 대조 → 점수·체크리스트 독립 재계산.

실행: backend/.venv/Scripts/python.exe -I .claude/co-work/tools/daily_check.py [--no-collect]
출력: .claude/co-work/daily-check/YYYY-MM-DD.md (요약·불일치 표), 원문 캐시 daily-check/cache/
DART 키는 backend/.env.local 에서 읽기만 하고 출력·기록하지 않는다.

판정: OK(일치) / MISMATCH(불일치) / NOT_FOUND(원문에서 정규식으로 못 찾음 → pm 이 원문 직접 확인)
       / SANITY(값 자체가 불가능 — 음수·합 불일치 등).
MISMATCH·NOT_FOUND·SANITY 는 pm 이 원문을 열어 실제 파싱 오류인지 판단한 뒤 backend 에 수정 요청한다.
"""
from __future__ import annotations

import html
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
API = "https://recommend-ipo-api.onrender.com"
OUT_DIR = ROOT / ".claude" / "co-work" / "daily-check"
CACHE = OUT_DIR / "cache"
CFG = yaml.safe_load((ROOT / "backend" / "app" / "config_files" / "scoring.yaml").read_text(encoding="utf-8"))


def _key() -> str:
    for line in (ROOT / "backend" / ".env.local").read_text(encoding="utf-8").splitlines():
        if line.startswith("DART_CERT_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("DART_CERT_KEY 없음")


def http_json(url: str, method: str = "GET", timeout: int = 90, tries: int = 4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8")
                return r.status, (json.loads(body) if body.strip() else None)
        except Exception as e:  # Render 슬립 깨우기 등
            last = e
            time.sleep(10 * (i + 1))
    raise RuntimeError(f"{url} 실패: {type(last).__name__}")


# ---------- 원문 ----------

def doc_text(rcept_no: str, key: str) -> str | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{rcept_no}.txt"
    if f.exists():
        return f.read_text(encoding="utf-8")
    url = "https://opendart.fss.or.kr/api/document.xml?" + urllib.parse.urlencode(
        {"crtfc_key": key, "rcept_no": rcept_no})
    try:
        data = urllib.request.urlopen(url, timeout=90).read()
        z = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        return None
    parts = []
    for n in z.namelist():
        raw = z.read(n)
        for enc in ("utf-8", "cp949"):
            try:
                parts.append(raw.decode(enc))
                break
            except UnicodeDecodeError:
                continue
    t = re.sub(r"<[^>]+>", " ", " ".join(parts))
    t = re.sub(r"\s+", " ", html.unescape(t))
    f.write_text(t, encoding="utf-8")
    return t


def num(s: str) -> float:
    return float(s.replace(",", ""))


def ymd(y, m, d) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def most_common(vals):
    vals = [v for v in vals if v is not None]
    return Counter(vals).most_common(1)[0][0] if vals else None


DATE = r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일"


def ext_band(t):
    pairs = re.findall(r"(?:희망공모가액|공모희망가액|희망 공모가액)[^0-9]{0,40}?([\d,]{4,})\s*원\s*~\s*([\d,]{4,})\s*원", t)
    return most_common([(int(num(a)), int(num(b))) for a, b in pairs])


def ext_final(t):
    c = re.findall(r"확정공모가액(?:은|인|을|:)?\s*(?:1주당\s*)?([\d,]{4,})\s*원", t)
    c += re.findall(r"확정공모가액을\s*([\d,]{4,})\s*원으로", t)
    c += re.findall(r"([\d,]{4,})\s*원으로\s*최종\s*결정", t)
    return most_common([int(num(x)) for x in c])


def ext_demand(t):
    out = []
    for m in re.finditer(r"수요예측\s*(?:예정일|일시|기간|일|실시일)\s*(?:은|는|:|인)?[^.。]{0,20}?" + DATE + r"\s*(?:\([^)]{1,3}\))?\s*~\s*(?:(\d{4})\s*년\s*)?(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일", t):
        y, mo, d, y2, mo2, d2 = m.groups()
        out.append((ymd(y, mo, d), ymd(y2 or y, mo2 or mo, d2)))
    return most_common(out)


def ext_subscription(t):
    out = []
    for m in re.finditer(r"청약(?:기일|일|기간|\s*예정일)[^.。]{0,40}?" + DATE + r"\s*(?:\([^)]{1,3}\))?\s*(?:~|,)\s*(?:(\d{4})\s*년\s*)?(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일", t):
        y, mo, d, y2, mo2, d2 = m.groups()
        out.append((ymd(y, mo, d), ymd(y2 or y, mo2 or mo, d2)))
    return most_common(out)


def ext_confirm(t):
    c = re.findall(r"(?:공모가액\s*확정공고|확정의\s*공고|공모가격\s*확정\s*공고)[^0-9]{0,30}" + DATE, t)
    return most_common([ymd(*g) for g in c])


def ext_listing(t):
    c = re.findall(r"상장일\s*\(?\s*매매개시일\s*\)?[^0-9]{0,30}(\d{4})\s*[.년\-/]\s*(\d{1,2})\s*[.월\-/]\s*(\d{1,2})", t)
    return most_common([ymd(*g) for g in c])


def ext_competition(t):
    c = []
    for m in re.finditer(r"경쟁률\s*(?:\(\s*주\s*\d+\s*\))?((?:\s+(?:[\d,]+\.\d+|[\d,]+|-))+)", t):
        nums = [x for x in m.group(1).split() if x != "-"]
        if nums and "." in nums[-1]:
            c.append(num(nums[-1]))
    return max(c) if c else None


def ext_lockup(t):
    """확약기간별 표의 마지막 '미확약 … 합 계 …' 블록에서 합계 열(마지막 수량) 사용 — 신청 수량 기준."""
    # 미확약 행과 합계 행 사이에 다른 확약기간 행(15일 확약 등)이 낄 수 있다.
    # 마지막 미확약 행의 숫자열과 그 뒤 첫 합계 행의 숫자열에서 끝에서 두 번째(=합계 열 수량)를 쓴다.
    # 후보가 여럿이면(국내·외국 표, 본문 언급 등) 합계 수량이 가장 큰 쌍 = 전체 합계 열.
    # "15일 확약"·"1개월 확약" 같은 다음 행 라벨의 숫자는 행에 넣지 않는다
    row = r"((?:\s+(?:[\d,]+(?![\d,]*\s*(?:일|개월))|-))+)"
    best = None
    for m in re.finditer(r"미확약" + row, t):
        s = re.compile(r"합\s*계" + row).search(t, m.end(), m.end() + 3000)
        if not s:
            continue
        u = [x for x in m.group(1).split() if x != "-"]
        v = [x for x in s.group(1).split() if x != "-"]
        if len(u) >= 3 and len(v) >= 3:
            unc, tot = num(u[-2]), num(v[-2])
            if tot > 0 and 0 < unc <= tot and (best is None or tot > best[1]):
                best = (unc, tot)
    return round((best[1] - best[0]) / best[1] * 100, 2) if best else None


def ext_tradable(t):
    """상장 직후(상장일) 전체 유통가능 비율. '기존 주주의' 부분값은 뒤에 '상장 직후'가 안 붙어 자연히 제외."""
    pct = r"(\d{1,3}[.,]\d{1,2})\s*%"
    pats = [
        pct + r"\s*에\s*해당하는\s*[\d,]+\s*주\s*(?:는|은)?\s*(?:상장\s*직후|상장일)",
        r"[\d,]+\s*주\s*\(\s*(?:공모\s*후\s*|상장일\s*기준\s*)?" + pct + r"\s*\)\s*(?:는|은|가|이)?\s*상장\s*직후",
        r"상장일\s*유통가능\s*(?:물량|주식수)\s*(?:은|는)?\s*[\d,]+\s*주?\s*\(?\s*(?:상장일\s*기준\s*|공모\s*후\s*)?" + pct,
        r"상장\s*직후[^%。]{0,80}?유통\s*가능[^%。]{0,80}?" + pct,
    ]
    for p in pats:  # 신뢰도 높은 패턴부터, 처음 잡히는 패턴의 최빈값
        c = re.findall(p, t)
        if c:
            return most_common([float(x.replace(",", ".")) for x in c])
    return None


# ---------- 독립 재계산 ----------

def tier(v, tiers, default):
    for t_ in tiers:
        if v >= t_["gte"]:
            return t_["points"]
    return default


def recompute(ind, final_price):
    s = CFG["score"]
    comp, pos, lock, trad, old = (ind.get(k) for k in
                                  ("competition_rate", "price_position", "lockup_ratio", "tradable_ratio", "old_share_ratio"))
    if None in (comp, pos, lock, trad, old):
        return None
    c = tier(comp, s["comp"]["tiers"], s["comp"]["default"])
    b = s["comp"]["large_cap_bonus"]
    amt = ind.get("offering_amount_krw")
    if amt is not None and amt >= b["min_offering_amount_krw"] and comp >= b["min_competition_rate"]:
        c = min(s["comp"]["max"], c + b["points"])
    p = s["price"]["points"][pos]
    lk = tier(lock, s["lockup"]["tiers"], s["lockup"]["default"])
    f = s["flow"]
    if trad > f["zero_if"]["tradable_gt"] or old >= f["zero_if"]["old_share_gte"]:
        fl = 0
    elif trad < f["top_if"]["tradable_lt"] and old == f["top_if"]["old_share_eq"]:
        fl = f["top_if"]["points"]
    else:
        fl = f["otherwise"]
    tot = c + p + lk + fl
    g = CFG["grade"]
    status = "PASS" if tot >= g["pass_min"] else "REJECT"
    grade = None if status == "REJECT" else ("S" if tot >= g["s_min"] else "A" if tot >= g["a_min"] else "B")
    return {"comp": c, "price": p, "lockup": lk, "flow": fl, "total": tot, "status": status, "grade": grade}


def checklist_expect(ind):
    cl = CFG["checklist"]
    out = {}
    comp = ind.get("competition_rate")
    out["competition"] = ("UNKNOWN", None) if comp is None else (
        ("MET", "VERY_GOOD") if comp >= cl["competition_very_good_min"] else
        ("MET", "GOOD") if comp >= cl["competition_good_min"] else ("NOT_MET", None))
    pos = ind.get("price_position")
    out["price_position"] = ("UNKNOWN", None) if pos is None else (
        ("MET", None) if pos in cl["price_positions_met"] else ("NOT_MET", None))
    lk = ind.get("lockup_ratio")
    out["lockup"] = ("UNKNOWN", None) if lk is None else (("MET", None) if lk >= cl["lockup_min"] else ("NOT_MET", None))
    tr, old = ind.get("tradable_ratio"), ind.get("old_share_ratio")
    if tr is not None and old is not None:
        out["flow"] = ("MET", None) if (tr <= cl["flow_tradable_max"] and old < cl["flow_old_share_lt"]) else ("NOT_MET", None)
    elif (tr is not None and tr > cl["flow_tradable_max"]) or (old is not None and old >= cl["flow_old_share_lt"]):
        out["flow"] = ("NOT_MET", None)
    else:
        out["flow"] = ("UNKNOWN", None)
    return out


def position(final, lo, hi):
    if None in (final, lo, hi):
        return None
    return "ABOVE_BAND" if final > hi else "TOP_OF_BAND" if final == hi else "BELOW_BAND" if final < lo else "WITHIN_BAND"


# ---------- 대조 ----------

def check_corp(d, key):
    rows = []

    def add(field, api, doc, kind="eq", tol=0.0, note=""):
        if doc is None:
            st = "OK" if api is None else "NOT_FOUND"
        elif api is None:
            st = "MISMATCH"
        elif kind == "num":
            st = "OK" if abs(float(api) - float(doc)) <= tol else "MISMATCH"
        else:
            st = "OK" if api == doc else "MISMATCH"
        rows.append((field, api, doc, st, note))

    ind = d.get("indicators") or {}
    core = ind.get("report_rcept_no")
    srcs = sorted(d.get("sources") or [], key=lambda s: s["rcept_no"])
    t = doc_text(core, key) if core else None
    if t is None:
        rows.append(("원문", core, None, "NOT_FOUND", "기준 공시 다운로드 실패"))
        return rows

    # 발행조건확정 문서는 일정·밴드·유통 서술을 생략하는 경우가 있어, 기준 공시에 없으면
    # 다른 신고서·투자설명서를 최신순으로 찾아 처음 나오는 값을 쓴다(정정으로 바뀐 최신 일정 우선).
    others = [s["rcept_no"] for s in reversed(srcs)
              if s["rcept_no"] != core and s["doc_type"] in
              ("REGISTRATION_AMENDED", "PROSPECTUS", "PROSPECTUS_AMENDED")]

    def body(tt):
        # 정정 신고서는 서두 정정표에 옛 값이 섞여 있으므로 본문("대표이사 등의 확인" 이후)만 본다
        if not tt or not re.search(r"정\s*정\s*[전후]", tt):
            return tt
        m = re.search(r"대표이사\s*등의\s*확인", tt)
        return tt[m.start():] if m else tt

    def find(fn):
        v_ = fn(body(t))
        if v_ is not None:
            return v_, ""
        for r in others:
            tt = doc_text(r, key)
            v_ = fn(body(tt)) if tt else None
            if v_ is not None:
                return v_, f"보조 문서 {r}"
        return None, ""

    band, nb = find(ext_band)
    add("band_low", d.get("band_low"), band[0] if band else None, note=nb)
    add("band_high", d.get("band_high"), band[1] if band else None, note=nb)
    dem, nd = find(ext_demand)
    add("demand_forecast_start", d.get("demand_forecast_start"), dem[0] if dem else None, note=nd)
    add("demand_forecast_end", d.get("demand_forecast_end"), dem[1] if dem else None, note=nd)
    sub, ns = find(ext_subscription)
    add("subscription_start", d.get("subscription_start"), sub[0] if sub else None, note=ns)
    add("subscription_end", d.get("subscription_end"), sub[1] if sub else None, note=ns)
    cf, nc = find(ext_confirm)
    add("price_confirm_date", d.get("price_confirm_date"), cf, note=nc)

    final_doc = ext_final(t)
    add("final_price", d.get("final_price"), final_doc)
    if d.get("final_price") is not None:
        add("price_position", ind.get("price_position"),
            position(d.get("final_price"), d.get("band_low"), d.get("band_high")), note="확정가 vs 밴드 계산")
        add("competition_rate", ind.get("competition_rate"), ext_competition(t), "num", 0.01)
        add("lockup_ratio", ind.get("lockup_ratio"), ext_lockup(t), "num", 0.1, "신청 수량 기준(합계 열)")
    tr, nt = find(ext_tradable)
    add("tradable_ratio", ind.get("tradable_ratio"), tr, "num", 0.06, nt)

    # 값 자체 점검
    n, o, tot = ind.get("new_share_count"), ind.get("old_share_count"), ind.get("total_offering_count")
    bad = []
    if any(v is not None and v < 0 for v in (n, o, tot)):
        bad.append("음수 주식수")
    if None not in (n, o, tot) and n + o != tot:
        bad.append(f"신주+구주({n}+{o}) ≠ 총공모({tot})")
    for k in ("old_share_ratio", "tradable_ratio", "lockup_ratio"):
        v = ind.get(k)
        if v is not None and not (0 <= v <= 100):
            bad.append(f"{k}={v} 범위 밖")
    if d.get("final_price") is not None and ind.get("competition_rate") is None:
        bad.append("확정가는 있는데 경쟁률 null — 수요예측 결과 표 미인식 의심")
    if tot is not None and f"{tot:,}" not in t:
        bad.append(f"총공모 {tot:,}주가 원문에 없음")
    if d.get("final_price") is not None and tot is not None:
        exp = tot * d["final_price"]
        if ind.get("offering_amount_krw") != exp:
            bad.append(f"공모금액 {ind.get('offering_amount_krw')} ≠ 총공모×확정가 {exp}")
    rows.append(("주식수·금액 점검", None, None, "SANITY" if bad else "OK", "; ".join(bad)))

    # 상장일 — 증권발행실적보고서
    iss = [s for s in srcs if s["doc_type"] == "ISSUANCE_REPORT"]
    if iss:
        ti = doc_text(iss[-1]["rcept_no"], key)
        add("listing_date", d.get("listing_date"), ext_listing(ti) if ti else None, note=iss[-1]["rcept_no"])

    # 점수·등급 독립 재계산
    v = d.get("verdict") or {}
    sc = d.get("scores") or {}
    exp = recompute(ind, d.get("final_price"))
    if v.get("status") in ("PASS", "REJECT") or exp:
        if exp is None:
            rows.append(("점수", v.get("status"), "지표 일부 null", "MISMATCH", "PASS/REJECT 인데 지표 누락"))
        elif v.get("status") not in ("CORRECTION",):
            got = (sc.get("comp"), sc.get("price"), sc.get("lockup"), sc.get("flow"), sc.get("total"), v.get("status"), v.get("grade"))
            want = (exp["comp"], exp["price"], exp["lockup"], exp["flow"], exp["total"], exp["status"], exp["grade"])
            rows.append(("점수·등급", got, want, "OK" if got == want else "MISMATCH", "comp,price,lockup,flow,total,status,grade"))
    for c in d.get("checklist") or []:
        want = checklist_expect(ind).get(c["key"])
        got = (c.get("result"), c.get("level"))
        if want is not None:
            rows.append((f"체크리스트 {c['key']}", got, want, "OK" if got == want else "MISMATCH", c.get("actual") or ""))
    return rows


def main():
    key = _key()
    today = date.today().isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"# 일일 검증 {today} ({datetime.now().strftime('%H:%M')})", ""]

    _, health = http_json(f"{API}/api/health")
    lines.append(f"- health: parser_version={health.get('parser_version')} commit={health.get('commit')}")
    if "--no-collect" not in sys.argv:
        code, _ = http_json(f"{API}/api/collect", method="POST")
        time.sleep(5)
        st = None
        for _ in range(120):
            _, st = http_json(f"{API}/api/collect/status")
            if st.get("status") != "RUNNING":
                break
            time.sleep(15)
        lines.append(f"- 수집: POST {code} → {st.get('status')} {st.get('finished_at')} summary={json.dumps(st.get('summary'), ensure_ascii=False)}")
        if st.get("failures"):
            lines.append(f"- 수집 실패: {json.dumps(st.get('failures'), ensure_ascii=False)}")

    _, lst = http_json(f"{API}/api/ipos")
    items = lst["items"]
    prev_f = sorted(f for f in OUT_DIR.glob("snapshot-*.json") if f.stem < f"snapshot-{today}")
    prev = json.loads(prev_f[-1].read_text(encoding="utf-8")) if prev_f else {}
    snap = {}
    issues = []
    for it in items:
        _, d = http_json(f"{API}/api/ipos/{it['id']}")
        v = d.get("verdict") or {}
        snap[it["id"]] = {"name": d["corp_name"], "status": v.get("status"), "grade": v.get("grade"), "score": v.get("score")}
        for row in check_corp(d, key):
            if row[3] != "OK":
                issues.append((d["corp_name"], it["id"], v.get("status"),
                               (d.get("indicators") or {}).get("report_rcept_no")) + row)
    (OUT_DIR / f"snapshot-{today}.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")

    cnt = Counter(s["status"] for s in snap.values())
    lines.append(f"- 종목 {len(snap)}: " + ", ".join(f"{k} {v}" for k, v in sorted(cnt.items())))
    lines += ["", "## 판정 변화 (직전 스냅샷 대비)"]
    changed = False
    for cid, s in snap.items():
        p = prev.get(cid)
        if p is None and prev:
            lines.append(f"- NEW {s['name']}({cid}) {s['status']} {s['grade'] or ''} {s['score'] or ''}")
            changed = True
        elif p and (p["status"], p["grade"], p["score"]) != (s["status"], s["grade"], s["score"]):
            lines.append(f"- {s['name']}({cid}) {p['status']} {p['grade'] or ''} {p['score'] or ''} → {s['status']} {s['grade'] or ''} {s['score'] or ''}")
            changed = True
    for cid, p in prev.items():
        if cid not in snap:
            lines.append(f"- GONE {p['name']}({cid})")
            changed = True
    if not changed:
        lines.append("- 없음" if prev else "- (첫 스냅샷)")

    lines += ["", f"## 원문 대조 이상 {len(issues)}건 (pm 이 원문 확인 후 판단)", "",
              "| 종목 | 상태 | 기준 공시 | 항목 | API | 원문/기대 | 결과 | 비고 |", "|---|---|---|---|---|---|---|---|"]
    for name, cid, status, core, field, api, doc, st, note in issues:
        lines.append(f"| {name}({cid}) | {status} | {core} | {field} | {api} | {doc} | {st} | {note} |")
    report = OUT_DIR / f"{today}.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report={report}")
    print(f"items={len(snap)} issues={len(issues)} " + " ".join(f"{k}={v}" for k, v in Counter(i[7] for i in issues).items()))


if __name__ == "__main__":
    main()
