"""ETF look-through: what a fund holds, its sector mix, and overlap between two
funds (OpenBB etf.holdings / etf.sectors / etf.info).

- US and other Yahoo-covered ETFs: Yahoo fund data (top 10 holdings, sector
  weights, asset classes, expense ratio, category).
- Indian index ETFs: Yahoo has no fund data, so the tracked Nifty index is
  inferred from the ETF's name and its full constituent list is read from
  niftyindices.com. Weights are estimated from market cap (the real index is
  free-float weighted, so promoter-heavy names come out overweight).
- Gold, silver, liquid and G-sec ETFs hold no stocks and say so.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import threading
import time
from typing import Callable, Optional

from src.core.home import app_home

logger = logging.getLogger(__name__)

NIFTY_CSV = "https://www.niftyindices.com/IndexConstituent/{file}.csv"
CACHE_SECONDS = 24 * 3600
TOP_N = 25

# (pattern on lower-cased ETF name, index file, index name); first match wins, specific before general
NIFTY_INDICES = [
    (r"private bank", "ind_nifty_privatebanklist", "Nifty Private Bank"),
    (r"psu bank", "ind_niftypsubanklist", "Nifty PSU Bank"),
    (r"nifty bank|bank (?:nifty|bees|etf)\b", "ind_niftybanklist", "Nifty Bank"),
    (r"nifty it\b", "ind_niftyitlist", "Nifty IT"),
    (r"pharma", "ind_niftypharmalist", "Nifty Pharma"),
    (r"healthcare", "ind_niftyhealthcarelist", "Nifty Healthcare"),
    (r"fmcg", "ind_niftyfmcglist", "Nifty FMCG"),
    (r"nifty auto", "ind_niftyautolist", "Nifty Auto"),
    (r"nifty metal", "ind_niftymetallist", "Nifty Metal"),
    (r"realty", "ind_niftyrealtylist", "Nifty Realty"),
    (r"nifty energy", "ind_niftyenergylist", "Nifty Energy"),
    (r"nifty infra", "ind_niftyinfralist", "Nifty Infrastructure"),
    (r"cpse", "ind_niftycpselist", "Nifty CPSE"),
    (r"nifty pse\b", "ind_niftypselist", "Nifty PSE"),
    (r"commodities", "ind_niftycommoditieslist", "Nifty Commodities"),
    (r"largemidcap 250|large ?mid ?cap 250", "ind_niftylargemidcap250list", "Nifty LargeMidcap 250"),
    (r"total market", "ind_niftytotalmarket_list", "Nifty Total Market"),
    (r"financial services", "ind_niftyfinancelist", "Nifty Financial Services"),
    (r"next 50|junior", "ind_niftynext50list", "Nifty Next 50"),
    (r"midcap 150", "ind_niftymidcap150list", "Nifty Midcap 150"),
    (r"midcap 100", "ind_niftymidcap100list", "Nifty Midcap 100"),
    (r"midcap 50", "ind_niftymidcap50list", "Nifty Midcap 50"),
    (r"smallcap 250", "ind_niftysmallcap250list", "Nifty Smallcap 250"),
    (r"smallcap 100", "ind_niftysmallcap100list", "Nifty Smallcap 100"),
    (r"nifty 500", "ind_nifty500list", "Nifty 500"),
    (r"nifty 200", "ind_nifty200list", "Nifty 200"),
    (r"nifty 100", "ind_nifty100list", "Nifty 100"),
    (r"nifty (?:index )?50\b|niftybees|nifty etf", "ind_nifty50list", "Nifty 50"),
]
# Factor / strategy / BSE indices we have no constituent list for
UNSUPPORTED = r"momentum|quality|low vol|alpha|value|equal weight|dividend|bse|sensex|nasdaq|s&p|hang seng|growth sectors"
NO_STOCKS = r"gold|silver|liquid|overnight|g-sec|gilt|government securities|bond|1d rate|money market|bharat bond|sdl"

SECTOR_LABELS = {
    "realestate": "Real estate", "consumer_cyclical": "Consumer cyclical", "basic_materials": "Basic materials",
    "consumer_defensive": "Consumer defensive", "technology": "Technology", "communication_services": "Communication",
    "financial_services": "Financial services", "utilities": "Utilities", "industrials": "Industrials",
    "energy": "Energy", "healthcare": "Healthcare",
}

Fetch = Callable[[str], str]
_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _http(url: str) -> str:
    import requests

    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126"}, timeout=20)
    r.raise_for_status()
    return r.text


def match_index(name: str) -> tuple[Optional[str], Optional[str], str]:
    """(file, index name, status) where status is ok | no_stocks | unsupported | unknown."""
    n = (name or "").lower()
    if re.search(NO_STOCKS, n):
        return None, None, "no_stocks"
    if re.search(UNSUPPORTED, n):
        return None, None, "unsupported"
    for pattern, file, label in NIFTY_INDICES:
        if re.search(pattern, n):
            return file, label, "ok"
    return None, None, "unknown"


def parse_constituents(text: str) -> list[dict]:
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    out = [{"symbol": r.get("Symbol", "").strip(), "name": r.get("Company Name", "").strip(),
            "industry": r.get("Industry", "").strip()} for r in rows if r.get("Symbol")]
    if not out:
        raise ValueError("no constituents in index file")
    return out


def _constituents(file: str, fetch: Fetch) -> list[dict]:
    key = f"nifty:{file}"
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]  # type: ignore[return-value]
    path = app_home() / "etf"
    path.mkdir(parents=True, exist_ok=True)
    snap = path / f"{file}.json"
    try:
        rows = parse_constituents(fetch(NIFTY_CSV.format(file=file)))
        snap.write_text(json.dumps(rows), encoding="utf-8")
    except Exception as exc:
        logger.warning("Index list %s failed: %s", file, exc)
        if not snap.exists():
            raise
        rows = json.loads(snap.read_text(encoding="utf-8"))
    with _lock:
        _cache[key] = (time.time(), rows)
    return rows


def _india(symbol: str, row: Optional[dict], caps: dict[str, float], fetch: Fetch) -> dict:
    name = (row or {}).get("name") or symbol
    file, index, status = match_index(name)
    base = {"symbol": symbol, "market": "india", "name": name, "is_etf": True, "source": "niftyindices.com"}
    if status == "no_stocks":
        return {**base, "status": status, "note": "This ETF holds gold, silver, bonds or cash, not stocks."}
    if status != "ok":
        return {**base, "status": status,
                "note": "Holdings are only available for ETFs tracking a standard Nifty index."}
    cons = _constituents(file, fetch)
    total = sum(caps.get(c["symbol"], 0) for c in cons)
    holdings = []
    for c in cons:
        w = caps.get(c["symbol"], 0) / total if total else 1 / len(cons)
        holdings.append({"symbol": c["symbol"], "name": c["name"], "weight": w, "sector": c["industry"]})
    holdings.sort(key=lambda h: -h["weight"])
    sectors: dict[str, float] = {}
    for h in holdings:
        sectors[h["sector"] or "Other"] = sectors.get(h["sector"] or "Other", 0) + h["weight"]
    return {**base, "status": "ok", "index": index, "count": len(holdings), "weights": "estimated",
            "holdings": holdings, "top": holdings[:TOP_N],
            "sectors": [{"name": k, "weight": v} for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])],
            "top10_weight": sum(h["weight"] for h in holdings[:10]),
            "note": f"Tracks the {index}. Weights estimated from market cap; the index itself uses free-float weights."}


def _yahoo(yf_symbol: str) -> dict:
    import yfinance as yf

    fd = yf.Ticker(yf_symbol).funds_data
    out: dict = {}
    top = fd.top_holdings
    out["top"] = [{"symbol": str(sym), "name": str(r.get("Name") or sym), "weight": float(r.get("Holding Percent") or 0)}
                  for sym, r in top.iterrows()] if top is not None else []
    out["sectors"] = dict(fd.sector_weightings or {})
    out["assets"] = dict(fd.asset_classes or {})
    overview = dict(fd.fund_overview or {})
    out["category"], out["family"] = overview.get("categoryName"), overview.get("family")
    ops = fd.fund_operations
    try:
        col = ops.columns[0]
        out["expense_ratio"] = float(ops.loc["Annual Report Expense Ratio", col])
        out["category_expense_ratio"] = float(ops.loc["Annual Report Expense Ratio", "Category Average"])
        out["turnover"] = float(ops.loc["Annual Holdings Turnover", col])
        out["total_assets"] = float(ops.loc["Total Net Assets", col])
    except Exception:
        pass
    try:
        out["description"] = fd.description
    except Exception:
        out["description"] = None
    return out


def lookthrough(symbol: str, market: str, fetch: Fetch = _http, yahoo: Callable[[str], dict] = _yahoo,
                rows: Optional[list[dict]] = None) -> dict:
    from .analysis_run import yahoo_symbol

    symbol, market = symbol.upper(), market.lower()
    if market == "india":
        if rows is None:
            from ..data.listings import get_store

            rows = get_store().rows("india")
        me = next((r for r in rows if r["symbol"].upper() == symbol), None)
        looks_etf = bool(me and re.search(r"\betf\b|bees\b", f"{me.get('name', '')} {symbol}".lower()))
        if me is not None and me.get("type") != "etf" and not looks_etf:
            return {"symbol": symbol, "market": market, "is_etf": False}
        caps = {r["symbol"]: r["market_cap"] for r in rows if r.get("type") == "stock" and r.get("market_cap")}
        return _india(symbol, me, caps, fetch)

    try:
        d = yahoo(yahoo_symbol(symbol, market))
    except Exception as exc:
        return {"symbol": symbol, "market": market, "is_etf": False, "note": str(exc)[:200]}
    if not d.get("top") and not d.get("sectors"):
        return {"symbol": symbol, "market": market, "is_etf": False}
    sectors = [{"name": SECTOR_LABELS.get(k, k.replace("_", " ").title()), "weight": float(v)}
               for k, v in d.get("sectors", {}).items() if v]
    return {
        "symbol": symbol, "market": market, "is_etf": True, "status": "ok", "source": "Market data feed",
        "name": d.get("family"), "category": d.get("category"), "family": d.get("family"),
        "expense_ratio": d.get("expense_ratio"), "category_expense_ratio": d.get("category_expense_ratio"),
        "turnover": d.get("turnover"), "total_assets": d.get("total_assets"), "description": d.get("description"),
        "assets": {k: float(v) for k, v in d.get("assets", {}).items() if v},
        "top": d["top"], "holdings": d["top"], "count": None, "weights": "reported",
        "top10_weight": sum(h["weight"] for h in d["top"][:10]),
        "sectors": sorted(sectors, key=lambda s: -s["weight"]),
        "note": "Only the top 10 holdings are published.",
    }


def overlap(a: dict, b: dict) -> dict:
    """Weight overlap = sum over shared holdings of min(weight in A, weight in B)."""
    wa = {h["symbol"]: h["weight"] for h in a.get("holdings") or []}
    wb = {h["symbol"]: h["weight"] for h in b.get("holdings") or []}
    shared = sorted(set(wa) & set(wb), key=lambda s: -min(wa[s], wb[s]))
    partial = a.get("weights") == "reported" or b.get("weights") == "reported"
    return {
        "a": a["symbol"], "b": b["symbol"],
        "overlap": sum(min(wa[s], wb[s]) for s in shared),
        "shared_count": len(shared),
        "shared": [{"symbol": s, "weight_a": wa[s], "weight_b": wb[s]} for s in shared[:15]],
        "partial": partial,
        "note": "Based on top-10 holdings only, so the true overlap is likely higher." if partial else None,
    }
