"""Market mood gauge: six breadth and volatility readings for one market,
each mapped to 0 (fear) - 100 (greed), and their average.

Universe: the market's 200 largest stocks by market cap (as the screens),
with a year of daily closes. Readings:

- Advancing vs declining today (share of movers that rose)
- Share above the 50-day average
- Share above the 200-day average
- New 52-week highs vs lows (within 2% of either; share that are highs)
- Index vs its 125-day average (-10% -> 0, +10% -> 100)
- Volatility index vs its own past year (low = calm = high score), where the
  market has one (India VIX, CBOE VIX)

The scale follows the familiar fear & greed style (0-25 extreme fear, 25-45
fear, 45-55 neutral, 55-75 greed, 75-100 extreme greed). It describes how
the market is behaving now; it is not a forecast or advice.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

UNIVERSE = 200
CACHE_SECONDS = 3600
VOL_INDEX = {"india": ("^INDIAVIX", "India VIX"), "us": ("^VIX", "VIX")}

Fetch = Callable[[list[str]], dict[str, pd.Series]]

_cache: dict[str, tuple[float, dict]] = {}
_closes_cache: dict[str, tuple[float, dict[str, pd.Series], set[str]]] = {}
_lock = threading.Lock()


def _closes(tickers: list[str]) -> dict[str, pd.Series]:
    from ..trading.scanner import _cache as bars

    return {t: df["close"].astype(float).dropna() for t, df in bars.get(tickers, "1d", "1y").items()}


def label(score: Optional[float]) -> Optional[str]:
    if score is None:
        return None
    if score < 25:
        return "Extreme fear"
    if score < 45:
        return "Fear"
    if score <= 55:
        return "Neutral"
    if score <= 75:
        return "Greed"
    return "Extreme greed"


def _clip(x: float) -> float:
    return max(0.0, min(100.0, x))


def readings(stocks: dict[str, pd.Series], changes: list[float], index: Optional[pd.Series],
             vol: Optional[pd.Series], vol_name: Optional[str]) -> list[dict]:
    out = []
    adv = sum(1 for c in changes if c > 0)
    dec = sum(1 for c in changes if c < 0)
    if adv + dec:
        out.append({"key": "breadth", "label": "Advancing vs declining today", "score": _clip(adv / (adv + dec) * 100),
                    "value": f"{adv} up, {dec} down"})

    def share_above(days: int) -> Optional[tuple[int, int]]:
        ok = [s for s in stocks.values() if len(s) >= days]
        if len(ok) < 20:
            return None
        return sum(1 for s in ok if s.iloc[-1] > s.iloc[-days:].mean()), len(ok)

    for days in (50, 200):
        got = share_above(days)
        if got:
            above, n = got
            out.append({"key": f"above_{days}", "label": f"Above the {days}-day average", "score": _clip(above / n * 100),
                        "value": f"{above} of {n} ({above / n:.0%})"})

    year = [s for s in stocks.values() if len(s) >= 200]
    if len(year) >= 20:
        highs = sum(1 for s in year if s.iloc[-1] >= s.max() * 0.98)
        lows = sum(1 for s in year if s.iloc[-1] <= s.min() * 1.02)
        if highs + lows:
            out.append({"key": "highs_lows", "label": "New 52-week highs vs lows", "score": _clip(highs / (highs + lows) * 100),
                        "value": f"{highs} near highs, {lows} near lows"})
        else:
            out.append({"key": "highs_lows", "label": "New 52-week highs vs lows", "score": 50.0,
                        "value": "none near a high or a low"})

    if index is not None and len(index) >= 125:
        gap = float(index.iloc[-1] / index.iloc[-125:].mean() - 1)
        out.append({"key": "momentum", "label": "Index vs its 125-day average", "score": _clip(50 + gap * 500),
                    "value": f"{gap:+.1%}"})

    if vol is not None and len(vol) >= 100:
        now = float(vol.iloc[-1])
        rank = float((vol < now).mean())  # share of the past year below today's level
        out.append({"key": "volatility", "label": f"{vol_name} vs its past year", "score": _clip((1 - rank) * 100),
                    "value": f"{now:.1f}, higher than {rank:.0%} of the year"})
    return out


def build(market: str, fetch: Fetch = _closes, rows: Optional[list[dict]] = None, use_cache: bool = True,
          live: Optional[dict] = None) -> dict:
    """`rows` may carry live prices (live_market.merge); `live` = Yahoo ticker ->
    {price, day} moves today's close of each stock, the index and the VIX, so
    every reading follows the session. A year of closes is cached either way."""
    from .analysis_run import MARKET_INDICES, yahoo_symbol
    from .live_market import extend_all

    if market not in ("india", "us", "hong_kong", "china_a"):
        raise ValueError("Market mood covers India, US, Hong Kong and China A shares")
    if use_cache and not live:
        with _lock:
            hit = _cache.get(market)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows(market)
    stocks = sorted((r for r in rows if r.get("type") == "stock" and r.get("market_cap")),
                    key=lambda r: -r["market_cap"])[:UNIVERSE]
    tick = {yahoo_symbol(r["symbol"], market): r for r in stocks}
    index_ticker, index_name = MARKET_INDICES[market][0]
    vol_ticker, vol_name = VOL_INDEX.get(market, (None, None))
    wanted = list(tick) + [index_ticker] + ([vol_ticker] if vol_ticker else [])
    closes = None
    if use_cache:
        with _lock:
            hit = _closes_cache.get(market)
        if hit and time.time() - hit[0] < CACHE_SECONDS and set(wanted) <= hit[2]:
            closes = hit[1]
    if closes is None:
        closes = fetch(wanted)
        if use_cache and closes:
            with _lock:
                _closes_cache[market] = (time.time(), closes, set(wanted))
    if live:
        closes = extend_all(closes, live)
    series = {t: closes[t] for t in tick if t in closes}
    changes = [float(r["change_percent"]) for r in stocks if r.get("change_percent") is not None]

    parts = readings(series, changes, closes.get(index_ticker), closes.get(vol_ticker) if vol_ticker else None, vol_name)
    score = round(sum(p["score"] for p in parts) / len(parts), 1) if parts else None
    for p in parts:
        p["score"] = round(p["score"], 1)
        p["label_text"] = label(p["score"])
    out = {
        "market": market, "score": score, "label": label(score), "readings": parts,
        "universe": f"the {len(series)} largest stocks with a year of prices",
        "index": index_name,
        "source": ("Daily closes from the market data feed, with today's live prices" if live
                   else "Daily closes from the market data feed; today's moves from the listings feed"),
    }
    if use_cache and parts and not live:
        with _lock:
            _cache[market] = (time.time(), out)
    return out
