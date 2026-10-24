"""Relative rotation (RRG): where each sector sits against the market index on
relative strength (RS-Ratio) and its momentum (RS-Momentum), with a weekly tail.

Yahoo lacks most NSE sector indices, so every sector is a market-cap-weighted
basket of its largest stocks (by our listings category), priced from the
scanner's batched daily bars. The JdK-style normalisation follows OpenBB's
technical.relative_rotation (Apache 2.0).

Quadrants: leading (strong, rising) -> weakening -> lagging -> improving.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROTATION_MARKETS = ("india", "us", "china_a", "hong_kong", "crypto")

# Crypto has no sectors in the listings; these are the usual narrative
# groups, each an equal-weight basket measured against Bitcoin.
CRYPTO_GROUPS = {
    "Smart-contract L1s": ["ETH", "SOL", "ADA", "AVAX", "DOT", "NEAR", "APT", "SUI", "TON", "TRX"],
    "Layer 2s": ["ARB", "OP", "POL", "STRK", "IMX", "MNT"],
    "DeFi": ["UNI", "AAVE", "LDO", "CRV", "COMP", "PENDLE", "JUP", "RAY"],
    "Payments & legacy": ["XRP", "LTC", "BCH", "XLM", "ETC"],
    "Exchange tokens": ["BNB", "OKB", "CRO"],
    "Oracles & infra": ["LINK", "FIL", "GRT", "QNT", "HBAR"],
    "AI": ["FET", "RENDER", "TAO", "WLD", "AR"],
    "Memecoins": ["DOGE", "SHIB", "PEPE", "BONK", "WIF", "FLOKI"],
    "Gaming & metaverse": ["SAND", "MANA", "AXS", "GALA"],
}
MEMBERS = 8
WINDOW = 10  # weeks used to normalise
TAIL = 8  # weeks of trail shown
CACHE_SECONDS = 1800

Fetch = Callable[[list[str]], dict[str, pd.Series]]

_cache: dict[str, tuple[float, dict]] = {}
_closes_cache: dict[str, tuple[float, dict[str, pd.Series], set[str]]] = {}
_lock = threading.Lock()


def _closes(tickers: list[str]) -> dict[str, pd.Series]:
    from ..trading.scanner import _cache as bars

    return {t: df["close"].astype(float) for t, df in bars.get(tickers, "1d", "1y").items()}


def _weekly(s: pd.Series) -> pd.Series:
    s = s.dropna().copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None)
    return s.resample("W-FRI").last().dropna()


def rrg(series: pd.Series, bench: pd.Series, window: int = WINDOW) -> pd.DataFrame:
    """Weekly RS-Ratio / RS-Momentum (both centred on 100) of `series` vs `bench`."""
    both = pd.concat([series, bench], axis=1).dropna()
    rs = both.iloc[:, 0] / both.iloc[:, 1]
    z = lambda s: (s - s.rolling(window).mean()) / s.rolling(window).std()  # noqa: E731
    ratio = 100 + z(rs)
    momentum = 100 + z(ratio.pct_change() * 100)
    return pd.DataFrame({"ratio": ratio, "momentum": momentum}).dropna()


def quadrant(ratio: float, momentum: float) -> str:
    if ratio >= 100:
        return "leading" if momentum >= 100 else "weakening"
    return "improving" if momentum >= 100 else "lagging"


def baskets(rows: list[dict], members: int = MEMBERS) -> dict[str, list[dict]]:
    """category -> its largest priced stocks (with market cap)."""
    out: dict[str, list[dict]] = {}
    for r in sorted((r for r in rows if r.get("type") == "stock" and r.get("market_cap")), key=lambda r: -r["market_cap"]):
        cat = r.get("category")
        if not cat or cat == "Other":
            continue
        group = out.setdefault(cat, [])
        if len(group) < members:
            group.append(r)
    return {k: v for k, v in out.items() if len(v) >= 3}


def _crypto_closes(tickers: list[str]) -> dict[str, pd.Series]:
    from .crypto_screens import _fetch

    return _fetch(tickers, days=400)


def _cached_closes(key: str, tickers: list[str], fetch: Fetch, use_cache: bool) -> dict[str, pd.Series]:
    """Daily closes, kept CACHE_SECONDS: live prices only move the last bar,
    so the year of history is fetched once and re-used."""
    if use_cache:
        with _lock:
            hit = _closes_cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS and set(tickers) <= hit[2]:
            return hit[1]
    closes = fetch(tickers)
    if use_cache and closes:
        with _lock:
            _closes_cache[key] = (time.time(), closes, set(tickers))
    return closes


def build_crypto(fetch: Fetch = _crypto_closes, use_cache: bool = True, live: Optional[dict] = None) -> dict:
    """Coin groups vs Bitcoin, same output shape as build(). `live`: ticker ->
    {price, day} moving today's close."""
    from .live_market import extend_all

    if use_cache and not live:
        with _lock:
            hit = _cache.get("crypto")
            if hit and time.time() - hit[0] < CACHE_SECONDS:
                return hit[1]
    tickers = ["BTC-USD"] + [f"{c}-USD" for coins in CRYPTO_GROUPS.values() for c in coins]
    closes = _cached_closes("crypto", list(dict.fromkeys(tickers)), fetch, use_cache)
    if live:
        closes = extend_all(closes, live)
    if "BTC-USD" not in closes:
        raise ValueError("Bitcoin price history unavailable")
    bench = _weekly(closes["BTC-USD"])
    sectors = []
    for group, coins in CRYPTO_GROUPS.items():
        parts, members = [], []
        for c in coins:
            s = closes.get(f"{c}-USD")
            if s is None or len(s.dropna()) < 120:
                continue
            w = _weekly(s)
            parts.append(w / w.iloc[0])
            members.append(f"{c}-USD")
        if len(parts) < 2:
            continue
        basket = pd.concat(parts, axis=1).ffill().dropna().mean(axis=1)  # equal weight
        path = rrg(basket, bench)
        if path.empty:
            continue
        tail = path.tail(TAIL)
        last = tail.iloc[-1]
        sectors.append({
            "sector": group, "members": members,
            "ratio": float(last["ratio"]), "momentum": float(last["momentum"]),
            "quadrant": quadrant(float(last["ratio"]), float(last["momentum"])),
            "return_4w": float(basket.iloc[-1] / basket.iloc[-5] - 1) * 100 if len(basket) > 5 else None,
            "tail": [{"week": str(i.date()), "ratio": float(v["ratio"]), "momentum": float(v["momentum"])} for i, v in tail.iterrows()],
        })
    order = {"leading": 0, "improving": 1, "weakening": 2, "lagging": 3}
    sectors.sort(key=lambda s: (order[s["quadrant"]], -s["ratio"]))
    out = {"market": "crypto", "benchmark": {"symbol": "BTC-USD", "name": "Bitcoin"},
           "as_of": str(bench.index[-1].date()), "window_weeks": WINDOW, "sectors": sectors}
    if use_cache and sectors and not live:
        with _lock:
            _cache["crypto"] = (time.time(), out)
    return out


def build(market: str, rows: Optional[list[dict]] = None, fetch: Fetch = _closes, live: Optional[dict] = None) -> dict:
    """`live`: Yahoo ticker -> {price, day} for the basket members and the
    benchmark; today's close moves with it, so the current week's point (and
    its quadrant) follows the session."""
    if market == "crypto":
        return build_crypto(live=live)
    from ..data.listings import get_store
    from .analysis_run import MARKET_INDICES, yahoo_symbol
    from .live_market import extend_all

    if rows is None and not live:
        with _lock:
            hit = _cache.get(market)
            if hit and time.time() - hit[0] < CACHE_SECONDS:
                return hit[1]
    groups = baskets(rows if rows is not None else get_store().rows(market))
    bench_ticker, bench_name = MARKET_INDICES[market][0]
    tickers = {r["symbol"]: yahoo_symbol(r["symbol"], market) for g in groups.values() for r in g}
    closes = _cached_closes(market, list(dict.fromkeys([*tickers.values(), bench_ticker])), fetch, rows is None)
    if live:
        closes = extend_all(closes, live)
    if bench_ticker not in closes:
        raise ValueError(f"Benchmark {bench_name} unavailable")
    bench = _weekly(closes[bench_ticker])

    sectors = []
    for cat, members in groups.items():
        parts, weights = [], []
        for r in members:
            s = closes.get(tickers[r["symbol"]])
            if s is None or len(s.dropna()) < 120:
                continue
            w = _weekly(s)
            parts.append(w / w.iloc[0])
            weights.append(float(r["market_cap"]))
        if len(parts) < 3:
            continue
        frame = pd.concat(parts, axis=1).ffill().dropna()
        basket = frame.mul(np.array(weights) / sum(weights), axis=1).sum(axis=1)
        path = rrg(basket, bench)
        if path.empty:
            continue
        tail = path.tail(TAIL)
        last = tail.iloc[-1]
        sectors.append({
            "sector": cat,
            "members": [r["symbol"] for r in members],
            "ratio": float(last["ratio"]), "momentum": float(last["momentum"]),
            "quadrant": quadrant(float(last["ratio"]), float(last["momentum"])),
            "return_4w": float(basket.iloc[-1] / basket.iloc[-5] - 1) * 100 if len(basket) > 5 else None,
            "tail": [{"week": str(i.date()), "ratio": float(v["ratio"]), "momentum": float(v["momentum"])} for i, v in tail.iterrows()],
        })
    order = {"leading": 0, "improving": 1, "weakening": 2, "lagging": 3}
    sectors.sort(key=lambda s: (order[s["quadrant"]], -s["ratio"]))
    out = {"market": market, "benchmark": {"symbol": bench_ticker, "name": bench_name},
           "as_of": str(bench.index[-1].date()), "window_weeks": WINDOW, "sectors": sectors}
    if rows is None and not live:
        with _lock:
            _cache[market] = (time.time(), out)
    return out
