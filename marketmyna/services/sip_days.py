"""Historically best SIP day for every Indian mutual fund and every listed ETF.

For one price series, replays a monthly SIP on each day 1-28 of the month
over the last 3, 5 and 10 years and ranks the days by XIRR (same rules as
services/sip.py: buy on the first trading day on or after the chosen day,
value everything at the last price). All 28 days are solved together with
numpy, so a fund costs a few milliseconds once its history is downloaded.

The edge is usually small and often down to chance, so each result carries
a label rather than a recommendation:
- "consistent": the best day of every window lands within a few days of
  the others (needs 5+ years of history, i.e. two windows or more).
- "no_edge": the windows disagree; any day is as good as another.
- "short": only 3-5 years of history, too short to check consistency.
- "negligible": best and worst day differ by under MIN_GAP points a year
  over the longest window (typical of debt funds, whose smooth NAV makes a
  month-end day "win" every time by a meaningless margin).

A background loop (refresh_loop) keeps a per-market summary on disk under
~/.marketmyna/sip_days/<market>.json, refreshing entries older than a week:
Indian schemes from mfapi.in NAVs, ETFs (India, US, Hong Kong) from Yahoo
daily closes adjusted for dividends. Past behaviour, not advice.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from marketmyna.core.home import app_home

logger = logging.getLogger(__name__)

DAYS = np.arange(1, 29)
WINDOWS = (3, 5, 10)  # years
NEAR_DAYS = 3  # best days this close count as the same answer
MIN_GAP = 0.10  # points a year; below this the day does not matter
MAX_AGE_DAYS = 7
ETF_MARKETS = ("india", "us", "hong_kong")
STALE_NAV_DAYS = 30  # a scheme with no NAV for a month is wound up / merged


# ------------------------------------------------------------------ maths

def _buy_positions(index: pd.DatetimeIndex, start: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    """Index positions of each day's monthly buys -> (pos[28, M], valid[28, M])."""
    end = index[-1]
    months = pd.date_range(pd.Timestamp(start.year, start.month, 1), end, freq="MS")
    targets = months.values[None, :] + (DAYS[:, None] - 1).astype("timedelta64[D]")
    pos = index.values.searchsorted(targets.ravel()).reshape(targets.shape)
    inside = pos < len(index)
    safe = np.minimum(pos, len(index) - 1)
    bought = index.values[safe]
    same_month = bought.astype("datetime64[M]") == targets.astype("datetime64[M]")
    valid = inside & same_month & (bought >= np.datetime64(start))
    return safe, valid


def day_xirrs(nav: pd.Series, start: pd.Timestamp) -> np.ndarray:
    """XIRR (fraction a year) of a monthly SIP from `start` for days 1..28;
    NaN where a day has fewer than two instalments or no solution."""
    index = pd.DatetimeIndex(nav.index)
    prices = nav.to_numpy(dtype=float)
    pos, valid = _buy_positions(index, start)
    count = valid.sum(axis=1)
    units = np.where(valid, 1.0 / prices[pos], 0.0).sum(axis=1)
    value = units * prices[-1]

    days_of = index.values[pos].astype("datetime64[D]").astype(np.int64)
    first = np.where(valid, days_of, np.iinfo(np.int64).max).min(axis=1)
    t = np.where(valid, (days_of - first[:, None]) / 365.0, 0.0)
    t_end = (np.int64(index.values[-1].astype("datetime64[D]").astype(np.int64)) - first) / 365.0

    def npv(rate: np.ndarray) -> np.ndarray:
        base = (1.0 + rate)[:, None]
        outflow = np.where(valid, base ** (-t), 0.0).sum(axis=1)
        return value * (1.0 + rate) ** (-t_end) - outflow

    lo = np.full(len(DAYS), -0.99)
    hi = np.full(len(DAYS), 10.0)
    ok = (count >= 2) & (npv(lo) * npv(hi) <= 0)
    for _ in range(80):
        mid = (lo + hi) / 2
        left = npv(lo) * npv(mid) <= 0
        hi = np.where(left, mid, hi)
        lo = np.where(left, lo, mid)
    return np.where(ok, (lo + hi) / 2, np.nan)


def clean(nav: pd.Series) -> pd.Series:
    """Sorted, positive, de-duplicated prices without one-off bad prints.

    Yahoo sometimes keeps a day or two at a tenth of the real price around a
    split (NIFTYBEES, Dec 2019); a price more than 40% away from the median of
    the surrounding 11 days is dropped. Real crashes move far less in a day.
    """
    nav = nav.dropna()
    nav = nav[nav > 0].sort_index()
    nav = nav[~nav.index.duplicated(keep="last")]
    if len(nav) < 11:
        return nav
    ratio = nav / nav.rolling(11, center=True, min_periods=3).median()
    return nav[(ratio < 1.4) & (ratio > 1 / 1.4)]


def _near(a: int, b: int) -> bool:
    gap = abs(a - b)
    return min(gap, 30 - gap) <= NEAR_DAYS  # day 28 sits next to next month's 1st


def label(windows: dict) -> str:
    """consistent / no_edge / short / negligible for a {"3y": {...}, ...} map."""
    longest = windows[list(windows)[-1]]
    bests = [w["best"] for w in windows.values()]
    if longest["spread"] < MIN_GAP:
        return "negligible"
    if len(bests) < 2:
        return "short"
    if all(_near(a, b) for a in bests for b in bests):
        return "consistent"
    return "no_edge"


def analyze(nav: pd.Series) -> Optional[dict]:
    """Best / worst SIP day per window plus a consistency label, or None when
    there are under 3 years of prices."""
    nav = clean(nav)
    if len(nav) < 30:
        return None
    end = nav.index[-1]
    windows = {}
    for years in WINDOWS:
        start = end - pd.DateOffset(years=years)
        if nav.index[0] > start + pd.Timedelta(days=31):
            continue  # not enough history for a full window
        x = day_xirrs(nav, start)
        if np.isnan(x).all():
            continue
        best, worst = int(np.nanargmax(x)), int(np.nanargmin(x))
        windows[f"{years}y"] = {
            "best": int(DAYS[best]),
            "worst": int(DAYS[worst]),
            "best_xirr": round(float(x[best]) * 100, 2),
            "spread": round(float(x[best] - x[worst]) * 100, 2),
        }
    if not windows:
        return None
    longest = windows[list(windows)[-1]]
    return {
        "as_of": str(end.date()),
        "best_day": longest["best"],
        "spread": longest["spread"],
        "edge": label(windows),
        "windows": windows,
    }


def curve(nav: pd.Series, years: int) -> list[dict]:
    """XIRR % for each day 1..28 over one window (the fund page's chart)."""
    nav = clean(nav)
    if len(nav) < 30:
        return []
    start = max(nav.index[-1] - pd.DateOffset(years=years), nav.index[0])
    x = day_xirrs(nav, start)
    return [{"day": int(d), "xirr_pct": None if np.isnan(v) else round(float(v) * 100, 3)} for d, v in zip(DAYS, x)]


# ------------------------------------------------------------ storage

_lock = threading.Lock()
_memory: dict[str, dict] = {}


def _root() -> Path:
    p = app_home() / "sip_days"
    p.mkdir(parents=True, exist_ok=True)
    return p


def load(market: str) -> dict:
    """symbol -> summary for one market (cached in memory)."""
    with _lock:
        if market in _memory:
            return _memory[market]
    f = _root() / f"{market}.json"
    try:
        data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError) as exc:
        logger.warning("SIP days %s unreadable: %s", market, exc)
        data = {}
    for entry in data.values():  # labels follow the current rules, no refetch needed
        if entry.get("windows"):
            entry["edge"] = label(entry["windows"])
    with _lock:
        _memory[market] = data
    return data


def _save(market: str, data: dict) -> None:
    f = _root() / f"{market}.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(f)
    with _lock:
        _memory[market] = data


def annotate(rows: list[dict], market: str) -> None:
    """Adds sip_day / sip_edge / sip_spread to mutual fund and ETF rows in place."""
    markets = ("india", *ETF_MARKETS) if market == "all" else (market,)
    tables = {m: load(m) for m in set(markets)}
    for row in rows:
        if row.get("type") not in ("mf", "etf"):
            continue
        hit = tables.get(row.get("market"), {}).get(str(row.get("symbol")))
        if hit and hit.get("best_day"):
            row["sip_day"] = hit["best_day"]
            row["sip_edge"] = hit["edge"]
            row["sip_spread"] = hit["spread"]


# ------------------------------------------------------------ fetching

def mf_nav(code: str) -> Optional[pd.Series]:
    from ..data.mutual_funds import MutualFundDataFetcher

    df = MutualFundDataFetcher().get_historical_nav(int(code), days=100_000)
    return None if df.empty else df["nav"].astype(float)


def _yahoo_closes(tickers: list[str]) -> dict[str, pd.Series]:
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    start = (pd.Timestamp.today() - pd.DateOffset(years=max(WINDOWS)) - pd.Timedelta(days=45)).date()
    with YF_DOWNLOAD_LOCK:
        df = yf.download(tickers, start=str(start), interval="1d", progress=False, auto_adjust=True, threads=True)
    if df is None or df.empty:
        return {}
    closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": tickers[0]})
    out = {}
    for t in tickers:
        if t in closes:
            s = closes[t].dropna()
            if len(s):
                idx = pd.DatetimeIndex(s.index)
                s.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
                out[t] = s
    return out


def etf_prices(symbol: str, market: str) -> Optional[pd.Series]:
    from .analysis_run import yahoo_symbol

    t = yahoo_symbol(symbol, market)
    return _yahoo_closes([t]).get(t)


def _fresh(entry: Optional[dict], today: date) -> bool:
    if not entry:
        return False
    try:
        checked = datetime.fromisoformat(entry["checked"]).date()
    except (KeyError, ValueError):
        return False
    return (today - checked).days < MAX_AGE_DAYS


def _targets(market: str, rows: list[dict]) -> list[str]:
    want = "mf" if market == "india_mf" else "etf"
    return [str(r["symbol"]) for r in rows if r.get("type") == want and r.get("symbol")]


def _record(series: Optional[pd.Series], today: date) -> dict:
    entry: dict = {"checked": today.isoformat()}
    if series is None or series.empty:
        entry["status"] = "no_data"
        return entry
    if (pd.Timestamp(today) - pd.DatetimeIndex(series.index).max()).days > STALE_NAV_DAYS:
        entry["status"] = "inactive"
        return entry
    result = analyze(series)
    if result is None:
        entry["status"] = "too_new"
        return entry
    entry.update(result)
    return entry


def refresh_mutual_funds(workers: int = 4, save_every: int = 200) -> int:
    """Indian schemes (every plan and option). Returns how many were updated."""
    from ..data.listings import get_store

    today = date.today()
    data = dict(load("india"))
    codes = [c for c in _targets("india_mf", get_store().rows("india")) if not _fresh(data.get(c), today)]
    done = 0

    def one(code: str) -> tuple[str, dict]:
        try:
            return code, _record(mf_nav(code), today)
        except Exception as exc:  # one bad scheme must not stop the run
            logger.debug("SIP days %s: %s", code, exc)
            return code, {"checked": today.isoformat(), "status": "error"}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for code, entry in pool.map(one, codes):
            data[code] = entry
            done += 1
            if done % save_every == 0:
                _save("india", data)
    if done:
        _save("india", data)
    return done


def refresh_etfs(batch: int = 40) -> int:
    from ..data.listings import get_store
    from .analysis_run import yahoo_symbol

    today = date.today()
    total = 0
    for market in ETF_MARKETS:
        data = dict(load(market))
        symbols = [s for s in _targets(market, get_store().rows(market)) if not _fresh(data.get(s), today)]
        for i in range(0, len(symbols), batch):
            chunk = symbols[i : i + batch]
            tickers = {yahoo_symbol(s, market): s for s in chunk}
            try:
                closes = _yahoo_closes(list(tickers))
            except Exception as exc:
                logger.warning("SIP days ETF batch (%s): %s", market, exc)
                continue
            for t, s in tickers.items():
                data[s] = _record(closes.get(t), today)
            total += len(chunk)
            _save(market, data)
            time.sleep(1)  # be gentle with Yahoo
    return total


def refresh_loop(first_delay: int = 300, every: int = 6 * 3600) -> None:
    """Background thread: fill and then keep the summaries fresh."""
    time.sleep(first_delay)  # after start-up and the listing warm-up
    while True:
        try:
            n = refresh_mutual_funds()
            m = refresh_etfs()
            logger.info("SIP days refreshed: %d funds, %d ETFs", n, m)
        except Exception as exc:  # never kill the thread
            logger.warning("SIP days refresh: %s", exc)
        time.sleep(every)
