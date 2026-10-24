"""Deeper analysis of one mutual fund from its daily NAV history:

  rolling     CAGR over every 1 / 3 / 5-year window (one per start day),
              its spread, and how often the fund beat its benchmark over the
              same windows - what point-to-point returns hide.
  risk        last 3 years against the category benchmark: beta, alpha,
              Sharpe, Sortino, tracking error, information ratio, up / down
              capture (same maths as the portfolio page).
  drawdowns   the deepest falls from a high, how long the recovery took,
              and how the fund did in the 2020 and 2022 sell-offs.

The benchmark follows SEBI's tier-1 index for the category (Nifty 100 for
large caps, Midcap 150, Smallcap 250, Nifty 500 for the broad equity
categories); hybrid, debt and fund-of-funds categories have no free index and
are shown without one. A NAV includes reinvested dividends but Yahoo's index
series are price-only, so each index gets its dividends back as a steady
yearly rate: the gap between the index and an ETF tracking it (an ETF's
dividend-adjusted price follows the total-return index), measured over the
years both exist. Indices without a long-lived ETF borrow a sister index's gap.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..core.numbers import finite

logger = logging.getLogger(__name__)

CACHE_SECONDS = 12 * 3600
WINDOWS = (1, 3, 5)  # rolling-return windows, years
RISK_YEARS = 3
RISK_FREE = 0.065  # Indian T-bill ballpark, a year
TRADING_DAYS = 252
TOP_DRAWDOWNS = 5
MIN_DRAWDOWN = 0.05  # falls shallower than 5% are not listed
EPISODES = [  # (label, from, to): market sell-offs to compare the fund in
    ("2020 Covid crash", "2020-01-14", "2020-03-31"),
    ("2022 rate-rise sell-off", "2021-10-01", "2022-10-31"),
    ("2024-25 correction", "2024-09-26", "2025-03-04"),
]

NIFTY_50 = ("^NSEI", "Nifty 50")
NIFTY_100 = ("^CNX100", "Nifty 100")
NIFTY_500 = ("^CRSLDX", "Nifty 500")
NEXT_50 = ("^NSMIDCP", "Nifty Next 50")
MIDCAP_150 = ("NIFTYMIDCAP150.NS", "Nifty Midcap 150")
MIDCAP_50 = ("^NSEMDCP50", "Nifty Midcap 50")
SMALLCAP_250 = ("NIFTYSMLCAP250.NS", "Nifty Smallcap 250")
SENSEX = ("^BSESN", "Sensex")

# Index funds / ETFs: the index named in the scheme (checked in order).
INDEX_NAMES = [("next 50", NEXT_50), ("midcap 150", MIDCAP_150), ("midcap 50", MIDCAP_50),
               ("smallcap 250", SMALLCAP_250), ("nifty 500", NIFTY_500), ("nifty 100", NIFTY_100),
               ("nifty 50", NIFTY_50), ("sensex", SENSEX)]
BROAD_EQUITY = ("flexi cap", "multi cap", "focused", "elss", "value", "contra", "dividend yield", "sectoral",
                "thematic", "equity funds", "growth (close ended)")

# price index -> ETF whose dividend-adjusted price gives that index's dividend yield
# (the most liquid, closest-tracking ETFs; smaller ones are too noisy)
TR_PROXY = {"^NSEI": "NIFTYBEES.NS", "NIFTYMIDCAP150.NS": "MID150BEES.NS"}
# other indices borrow the yield of the closest of those two
TR_SISTER = {"^CNX100": "^NSEI", "^CRSLDX": "^NSEI", "^NSMIDCP": "^NSEI", "^BSESN": "^NSEI",
             "NIFTYSMLCAP250.NS": "NIFTYMIDCAP150.NS", "^NSEMDCP50": "NIFTYMIDCAP150.NS"}
YIELD_YEARS = 5  # recent years only: ETF fees were higher a decade ago
MAX_YIELD = 0.025  # a dividend gap above 2.5% a year is a data problem
JUMP = 0.4  # a one-day log move this big in a NAV is a data break, not a market move

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()

NavFetch = Callable[[str], Optional[pd.Series]]
BenchFetch = Callable[[str], Optional[pd.Series]]


def benchmark_for(category: Optional[str], name: str = "") -> Optional[tuple[str, str]]:
    """(Yahoo ticker, label) of the index to judge this fund against, or None."""
    cat, nm = (category or "").lower(), (name or "").lower()
    if "index" in cat or "etf" in cat:
        return next((b for key, b in INDEX_NAMES if key in nm), None)
    if "large & mid" in cat:
        return NIFTY_500  # Nifty LargeMidcap 250 has no free daily series
    if "large cap" in cat:
        return NIFTY_100
    if "mid cap" in cat:
        return MIDCAP_150
    if "small cap" in cat:
        return SMALLCAP_250
    if any(k in cat for k in BROAD_EQUITY):
        return NIFTY_500
    return None


def clean_nav(nav: pd.Series) -> pd.Series:
    """Fix NAV data breaks: a one-day spike that reverts is dropped; a lasting
    jump (face-value change, e.g. 28.56 -> 2857.24) rescales the history before
    it, so returns across the change stay right."""
    s = nav.astype(float)
    s = s[s > 0].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    for _ in range(10):
        lr = np.log(s / s.shift(1))
        jumps = lr[lr.abs() > JUMP]
        if jumps.empty:
            break
        i = s.index.get_loc(jumps.index[0])
        nxt = float(np.log(s.iloc[i + 1] / s.iloc[i])) if i + 1 < len(s) else 0.0
        if abs(nxt) > JUMP and np.sign(nxt) != np.sign(jumps.iloc[0]):
            s = s.drop(s.index[i])
        else:
            s.iloc[:i] = s.iloc[:i] * (s.iloc[i] / s.iloc[i - 1])
    return s


def _daily(s: pd.Series) -> pd.Series:
    """Calendar-daily, forward-filled: lets a window be exactly N years."""
    s = s.sort_index()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    s = s[~s.index.duplicated(keep="last")]
    return s.asfreq("D").ffill()


def _cagr_series(daily: pd.Series, years: int) -> pd.Series:
    """CAGR (%) of the window starting on each day, indexed by start day."""
    days = round(365.25 * years)
    end = daily.shift(-days)
    return ((end / daily) ** (1 / years) - 1).dropna() * 100


def rolling(nav: pd.Series, bench: Optional[pd.Series] = None) -> dict:
    fund = _daily(nav)
    idx = _daily(bench) if bench is not None and len(bench) else None
    out = []
    for years in WINDOWS:
        f = _cagr_series(fund, years)
        if len(f) < 30:
            continue
        row = {"years": years, "windows": int(len(f)), "from": str(f.index[0].date()),
               "median": float(f.median()), "mean": float(f.mean()), "min": float(f.min()), "max": float(f.max()),
               "worst_start": str(f.idxmin().date()), "best_start": str(f.idxmax().date()),
               "negative_pct": float((f < 0).mean() * 100),
               "above_8_pct": float((f > 8).mean() * 100), "above_12_pct": float((f > 12).mean() * 100),
               "bench_median": None, "beat_pct": None, "compared": 0}
        if idx is not None:
            b = _cagr_series(idx, years)
            pair = pd.concat([f, b], axis=1, keys=["f", "b"]).dropna()
            if len(pair) >= 30:
                row.update(bench_median=float(pair["b"].median()), compared=int(len(pair)),
                           beat_pct=float((pair["f"] > pair["b"]).mean() * 100))
        out.append(row)
    # 3-year rolling CAGR (or the longest window there is) for a chart, weekly points
    chart_years = next((y for y in (3, 1) if any(r["years"] == y for r in out)), None)
    chart = []
    if chart_years:
        f = _cagr_series(fund, chart_years).resample("W").last().dropna()
        b = _cagr_series(idx, chart_years).resample("W").last() if idx is not None else None
        for day, v in f.items():
            bv = b.get(day) if b is not None else None
            chart.append({"date": str(day.date()), "fund": round(float(v), 2),
                          "bench": None if bv is None or pd.isna(bv) else round(float(bv), 2)})
    return {"windows": out, "chart_years": chart_years, "chart": chart}


def _returns(s: pd.Series, since: pd.Timestamp) -> pd.Series:
    s = s.sort_index()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    s = s[~s.index.duplicated(keep="last")]
    return s[s.index >= since].pct_change().dropna()


def risk(nav: pd.Series, bench: Optional[pd.Series] = None) -> Optional[dict]:
    """Last RISK_YEARS of daily returns (business days both series traded)."""
    from ..portfolio.analytics import ratios, versus_benchmark

    end = pd.DatetimeIndex(nav.index).tz_localize(None).max()
    since = end - pd.DateOffset(years=RISK_YEARS)
    fund = _returns(nav, since)
    if len(fund) < 120:
        return None
    out = {"years": RISK_YEARS, "from": str(fund.index[0].date()), "risk_free": RISK_FREE * 100,
           **ratios(fund, RISK_FREE), "beta": None, "alpha": None, "correlation": None,
           "bench_annual_return": None, "bench_volatility": None, "bench_max_drawdown": None}
    if bench is not None and len(bench):
        b = _returns(bench, since)
        pair = pd.concat([fund, b], axis=1, keys=["f", "b"]).dropna()
        if len(pair) >= 120:
            bvar = float(pair["b"].var())
            beta = float(pair["f"].cov(pair["b"]) / bvar) if bvar else None
            bstats = ratios(pair["b"], RISK_FREE)
            fann = float((1 + pair["f"]).prod()) ** (TRADING_DAYS / len(pair)) - 1
            alpha = (fann - RISK_FREE - beta * (bstats["annual_return"] - RISK_FREE)) if beta is not None else None
            out.update(versus_benchmark(pair["f"], pair["b"]))
            out.update(beta=finite(beta), alpha=finite(alpha), correlation=finite(pair["f"].corr(pair["b"])),
                       bench_annual_return=bstats["annual_return"], bench_volatility=bstats["volatility"],
                       bench_max_drawdown=bstats["max_drawdown"])
    return out


def _episodes(curve: pd.Series) -> list[dict]:
    """Every fall from a high, deepest first: peak, trough, depth, recovery."""
    curve = curve.dropna()
    peak = curve.cummax()
    under = curve / peak - 1
    out, start = [], None
    for day, dd in under.items():
        if dd < -1e-9 and start is None:
            start = day
        elif dd >= -1e-9 and start is not None:  # back at the old high (allowing float noise)
            out.append((start, day))
            start = None
    if start is not None:
        out.append((start, None))
    rows = []
    for begin, back in out:
        span = under[begin:back] if back is not None else under[begin:]
        trough_day = span.idxmin()
        depth = float(span.min())
        if -depth < MIN_DRAWDOWN:
            continue
        peak_day = curve[:begin].index[-2] if len(curve[:begin]) > 1 else begin
        rows.append({"peak": str(peak_day.date()), "trough": str(trough_day.date()),
                     "recovered": str(back.date()) if back is not None else None, "depth": depth * 100,
                     "days_down": int((trough_day - peak_day).days),
                     "days_to_recover": int((back - trough_day).days) if back is not None else None})
    rows.sort(key=lambda r: r["depth"])
    return rows[:TOP_DRAWDOWNS]


def _window_move(s: pd.Series, start: str, end: str) -> Optional[float]:
    """Worst peak-to-trough fall (%) inside the window."""
    w = s[(s.index >= start) & (s.index <= end)].dropna()
    if len(w) < 10:
        return None
    return float((w / w.cummax() - 1).min() * 100)


def drawdowns(nav: pd.Series, bench: Optional[pd.Series] = None) -> dict:
    fund = _daily(nav)
    under = (fund / fund.cummax() - 1) * 100
    idx = _daily(bench) if bench is not None and len(bench) else None
    weekly = under.resample("W").min().dropna()
    bweekly = None
    if idx is not None:
        bunder = (idx / idx.cummax() - 1) * 100
        bweekly = bunder[bunder.index >= fund.index[0]].resample("W").min()
    chart = [{"date": str(d.date()), "fund": round(float(v), 2),
              "bench": None if bweekly is None or pd.isna(bweekly.get(d)) else round(float(bweekly.get(d)), 2)}
             for d, v in weekly.items()]
    crashes = []
    for label, start, end in EPISODES:
        f = _window_move(fund, start, end)
        if f is None:
            continue
        crashes.append({"label": label, "from": start, "to": end, "fund": f,
                        "bench": _window_move(idx, start, end) if idx is not None else None})
    return {"current": float(under.iloc[-1]), "max": float(under.min()), "episodes": _episodes(fund),
            "crashes": crashes, "chart": chart}


def _bench_history(ticker: str) -> Optional[pd.Series]:
    from ..portfolio.analytics import _benchmark_long

    return _benchmark_long(ticker)


def dividend_yield(ticker: str, fetch: BenchFetch = _bench_history) -> Optional[float]:
    """Yearly gap between an ETF's dividend-adjusted price and its price index
    over the last YIELD_YEARS (or as long as both exist, after the ETF's first month)."""
    etf_ticker = TR_PROXY.get(ticker)
    if etf_ticker is None:
        sister = TR_SISTER.get(ticker)
        return dividend_yield(sister, fetch) if sister else None
    index, etf = fetch(ticker), fetch(etf_ticker)
    if index is None or etf is None or len(etf) < 260:
        return None
    pair = pd.concat([_daily(index), _daily(etf)], axis=1, keys=["i", "e"]).dropna()
    pair = pair[pair.index >= max(pair.index[0] + pd.Timedelta(days=30),
                                  pair.index[-1] - pd.DateOffset(years=YIELD_YEARS))]
    if len(pair) < 365:
        return None
    years = (pair.index[-1] - pair.index[0]).days / 365.25
    growth = (pair["e"].iloc[-1] / pair["e"].iloc[0]) / (pair["i"].iloc[-1] / pair["i"].iloc[0])
    gap = growth ** (1 / years) - 1  # the rate total_return() compounds back in
    return float(min(max(gap, 0.0), MAX_YIELD))


def total_return(index: pd.Series, yearly: float) -> pd.Series:
    """Price index with dividends credited at a steady yearly rate."""
    idx = index.sort_index()
    t = (pd.DatetimeIndex(idx.index) - pd.DatetimeIndex(idx.index)[0]).days / 365.25
    return idx * np.power(1 + yearly, t)


def _row(code: str) -> Optional[dict]:
    from ..data.listings import get_store

    return next((r for r in get_store().rows("india") if r.get("type") == "mf" and str(r["symbol"]) == code), None)


def is_payout(row: Optional[dict]) -> bool:
    """IDCW / dividend options: each payout lowers the NAV, so NAV returns understate them."""
    text = f"{(row or {}).get('option') or ''} {(row or {}).get('name') or ''}".lower()
    return any(k in text for k in ("idcw", "dividend option", "payout", "income distribution"))


def build(code: str, fetch: Optional[NavFetch] = None, bench_fetch: BenchFetch = _bench_history,
          row: Optional[dict] = None, use_cache: bool = True) -> dict:
    code = str(code)
    if use_cache:
        with _lock:
            hit = _cache.get(code)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    if fetch is None:
        from .fund_peers import nav as fetch
    row = row if row is not None else _row(code)
    nav = fetch(code)
    if nav is None or len(nav) < 60:
        return {"status": "no_history", "note": "Not enough NAV history for this fund yet."}
    nav = clean_nav(nav)
    bench_info = benchmark_for((row or {}).get("sector"), (row or {}).get("name", ""))
    bench, yearly = None, None
    if bench_info:
        try:
            price = bench_fetch(bench_info[0])
            yearly = dividend_yield(bench_info[0], bench_fetch) if price is not None else None
            bench = total_return(price, yearly or 0.0) if price is not None else None
        except Exception as exc:
            logger.info("Benchmark %s unavailable: %s", bench_info[0], exc)
    out = {
        "status": "ok",
        "code": code,
        "category": (row or {}).get("sector"),
        "nav_from": str(pd.Timestamp(nav.index.min()).date()),
        "nav_to": str(pd.Timestamp(nav.index.max()).date()),
        "benchmark": {"symbol": bench_info[0], "name": bench_info[1], "available": bench is not None,
                      "dividend_yield": yearly * 100 if yearly is not None else None}
        if bench_info else None,
        "rolling": rolling(nav, bench),
        "payout_option": is_payout(row),
        "risk": risk(nav, bench),
        "drawdowns": drawdowns(nav, bench),
        "note": "NAV history from official fund data; index history from the market data feed, with dividends added back at the "
                "rate an ETF on the index earned over it, so the comparison is total return against total "
                "return, as SEBI asks. Past returns don't predict future ones.",
    }
    _clean(out)
    if use_cache:
        with _lock:
            _cache[code] = (time.time(), out)
    return out


def _clean(obj):
    """NaN / inf -> None everywhere (JSON has no NaN)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = _clean(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            obj[i] = _clean(v)
    elif isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj
