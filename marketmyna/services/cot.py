"""Commitments of Traders: how hedge funds and producers are positioned in the
main US commodity futures, from the CFTC's disaggregated futures-only report
(publicreporting.cftc.gov, no key).

Positions are as of each Tuesday and published the following Friday. For each
market this gives managed money (hedge funds, CTAs) net long contracts, the
weekly change, net as a share of open interest, producers' / merchants' net
(commercial hedgers) and a 3-year position index: where this week's managed
money net sits between its 3-year low (0) and high (100). The reading is a
description of positioning, not a forecast. Brent is not covered: it trades on
ICE Futures Europe, outside the CFTC's report.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, timedelta
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

API = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
CACHE_SECONDS = 6 * 3600
YEARS = 3

# Yahoo ticker on the Commodities card, label, CFTC contract market code
MARKETS = [
    ("GC=F", "Gold", "088691"),
    ("SI=F", "Silver", "084691"),
    ("HG=F", "Copper", "085692"),
    ("CL=F", "WTI crude", "067651"),
    ("NG=F", "Natural gas", "023651"),
    ("ZW=F", "Wheat", "001602"),
    ("ZC=F", "Corn", "002602"),
]

Fetch = Callable[[list[str], date], list[dict]]

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _fetch(codes: list[str], since: date) -> list[dict]:
    where = (f"cftc_contract_market_code in({','.join(repr(c) for c in codes)}) "
             f"AND report_date_as_yyyy_mm_dd >= '{since.isoformat()}T00:00:00'")
    params = {
        "$select": ("cftc_contract_market_code,report_date_as_yyyy_mm_dd,open_interest_all,"
                    "m_money_positions_long_all,m_money_positions_short_all,"
                    "prod_merc_positions_long,prod_merc_positions_short"),
        "$where": where,
        "$order": "report_date_as_yyyy_mm_dd",
        "$limit": 5000,
    }
    r = requests.get(API, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _int(row: dict, key: str) -> int:
    return int(float(row.get(key) or 0))


def reading(index: Optional[float]) -> str:
    if index is None:
        return ""
    if index >= 90:
        return "Funds near their most long in 3 years"
    if index <= 10:
        return "Funds near their most short in 3 years"
    if index >= 70:
        return "Funds longer than usual"
    if index <= 30:
        return "Funds shorter than usual"
    return "Fund positioning mid-range"


def summarise(rows: list[dict]) -> Optional[dict]:
    """One market's weekly rows (oldest first) -> latest positioning."""
    weeks = []
    for r in rows:
        weeks.append({
            "date": (r.get("report_date_as_yyyy_mm_dd") or "")[:10],
            "oi": _int(r, "open_interest_all"),
            "mm_net": _int(r, "m_money_positions_long_all") - _int(r, "m_money_positions_short_all"),
            "mm_long": _int(r, "m_money_positions_long_all"),
            "mm_short": _int(r, "m_money_positions_short_all"),
            "prod_net": _int(r, "prod_merc_positions_long") - _int(r, "prod_merc_positions_short"),
        })
    weeks = sorted({w["date"]: w for w in weeks if w["date"]}.values(), key=lambda w: w["date"])
    if not weeks:
        return None
    last = weeks[-1]
    nets = [w["mm_net"] for w in weeks]
    lo, hi = min(nets), max(nets)
    index = round((last["mm_net"] - lo) / (hi - lo) * 100) if hi > lo and len(weeks) >= 52 else None
    return {
        "as_of": last["date"],
        "open_interest": last["oi"],
        "managed_money_long": last["mm_long"],
        "managed_money_short": last["mm_short"],
        "managed_money_net": last["mm_net"],
        "net_change_1w": last["mm_net"] - weeks[-2]["mm_net"] if len(weeks) > 1 else None,
        "net_pct_oi": round(last["mm_net"] / last["oi"] * 100, 1) if last["oi"] else None,
        "producer_net": last["prod_net"],
        "index_3y": index,
        "reading": reading(index),
        "history": [w["mm_net"] for w in weeks[-52:]],
    }


def build(fetch: Fetch = _fetch, use_cache: bool = True, today: Optional[date] = None) -> dict:
    if use_cache:
        with _lock:
            hit = _cache.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]

    since = (today or date.today()) - timedelta(days=365 * YEARS + 7)
    try:
        raw = fetch([code for *_, code in MARKETS], since)
    except Exception as exc:
        logger.warning("CFTC commitments of traders fetch failed: %s", exc)
        raw = []

    by_code: dict[str, list[dict]] = {}
    for r in raw:
        by_code.setdefault(r.get("cftc_contract_market_code", "").strip(), []).append(r)

    items = []
    for ticker, label, code in MARKETS:
        s = summarise(by_code.get(code, []))
        if s:
            items.append({"key": ticker, "label": label, **s})

    out = {
        "items": items,
        "as_of": max((i["as_of"] for i in items), default=None),
        "source": "CFTC Commitments of Traders (disaggregated, futures only); positions as of Tuesday, "
                  "published Friday. Managed money = hedge funds and commodity trading advisers",
    }
    if use_cache and items:
        with _lock:
            _cache["all"] = (time.time(), out)
    return out
