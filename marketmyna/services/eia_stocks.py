"""US oil inventories from the EIA's Weekly Petroleum Status Report (no key).

Each series is the EIA's own history file (eia.gov/dnav/pet/hist_xls/<id>w.xls,
weekly since the 1980s), updated after the report on Wednesday (Thursday in
holiday weeks), with figures for the week ending the previous Friday. For
each series: latest level, change on the week, and the gap to the 5-year
average for the same week of the year, the way the market reads the report
(stocks swing with the season, so a raw number says little on its own).
"""

from __future__ import annotations

import io
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

URL = "https://www.eia.gov/dnav/pet/hist_xls/{sid}w.xls"
CACHE_SECONDS = 6 * 3600

# EIA series id, label, unit, note
SERIES = [
    ("WCESTUS1", "Crude oil", "mb", "Commercial stocks, excluding the strategic reserve"),
    ("W_EPC0_SAX_YCUOK_MBBL", "Cushing, Oklahoma", "mb", "Crude at the delivery point of the WTI futures contract"),
    ("WGTSTUS1", "Gasoline", "mb", "Total motor gasoline stocks"),
    ("WDISTUS1", "Distillates", "mb", "Diesel and heating oil stocks"),
    ("WCSSTUS1", "Strategic reserve", "mb", "Crude held by the US government (SPR)"),
    ("WPULEUS3", "Refinery use", "%", "Share of operable refining capacity in use"),
]

Fetch = Callable[[str], pd.Series]

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _fetch(sid: str) -> pd.Series:
    r = requests.get(URL.format(sid=sid), timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), sheet_name="Data 1", skiprows=2)
    s = pd.Series(df.iloc[:, 1].to_numpy(dtype=float), index=pd.DatetimeIndex(df["Date"])).dropna()
    return s.sort_index()


def five_year_average(s: pd.Series) -> Optional[float]:
    """Average of the same week in each of the five previous years (the
    reading closest to the same date, within 4 days)."""
    last = s.index[-1]
    values = []
    for k in range(1, 6):
        target = last - pd.DateOffset(years=k)
        near = s[(s.index >= target - pd.Timedelta(days=4)) & (s.index <= target + pd.Timedelta(days=4))]
        if not len(near):
            return None
        values.append(float(near.iloc[abs(near.index - target).argmin()]))
    return sum(values) / len(values)


def summarise(sid: str, label: str, unit: str, note: str, s: pd.Series) -> Optional[dict]:
    if len(s) < 2:
        return None
    scale = 1000.0 if unit == "mb" else 1.0  # thousand barrels -> million barrels
    latest, prev = float(s.iloc[-1]) / scale, float(s.iloc[-2]) / scale
    avg = five_year_average(s)
    avg = avg / scale if avg is not None else None
    vs_avg = None
    if avg:
        vs_avg = round(latest - avg, 1) if unit == "%" else round((latest / avg - 1) * 100, 1)
    year = s[s.index >= s.index[-1] - pd.Timedelta(days=365)]
    return {
        "key": sid, "label": label, "unit": unit, "note": note,
        "week_ending": str(s.index[-1].date()),
        "value": round(latest, 1),
        "change_1w": round(latest - prev, 2),
        "avg_5y": round(avg, 1) if avg is not None else None,
        "vs_avg_5y": vs_avg,  # % for stocks, points for refinery use
        "spark": [round(float(v) / scale, 2) for v in year.to_numpy()],
    }


def build(fetch: Fetch = _fetch, use_cache: bool = True) -> dict:
    if use_cache:
        with _lock:
            hit = _cache.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]

    def one(spec):
        sid, label, unit, note = spec
        try:
            return summarise(sid, label, unit, note, fetch(sid))
        except Exception as exc:
            logger.info("EIA %s failed: %s", sid, exc)
            return None

    with ThreadPoolExecutor(max_workers=len(SERIES)) as pool:
        items = [r for r in pool.map(one, SERIES) if r]

    out = {
        "items": items,
        "week_ending": max((i["week_ending"] for i in items), default=None),
        "source": "US Energy Information Administration, Weekly Petroleum Status Report (released Wednesday "
                  "for the week ending the previous Friday)",
    }
    if use_cache and items:
        with _lock:
            _cache["all"] = (time.time(), out)
    return out
