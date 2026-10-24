"""A fund's investing style from what it actually holds, and whether it
stays inside its SEBI category's rules.

Style: the fund's P/E and P/B (weight-averaged the harmonic way, which is
how an index's P/E is built) against the same measures for the 100 largest
Indian companies. Cheaper on both = Value, dearer = Growth, else Blend.
Size: from the large / mid / small split of its Indian shares.

Drift: SEBI's categorisation rules (2017, multi cap amended 2020) as a share
of the whole fund - Large Cap >= 80% large caps, Mid Cap >= 65% mid, Small
Cap >= 65% small, Large & Mid >= 35% each, Multi Cap >= 25% each of large,
mid and small, Focused <= 30 stocks, equity categories >= 65% (ELSS 80%) in
shares. Company sizes here use today's market caps; AMFI's official list uses
six-month averages, so a fund right at a limit may differ slightly.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CACHE_SECONDS = 12 * 3600
MARKET_N = 100  # "the market" for style = the 100 largest companies (like the Nifty 100)
VALUE_GROWTH_BAND = 0.15  # average log ratio beyond +-0.15 (~16%) leaves Blend

# category keyword -> list of (rule label, check(split, equity_pct, count) -> bool)
RULES: list[tuple[str, list[tuple[str, Callable[[dict, float, int], bool]]]]] = [
    ("large & mid", [("At least 35% in large caps", lambda s, e, n: s["large"] >= 35),
                     ("At least 35% in mid caps", lambda s, e, n: s["mid"] >= 35)]),
    ("large cap", [("At least 80% in large caps", lambda s, e, n: s["large"] >= 80)]),
    ("mid cap", [("At least 65% in mid caps", lambda s, e, n: s["mid"] >= 65)]),
    ("small cap", [("At least 65% in small caps", lambda s, e, n: s["small"] >= 65)]),
    ("multi cap", [("At least 75% in shares", lambda s, e, n: e >= 75),
                   ("At least 25% each in large, mid and small caps",
                    lambda s, e, n: min(s["large"], s["mid"], s["small"]) >= 25)]),
    ("focused", [("No more than 30 stocks", lambda s, e, n: n <= 30),
                 ("At least 65% in shares", lambda s, e, n: e >= 65)]),
    ("elss", [("At least 80% in shares", lambda s, e, n: e >= 80)]),
    ("flexi cap", [("At least 65% in shares", lambda s, e, n: e >= 65)]),
    ("value", [("At least 65% in shares", lambda s, e, n: e >= 65)]),
    ("contra", [("At least 65% in shares", lambda s, e, n: e >= 65)]),
    ("dividend yield", [("At least 65% in shares", lambda s, e, n: e >= 65)]),
]

_cache: dict[str, tuple[float, dict]] = {}
_market: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()

InfoFetch = Callable[[str], dict]


def _info(symbol: str) -> dict:
    from .analysis_run import yahoo_symbol
    from .compare import _yahoo_info

    return _yahoo_info(yahoo_symbol(symbol, "india")) or {}


def _pos(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def weighted_ratios(items: list[tuple[float, dict]]) -> dict:
    """items: (weight, yahoo info). Harmonic weight-average for P/E and P/B (a
    loss-maker's P/E is skipped), plain weight-average for ROE; with coverage."""
    out: dict = {}
    total = sum(w for w, _ in items) or 1.0
    for key, field in (("pe", "trailingPE"), ("pb", "priceToBook")):
        pairs = [(w, _pos(i.get(field))) for w, i in items]
        pairs = [(w, v) for w, v in pairs if v]
        cover = sum(w for w, _ in pairs)
        out[key] = cover / sum(w / v for w, v in pairs) if pairs else None
        out[f"{key}_coverage"] = cover / total * 100
    roe = [(w, i.get("returnOnEquity")) for w, i in items if isinstance(i.get("returnOnEquity"), (int, float))]
    cw = sum(w for w, _ in roe)
    out["roe"] = sum(w * v for w, v in roe) / cw * 100 if cw else None
    return out


def market_ratios(fetch: InfoFetch = _info, rows: Optional[list[dict]] = None) -> dict:
    """Cap-weighted P/E and P/B of the 100 largest Indian companies, cached."""
    with _lock:
        hit = _market.get("india")
    if rows is None and hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows("india")
    top = sorted((r for r in rows if r.get("type") == "stock" and r.get("market_cap")),
                 key=lambda r: -r["market_cap"])[:MARKET_N]
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(lambda r: fetch(r["symbol"]), top))
    out = weighted_ratios([(r["market_cap"], i or {}) for r, i in zip(top, infos)])
    with _lock:
        _market["india"] = (time.time(), out)
    return out


def style_label(fund: dict, market: dict) -> Optional[dict]:
    logs = [math.log(fund[k] / market[k]) for k in ("pe", "pb") if fund.get(k) and market.get(k)]
    if not logs:
        return None
    score = sum(logs) / len(logs)
    label = "Value" if score < -VALUE_GROWTH_BAND else "Growth" if score > VALUE_GROWTH_BAND else "Blend"
    return {"label": label, "score": score}


def size_label(split: dict) -> Optional[str]:
    domestic = split["large"] + split["mid"] + split["small"]
    if domestic <= 0:
        return None
    large, mid, small = (split[k] / domestic * 100 for k in ("large", "mid", "small"))
    if large >= 70:
        return "Large"
    if small >= 35:
        return "Small"
    if mid >= 35:
        return "Mid"
    return "Multi"


def rule_checks(category: Optional[str], split: dict, equity_pct: float, count: int) -> list[dict]:
    cat = (category or "").lower()
    for key, rules in RULES:
        if key in cat:
            return [{"rule": label, "ok": bool(check(split, equity_pct, count))} for label, check in rules]
    return []


def build(code: str, holdings: Optional[dict] = None, fetch: InfoFetch = _info,
          market: Optional[dict] = None, category: Optional[str] = None, use_cache: bool = True) -> dict:
    code = str(code)
    if use_cache and holdings is None:
        with _lock:
            hit = _cache.get(code)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    if holdings is None:
        from . import fund_holdings

        holdings = fund_holdings.for_fund(code)
    if holdings.get("status") != "ok":
        return {"status": "missing", "note": holdings.get("note") or "Holdings are not available for this fund yet."}
    if category is None:
        from ..data.listings import get_store

        row = next((r for r in get_store().rows("india") if r.get("type") == "mf" and str(r["symbol"]) == code), {})
        category = row.get("sector")
    split = {"large": 0.0, "mid": 0.0, "small": 0.0, "foreign": 0.0, "other": 0.0}
    for c in holdings.get("cap_split") or []:
        split[c["kind"]] = c["weight"]
    stocks = [h for h in holdings.get("holdings", []) if h.get("kind") in ("equity", "foreign_equity") and h.get("weight")]
    equity_pct = sum(h["weight"] for h in stocks)
    indian = [h for h in stocks if h.get("symbol")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(lambda h: fetch(h["symbol"]), indian))
    ratios = weighted_ratios([(h["weight"], i or {}) for h, i in zip(indian, infos)])
    mkt = market if market is not None else market_ratios(fetch)
    out = {"status": "ok", "category": category, "size": size_label(split), "style": style_label(ratios, mkt),
           "fund": ratios, "market": mkt, "equity_pct": equity_pct, "split": split, "count": len(stocks),
           "checks": rule_checks(category, split, equity_pct, len(stocks)), "as_of": holdings.get("as_of"),
           "note": "Valuations from the market data feed for the fund's Indian holdings; 'market' = the 100 largest "
                   "Indian companies. Company sizes use today's market caps (AMFI's official list uses "
                   "six-month averages)."}
    if use_cache:
        with _lock:
            _cache[code] = (time.time(), out)
    return out
