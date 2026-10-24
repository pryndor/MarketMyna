"""Crypto market mood: the stock gauge's idea (marketmyna/services/market_mood.py)
for coins, which have no 52-week history in our feed, no index and no VIX.

Universe: the most-traded coins of the crypto screens (stablecoins dropped),
six months of daily closes shared with them. Readings, each 0 (fear) - 100 (greed):

- Advancing vs declining today (24h change of each coin)
- Share above the 50-day average
- Share above the 100-day average
- Near 90-day highs vs lows (within 5% of either; share that are highs)
- Bitcoin vs its 125-day average (-20% -> 0, +20% -> 100; coins swing more than indices)
- Bitcoin's 30-day volatility vs its past months (calm = high score)
- Perpetual funding (BTC and ETH, annualised): about 11%/yr is the usual
  baseline; crowded longs push it up (greed), crowded shorts below zero (fear)

Describes how the market behaves now; not a forecast or advice.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable, Optional

import pandas as pd

from . import crypto_screens
from .market_mood import _clip, label

logger = logging.getLogger(__name__)

CACHE_SECONDS = 300
FUNDING_BASELINE = 11.0  # % / yr: 0.01% per 8h, the exchanges' default

_cache: dict[str, tuple[float, Optional[float]]] = {}
_lock = threading.Lock()


def _funding() -> Optional[float]:
    """Average annualised BTC / ETH perpetual funding in %, or None."""
    from .rates import _funding_binance, _funding_bybit

    for fn in (_funding_binance, _funding_bybit):
        try:
            rows = [r for r in fn() if r["coin"] in ("BTC", "ETH")]
        except Exception as exc:
            logger.warning("Funding for crypto mood via %s failed: %s", fn.__name__, exc)
            continue
        if rows:
            return sum(r["rate_8h"] for r in rows) / len(rows) * 3 * 365 * 100
    return None


def readings(coins: dict[str, pd.Series], changes: list[float], btc: Optional[pd.Series],
             funding: Optional[float]) -> list[dict]:
    out = []
    adv = sum(1 for c in changes if c > 0)
    dec = sum(1 for c in changes if c < 0)
    if adv + dec:
        out.append({"key": "breadth", "label": "Advancing vs declining (24h)", "score": _clip(adv / (adv + dec) * 100),
                    "value": f"{adv} up, {dec} down"})

    for days in (50, 100):
        ok = [s for s in coins.values() if len(s) >= days]
        if len(ok) >= 20:
            above = sum(1 for s in ok if s.iloc[-1] > s.iloc[-days:].mean())
            out.append({"key": f"above_{days}", "label": f"Above the {days}-day average", "score": _clip(above / len(ok) * 100),
                        "value": f"{above} of {len(ok)} ({above / len(ok):.0%})"})

    ok = [s for s in coins.values() if len(s) >= 90]
    if len(ok) >= 20:
        highs = sum(1 for s in ok if s.iloc[-1] >= s.iloc[-90:].max() * 0.95)
        lows = sum(1 for s in ok if s.iloc[-1] <= s.iloc[-90:].min() * 1.05)
        out.append({"key": "highs_lows", "label": "Near 90-day highs vs lows",
                    "score": _clip(highs / (highs + lows) * 100) if highs + lows else 50.0,
                    "value": f"{highs} near highs, {lows} near lows" if highs + lows else "none near a high or a low"})

    if btc is not None and len(btc) >= 125:
        gap = float(btc.iloc[-1] / btc.iloc[-125:].mean() - 1)
        out.append({"key": "momentum", "label": "Bitcoin vs its 125-day average", "score": _clip(50 + gap * 250),
                    "value": f"{gap:+.1%}"})

    if btc is not None and len(btc) >= 90:
        vol = btc.pct_change().rolling(30).std().dropna() * math.sqrt(365) * 100
        if len(vol) >= 30:
            now = float(vol.iloc[-1])
            rank = float((vol < now).mean())
            out.append({"key": "volatility", "label": "Bitcoin volatility vs recent months", "score": _clip((1 - rank) * 100),
                        "value": f"{now:.0f}%/yr, higher than {rank:.0%} of the period"})

    if funding is not None:
        out.append({"key": "funding", "label": "Funding rates (BTC, ETH)", "score": _clip(50 + (funding - FUNDING_BASELINE) * 2.5),
                    "value": f"{funding:+.1f}% / yr"})
    return out


def _funding_cached(funding: Callable[[], Optional[float]], use_cache: bool) -> Optional[float]:
    if use_cache:
        with _lock:
            hit = _cache.get("funding")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = funding()
    if use_cache and value is not None:
        with _lock:
            _cache["funding"] = (time.time(), value)
    return value


def build(rows: Optional[list[dict]] = None, fetch: Callable = crypto_screens._fetch,
          funding: Callable[[], Optional[float]] = _funding, use_cache: bool = True) -> dict:
    """`rows` = the crypto listing, ideally with live prices merged in: today's
    breadth follows them on every call; closes and funding are cached."""
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows("crypto")
    coins = crypto_screens.universe(rows)
    closes = crypto_screens.history(coins, fetch, use_cache)
    series = {c["symbol"]: closes[c["symbol"]] for c in coins if c["symbol"] in closes}
    changes = [float(c["change_percent"]) for c in coins if c.get("change_percent") is not None]
    parts = readings(series, changes, closes.get("BTC-USD"), _funding_cached(funding, use_cache))
    score = round(sum(p["score"] for p in parts) / len(parts), 1) if parts else None
    for p in parts:
        p["score"] = round(p["score"], 1)
        p["label_text"] = label(p["score"])
    out = {
        "market": "crypto", "score": score, "label": label(score), "readings": parts,
        "universe": f"the {len(series)} most-traded coins (stablecoins excluded)",
        "index": "Bitcoin",
        "source": "Daily closes from crypto exchange data; today's moves and funding from live exchange data",
    }
    return out
