"""ECB reference rates through Frankfurter (api.frankfurter.dev, no key) as a
backup for Yahoo currency pairs.

The ECB publishes one rate per business day at about 16:00 CET for ~30
currencies (INR, CNY, HKD, JPY, GBP, AUD... but no dollar index). Rates come
with the dollar as base and are crossed for other pairs. Pairs are named the
Yahoo way: "EURUSD=X" (dollars per euro), "USDINR=X", "HKD=X" (= USDHKD).
A pair is filled only when Yahoo returned nothing for it or its last bar is
more than STALE_DAYS older than the ECB's; filled series carry
attrs["source"] = SOURCE so a page can say where the number came from.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, timedelta
from typing import Callable, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

API = "https://api.frankfurter.dev/v1"
SOURCE = "ECB reference rate"
CACHE_SECONDS = 3600
STALE_DAYS = 4

_PAIR = re.compile(r"^([A-Z]{3})?([A-Z]{3})=X$")

_cache: dict[tuple[int, str], tuple[float, dict[str, pd.Series]]] = {}
_lock = threading.Lock()


def pair(ticker: str) -> Optional[tuple[str, str]]:
    """(base, quote) for a Yahoo FX ticker, None for anything else."""
    m = _PAIR.match(ticker)
    if not m:
        return None
    return (m.group(1), m.group(2)) if m.group(1) else ("USD", m.group(2))


def _fetch(start: date, symbols: str) -> dict:
    r = requests.get(f"{API}/{start.isoformat()}..", params={"base": "USD", "symbols": symbols}, timeout=20)
    r.raise_for_status()
    return r.json()


def usd_rates(currencies: set[str], days: int, fetch: Optional[Callable[[date, str], dict]] = None) -> dict[str, pd.Series]:
    """Currency -> units per US dollar by day, over the last `days` days."""
    wanted = sorted(currencies - {"USD"})
    if not wanted:
        return {}
    key = (days, ",".join(wanted))
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    payload = (fetch or _fetch)(date.today() - timedelta(days=days), ",".join(wanted))
    rows = payload.get("rates") or {}
    frame = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    frame.index = pd.DatetimeIndex(frame.index)
    out = {c: frame[c].dropna().astype(float) for c in frame.columns if frame[c].notna().any()}
    with _lock:
        _cache[key] = (time.time(), out)
    return out


def series(tickers: list[str], days: int = 730, fetch: Optional[Callable[[date, str], dict]] = None) -> dict[str, pd.Series]:
    """Yahoo-named FX ticker -> daily ECB series (quote currency per base)."""
    pairs = {t: p for t in tickers if (p := pair(t))}
    if not pairs:
        return {}
    usd = usd_rates({c for p in pairs.values() for c in p}, days, fetch)
    out = {}
    for t, (base, quote) in pairs.items():
        q = usd.get(quote) if quote != "USD" else None
        b = usd.get(base) if base != "USD" else None
        if (quote != "USD" and q is None) or (base != "USD" and b is None):
            continue
        if q is None:  # e.g. EURUSD = 1 / (euros per dollar)
            s = 1 / b
        elif b is None:
            s = q
        else:
            s = (q / b).dropna()
        s = s.rename(t)
        s.attrs["source"] = SOURCE
        out[t] = s
    return out


def _last(s: pd.Series) -> pd.Timestamp:
    t = pd.Timestamp(s.index[-1])
    return t.tz_localize(None) if t.tzinfo else t


def fill(data: dict[str, pd.Series], tickers: list[str], days: int = 730,
         fetch: Optional[Callable[[date, str], dict]] = None, today: Optional[date] = None) -> dict[str, pd.Series]:
    """Fill FX pairs Yahoo missed or left stale with ECB rates (in place, returned).
    No request is made while Yahoo's pairs are fresh."""
    cutoff = pd.Timestamp(today or date.today()) - pd.Timedelta(days=STALE_DAYS)
    weak = [t for t in tickers if pair(t) and (t not in data or len(data[t]) < 2 or _last(data[t]) < cutoff)]
    if not weak:
        return data
    try:
        ecb = series(weak, days, fetch)
    except Exception as exc:
        logger.info("ECB FX backup unavailable: %s", exc)
        return data
    for t, s in ecb.items():
        old = data.get(t)
        if len(s) > 1 and (old is None or len(old) < 2 or s.index[-1] > _last(old)):
            data[t] = s
    return data


def guarded(download: Callable[[], dict[str, pd.Series]], tickers: list[str], days: int = 730) -> dict[str, pd.Series]:
    """Run a Yahoo download; when it fails outright and FX pairs were asked for,
    still return those pairs from the ECB. Other failures raise as before."""
    try:
        out = download()
    except Exception as exc:
        if not any(pair(t) for t in tickers):
            raise
        logger.warning("Yahoo download failed, ECB rates for currencies only: %s", exc)
        out = {}
    return fill(out, tickers, days)
