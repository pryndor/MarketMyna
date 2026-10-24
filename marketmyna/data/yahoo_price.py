"""A price from a Yahoo `info` dict that is safe to use.

Yahoo's quote fields go stale for some listings while their daily bars stay
current: Indian REITs and InvITs report a `regularMarketPrice` frozen in
2024 with no `currentPrice` at all. A price older than MAX_AGE is treated as
missing (or replaced by the latest daily close when a ticker is given), so
a yield or upside is never worked out from it.
"""

from __future__ import annotations

import math
import time
from typing import Any, Optional

MAX_AGE = 10 * 24 * 3600  # a week of holidays plus a weekend


def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def info_price(info: dict, now: Optional[float] = None) -> Optional[float]:
    """currentPrice, else a regularMarketPrice that is still fresh."""
    price = _num(info.get("currentPrice"))
    if price:
        return price
    price = _num(info.get("regularMarketPrice"))
    stamp = _num(info.get("regularMarketTime"))
    if price and stamp and (now or time.time()) - stamp > MAX_AGE:
        return None
    return price


def fresh_price(info: dict, ticker=None) -> Optional[float]:
    """info_price(), falling back to the ticker's latest daily close."""
    price = info_price(info)
    if price or ticker is None:
        return price
    try:
        bars = ticker.history(period="5d", interval="1d")
        return _num(bars["Close"].iloc[-1]) if not bars.empty else None
    except Exception:
        return None
