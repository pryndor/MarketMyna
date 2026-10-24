"""Market discovery: index snapshot, breadth, top gainers / losers / most
active, 52-week extremes and sector performance for one market.

Everything except the index quotes comes from the listings store
(marketmyna/data/listings.py), which already carries each stock's price, day change,
volume, market cap, sector and 52-week range, so no extra downloads are needed.
Modeled on the OpenBB equity.discovery endpoints (Apache 2.0).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DISCOVERY_MARKETS = ("india", "us", "china_a", "hong_kong", "crypto")
INDEX_TTL = 60
TOP = 50  # rows per leader board (the table scrolls)
SECTOR_MEMBERS = 8  # stocks listed when a sector is pinned

_index_cache: dict[str, tuple[float, list[dict]]] = {}
_index_lock = threading.Lock()


def _indices(market: str) -> list[dict]:
    from .analysis_run import market_overview

    now = time.time()
    with _index_lock:
        hit = _index_cache.get(market)
        if hit and now - hit[0] < INDEX_TTL:
            return hit[1]
    try:
        rows = market_overview([market])
    except Exception as exc:
        logger.warning("Index snapshot for %s failed: %s", market, exc)
        rows = []
    with _index_lock:
        _index_cache[market] = (now, rows)
    return rows


def _item(r: dict) -> dict:
    price, volume = r.get("price"), r.get("volume")
    return {
        "symbol": r["symbol"], "name": r.get("name"), "price": price, "change_percent": r.get("change_percent"),
        "volume": volume, "traded_value": price * volume if price and volume else None,
        "market_cap": r.get("market_cap"), "currency": r.get("currency"), "sector": r.get("sector"),
        "high_52w": r.get("high_52w"), "low_52w": r.get("low_52w"),
    }


def _priced(r: dict) -> bool:
    return r.get("price") is not None and r.get("change_percent") is not None and (r.get("volume") or 0) > 0


def build(market: str, size: int = 500, rows: Optional[list[dict]] = None, with_indices: bool = True,
          live: Optional[dict] = None) -> dict:
    """Discovery payload. `size` = how many of the largest names (by market cap,
    by volume for crypto) the leader boards rank, so illiquid micro-caps do not
    flood the gainers list. Breadth always covers every priced stock.

    `live` = live_market.market(): its quotes replace the snapshot prices, and
    only live-priced names are ranked, so today's moves never mix with an
    earlier session's."""
    from ..data.listings import get_store
    from .live_market import merge

    store = get_store()
    if rows is None:
        rows = store.rows(market)
    quotes = (live or {}).get("quotes") or {}
    if quotes:
        rows = merge(rows, quotes, only_live=True)
    kind = "crypto" if market == "crypto" else "stock"
    stocks = [r for r in rows if r.get("type") == kind and _priced(r)]

    size_key = "volume" if market == "crypto" else "market_cap"
    universe = sorted((r for r in stocks if r.get(size_key)), key=lambda r: -r[size_key])[:max(20, size)]

    by_change = sorted(universe, key=lambda r: r["change_percent"])
    traded = sorted(universe, key=lambda r: -(r["price"] * r["volume"]))

    def near(r: dict, key: str) -> Optional[float]:
        ref = r.get(key)
        return (r["price"] / ref - 1) * 100 if ref else None

    with_range = [r for r in universe if r.get("high_52w") and r.get("low_52w")]
    near_high = sorted((r for r in with_range if near(r, "high_52w") >= -2), key=lambda r: -near(r, "high_52w"))
    near_low = sorted((r for r in with_range if near(r, "low_52w") <= 2), key=lambda r: near(r, "low_52w"))

    adv = sum(r["change_percent"] > 0 for r in stocks)
    dec = sum(r["change_percent"] < 0 for r in stocks)

    sectors: dict[str, dict] = {}
    for r in universe:
        # Broad category (same taxonomy in every market), not the exchange's fine-grained sector.
        name = r.get("category")
        if market == "crypto" or not name or name == "Other":
            continue
        s = sectors.setdefault(name, {"sector": name, "count": 0, "advancers": 0, "decliners": 0,
                                      "_w": 0.0, "_wc": 0.0, "_rows": [], "leader": None, "laggard": None})
        weight = r.get(size_key) or 0
        s["count"] += 1
        s["advancers"] += r["change_percent"] > 0
        s["decliners"] += r["change_percent"] < 0
        s["_w"] += weight
        s["_wc"] += weight * r["change_percent"]
        s["_rows"].append((weight, r))
        if s["leader"] is None or r["change_percent"] > s["leader"]["change_percent"]:
            s["leader"] = {"symbol": r["symbol"], "change_percent": r["change_percent"]}
        if s["laggard"] is None or r["change_percent"] < s["laggard"]["change_percent"]:
            s["laggard"] = {"symbol": r["symbol"], "change_percent": r["change_percent"]}
    sector_rows = []
    for s in sectors.values():
        w, wc = s.pop("_w"), s.pop("_wc")
        s["change_percent"] = wc / w if w else None
        # Largest stocks first, so a pinned sector shows what drives its number.
        biggest = sorted(s.pop("_rows"), key=lambda t: -t[0])[:SECTOR_MEMBERS]
        s["members"] = [{"symbol": r["symbol"], "change_percent": r["change_percent"]} for _, r in biggest]
        sector_rows.append(s)
    sector_rows.sort(key=lambda s: -(s["change_percent"] if s["change_percent"] is not None else -1e9))

    if quotes:
        as_of = datetime.fromtimestamp(live["status"]["updated"]).isoformat(timespec="seconds")
    else:
        fetched = [s.get("fetched_at") for s in store.status() if s["market"] == market and s.get("fetched_at")]
        as_of = max(fetched) if fetched else None
    return {
        "market": market,
        "as_of": as_of,
        "live": (live or {}).get("status"),
        "universe": len(universe),
        "indices": _indices(market) if with_indices else [],
        "breadth": {"advancers": adv, "decliners": dec, "unchanged": len(stocks) - adv - dec, "total": len(stocks)},
        "gainers": [_item(r) for r in reversed(by_change[-TOP:]) if r["change_percent"] > 0],
        "losers": [_item(r) for r in by_change[:TOP] if r["change_percent"] < 0],
        "active": [_item(r) for r in traded[:TOP]],
        "near_high": [_item(r) for r in near_high[:TOP]],
        "near_low": [_item(r) for r in near_low[:TOP]],
        "sectors": sector_rows,
    }
