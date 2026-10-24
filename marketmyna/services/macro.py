"""Macro dashboard: key US / India / global series from FRED's public CSV
export (no API key), with latest value, 1-month and 1-year change and a
monthly sparkline. Covers the core of OpenBB's economy / fixedincome
endpoints that matter to an equity investor.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd={start}"
CACHE_SECONDS = 6 * 3600
YEARS = 5

# id, label, group, unit, transform (level | yoy), note
SERIES = [
    ("CPIAUCSL", "US inflation (CPI)", "us", "%", "yoy", "Consumer prices vs a year ago"),
    ("FEDFUNDS", "Fed funds rate", "us", "%", "level", "US policy rate"),
    ("DGS10", "US 10-year yield", "us", "%", "level", "Long-term borrowing cost; higher weighs on stock valuations"),
    ("DGS2", "US 2-year yield", "us", "%", "level", "Tracks where the Fed is expected to go"),
    ("T10Y2Y", "US yield curve (10y - 2y)", "us", "pts", "level", "Below 0 (inverted) has preceded most US recessions"),
    ("UNRATE", "US unemployment", "us", "%", "level", "Share of the labour force out of work"),
    ("INDIRLTLT01STM", "India 10-year yield", "india", "%", "level", "Government bond yield"),
    ("IRSTCI01INM156N", "India call money rate", "india", "%", "level", "Overnight interbank rate, tracks RBI policy"),
    ("DEXINUS", "USD / INR", "india", "₹", "level", "Rupees per dollar; higher = weaker rupee"),
    ("DCOILBRENTEU", "Brent crude", "global", "$", "level", "Oil price; a big cost driver for India"),
]

Fetch = Callable[[str, date], pd.Series]

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _fred(series_id: str, start: date) -> pd.Series:
    import requests

    # FRED stalls requests with an unknown custom User-Agent; the library default works.
    resp = requests.get(FRED_CSV.format(id=series_id, start=start.isoformat()), timeout=20)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    return s.dropna()


def _asof(s: pd.Series, when: pd.Timestamp) -> Optional[float]:
    past = s[s.index <= when]
    return float(past.iloc[-1]) if len(past) else None


def _fetch_one(fetch: Fetch, spec: tuple, start: date) -> tuple:
    """(spec, series) for one FRED series; series is None when the fetch fails."""
    try:
        return spec, fetch(spec[0], start)
    except Exception as exc:
        logger.warning("FRED %s failed: %s", spec[0], exc)
        return spec, None


def shape(series_id: str, label: str, group: str, unit: str, transform: str, note: str, raw: pd.Series) -> Optional[dict]:
    s = raw.sort_index()
    if transform == "yoy":
        monthly = s.resample("MS").last().dropna()
        s = (monthly / monthly.shift(12) - 1).dropna() * 100
    if s.empty:
        return None
    last_day = s.index[-1]
    value = float(s.iloc[-1])
    m1, y1 = _asof(s, last_day - pd.DateOffset(months=1)), _asof(s, last_day - pd.DateOffset(years=1))
    spark = s.resample("MS").last().dropna().tail(36)
    return {"id": series_id, "label": label, "group": group, "unit": unit, "note": note,
            "value": value, "date": str(last_day.date()),
            "change_1m": value - m1 if m1 is not None else None,
            "change_1y": value - y1 if y1 is not None else None,
            "spark": [{"date": str(i.date()), "value": float(v)} for i, v in spark.items()]}


def build(fetch: Fetch = _fred, use_cache: bool = True) -> dict:
    if use_cache:
        with _lock:
            hit = _cache.get("all")
            if hit and time.time() - hit[0] < CACHE_SECONDS:
                return hit[1]
    start = date.today() - timedelta(days=365 * YEARS + 400)  # extra year for YoY

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda spec: _fetch_one(fetch, spec, start), SERIES))
    series, failed = [], []
    for spec, raw in results:
        item = shape(*spec, raw) if raw is not None and len(raw) else None
        (series.append(item) if item else failed.append(spec[1]))
    curve = next((s for s in series if s["id"] == "T10Y2Y"), None)
    out = {"series": series, "failed": failed,
           "signals": {"us_curve_inverted": curve["value"] < 0 if curve else None},
           "source": "Official central bank and government statistics"}
    if use_cache and series:
        with _lock:
            _cache["all"] = (time.time(), out)
    return out


def context_lines(data: Optional[dict] = None) -> list[str]:
    """Short text lines for LLM prompts (agent context)."""
    data = data or build()
    lines = []
    for s in data["series"]:
        chg = f", {s['change_1y']:+.2f} over 1y" if s.get("change_1y") is not None else ""
        lines.append(f"{s['label']}: {s['value']:.2f}{'' if s['unit'] in ('₹', '$') else s['unit']} ({s['date']}{chg})")
    return lines


def cached_context() -> list[str]:
    """Macro lines for prompts without ever blocking: uses the cache, and if it
    is cold, warms it on a background thread and returns nothing this time."""
    with _lock:
        hit = _cache.get("all")
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return context_lines(hit[1]) + _india_cached()
    threading.Thread(target=build, name="macro-warm", daemon=True).start()
    return []


def _india_cached() -> list[str]:
    """RBI / IBJA lines if that cache is warm; never fetches."""
    from . import india_rates

    with india_rates._lock:
        hit = india_rates._cache.get("all")
    if hit and time.time() - hit[0] < india_rates.CACHE_SECONDS:
        return india_rates.context_lines(hit[1])
    return []


# US Treasury constant-maturity yields, short to long (FRED, daily).
CURVE = [("DGS1MO", "1M", 1 / 12), ("DGS3MO", "3M", 0.25), ("DGS6MO", "6M", 0.5), ("DGS1", "1Y", 1),
         ("DGS2", "2Y", 2), ("DGS3", "3Y", 3), ("DGS5", "5Y", 5), ("DGS7", "7Y", 7),
         ("DGS10", "10Y", 10), ("DGS20", "20Y", 20), ("DGS30", "30Y", 30)]


def yield_curve(fetch: Fetch = _fred, use_cache: bool = True) -> dict:
    """US Treasury curve today vs 1 month and 1 year ago, plus its shape."""
    if use_cache:
        with _lock:
            hit = _cache.get("curve")
            if hit and time.time() - hit[0] < CACHE_SECONDS:
                return hit[1]
    start = date.today() - timedelta(days=400)

    with ThreadPoolExecutor(max_workers=6) as pool:
        got = [(spec, s) for spec, s in pool.map(lambda spec: _fetch_one(fetch, spec, start), CURVE) if s is not None and len(s)]
    if not got:
        return {"points": [], "as_of": None}
    as_of = min(s.index[-1] for _, s in got)  # a date every tenor has printed
    points = []
    for (sid, label, years), s in got:
        points.append({"id": sid, "tenor": label, "years": years,
                       "now": _asof(s, as_of),
                       "month_ago": _asof(s, as_of - pd.Timedelta(days=30)),
                       "year_ago": _asof(s, as_of - pd.Timedelta(days=365))})
    by = {p["tenor"]: p["now"] for p in points}
    shape_ = None
    if by.get("3M") is not None and by.get("10Y") is not None:
        spread = by["10Y"] - by["3M"]
        shape_ = {"spread_10y_3m": spread,
                  "label": "inverted" if spread < 0 else "flat" if spread < 0.5 else "normal"}
    out = {"points": points, "as_of": str(as_of.date()), "shape": shape_,
           "source": "Official US Treasury constant-maturity yields"}
    if use_cache:
        with _lock:
            _cache["curve"] = (time.time(), out)
    return out
