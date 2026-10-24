"""Valuation meter for one stock: how its price compares with its sector.

At today's price, the stock's P/E, price/book and price/sales are each divided
by the median of the same sector among the market's largest companies (the
universe the ready-made screens use). The combined position is the geometric
mean of those multiples:

    below 0.8x  -> priced below its sector
    0.8 - 1.2x  -> in line with its sector
    above 1.2x  -> priced above its sector

A separate growth check reports PEG (P/E / earnings growth %) and the rules of
the "Growth at a reasonable price" screen, each pass/fail, so a dear stock
that is growing fast is visible as such. Everything is a comparison with
numbers shown; the label wording is chosen by the frontend (see
sebi-compliance-mode.md: no bare "overvalued" on public deploys).
"""

from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from ..core.numbers import finite as _num
from ..core.numbers import median as _median
from ..data.yahoo_price import info_price

UNIVERSE = 200
MIN_PEERS = 5  # profitable companies a sector needs before its median means anything
BELOW, ABOVE = 0.8, 1.2
CACHE_SECONDS = 6 * 3600

# key -> (Yahoo field, label)
MULTIPLES = {
    "pe": ("trailingPE", "P/E"),
    "pb": ("priceToBook", "Price / book"),
    "ps": ("priceToSalesTrailing12Months", "Price / sales"),
}

InfoFetch = Callable[[str], dict]

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def sector_medians(market: str, info_fetch: Optional[InfoFetch] = None, rows: Optional[list[dict]] = None) -> dict:
    """sector -> {pe, pb, ps: median or None, n: profitable companies}, from
    the market's largest stocks. Cached for a few hours per market."""
    if info_fetch is None and rows is None:
        with _lock:
            hit = _cache.get(market)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    from .analysis_run import yahoo_symbol
    from .compare import _yahoo_info

    fetch = info_fetch or _yahoo_info
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows(market)
    stocks = sorted((r for r in rows if r.get("type") == "stock" and r.get("market_cap")),
                    key=lambda r: -r["market_cap"])[:UNIVERSE]
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(lambda r: fetch(yahoo_symbol(r["symbol"], market)), stocks))

    groups: dict[str, dict[str, list[float]]] = {}
    for info in infos:
        sector = (info or {}).get("sector")
        pe = _num((info or {}).get("trailingPE"))
        if not sector or not pe or pe <= 0:
            continue  # loss-makers would drag a P/E median around
        g = groups.setdefault(sector, {k: [] for k in MULTIPLES})
        for key, (field, _) in MULTIPLES.items():
            v = _num(info.get(field))
            if v and v > 0:
                g[key].append(v)
    out = {s: {"n": len(g["pe"]), **{k: _median(g[k]) for k in MULTIPLES}} for s, g in groups.items()}
    if info_fetch is None and rows is None:
        with _lock:
            _cache[market] = (time.time(), out)
    return out


def zone(position: Optional[float]) -> Optional[str]:
    if position is None:
        return None
    if position < BELOW:
        return "below"
    if position > ABOVE:
        return "above"
    return "in_line"


def _garp(info: dict, pe: Optional[float]) -> dict:
    """PEG and the "Growth at a reasonable price" screen rules, each checked."""
    from .screens import PRESETS, _rule_text, metrics

    m = metrics(info)
    growth = m.get("earnings_growth")
    peg = pe / growth if pe and pe > 0 and growth and growth > 0 else None
    rules = []
    for rule in PRESETS["garp"][3]:
        field, op, value = rule
        v = m.get(field)
        ok = v is not None and ((op == ">" and v > value) or (op == "<" and v < value)
                                or (op == "between" and value[0] < v < value[1]))
        # pass: True / False, or None when Yahoo has no figure (not counted).
        rules.append({"rule": _rule_text(rule), "field": field, "value": v, "pass": None if v is None else bool(ok)})
    known = [r for r in rules if r["pass"] is not None]
    return {
        "peg": peg,
        "earnings_growth": growth,
        "revenue_growth": m.get("revenue_growth"),
        "rules": rules,
        "passed": sum(1 for r in known if r["pass"]),
        "total": len(known),
        "missing": len(rules) - len(known),
    }


def meter(symbol: str, market: str, info_fetch: Optional[InfoFetch] = None,
          medians: Optional[dict] = None) -> dict:
    from .analysis_run import yahoo_symbol
    from .compare import _yahoo_info

    if market == "crypto":
        return {"status": "unavailable", "reason": "Crypto has no earnings or book value to compare."}
    info = (info_fetch or _yahoo_info)(yahoo_symbol(symbol, market)) or {}
    if not info:
        return {"status": "unavailable", "reason": "No fundamentals available for this symbol right now."}
    sector = info.get("sector")
    if medians is None:
        medians = sector_medians(market)
    peers = medians.get(sector or "") or {}

    pe = _num(info.get("trailingPE"))
    multiples, ratios = [], []
    for key, (field, label) in MULTIPLES.items():
        v = _num(info.get(field))
        med = peers.get(key) if peers.get("n", 0) >= MIN_PEERS else None
        ratio = v / med if v and v > 0 and med else None
        if ratio:
            ratios.append(ratio)
        multiples.append({"key": key, "label": label, "value": v, "sector_median": med, "ratio": ratio})

    position = math.exp(sum(math.log(r) for r in ratios) / len(ratios)) if ratios else None
    reason = None
    if position is None:
        if not sector:
            reason = "Our market data has no sector for this company, so there is no peer group to compare with."
        elif peers.get("n", 0) < MIN_PEERS:
            reason = f"Too few profitable {sector} companies among the market's largest to form a sector median."
        else:
            reason = "The company has no positive P/E, book value or sales figure to compare (for example a loss-maker)."
    return {
        "status": "ok" if position is not None else "unavailable",
        "reason": reason,
        "symbol": symbol,
        "sector": sector,
        "peers": peers.get("n", 0),
        "universe": f"the {UNIVERSE} largest companies in this market",
        "price": info_price(info),
        "currency": info.get("currency"),
        "multiples": multiples,
        "position": position,
        "zone": zone(position),
        "bands": {"below": BELOW, "above": ABOVE},
        "garp": _garp(info, pe),
    }
