"""Ready-made ETF screens. ETFs carry no earnings of their own, so like the
crypto screens (src/services/crypto_screens.py) these work on price and
volume: returns over 1 / 3 / 12 months, strength against the home index,
volatility, distance from the 52-week high, liquidity.

Universe per market (india, us, hong_kong, china_a): the hand-picked ETFs of
the ETF rotation view (src/services/etf_rotation.py) plus the market's most
traded ETFs by turnover in our listing, up to UNIVERSE. Leveraged and inverse
funds are left out: their returns are not comparable. A year of daily closes
from the bar cache. Same result shape as src/services/screens.py.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from typing import Callable, Optional

import pandas as pd

from .crypto_screens import _passes, _ret

logger = logging.getLogger(__name__)

MARKETS = ("india", "us", "hong_kong", "china_a")
UNIVERSE = 120
CACHE_SECONDS = 3600
LEVERAGED = re.compile(r"\b(\d(\.\d)?x|ultra|ultrapro|inverse|bear|short|leveraged|daily (2|3)x)\b", re.I)

# Large US funds the rotation view leaves out (it groups by theme, not by size).
US_CORE = [
    ("SPY", "SPDR S&P 500"), ("VOO", "Vanguard S&P 500"), ("IVV", "iShares Core S&P 500"), ("VTI", "Vanguard Total Stock Market"),
    ("DIA", "SPDR Dow Jones"), ("VUG", "Vanguard Growth"), ("VTV", "Vanguard Value"), ("SCHD", "Schwab US Dividend Equity"),
    ("VEA", "Vanguard Developed Markets"), ("VWO", "Vanguard Emerging Markets"), ("IEMG", "iShares Core MSCI Emerging"),
    ("VNQ", "Vanguard Real Estate"), ("BND", "Vanguard Total Bond"), ("AGG", "iShares Core US Aggregate Bond"),
    ("IEF", "iShares 7-10 Year Treasury"), ("SHY", "iShares 1-3 Year Treasury"), ("LQD", "iShares Investment Grade Corporate"),
    ("SLV", "iShares Silver"), ("IAU", "iShares Gold"), ("XLK", "Technology Select Sector"),
]

LABELS = {
    "volume": "Avg daily turnover", "ret_1m": "1M %", "ret_3m": "3M %", "ret_1y": "1Y %", "vs_index_3m": "vs index 3M pts",
    "volatility": "Volatility %/yr", "from_high": "From 52w high %", "above_ma200": "Above 200d avg %",
}

# key: title, description, [(field, op, value)], (sort field, descending), columns
PRESETS = {
    "most_traded": ("Most traded", "The most liquid ETFs by average daily turnover (20 days)",
                    [], ("volume", True), ["volume", "ret_1m", "ret_1y", "volatility"]),
    "best_1y": ("Best 1-year return", "Highest price return over the past 12 months",
                [("ret_1y", ">", 0)], ("ret_1y", True), ["ret_1y", "ret_3m", "volatility", "from_high"]),
    "momentum": ("Strong momentum", "Up over 5% in 3 months and above the 200-day average",
                 [("ret_3m", ">", 5), ("above_ma200", ">", 0)], ("ret_3m", True), ["ret_3m", "ret_1m", "above_ma200", "volume"]),
    "beating_index": ("Beating the index", "3-month return ahead of the home market index",
                      [("vs_index_3m", ">", 0)], ("vs_index_3m", True), ["vs_index_3m", "ret_3m", "ret_1y", "volatility"]),
    "low_volatility": ("Low volatility", "Calmest price path over the past year (under 15%/yr)",
                       [("volatility", "<", 15)], ("volatility", False), ["volatility", "ret_1y", "from_high", "volume"]),
    "near_high": ("Near 52-week high", "Within 3% of the 52-week closing high",
                  [("from_high", ">", -3)], ("from_high", True), ["from_high", "ret_3m", "ret_1y", "volume"]),
    "drawdown": ("Deep drawdown", "More than 20% below the 52-week high",
                 [("from_high", "<", -20)], ("from_high", False), ["from_high", "ret_1y", "volatility", "volume"]),
}

# ticker -> daily bars with "close" and (where the feed has it) "volume".
Fetch = Callable[[list[str]], dict[str, pd.DataFrame]]

_cache: dict[str, tuple[float, tuple[list[dict], dict]]] = {}
_lock = threading.Lock()


def _bars(tickers: list[str]) -> dict[str, pd.DataFrame]:
    from ..trading.scanner import _cache as bars

    return bars.get(tickers, "1d", "1y")


def turnover(df: pd.DataFrame) -> Optional[float]:
    """Average daily traded value over the last 20 sessions, in the fund's currency."""
    if "volume" not in df:
        return None
    value = (df["close"].astype(float) * df["volume"].astype(float)).dropna().tail(20)
    return float(value.mean()) if len(value) and value.mean() > 0 else None


def _leveraged(r: dict, market: str = "") -> bool:
    sym = r.get("symbol") or ""
    # HKEX lists its leveraged and inverse products under stock codes 07200-07599.
    if market == "hong_kong" and sym.isdigit() and 7200 <= int(sym) <= 7599:
        return True
    return r.get("category") == "Leveraged & Inverse" or bool(LEVERAGED.search(r.get("name") or ""))


def universe(market: str, rows: list[dict]) -> list[dict]:
    """[{symbol, name, ticker, ...listing row}] for the market, liquid first."""
    from .analysis_run import yahoo_symbol
    from .etf_rotation import UNIVERSES, app_symbol

    etfs = {r["symbol"]: r for r in rows if r.get("type") == "etf" and not _leveraged(r, market)}
    picked: dict[str, dict] = {}
    curated = [pair for group in UNIVERSES.get(market, {}).get("views", {}).values() for pair in group]
    if market == "us":
        curated = US_CORE + curated
    for ticker, name in curated:
        sym = app_symbol(ticker, market)
        picked.setdefault(sym, {**etfs.get(sym, {}), "symbol": sym, "name": (etfs.get(sym) or {}).get("name") or name, "ticker": ticker})
    traded = sorted((r for r in etfs.values() if r.get("volume") and r.get("price")),
                    key=lambda r: -(r["volume"] * r["price"]))
    for r in traded:
        if len(picked) >= UNIVERSE:
            break
        picked.setdefault(r["symbol"], {**r, "ticker": yahoo_symbol(r["symbol"], market)})
    return list(picked.values())[:UNIVERSE]


def metrics(s: pd.Series, index_3m: Optional[float]) -> dict:
    s = s.dropna()
    out = {"ret_1m": _ret(s, 21), "ret_3m": _ret(s, 63)}
    # A year of bars is 240-252 sessions depending on the market's holidays: measure from the first one.
    covers_year = len(s) > 1 and (s.index[-1] - s.index[0]).days >= 330
    out["ret_1y"] = float(s.iloc[-1] / s.iloc[0] - 1) * 100 if covers_year else None
    out["from_high"] = float(s.iloc[-1] / s.max() - 1) * 100 if len(s) else None
    out["above_ma200"] = float(s.iloc[-1] / s.tail(200).mean() - 1) * 100 if len(s) >= 200 else None
    daily = s.pct_change().dropna()
    out["volatility"] = float(daily.std() * math.sqrt(252) * 100) if len(daily) > 60 else None
    out["vs_index_3m"] = out["ret_3m"] - index_3m if out["ret_3m"] is not None and index_3m is not None else None
    return out


def _rule_text(rule) -> str:
    field, op, value = rule
    return f"{LABELS.get(field, field)} {op} {value:g}"


def list_presets() -> list[dict]:
    return [{"key": k, "title": p[0], "description": p[1], "large_only": False, "rules": [_rule_text(r) for r in p[2]]}
            for k, p in PRESETS.items()]


def _measured(market: str, rows: Optional[list[dict]], fetch: Fetch) -> tuple[list[dict], dict]:
    from .analysis_run import MARKET_INDICES

    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows(market)
    funds = universe(market, rows)
    index = MARKET_INDICES[market][0][0]
    bars = fetch([f["ticker"] for f in funds] + [index])
    closes = {t: df["close"].astype(float).dropna() for t, df in bars.items()}
    index_3m = _ret(closes[index], 63) if index in closes else None
    return funds, {f["symbol"]: {**metrics(closes[f["ticker"]], index_3m), "volume": turnover(bars[f["ticker"]])}
                   for f in funds if f["ticker"] in closes and len(closes[f["ticker"]]) > 60}


def run(key: str, market: str, fetch: Fetch = _bars, rows: Optional[list[dict]] = None, use_cache: bool = True) -> dict:
    from .analysis_run import MARKET_INDICES

    if market not in MARKETS:
        raise ValueError("ETF screens cover India, US, Hong Kong and China A")
    if key not in PRESETS:
        raise ValueError(f"Unknown screen '{key}'")
    title, desc, rules, (sort_field, desc_sort), columns = PRESETS[key]
    hit = None
    if use_cache:
        with _lock:
            hit = _cache.get(market)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        funds, ms = hit[1]
    else:
        funds, ms = _measured(market, rows, fetch)
        if use_cache and ms:
            with _lock:
                _cache[market] = (time.time(), (funds, ms))

    hits = []
    for f in funds:
        m = ms.get(f["symbol"])
        if m is None:
            continue
        if _passes(m, rules):
            hits.append({"symbol": f["symbol"], "name": f.get("name"), "market": market, "market_cap": None,
                         "volume": m["volume"], "price": f.get("price"), "currency": f.get("currency"),
                         "change_percent": f.get("change_percent"), "sector": f.get("category"),
                         **{col: m.get(col) for col in columns}})
    hits.sort(key=lambda h: (h.get(sort_field) is None, -(h.get(sort_field) or 0) if desc_sort else (h.get(sort_field) or 0)))
    return {
        "key": key, "title": title, "description": desc, "market": market,
        "rules": [_rule_text(r) for r in rules] or ["Ranked by turnover"],
        "columns": [{"key": c, "label": LABELS.get(c, c)} for c in columns],
        "universe": f"{len(funds)} large and most-traded ETFs (leveraged and inverse excluded), "
                    f"index: {MARKET_INDICES[market][0][1]}",
        "scanned": len(ms),
        "results": hits[:50],
    }
