"""Hot stocks, by what each side of the app is looking for.

Trader: what is moving *today* and tradeable - built only from the listings
store (price, day change, volume, market cap, 52-week range), so it is
instant and refreshes with prices:
  momentum     big move on heavy trading
  breakouts    within 2% of the 52-week high and up today
  activity     traded far more of its size than the market usually does
  selloffs     down 3% or more on heavy trading
  bounces      near the 52-week low but bouncing hard today
  breakdowns   at or below the 52-week low and falling
Boards that need the 52-week range say so when a market's listing feed has
none (the US feed carries no range).

"Activity" is turnover (traded value / market cap) against the median
turnover of the same universe: there is no free average-volume field in the
listings, and a stock trading 4x the market's typical share of its size is
the same signal traders look for in volume surges.

Investor: businesses the market is re-pricing over weeks to months, with the
fundamentals to back them - the screens' Yahoo fundamentals (shared 6-hour
cache) combined with where price sits in its 52-week range:
  quality_dip     strong, profitable, low debt, 10-30% off the high
  earnings        fast earnings and revenue growth, price near highs
  value_turning   cheap against its own sector and climbing off the low
  compounders     high returns, fat margins, little debt, at new highs
  income          dividend payers with sustainable payouts, off the high
  funds_adding    (India) stocks mutual funds added most last month
Crypto has no fundamentals, so investors get size-and-range boards there.

Facts, not calls: every row carries a plain "why" line, never buy / sell.
"""

from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, Optional

from ..core.numbers import finite as _f
from ..core.numbers import median as _median

TOP = 20  # rows per board
INVESTOR_TTL = 6 * 3600

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _base(r: dict, market: str) -> dict:
    return {"symbol": r["symbol"], "name": r.get("name"), "market": market, "price": r.get("price"),
            "change_percent": r.get("change_percent"), "market_cap": r.get("market_cap"),
            "currency": r.get("currency"), "sector": r.get("category") or r.get("sector")}


def _range(r: dict) -> tuple[Optional[float], Optional[float]]:
    """Percent from the 52-week high (<= 0) and above the 52-week low (>= 0)."""
    p, hi, lo = _f(r.get("price")), _f(r.get("high_52w")), _f(r.get("low_52w"))
    return ((p / hi - 1) * 100 if p and hi else None, (p / lo - 1) * 100 if p and lo else None)


def _board(key: str, title: str, description: str, rows: list[dict], note: Optional[str] = None) -> dict:
    return {"key": key, "title": title, "description": description, "rows": rows[:TOP], "note": note}


# ---------------------------------------------------------------- trader

def trader(market: str, rows: Optional[list[dict]] = None, size: int = 500, live: Optional[dict] = None) -> dict:
    """`live` = live_market.market(): boards are ranked on live prices, among
    live-priced names only."""
    from ..data.listings import get_store
    from .live_market import merge

    store = get_store()
    if rows is None:
        rows = store.rows(market)
    quotes = (live or {}).get("quotes") or {}
    if quotes:
        rows = merge(rows, quotes, only_live=True)
    kind = "crypto" if market == "crypto" else "stock"
    priced = [r for r in rows if r.get("type") == kind and _f(r.get("price")) and r.get("change_percent") is not None
              and (r.get("volume") or 0) > 0]
    size_key = "volume" if market == "crypto" else "market_cap"
    universe = sorted((r for r in priced if r.get(size_key)), key=lambda r: -r[size_key])[:max(50, size)]

    # Tradeable only: drop the thinnest third by traded value.
    traded = sorted(universe, key=lambda r: r["price"] * r["volume"])
    liquid = traded[len(traded) // 3:]

    turnovers = [r["price"] * r["volume"] / r["market_cap"] for r in liquid if r.get("market_cap")]
    typical = _median(turnovers)

    def activity(r: dict) -> Optional[float]:
        if not typical or not r.get("market_cap"):
            return None
        return (r["price"] * r["volume"] / r["market_cap"]) / typical

    def row(r: dict, why: str) -> dict:
        from_high, from_low = _range(r)
        act = activity(r)
        return {**_base(r, market), "traded_value": r["price"] * r["volume"], "activity": act,
                "from_high": from_high, "from_low": from_low, "why": why}

    def act_text(r: dict) -> str:
        a = activity(r)
        return f" on {a:.1f}× usual activity" if a and a >= 1.5 else ""

    chg = lambda r: r["change_percent"]  # noqa: E731

    momentum = sorted((r for r in liquid if chg(r) >= 2), key=lambda r: -(chg(r) * (1 + min(activity(r) or 1, 5)) ** 0.5))
    breakouts = []
    for r in liquid:
        from_high, _ = _range(r)
        if from_high is not None and from_high >= -2 and chg(r) > 0:
            breakouts.append(r)
    breakouts.sort(key=lambda r: -chg(r))
    unusual = sorted((r for r in liquid if (activity(r) or 0) >= 2.5), key=lambda r: -(activity(r) or 0))
    selloffs = sorted((r for r in liquid if chg(r) <= -3), key=lambda r: chg(r) * (1 + min(activity(r) or 1, 5)) ** 0.5)
    has_range = sum(1 for r in liquid if r.get("high_52w") and r.get("low_52w")) >= len(liquid) / 2
    no_range = None if has_range else "This market's listing feed has no 52-week range, so this board is empty here."
    bounces, breakdowns = [], []
    for r in liquid:
        _, from_low = _range(r)
        if from_low is None:
            continue
        if from_low <= 8 and chg(r) >= 2:
            bounces.append(r)
        if from_low <= 1 and chg(r) <= -1:
            breakdowns.append(r)
    bounces.sort(key=lambda r: -chg(r))
    breakdowns.sort(key=chg)

    boards = [
        _board("momentum", "Momentum", "Up 2% or more today, strongest moves on heavy trading first",
               [row(r, f"{chg(r):+.1f}% today{act_text(r)}") for r in momentum]),
        _board("breakouts", "Breakouts", "Within 2% of the 52-week high and up today",
               [row(r, f"{abs(_range(r)[0]):.1f}% from the 52-week high, {chg(r):+.1f}% today{act_text(r)}") for r in breakouts],
               no_range),
        _board("activity", "Unusual activity", "Trading 2.5× or more of the market's usual share of their size",
               [row(r, f"{activity(r):.1f}× usual activity, {chg(r):+.1f}% today") for r in unusual]),
        _board("selloffs", "Sell-offs", "Down 3% or more today, heaviest trading first",
               [row(r, f"{chg(r):+.1f}% today{act_text(r)}") for r in selloffs]),
        _board("bounces", "Bouncing off lows", "Within 8% of the 52-week low and up 2% or more today",
               [row(r, f"{_range(r)[1]:.1f}% above the 52-week low, {chg(r):+.1f}% today") for r in bounces], no_range),
        _board("breakdowns", "Breaking down", "At or under the 52-week low and falling today",
               [row(r, f"at the 52-week low, {chg(r):+.1f}% today{act_text(r)}") for r in breakdowns], no_range),
    ]
    if market == "crypto":  # no market cap, so no activity measure
        boards = [b for b in boards if b["key"] != "activity"]
    if quotes:
        as_of = datetime.fromtimestamp(live["status"]["updated"]).isoformat(timespec="seconds")
    else:
        fetched = [s.get("fetched_at") for s in store.status() if s["market"] == market and s.get("fetched_at")]
        as_of = max(fetched) if fetched else None
    return {"market": market, "area": "trader", "as_of": as_of, "live": (live or {}).get("status"),
            "universe": f"{len(liquid)} most-traded of the largest {len(universe)}", "boards": boards}


def with_live_prices(out: dict, live: Optional[dict]) -> dict:
    """Investor boards (picked on fundamentals, cached for hours) with each
    row's price, day change and distance from the 52-week high / low taken
    from live quotes."""
    quotes = (live or {}).get("quotes") or {}
    if not quotes:
        return out
    boards = []
    for b in out.get("boards", []):
        rows = []
        for r in b["rows"]:
            q = quotes.get(r["symbol"])
            if q:
                r = {**r, "price": q["price"], "change_percent": q.get("change_percent", r.get("change_percent"))}
                for key, ref in (("from_high", "high_52w"), ("from_low", "low_52w")):
                    if r.get(ref):
                        r[key] = (q["price"] / r[ref] - 1) * 100
            rows.append(r)
        boards.append({**b, "rows": rows})
    return {**out, "boards": boards, "live": live["status"]}


# ---------------------------------------------------------------- investor

InfoFetch = Callable[[str], dict]


def investor(market: str, rows: Optional[list[dict]] = None, info_fetch: Optional[InfoFetch] = None,
             use_cache: bool = True) -> dict:
    if use_cache and rows is None and info_fetch is None:
        with _lock:
            hit = _cache.get(market)
        if hit and time.time() - hit[0] < INVESTOR_TTL:
            return hit[1]
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows(market)
    out = _crypto_investor(rows) if market == "crypto" else _stock_investor(market, rows, info_fetch)
    if use_cache and info_fetch is None:
        with _lock:
            _cache[market] = (time.time(), out)
    return out


def _stock_investor(market: str, rows: list[dict], info_fetch: Optional[InfoFetch]) -> dict:
    from . import screens
    from .analysis_run import yahoo_symbol

    if info_fetch is None:
        from .compare import _yahoo_info as info_fetch
    stocks = sorted((r for r in rows if r.get("type") == "stock" and r.get("market_cap")),
                    key=lambda r: -r["market_cap"])[:screens.UNIVERSE]
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(lambda r: info_fetch(yahoo_symbol(r["symbol"], market)), stocks))

    measured = []
    seen = set()
    for r, info in zip(stocks, infos):
        if not info:
            continue
        company = (info.get("longName") or info.get("shortName") or r["symbol"]).lower()
        if company in seen:  # second share class of the same company
            continue
        seen.add(company)
        m = screens.metrics(info)
        m["sector"] = info.get("sector") or r.get("sector")
        # Listings prices are fresher than Yahoo's info snapshot.
        live_high, live_low = _range(r)
        m["from_high"] = live_high if live_high is not None else m["from_high"]
        m["from_low"] = live_low if live_low is not None else m["from_low"]
        measured.append((r, m))
    screens._sector_relative([m for _, m in measured])

    def g(m: dict, k: str) -> float:
        return m.get(k) if m.get(k) is not None else math.nan

    def pick(test, sort_key, why) -> list[dict]:
        hits = [(r, m) for r, m in measured if test(m)]
        hits.sort(key=lambda t: sort_key(t[1]))
        return [{**_base(r, market), "sector": m["sector"] or r.get("category"),
                 **{k: m.get(k) for k in ("pe", "pe_vs_sector", "roe", "debt_equity", "earnings_growth",
                                          "revenue_growth", "operating_margin", "dividend_yield", "payout",
                                          "from_high", "from_low")},
                 "why": why(m)} for r, m in hits]

    def pct(v: Optional[float]) -> str:
        return f"{v:.0f}%" if v is not None else "—"

    boards = [
        _board("quality_dip", "Quality on a dip",
               "ROE over 15%, debt under equity, earnings growing - and 10-30% below the 52-week high",
               pick(lambda m: g(m, "roe") > 15 and g(m, "debt_equity") < 1 and g(m, "earnings_growth") > 0
                    and -30 <= g(m, "from_high") <= -10,
                    lambda m: -m["roe"],
                    lambda m: f"ROE {pct(m['roe'])}, EPS growth {pct(m['earnings_growth'])}, {abs(m['from_high']):.0f}% off the high")),
        _board("earnings", "Earnings momentum",
               "EPS growth 20-300% and revenue growth over 10%, price within 15% of the high; fastest sales growth first",
               # EPS growth over 300% is usually a one-off (a loss year last year), not momentum.
               pick(lambda m: 20 < g(m, "earnings_growth") < 300 and g(m, "revenue_growth") > 10 and g(m, "from_high") >= -15,
                    lambda m: -m["revenue_growth"],
                    lambda m: f"EPS {pct(m['earnings_growth'])}, revenue {pct(m['revenue_growth'])}, {abs(m['from_high']):.0f}% off the high")),
        _board("value_turning", "Cheap vs sector, turning up",
               "P/E under 85% of the sector median, profitable and growing, 15%+ above the 52-week low",
               pick(lambda m: g(m, "pe_vs_sector") < 0.85 and g(m, "pe") > 0 and g(m, "roe") > 10
                    and g(m, "earnings_growth") > 0 and g(m, "from_low") >= 15,
                    lambda m: m["pe_vs_sector"],
                    lambda m: f"P/E {m['pe']:.0f} = {m['pe_vs_sector']:.2f}× sector, {m['from_low']:.0f}% above the low")),
        _board("compounders", "Compounders at highs",
               "ROE over 18%, operating margin over 15%, little debt, within 10% of the 52-week high",
               pick(lambda m: g(m, "roe") > 18 and g(m, "operating_margin") > 15 and g(m, "debt_equity") < 0.5
                    and g(m, "from_high") >= -10,
                    lambda m: -m["roe"],
                    lambda m: f"ROE {pct(m['roe'])}, margin {pct(m['operating_margin'])}, debt/eq {m['debt_equity']:.2f}")),
        _board("income", "Dividend payers off the high",
               "Yield over 2.5% with payout under 80%, 10% or more below the 52-week high",
               pick(lambda m: g(m, "dividend_yield") > 2.5 and 0 < g(m, "payout") < 80 and g(m, "from_high") <= -10,
                    lambda m: -m["dividend_yield"],
                    lambda m: f"yield {m['dividend_yield']:.1f}%, payout {pct(m['payout'])}, {abs(m['from_high']):.0f}% off the high")),
    ]
    if market == "india":
        adding = funds_adding(rows)
        if adding:
            boards.append(_board("funds_adding", "Mutual funds adding",
                                 "Stocks the most fund schemes bought or added to in their latest monthly portfolio",
                                 adding))
    return {"market": market, "area": "investor", "as_of": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "universe": f"Largest {len(stocks)} stocks by market cap ({len(measured)} with fundamentals)",
            "boards": boards}


def _crypto_investor(rows: list[dict]) -> dict:
    coins = sorted((r for r in rows if r.get("type") == "crypto" and _f(r.get("price")) and r.get("volume")),
                   key=lambda r: -(r["price"] * r["volume"]))[:50]

    def item(r: dict, why: str) -> dict:
        from_high, from_low = _range(r)
        return {**_base(r, "crypto"), "from_high": from_high, "from_low": from_low, "why": why}

    dips = [r for r in coins if (_range(r)[0] or 0) <= -30]
    dips.sort(key=lambda r: _range(r)[0])
    strong = [r for r in coins if (_range(r)[0] or -100) >= -10]
    strong.sort(key=lambda r: -(_range(r)[0] or -100))
    return {"market": "crypto", "area": "investor", "as_of": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "universe": "50 most-traded coins",
            "boards": [
                _board("crypto_dips", "Large coins far off the high", "Most-traded coins 30% or more below their 52-week high",
                       [item(r, f"{abs(_range(r)[0]):.0f}% below the 52-week high") for r in dips]),
                _board("crypto_strong", "Large coins near highs", "Most-traded coins within 10% of their 52-week high",
                       [item(r, f"{abs(_range(r)[0]):.0f}% below the 52-week high") for r in strong]),
            ]}


def funds_adding(rows: list[dict], limit: int = TOP) -> list[dict]:
    """India: count fund schemes that newly bought or raised a stock between
    their last two monthly portfolio files (marketmyna/services/fund_holdings.py)."""
    try:
        from . import fund_holdings as fh

        root = fh._root()
        folders = [p for p in root.iterdir() if p.is_dir()] if root.exists() else []
    except Exception:
        return []
    by_isin = {r["isin"]: r for r in rows if r.get("type") == "stock" and r.get("isin")}
    tally: dict[str, dict] = {}
    for folder in folders:
        docs = fh._load(folder.name)
        if len(docs) < 2:
            continue
        prev = {s["scheme"]: s for s in docs[1]["schemes"]}
        for s in docs[0]["schemes"]:
            p = prev.get(s["scheme"])
            if not p:
                continue
            before: dict[str, float] = {}
            for h in p["holdings"]:
                if h["kind"] in ("equity", "arbitrage"):
                    before[h["isin"]] = before.get(h["isin"], 0) + h["weight"]
            now: dict[str, float] = {}
            for h in s["holdings"]:
                if h["kind"] in ("equity", "arbitrage"):
                    now[h["isin"]] = now.get(h["isin"], 0) + h["weight"]
            for isin, w in now.items():
                was = before.get(isin)
                if isin not in by_isin or (was is not None and w - was < 0.25):
                    continue
                t = tally.setdefault(isin, {"new": 0, "raised": 0})
                t["new" if was is None else "raised"] += 1
    ranked = sorted(tally.items(), key=lambda kv: -(kv[1]["new"] * 2 + kv[1]["raised"]))
    out = []
    for isin, t in ranked[:limit]:
        r = by_isin[isin]
        from_high, from_low = _range(r)
        parts = [f"{t['new']} new" if t["new"] else "", f"{t['raised']} added more" if t["raised"] else ""]
        out.append({**_base(r, "india"), "from_high": from_high, "from_low": from_low,
                    "why": "fund schemes: " + ", ".join(p for p in parts if p)})
    return out
