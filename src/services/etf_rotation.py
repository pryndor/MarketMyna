"""Relative rotation for ETFs - the US / Hong Kong / China A counterpart of
India's mutual-fund rotation (services/fund_rotation.py). Same RS-Ratio /
RS-Momentum maths (services/rotation.py) on weekly closes, each ETF against
its home market:

- us:        S&P 500 (SPY); sector SPDRs, themes, styles & size, countries & assets
- hong_kong: Hang Seng Index; HK / China index ETFs and HK-listed global ETFs
- china_a:   Shanghai Composite; broad-index and sector ETFs

Views group the ETFs; every ETF is its own point (no baskets needed - an
ETF already is one). Cached a few hours.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import pandas as pd

from .rotation import TAIL, WINDOW, _weekly, quadrant, rrg

logger = logging.getLogger(__name__)

CACHE_SECONDS = 4 * 3600
MIN_WEEKS = 30

UNIVERSES: dict[str, dict] = {
    "us": {
        "benchmark": ("SPY", "S&P 500"),
        "views": {
            "Sectors": [
                ("XLK", "Technology"), ("XLF", "Financials"), ("XLV", "Health care"), ("XLY", "Consumer discretionary"),
                ("XLP", "Consumer staples"), ("XLE", "Energy"), ("XLI", "Industrials"), ("XLB", "Materials"),
                ("XLU", "Utilities"), ("XLRE", "Real estate"), ("XLC", "Communication services"),
            ],
            "Themes": [
                ("SMH", "Semiconductors"), ("IGV", "Software"), ("CIBR", "Cybersecurity"), ("XBI", "Biotech"),
                ("ITA", "Aerospace & defense"), ("XHB", "Homebuilders"), ("KRE", "Regional banks"), ("JETS", "Airlines"),
                ("TAN", "Solar"), ("URA", "Uranium"), ("GDX", "Gold miners"), ("BOTZ", "Robotics & AI"), ("ARKK", "Disruptive innovation"),
            ],
            "Styles & size": [
                ("QQQ", "Nasdaq 100"), ("RSP", "S&P 500 equal weight"), ("MDY", "Mid caps"), ("IWM", "Small caps"),
                ("IWF", "Large growth"), ("IWD", "Large value"), ("MTUM", "Momentum"), ("QUAL", "Quality"),
                ("USMV", "Minimum volatility"), ("VYM", "High dividend"),
            ],
            "Countries & assets": [
                ("EFA", "Developed ex-US"), ("EEM", "Emerging markets"), ("EWJ", "Japan"), ("EWG", "Germany"),
                ("EWU", "United Kingdom"), ("INDA", "India"), ("MCHI", "China"), ("EWT", "Taiwan"), ("EWY", "South Korea"),
                ("EWZ", "Brazil"), ("GLD", "Gold"), ("TLT", "Long Treasuries"), ("HYG", "High-yield bonds"), ("USO", "Crude oil"),
            ],
        },
    },
    "hong_kong": {
        "benchmark": ("^HSI", "Hang Seng Index"),
        "views": {
            "Hong Kong & China": [
                ("2800.HK", "Tracker Fund (Hang Seng)"), ("2828.HK", "Hang Seng China Enterprises"),
                ("3033.HK", "CSOP Hang Seng TECH"), ("3067.HK", "iShares Hang Seng TECH"),
                ("3069.HK", "ChinaAMC Hang Seng Biotech"), ("3110.HK", "Global X HS High Dividend"),
                ("2801.HK", "iShares Core MSCI China"), ("2823.HK", "iShares FTSE China A50"), ("3188.HK", "ChinaAMC CSI 300"),
            ],
            "Global": [
                ("2834.HK", "iShares Nasdaq 100"), ("2836.HK", "iShares Core S&P BSE Sensex India"),
                ("3010.HK", "iShares Core MSCI Asia ex Japan"), ("2840.HK", "SPDR Gold"),
            ],
        },
    },
    "china_a": {
        "benchmark": ("000001.SS", "Shanghai Composite"),
        "views": {
            "Broad indices": [
                ("510300.SS", "CSI 300"), ("510500.SS", "CSI 500 (mid caps)"), ("159915.SZ", "ChiNext (growth)"),
                ("588000.SS", "STAR 50 (tech)"),
            ],
            "Sectors": [
                ("512800.SS", "Banks"), ("512880.SS", "Brokers"), ("512690.SS", "Liquor (baijiu)"), ("159928.SZ", "Consumer staples"),
                ("512170.SS", "Healthcare"), ("512010.SS", "Pharma"), ("512480.SS", "Semiconductors"), ("159819.SZ", "Artificial intelligence"),
                ("515050.SS", "5G & telecom"), ("515030.SS", "New-energy vehicles"), ("515790.SS", "Solar (photovoltaic)"),
                ("516160.SS", "New energy"), ("512660.SS", "Defense"), ("512400.SS", "Non-ferrous metals"), ("515220.SS", "Coal"),
                ("512200.SS", "Real estate"), ("518880.SS", "Gold"),
            ],
        },
    },
}

Fetch = Callable[[list[str]], dict[str, pd.Series]]
_cache: dict[tuple, tuple[float, dict]] = {}
_closes_cache: dict[tuple[str, str], tuple[float, dict[str, pd.Series]]] = {}
_lock = threading.Lock()


def _yahoo(tickers: list[str]) -> dict[str, pd.Series]:
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    with YF_DOWNLOAD_LOCK:
        df = yf.download(tickers, period="2y", interval="1d", progress=False, auto_adjust=True, threads=True)
    closes = df["Close"]
    return {t: closes[t].dropna() for t in tickers if t in closes and closes[t].notna().sum()}


def app_symbol(ticker: str, market: str) -> str:
    """Yahoo ticker -> the app's symbol for /analyze links (2800.HK -> 02800)."""
    if market == "hong_kong":
        return f"{int(ticker.split('.')[0]):05d}"
    if market == "china_a":
        return ticker.split(".")[0]
    return ticker


def views(market: str) -> list[str]:
    return list(UNIVERSES[market]["views"]) if market in UNIVERSES else []


def tickers(market: str, view: Optional[str] = None) -> list[str]:
    """Benchmark + the view's ETFs (Yahoo tickers), for live prices."""
    cfg = UNIVERSES[market]
    members = cfg["views"].get(view or next(iter(cfg["views"])), [])
    return [cfg["benchmark"][0]] + [t for t, _ in members]


def build(market: str, view: Optional[str] = None, fetch: Fetch = _yahoo, use_cache: bool = True,
          live: Optional[dict] = None) -> dict:
    """`live`: ticker -> {price, day}; today's close moves with it, so the
    current week's point and quadrant follow the session."""
    from .live_market import extend_all

    if market not in UNIVERSES:
        raise ValueError("ETF rotation covers US, Hong Kong and China A")
    cfg = UNIVERSES[market]
    view = view or next(iter(cfg["views"]))
    if view not in cfg["views"]:
        raise ValueError(f"Unknown view '{view}'")
    key = (market, view)
    if use_cache and not live:
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]

    bench_t, bench_name = cfg["benchmark"]
    members = cfg["views"][view]
    closes = None
    if use_cache:
        with _lock:
            hit = _closes_cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            closes = hit[1]
    if closes is None:
        closes = fetch([bench_t] + [t for t, _ in members])
        if use_cache and closes:
            with _lock:
                _closes_cache[key] = (time.time(), closes)
    if live:
        closes = extend_all(closes, live)
    if bench_t not in closes:
        raise ValueError(f"Benchmark {bench_name} unavailable")
    bench = _weekly(closes[bench_t])

    items = []
    for ticker, name in members:
        s = closes.get(ticker)
        if s is None:
            continue
        w = _weekly(s)
        if len(w) < MIN_WEEKS:
            continue
        path = rrg(w, bench)
        if path.empty:
            continue
        tail = path.tail(TAIL)
        last = tail.iloc[-1]
        items.append({
            "name": name, "code": ticker, "symbol": app_symbol(ticker, market), "category": view,
            "ratio": float(last["ratio"]), "momentum": float(last["momentum"]),
            "quadrant": quadrant(float(last["ratio"]), float(last["momentum"])),
            "return_4w": float(w.iloc[-1] / w.iloc[-5] - 1) * 100 if len(w) > 5 else None,
            "tail": [{"week": str(i.date()), "ratio": float(v["ratio"]), "momentum": float(v["momentum"])}
                     for i, v in tail.iterrows()],
        })
    order = {"leading": 0, "improving": 1, "weakening": 2, "lagging": 3}
    items.sort(key=lambda s: (order[s["quadrant"]], -s["ratio"]))
    out = {"by": "view", "group": view, "market": market,
           "benchmark": {"symbol": bench_t, "name": bench_name},
           "as_of": str(bench.index[-1].date()), "window_weeks": WINDOW, "items": items, "groups": views(market)}
    if use_cache and items and not live:
        with _lock:
            _cache[key] = (time.time(), out)
    return out
