"""Commodities snapshot: front-month futures from Yahoo (no key) with 1-day,
1-month and 1-year change and a 3-month sparkline, plus gold and silver in
rupees for Indian users. Covers the useful core of OpenBB's commodity
endpoints. CFTC positioning (cot.py) and EIA oil stocks (eia_stocks.py) are
separate endpoints the card loads after the prices.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_SECONDS = 15 * 60
TROY_OZ_G = 31.1034768

# ticker, label, group, unit, note
ITEMS = [
    ("GC=F", "Gold", "metals", "$/oz", "Safe-haven; tends to rise when real interest rates fall"),
    ("SI=F", "Silver", "metals", "$/oz", "Part precious, part industrial metal"),
    ("HG=F", "Copper", "metals", "$/lb", "Industrial demand gauge (\"Dr Copper\")"),
    ("CL=F", "WTI crude", "energy", "$/bbl", "US oil benchmark"),
    ("BZ=F", "Brent crude", "energy", "$/bbl", "Global oil benchmark; India's import bill moves with it"),
    ("NG=F", "Natural gas", "energy", "$/MMBtu", "US Henry Hub gas"),
    ("ZW=F", "Wheat", "agri", "¢/bu", "CBOT wheat"),
    ("ZC=F", "Corn", "agri", "¢/bu", "CBOT corn"),
]
FX = "USDINR=X"

Fetch = Callable[[list[str]], dict[str, pd.Series]]

_cache: dict[str, tuple[float, dict]] = {}
_raw_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _yahoo(tickers: list[str]) -> dict[str, pd.Series]:
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    from ..data import ecb_fx

    def download() -> dict[str, pd.Series]:
        # 2y, not 1y: a 1-year window ending at a bar dated yesterday has no bar a
        # full year back, so the 1-year change would come out empty.
        with YF_DOWNLOAD_LOCK:
            df = yf.download(tickers, period="2y", interval="1d", progress=False, auto_adjust=False, threads=True)
        closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": tickers[0]})
        return {t: closes[t].dropna() for t in tickers if t in closes and closes[t].notna().sum()}

    # Currency pairs Yahoo misses come from the ECB's daily reference rates
    return ecb_fx.guarded(download, tickers)


def _change(s: pd.Series, days: int) -> Optional[float]:
    when = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= when]
    return float(s.iloc[-1] / past.iloc[-1] - 1) * 100 if len(past) and past.iloc[-1] else None


def _row(key: str, label: str, group: str, unit: str, note: str, s: pd.Series) -> dict:
    spark = s[s.index >= s.index[-1] - pd.Timedelta(days=92)]
    return {
        "key": key, "label": label, "group": group, "unit": unit, "note": note,
        "price": float(s.iloc[-1]),
        "as_of": str(pd.Timestamp(s.index[-1]).date()),
        "change_1d": float(s.iloc[-1] / s.iloc[-2] - 1) * 100 if len(s) > 1 and s.iloc[-2] else None,
        "change_1m": _change(s, 30),
        "change_1y": _change(s, 365),
        "spark": [round(float(v), 4) for v in spark.to_numpy()],
    }


def tickers() -> list[str]:
    return [t for t, *_ in ITEMS] + [FX]


def build(fetch: Fetch = _yahoo, use_cache: bool = True, live: Optional[dict] = None) -> dict:
    """`live`: ticker -> {price, day} from live_market.latest, moving each
    contract's latest price (and the rupee prices with it); the history
    behind it is cached CACHE_SECONDS."""
    from .live_market import extend_all

    if use_cache and not live:
        with _lock:
            hit = _cache.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]

    data = None
    if use_cache:
        with _lock:
            hit = _raw_cache.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            data = hit[1]
    if data is None:
        try:
            data = fetch(tickers())
        except Exception as exc:  # network / Yahoo hiccup
            logger.warning("Commodity fetch failed: %s", exc)
            data = {}
        if use_cache and data:
            with _lock:
                _raw_cache["all"] = (time.time(), data)
    if live:
        data = extend_all(data, live)

    rows = [_row(t, label, group, unit, note, data[t]) for t, label, group, unit, note in ITEMS
            if t in data and len(data[t]) > 1]

    # Gold / silver in rupees: international price x USDINR, before import duty and GST,
    # so MCX / jeweller prices run a few percent higher.
    fx = data.get(FX)
    if fx is not None and len(fx) > 1:
        for t, label, unit, grams in (("GC=F", "Gold (₹)", "₹/10g", 10), ("SI=F", "Silver (₹)", "₹/kg", 1000)):
            if t in data:
                usd = data[t]
                joined = pd.concat([usd, fx], axis=1, keys=["p", "fx"]).ffill().dropna()
                inr = joined["p"] * joined["fx"] / TROY_OZ_G * grams
                if len(inr) > 1:
                    rows.append(_row(f"{t}:INR", label, "india", unit,
                                     "International price in rupees, before import duty and GST", inr))

    out = {"items": rows, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "usd_inr": float(fx.iloc[-1]) if fx is not None and len(fx) else None}
    if use_cache and rows and not live:
        with _lock:
            _cache["all"] = (time.time(), out)
    return out
