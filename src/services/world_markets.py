"""World markets: major stock indices by region, currencies, US Treasury
yields and fear gauges, each with 1-day / 1-month / 1-year change and a
3-month sparkline.

Prices are Yahoo daily closes (no key); currency pairs Yahoo misses come from
the ECB reference rates (src/data/ecb_fx.py). The VIX family's latest value is
taken from CBOE's own delayed quotes when they answer (fresher than Yahoo
before the US open). Crypto mood is alternative.me's fear & greed index.
The VIX term structure is reported as a reading, not advice: a 1-month VIX
above the 3-month one (backwardation) has historically come with market stress.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import pandas as pd
import requests

from .commodities import _change, _yahoo

logger = logging.getLogger(__name__)

CACHE_SECONDS = 15 * 60

# ticker, label, group, note
ITEMS = [
    ("^GSPC", "S&P 500", "americas", "US large caps"),
    ("^IXIC", "Nasdaq Composite", "americas", "US, tech-heavy"),
    ("^DJI", "Dow Jones", "americas", "30 US blue chips"),
    ("^GSPTSE", "S&P/TSX", "americas", "Canada"),
    ("^BVSP", "Bovespa", "americas", "Brazil"),
    ("^STOXX50E", "Euro Stoxx 50", "europe", "Eurozone blue chips"),
    ("^FTSE", "FTSE 100", "europe", "UK"),
    ("^GDAXI", "DAX", "europe", "Germany"),
    ("^FCHI", "CAC 40", "europe", "France"),
    ("^NSEI", "Nifty 50", "asia", "India"),
    ("^N225", "Nikkei 225", "asia", "Japan"),
    ("000001.SS", "Shanghai Composite", "asia", "China A-shares"),
    ("^HSI", "Hang Seng", "asia", "Hong Kong"),
    ("^KS11", "KOSPI", "asia", "South Korea"),
    ("^TWII", "Taiwan Weighted", "asia", "Taiwan"),
    ("^AXJO", "ASX 200", "asia", "Australia"),
    ("DX-Y.NYB", "US dollar index", "fx", "Dollar against six major currencies"),
    ("EURUSD=X", "EUR / USD", "fx", "Dollars per euro"),
    ("GBPUSD=X", "GBP / USD", "fx", "Dollars per pound"),
    ("USDJPY=X", "USD / JPY", "fx", "Yen per dollar"),
    ("USDCNY=X", "USD / CNY", "fx", "Yuan per dollar"),
    ("USDINR=X", "USD / INR", "fx", "Rupees per dollar"),
    ("AUDUSD=X", "AUD / USD", "fx", "Dollars per Australian dollar"),
    ("^IRX", "US 3-month", "yields", "Treasury bill yield, %"),
    ("^FVX", "US 5-year", "yields", "Treasury yield, %"),
    ("^TNX", "US 10-year", "yields", "Treasury yield, %"),
    ("^TYX", "US 30-year", "yields", "Treasury yield, %"),
    ("^VIX9D", "VIX 9-day", "volatility", "Expected S&P 500 volatility, next 9 days"),
    ("^VIX", "VIX", "volatility", "Expected S&P 500 volatility, next 30 days"),
    ("^VIX3M", "VIX 3-month", "volatility", "Expected S&P 500 volatility, next 3 months"),
    ("^VIX6M", "VIX 6-month", "volatility", "Expected S&P 500 volatility, next 6 months"),
    ("^INDIAVIX", "India VIX", "volatility", "Expected Nifty volatility, next 30 days"),
]
# Yields move in points, not percent: their changes are reported as differences.
POINT_CHANGE = {"yields", "volatility"}

Fetch = Callable[[list[str]], dict[str, pd.Series]]

_cache: dict[str, tuple[float, dict]] = {}
_raw_cache: dict[str, tuple[float, tuple]] = {}
_lock = threading.Lock()


def _cboe_latest(symbols: list[str]) -> dict[str, float]:
    """Latest CBOE delayed values for VIX indices (^VIX -> _VIX.json)."""
    def one(sym: str) -> tuple[str, Optional[float]]:
        try:
            r = requests.get(f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/_{sym.lstrip('^')}.json",
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            r.raise_for_status()
            price = ((r.json() or {}).get("data") or {}).get("current_price")
            return sym, float(price) if price else None
        except Exception:  # noqa: BLE001 - CBOE is only a fresher override
            return sym, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        return {s: v for s, v in pool.map(one, symbols) if v}


def _fear_greed() -> Optional[dict]:
    from ..data.extra_sources import crypto_fear_greed

    try:
        rows = crypto_fear_greed(31)
    except Exception as exc:  # noqa: BLE001
        logger.info("Crypto fear & greed unavailable: %s", exc)
        return None
    if not rows:
        return None
    month = rows[30]["value"] if len(rows) > 30 else None
    return {"value": rows[0]["value"], "label": rows[0]["label"], "date": rows[0]["date"],
            "week_ago": rows[7]["value"] if len(rows) > 7 else None, "month_ago": month,
            "spark": [r["value"] for r in reversed(rows)], "source": "Crypto fear & greed index"}


def _diff(s: pd.Series, days: int) -> Optional[float]:
    when = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= when]
    return float(s.iloc[-1] - past.iloc[-1]) if len(past) else None


def _row(ticker: str, label: str, group: str, note: str, s: pd.Series) -> dict:
    spark = s[s.index >= s.index[-1] - pd.Timedelta(days=92)]
    points = group in POINT_CHANGE
    prev = s.iloc[-2] if len(s) > 1 else None
    return {
        "key": ticker, "label": label, "group": group, "note": note,
        "price": float(s.iloc[-1]),
        "as_of": str(pd.Timestamp(s.index[-1]).date()),
        "change_unit": "points" if points else "%",
        "change_1d": (float(s.iloc[-1] - prev) if points else float(s.iloc[-1] / prev - 1) * 100)
        if prev else None,
        "change_1m": _diff(s, 30) if points else _change(s, 30),
        "change_1y": _diff(s, 365) if points else _change(s, 365),
        "spark": [round(float(v), 4) for v in spark.to_numpy()],
        "source": s.attrs.get("source"),
    }


def term_structure(rows: list[dict]) -> Optional[dict]:
    by = {r["key"]: r["price"] for r in rows}
    vix, vix3m = by.get("^VIX"), by.get("^VIX3M")
    if not vix or not vix3m:
        return None
    ratio = vix / vix3m
    shape = "backwardation" if ratio > 1 else "contango"
    return {"vix": vix, "vix3m": vix3m, "ratio": round(ratio, 3), "shape": shape,
            "note": ("Near-term fear above longer-term: usually seen during sell-offs"
                     if shape == "backwardation" else "Calm near term: the usual shape")}


def tickers() -> list[str]:
    return [t for t, *_ in ITEMS]


def build(fetch: Fetch = _yahoo, cboe: Callable[[list[str]], dict[str, float]] = _cboe_latest,
          fear_greed: Callable[[], Optional[dict]] = _fear_greed, use_cache: bool = True,
          live: Optional[dict] = None) -> dict:
    """`live`: ticker -> {price, day} from live_market.latest, moving each
    item's latest value; the history behind it is cached CACHE_SECONDS."""
    from .live_market import extend_all

    if use_cache and not live:
        with _lock:
            hit = _cache.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]

    raw = None
    if use_cache:
        with _lock:
            hit = _raw_cache.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            raw = hit[1]
    if raw is None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            mood = pool.submit(fear_greed)
            fresh = pool.submit(cboe, [t for t, *_ in ITEMS if t.startswith("^VIX")])
            try:
                data = fetch([t for t, *_ in ITEMS])
            except Exception as exc:  # network / Yahoo hiccup
                logger.warning("World markets fetch failed: %s", exc)
                data = {}
            raw = (data, mood.result(), fresh.result())
        if use_cache and raw[0]:
            with _lock:
                _raw_cache["all"] = (time.time(), raw)
    data, crypto, latest = raw
    data = dict(data)

    today = pd.Timestamp.today().normalize()
    for sym, value in latest.items():  # CBOE's value is today's; replace or append the last bar
        s = data.get(sym)
        if s is None or not len(s):
            continue
        s = s.copy()
        if s.index[-1].normalize() >= today:
            s.iloc[-1] = value
        else:
            s.loc[today] = value
        data[sym] = s
    if live:
        data = extend_all(data, live)

    rows = [_row(t, label, group, note, data[t]) for t, label, group, note in ITEMS
            if t in data and len(data[t]) > 1]
    failed = [label for t, label, *_ in ITEMS if not any(r["key"] == t for r in rows)]
    source = "Daily closes from the market data feed; VIX from the exchange's delayed quotes; crypto fear & greed index"
    backup = [r["label"] for r in rows if r["source"]]
    if backup:
        source += f"; central bank reference rates for {', '.join(backup)} (feed missing or stale)"
    out = {"items": rows, "failed": failed, "vix_term": term_structure(rows), "crypto_mood": crypto,
           "updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "source": source}
    if use_cache and rows and not live:
        with _lock:
            _cache["all"] = (time.time(), out)
    return out
