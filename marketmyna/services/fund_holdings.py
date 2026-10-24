"""What a mutual fund holds, from the official monthly portfolio files.

SEBI makes every fund house publish each scheme's full portfolio within ten
days of month end, as an Excel workbook with one sheet per scheme in a common
layout: a "Name of the Instrument | ISIN | Industry / Rating | Quantity |
Market Value | % to Net Assets" table split into sections (equity, arbitrage,
REITs, foreign equity, money market, TREPS ...) ending at GRAND TOTAL, with
derivatives listed after it.

Files reach the app two ways:
- auto-download for fund houses whose site lists the files at a stable page
  (AUTO_SOURCES), refreshed in the background;
- a file placed by hand with ingest() (no upload screen in this build).
The last two months are kept per fund house, so a fund's page can show what
it bought and sold. Index funds without a file fall back to the NSE index
list (marketmyna/services/etf.py), with estimated weights.
"""

from __future__ import annotations

import difflib
import io
import json
import logging
import re
import threading
import time
import zipfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from marketmyna.core.home import app_home

logger = logging.getLogger(__name__)

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
KEEP_MONTHS = 2
MAX_UPLOAD = 25 * 1024 * 1024
REFRESH_SECONDS = 24 * 3600
TOP_N = 15

# Section headings -> holding kind. Checked in order; first match wins.
SECTIONS = (
    (r"arbitrage", "arbitrage"),
    (r"foreign|overseas|international", "foreign_equity"),
    (r"reit|invit", "reit"),
    (r"mutual fund|units of|etf", "fund"),
    (r"repo|treps|tri-party|cblo", "cash"),
    (r"money market|certificate of deposit|commercial paper|treasury|t-bill|debt|bond|debenture|"
     r"government|g-sec|state development|sdl|securiti|ptc|zero coupon", "debt"),
    (r"equity|shares", "equity"),
)
STOP = re.compile(r"grand total|^derivatives|^total net assets", re.I)

_lock = threading.Lock()
_index_cache: dict[str, tuple[float, dict]] = {}


def _root() -> Path:
    p = app_home() / "mf_portfolios"
    p.mkdir(parents=True, exist_ok=True)
    return p


def slug(amc: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (amc or "").lower()).strip("-")[:60] or "unknown"


# ---------------------------------------------------------------- parsing

def _num(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("$", "").replace("%", "").replace("^", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _text(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def _header(df: pd.DataFrame) -> Optional[tuple[int, dict[str, int]]]:
    for i in range(min(len(df), 40)):
        cells = [_text(v).lower() for v in df.iloc[i].tolist()]
        if not any(c == "isin" or c.startswith("isin") for c in cells):
            continue
        cols: dict[str, int] = {}
        for j, c in enumerate(cells):
            if "isin" in c and "isin" not in cols:
                cols["isin"] = j
            elif ("instrument" in c or "name of" in c or c in ("security", "name", "company")) and "name" not in cols:
                cols["name"] = j
            elif ("industry" in c or "rating" in c or "sector" in c) and "industry" not in cols:
                cols["industry"] = j
            elif "quantity" in c and "qty" not in cols:
                cols["qty"] = j
            elif ("market" in c or "fair value" in c or "value" in c) and "value" not in cols and "%" not in c:
                cols["value"] = j
            elif ("% to" in c or "% of" in c or "net asset" in c or c.startswith("%")) and "pct" not in cols:
                cols["pct"] = j
        if "isin" in cols and "pct" in cols:
            cols.setdefault("name", max(cols["isin"] - 1, 0))
            return i, cols
    return None


def _scheme_title(df: pd.DataFrame, header_row: int) -> tuple[str, Optional[str]]:
    title, as_of = "", None
    for i in range(header_row):
        for v in df.iloc[i].tolist():
            t = _text(v)
            if not t:
                continue
            m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?[\s\-/.,]*([A-Za-z]{3,9})[\s\-/.,]*(\d{4})", t) or \
                re.search(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", t)
            if m and as_of is None and re.search(r"as on|as at|portfolio|statement", t, re.I):
                parts = m.groups()
                day, mon, yr = (parts[1], parts[0], parts[2]) if parts[0].isalpha() else parts
                for fmt in ("%d %B %Y", "%d %b %Y"):
                    try:
                        as_of = datetime.strptime(f"{int(day)} {mon} {yr}", fmt).date().isoformat()
                        break
                    except ValueError:
                        continue
            if not title and not re.search(r"portfolio statement|monthly portfolio|as on|as at|^scheme name\s*:?$", t, re.I) \
                    and re.search(r"fund|scheme|plan|etf", t, re.I):
                title = re.sub(r"^scheme name\s*:?\s*", "", t, flags=re.I)
    title = re.sub(r"\s*\((?:an |a )?open[- ]ended.*$", "", title, flags=re.I)
    title = re.sub(r"\s*\(.*?\)\s*$", "", title).strip(" -:")
    return title, as_of


def parse_sheet(df: pd.DataFrame, sheet: str = "") -> Optional[dict]:
    """One scheme's holdings from a SEBI-format sheet, or None if it isn't one."""
    found = _header(df)
    if not found:
        return None
    hrow, cols = found
    title, as_of = _scheme_title(df, hrow)
    kind = "equity"
    raw, grand = [], None
    for i in range(hrow + 1, len(df)):
        row = df.iloc[i].tolist()
        get = lambda k: row[cols[k]] if k in cols and cols[k] < len(row) else None  # noqa: E731
        name, isin = _text(get("name")), _text(get("isin")).upper()
        label = name or " ".join(_text(v) for v in row if _text(v))
        if STOP.search(label):
            if re.search(r"grand total", label, re.I):
                grand = _num(get("pct"))
            break
        if not ISIN_RE.match(isin):
            if label and not re.match(r"^(sub ?total|total)\b", label, re.I):
                low = label.lower()
                for pattern, k in SECTIONS:
                    if re.search(pattern, low):
                        kind = k
                        break
            continue
        pct = _num(get("pct"))
        if pct is None:
            continue
        raw.append({"name": name, "isin": isin, "industry": _text(get("industry")) or None,
                    "qty": _num(get("qty")), "value_lakh": _num(get("value")), "pct": pct, "kind": kind})
    if not raw:
        return None
    # Weights come as fractions (0.0763) or percent (7.63) depending on the house.
    total = sum(h["pct"] for h in raw)
    fraction = (grand is not None and grand <= 1.5) or (grand is None and total <= 1.5)
    holdings = []
    for h in raw:
        w = h.pop("pct")
        h["weight"] = w * 100 if fraction else w
        if h["kind"] == "equity" and not h["isin"].startswith("IN"):
            h["kind"] = "foreign_equity"
        holdings.append(h)
    return {"sheet": sheet, "scheme": title or sheet, "as_of": as_of, "holdings": holdings}


def _frames(data: bytes, filename: str = "") -> list[tuple[str, pd.DataFrame]]:
    if data[:2] == b"PK" and _is_plain_zip(data):
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for n in zf.namelist():
                if re.search(r"\.(xlsx?|xlsm)$", n, re.I):
                    out += _frames(zf.read(n), n)
        return out
    if data[:2] == b"PK":
        book = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, engine="openpyxl")
    elif data[:4] == b"\xd0\xcf\x11\xe0":
        book = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, engine="xlrd")
    elif data.lstrip()[:1] == b"<":  # some houses serve HTML tables named .xls
        book = {f"Table {i + 1}": t for i, t in enumerate(pd.read_html(io.BytesIO(data), header=None))}
    else:
        raise ValueError("Not an Excel file")
    return list(book.items())


def _is_plain_zip(data: bytes) -> bool:
    """A zip of workbooks (not an .xlsx, which is itself a zip)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
        return "[Content_Types].xml" not in names and any(re.search(r"\.xlsx?$", n, re.I) for n in names)
    except zipfile.BadZipFile:
        return False


def parse_workbook(data: bytes, filename: str = "") -> list[dict]:
    schemes = []
    for sheet, df in _frames(data, filename):
        try:
            s = parse_sheet(df, str(sheet))
        except Exception as exc:
            logger.debug("Sheet %s skipped: %s", sheet, exc)
            continue
        if s:
            schemes.append(s)
    if not schemes:
        raise ValueError("No scheme portfolios found. Expected the SEBI monthly portfolio layout "
                         "(Name of the Instrument, ISIN, ..., % to Net Assets).")
    return schemes


# ---------------------------------------------------------------- storage

def _month(schemes: list[dict]) -> str:
    dates = sorted({s["as_of"] for s in schemes if s.get("as_of")})
    return (dates[-1] if dates else datetime.now().date().isoformat())[:7]


def store(amc: str, schemes: list[dict], source: str) -> dict:
    """Save one fund house's month; keeps the newest KEEP_MONTHS."""
    folder = _root() / slug(amc)
    folder.mkdir(parents=True, exist_ok=True)
    month = _month(schemes)
    doc = {"amc": amc, "month": month, "source": source, "saved_at": time.time(), "schemes": schemes}
    with _lock:
        (folder / f"{month}.json").write_text(json.dumps(doc), encoding="utf-8")
        files = sorted(folder.glob("*.json"))
        for old in files[:-KEEP_MONTHS]:
            old.unlink()
        _load.cache_clear()
    return {"amc": amc, "month": month, "schemes": len(schemes)}


def ingest(amc: str, data: bytes, filename: str = "", source: str = "upload") -> dict:
    if len(data) > MAX_UPLOAD:
        raise ValueError("File is larger than 25 MB")
    return store(amc, parse_workbook(data, filename), source)


def ingest_many(amc: str, files: list[tuple[bytes, str]], source: str) -> dict:
    """Several workbooks for the same month (houses that publish one file per scheme)."""
    schemes = []
    for data, name in files:
        try:
            schemes += parse_workbook(data, name)
        except Exception as exc:
            logger.info("%s: %s skipped: %s", amc, name, exc)
    if not schemes:
        raise ValueError(f"No portfolios parsed for {amc}")
    return store(amc, schemes, source)



@lru_cache(maxsize=256)
def _load(amc_slug: str) -> tuple[dict, ...]:
    folder = _root() / amc_slug
    if not folder.exists():
        return ()
    docs = []
    for f in sorted(folder.glob("*.json"), reverse=True):
        try:
            docs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return tuple(docs)  # newest first


def status() -> list[dict]:
    out = []
    for folder in sorted(p for p in _root().iterdir() if p.is_dir()):
        docs = _load(folder.name)
        if docs:
            d = docs[0]
            out.append({"amc": d["amc"], "month": d["month"], "schemes": len(d["schemes"]), "source": d.get("source"),
                        "saved_at": d.get("saved_at"), "months": [x["month"] for x in docs],
                        "auto": d["amc"] in AUTO_SOURCES})
    return out


def delete(amc: str) -> None:
    folder = _root() / slug(amc)
    with _lock:
        for f in folder.glob("*.json"):
            f.unlink()
        _load.cache_clear()


# ---------------------------------------------------------------- matching

_NOISE = re.compile(r"\b(direct|regular|plan|option|growth|idcw|dividend|payout|reinvest(?:ment)?|bonus|"
                    r"the|an|open ended|scheme|fund|mutual)\b")


def norm(name: str) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = re.split(r"\s+-\s+(?:direct|regular)|\(", n)[0]
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    n = _NOISE.sub(" ", n)
    return re.sub(r"\s+", " ", n).strip()


def match_scheme(fund_name: str, schemes: list[dict]) -> Optional[dict]:
    target = norm(fund_name)
    if not target:
        return None
    best, score = None, 0.0
    for s in schemes:
        cand = norm(s["scheme"])
        if not cand:
            continue
        r = 1.0 if cand == target else difflib.SequenceMatcher(None, cand, target).ratio()
        if r > score:
            best, score = s, r
    return best if score >= 0.86 else None


# ---------------------------------------------------------------- views

def _isin_symbols() -> dict[str, dict]:
    from ..data.listings import get_store

    return {r["isin"]: r for r in get_store().rows("india") if r.get("type") == "stock" and r.get("isin")}


def cap_split(stocks: list[dict], symbols: dict[str, dict]) -> Optional[list[dict]]:
    """Large / mid / small cap share of the equity, SEBI's way: the 100
    largest listed companies by market cap are large, the next 150 mid, the
    rest small. Foreign shares and unlisted names are counted on their own."""
    caps = sorted((r["market_cap"] for r in symbols.values() if r.get("market_cap")), reverse=True)
    if len(caps) < 250 or not stocks:
        return None
    large_min, mid_min = caps[99], caps[249]
    split = {"large": 0.0, "mid": 0.0, "small": 0.0, "foreign": 0.0, "other": 0.0}
    for h in stocks:
        row = symbols.get(h.get("isin") or "")
        cap = (row or {}).get("market_cap")
        if h["kind"] == "foreign_equity":
            split["foreign"] += h["weight"]
        elif not cap:
            split["other"] += h["weight"]
        else:
            split["large" if cap >= large_min else "mid" if cap >= mid_min else "small"] += h["weight"]
    return [{"kind": k, "weight": v} for k, v in split.items() if v > 0.05]


def _summarise(scheme: dict, prev: Optional[dict], symbols: dict[str, dict]) -> dict:
    merged: dict[str, dict] = {}
    for h in scheme["holdings"]:
        key = f'{h["isin"]}:{"equity" if h["kind"] in ("equity", "arbitrage") else h["kind"]}'
        m = merged.get(key)
        if m:
            m["weight"] += h["weight"]
            m["value_lakh"] = (m.get("value_lakh") or 0) + (h.get("value_lakh") or 0)
            if h["kind"] == "arbitrage":
                m["hedged"] = (m.get("hedged") or 0) + h["weight"]
            continue
        row = symbols.get(h["isin"])
        merged[key] = {**h, "kind": "equity" if h["kind"] == "arbitrage" else h["kind"],
                       "hedged": h["weight"] if h["kind"] == "arbitrage" else None,
                       "symbol": row["symbol"] if row else None,
                       "sector": h.get("industry") or (row or {}).get("sector")}
    items = sorted(merged.values(), key=lambda h: -h["weight"])
    stocks = [h for h in items if h["kind"] in ("equity", "foreign_equity")]

    mix: dict[str, float] = {}
    for h in items:
        mix[h["kind"]] = mix.get(h["kind"], 0) + h["weight"]
    rest = 100 - sum(mix.values())
    if rest > 0.5:  # TREPS, cash and net receivables carry no ISIN
        mix["cash"] = mix.get("cash", 0) + rest
    sectors: dict[str, float] = {}
    for h in stocks:
        sectors[h["sector"] or "Other"] = sectors.get(h["sector"] or "Other", 0) + h["weight"]

    changes = None
    if prev:
        before: dict[str, float] = {}
        for h in prev["holdings"]:
            if h["kind"] in ("equity", "arbitrage", "foreign_equity"):
                before[h["isin"]] = before.get(h["isin"], 0) + h["weight"]
        now = {h["isin"]: h for h in stocks}
        new = [{"name": h["name"], "symbol": h["symbol"], "weight": h["weight"]}
               for i, h in now.items() if i not in before]
        names = {h["isin"]: h["name"] for h in prev["holdings"]}
        exited = [{"name": names.get(i, i), "weight": w} for i, w in before.items() if i not in now]
        moved = sorted(({"name": h["name"], "symbol": h["symbol"], "from": before[i], "to": h["weight"]}
                        for i, h in now.items() if i in before and abs(h["weight"] - before[i]) >= 0.25),
                       key=lambda c: -abs(c["to"] - c["from"]))
        changes = {"since": prev.get("as_of"), "new": sorted(new, key=lambda x: -x["weight"])[:15],
                   "exited": sorted(exited, key=lambda x: -x["weight"])[:15], "moved": moved[:15]}

    aum_cr = sum((h.get("value_lakh") or 0) for h in scheme["holdings"]) / 100 or None

    return {
        "status": "ok", "scheme": scheme["scheme"], "as_of": scheme.get("as_of"),
        "count": len(stocks), "holdings": items, "top": stocks[:TOP_N],
        "cap_split": cap_split(stocks, symbols),
        "top10_weight": sum(h["weight"] for h in stocks[:10]),
        "sectors": [{"name": k, "weight": v} for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])],
        "mix": [{"kind": k, "weight": v} for k, v in sorted(mix.items(), key=lambda kv: -kv[1])],
        "aum_cr": aum_cr,
        "changes": changes, "weights": "reported",
        "concentration": concentration(stocks),
        "churn": churn(scheme["holdings"], prev["holdings"], aum_cr) if prev else None,
    }


EQUITY_KINDS = ("equity", "arbitrage", "foreign_equity")


def concentration(stocks: list[dict]) -> Optional[dict]:
    """How concentrated the stock book is: the effective number of equal-weight
    stocks it behaves like (1 / sum of squared weights) and the largest holding."""
    weights = [h["weight"] / 100 for h in stocks if h.get("weight")]
    if not weights:
        return None
    hhi = sum(w * w for w in weights)
    return {"effective_stocks": 1 / hhi if hhi else None, "top_weight": max(weights) * 100,
            "count": len(weights)}


def churn(now: list[dict], before: list[dict], aum_cr: Optional[float]) -> Optional[dict]:
    """Trading in the month from the change in shares held (not weights, which
    also move with prices), valued at this month's prices. Turnover follows
    SEBI's definition: the smaller of purchases and sales over the fund size."""
    def shares(rows):
        out: dict[str, float] = {}
        for h in rows:
            if h["kind"] in EQUITY_KINDS and h.get("qty"):
                out[h["isin"]] = out.get(h["isin"], 0) + float(h["qty"])
        return out

    q_now, q_before = shares(now), shares(before)
    price: dict[str, float] = {}
    for h in now:
        if h["kind"] in EQUITY_KINDS and h.get("qty") and h.get("value_lakh"):
            price[h["isin"]] = float(h["value_lakh"]) / float(h["qty"])
    prev_price: dict[str, float] = {}
    for h in before:
        if h["kind"] in EQUITY_KINDS and h.get("qty") and h.get("value_lakh"):
            prev_price[h["isin"]] = float(h["value_lakh"]) / float(h["qty"])
    if not aum_cr or not q_now or not q_before:
        return None
    bought = sold = 0.0  # lakh
    for isin in set(q_now) | set(q_before):
        diff = q_now.get(isin, 0.0) - q_before.get(isin, 0.0)
        px = price.get(isin) or prev_price.get(isin)
        if not px or abs(diff) < 1:
            continue
        if diff > 0:
            bought += diff * px
        else:
            sold += -diff * px
    month = min(bought, sold) / 100 / aum_cr * 100
    return {"month_pct": month, "yearly_pct": month * 12, "bought_cr": bought / 100, "sold_cr": sold / 100}


def _index_fallback(fund: dict) -> Optional[dict]:
    from . import etf

    name = fund.get("name", "")
    if not re.search(r"\bindex\b|\betf\b|nifty|sensex", name, re.I):
        return None
    _file, index, st = etf.match_index(name)
    if st != "ok":
        return None
    from ..data.listings import get_store

    rows = get_store().rows("india")
    caps = {r["symbol"]: r["market_cap"] for r in rows if r.get("type") == "stock" and r.get("market_cap")}
    d = etf._india(fund["symbol"], {"name": name}, caps, etf._http)
    if d.get("status") != "ok":
        return None
    hold = [{"name": h["name"], "symbol": h["symbol"], "isin": None, "weight": h["weight"] * 100,
             "sector": h["sector"], "kind": "equity"} for h in d["holdings"]]
    return {"status": "ok", "scheme": name, "as_of": None, "count": len(hold), "holdings": hold, "top": hold[:TOP_N],
            "top10_weight": sum(h["weight"] for h in hold[:10]),
            "sectors": [{"name": s["name"], "weight": s["weight"] * 100} for s in d["sectors"]],
            "mix": [{"kind": "equity", "weight": 100.0}], "changes": None, "aum_cr": None,
            "weights": "estimated", "source": "niftyindices.com",
            "note": f"Tracks the {index}. Weights estimated from market cap; the fund's own file gives exact weights."}


def for_fund(code: str, rows: Optional[list[dict]] = None) -> dict:
    """Holdings of one listed scheme (by AMFI scheme code)."""
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows("india")
    fund = next((r for r in rows if r.get("type") == "mf" and str(r["symbol"]) == str(code)), None)
    if fund is None:
        return {"status": "unknown", "note": "No such scheme."}
    docs = _load(slug(fund.get("amc", "")))
    if docs:
        scheme = match_scheme(fund["name"], docs[0]["schemes"])
        if scheme:
            prev = match_scheme(scheme["scheme"], docs[1]["schemes"]) if len(docs) > 1 else None
            out = _summarise(scheme, prev, _isin_symbols())
            return {**out, "amc": fund.get("amc"), "source": f'{fund.get("amc")} monthly portfolio',
                    "note": None}
    fb = _index_fallback(fund)
    if fb:
        return {**fb, "amc": fund.get("amc")}
    have = bool(docs)
    return {"status": "missing", "amc": fund.get("amc"),
            "note": (f"{fund.get('amc')}'s latest portfolio file doesn't list this scheme by name."
                     if have else f"{fund.get('amc')}'s monthly portfolio hasn't been loaded yet.")}


def funds_holding(symbol: str, limit: int = 40) -> dict:
    """Which funds hold a stock (latest month of every loaded fund house)."""
    from ..data.listings import get_store

    rows = get_store().rows("india")
    me = next((r for r in rows if r.get("type") == "stock" and r["symbol"].upper() == symbol.upper()), None)
    if me is None or not me.get("isin"):
        return {"symbol": symbol, "funds": [], "note": "No ISIN for this stock."}
    isin = me["isin"]
    out = []
    for folder in _root().iterdir():
        docs = _load(folder.name) if folder.is_dir() else ()
        if not docs:
            continue
        doc = docs[0]
        prev = {s["scheme"]: s for s in docs[1]["schemes"]} if len(docs) > 1 else {}
        for s in doc["schemes"]:
            w = sum(h["weight"] for h in s["holdings"] if h["isin"] == isin and h["kind"] != "debt")
            if w <= 0:
                continue
            p = prev.get(s["scheme"])
            before = sum(h["weight"] for h in p["holdings"] if h["isin"] == isin) if p else None
            value = sum((h.get("value_lakh") or 0) for h in s["holdings"] if h["isin"] == isin)
            out.append({"amc": doc["amc"], "scheme": s["scheme"], "weight": w, "prev_weight": before,
                        "value_cr": value / 100 if value else None, "as_of": s.get("as_of")})
    out.sort(key=lambda f: -(f["value_cr"] or 0))
    return {"symbol": me["symbol"], "isin": isin, "count": len(out), "funds": out[:limit],
            "houses_loaded": sum(1 for p in _root().iterdir() if p.is_dir() and _load(p.name))}


# ---------------------------------------------------------------- auto sources

def _http(url: str) -> bytes:
    import requests

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126"}, timeout=60)
    r.raise_for_status()
    return r.content


MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


def _ppfas(fetch: Callable[[str], bytes]) -> list[tuple[bytes, str]]:
    base = "https://amc.ppfas.com"
    page = fetch(base + "/downloads/portfolio-disclosure/").decode("utf-8", "ignore")
    links = re.findall(r'href="(/downloads/portfolio-disclosure/\d{4}/[^"]+\.xlsx?)(?:\?[^"]*)?"', page, re.I)
    dated = []
    for link in links:
        m = re.search(rf"({MONTHS})_(\d{{1,2}})_(\d{{4}})", link, re.I)
        if m:
            dated.append((datetime.strptime(f"{m.group(3)} {m.group(1)} {m.group(2)}", "%Y %B %d"), link))
    if not dated:
        raise ValueError("No portfolio links on the PPFAS page")
    latest = max(d for d, _ in dated)
    month = [l for d, l in dated if d == latest]
    combined = [l for l in month if re.search(r"/PPFAS_Monthly", l)]
    return [(fetch(base + l), l) for l in (combined or month)]


# Fund house (as named in the AMFI scheme list) -> downloader for its latest month.
AUTO_SOURCES: dict[str, Callable[[Callable[[str], bytes]], list[tuple[bytes, str]]]] = {
    "PPFAS Mutual Fund": _ppfas,
}


def refresh(amc: Optional[str] = None, fetch: Callable[[str], bytes] = _http, force: bool = False) -> list[dict]:
    results = []
    for name, source in AUTO_SOURCES.items():
        if amc and name != amc:
            continue
        docs = _load(slug(name))
        if docs and not force and time.time() - docs[0].get("saved_at", 0) < REFRESH_SECONDS:
            results.append({"amc": name, "skipped": "fresh"})
            continue
        try:
            results.append(ingest_many(name, source(fetch), "auto"))
        except Exception as exc:
            logger.warning("Portfolio refresh for %s failed: %s", name, exc)
            results.append({"amc": name, "error": str(exc)[:200]})
    return results


def refresh_loop() -> None:
    time.sleep(90)  # let start-up finish first
    while True:
        try:
            refresh()
        except Exception as exc:  # never kill the thread
            logger.warning("Portfolio refresh loop: %s", exc)
        time.sleep(REFRESH_SECONDS)


def pair_overlap(a: Optional[dict], b: Optional[dict]) -> Optional[dict]:
    """Stocks two funds hold in common, from their portfolio files: overlap =
    sum over shared stocks of the smaller weight (the part of the money that
    sits in the same companies)."""
    if not a or not b or a.get("status") != "ok" or b.get("status") != "ok":
        return None

    def weights(d: dict) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for h in d.get("holdings", []):
            if h.get("kind") in ("equity", "foreign_equity") and h.get("weight"):
                k = h.get("isin") or h.get("symbol") or h.get("name")
                cur = out.setdefault(k, {"name": h.get("name"), "symbol": h.get("symbol"), "weight": 0.0})
                cur["weight"] += h["weight"]
        return out

    wa, wb = weights(a), weights(b)
    if not wa or not wb:
        return None
    shared = sorted(set(wa) & set(wb), key=lambda k: -min(wa[k]["weight"], wb[k]["weight"]))
    return {"overlap": sum(min(wa[k]["weight"], wb[k]["weight"]) for k in shared),
            "shared_count": len(shared), "only_a": len(set(wa) - set(wb)), "only_b": len(set(wb) - set(wa)),
            "shared": [{"name": wa[k]["name"], "symbol": wa[k]["symbol"], "weight_a": wa[k]["weight"],
                        "weight_b": wb[k]["weight"]} for k in shared[:20]]}


def overlap(code_a: str, code_b: str) -> dict:
    a, b = for_fund(code_a), for_fund(code_b)
    out = pair_overlap(a, b)
    missing = [d.get("note") or "Portfolio not available" for d in (a, b) if d.get("status") != "ok"]
    if out and a.get("scheme") and a.get("scheme") == b.get("scheme"):
        missing.append("These are two plans / options of the same scheme: one portfolio, so the overlap is "
                       "simply its stock holdings.")
    return {"status": "ok" if out else "missing", "a": {"scheme": a.get("scheme"), "as_of": a.get("as_of")},
            "b": {"scheme": b.get("scheme"), "as_of": b.get("as_of")}, **(out or {}),
            "note": " ".join(missing) or None}

