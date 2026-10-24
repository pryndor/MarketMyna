"""Side-by-side comparison of 2-5 instruments, and automatic peer discovery.

Mirrors OpenBB's equity "compare" / "peers" commands with free data: prices
from Yahoo (adjusted, so dividends are included), fundamentals from Yahoo's
quote summary, peers from our own listings (same market and sector, nearest in
size) confirmed against Yahoo's finer "industry" label.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from marketmyna.core.home import app_home

from ..core.numbers import finite as _f
from ..data.yahoo_price import info_price

logger = logging.getLogger(__name__)

MAX_SYMBOLS = 5
PERIODS = {"6mo": 182, "1y": 365, "3y": 1095, "5y": 1826}
RETURN_WINDOWS = [("1M", 30), ("3M", 91), ("6M", 182), ("1Y", 365), ("3Y", 1095), ("5Y", 1826)]
INFO_TTL = 6 * 3600

# label, yahoo key, kind, higher is better (None = no ranking), group
METRICS = [
    ("Market cap", "marketCap", "money", None, "Size & valuation"),
    ("P/E (trailing)", "trailingPE", "ratio", False, "Size & valuation"),
    ("P/E (forward)", "forwardPE", "ratio", False, "Size & valuation"),
    ("PEG", "pegRatio", "ratio", False, "Size & valuation"),
    ("Price / book", "priceToBook", "ratio", False, "Size & valuation"),
    ("Price / sales", "priceToSalesTrailing12Months", "ratio", False, "Size & valuation"),
    ("EV / EBITDA", "enterpriseToEbitda", "ratio", False, "Size & valuation"),
    ("Revenue growth", "revenueGrowth", "pct", True, "Growth & profitability"),
    ("Earnings growth", "earningsGrowth", "pct", True, "Growth & profitability"),
    ("Gross margin", "grossMargins", "pct", True, "Growth & profitability"),
    ("Operating margin", "operatingMargins", "pct", True, "Growth & profitability"),
    ("Profit margin", "profitMargins", "pct", True, "Growth & profitability"),
    ("Return on equity", "returnOnEquity", "pct", True, "Growth & profitability"),
    ("Return on assets", "returnOnAssets", "pct", True, "Growth & profitability"),
    ("Debt / equity", "debtToEquity", "ratio", False, "Balance sheet & income"),
    ("Current ratio", "currentRatio", "ratio", True, "Balance sheet & income"),
    ("Free cash flow", "freeCashflow", "money", True, "Balance sheet & income"),
    ("Dividend yield", "dividendYield", "pct_raw", True, "Balance sheet & income"),
    ("Payout ratio", "payoutRatio", "pct", None, "Balance sheet & income"),
    ("Analyst target upside", None, "pct_raw", True, "Analysts"),
    ("Analyst rating (1 buy - 5 sell)", "recommendationMean", "ratio", False, "Analysts"),
    ("Analysts", "numberOfAnalystOpinions", "count", None, "Analysts"),
]

InfoFetch = Callable[[str], dict]
PriceFetch = Callable[[list[str], str], dict[str, pd.Series]]

_info_cache: dict[str, tuple[float, dict]] = {}
_info_lock = threading.Lock()


def _info_file(yf_symbol: str) -> Path:
    base = Path(os.environ.get("YAHOO_INFO_CACHE_DIR") or app_home() / "cache" / "yahoo_info")
    return base / (hashlib.sha256(yf_symbol.encode()).hexdigest()[:24] + ".json")


def _disk_info(yf_symbol: str) -> Optional[tuple[float, dict]]:
    """The saved copy, so an API restart or deploy doesn't make every screen
    and Compare page fetch ~100 stocks from Yahoo again."""
    try:
        saved = json.loads(_info_file(yf_symbol).read_text(encoding="utf-8"))
        return float(saved["at"]), saved["info"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_info(yf_symbol: str, at: float, info: dict) -> None:
    path = _info_file(yf_symbol)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": at, "info": info}, default=str), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.debug("Could not save Yahoo info for %s: %s", yf_symbol, exc)


def _yahoo_info(yf_symbol: str) -> dict:
    with _info_lock:
        hit = _info_cache.get(yf_symbol)
    if not hit:
        hit = _disk_info(yf_symbol)
        if hit:
            with _info_lock:
                _info_cache[yf_symbol] = hit
    if hit and time.time() - hit[0] < INFO_TTL:
        return hit[1]
    import yfinance as yf

    try:
        info = yf.Ticker(yf_symbol).info or {}
    except Exception as exc:
        logger.info("Yahoo info %s failed: %s", yf_symbol, exc)
        info = {}
    if info:  # never cache a failed lookup; Yahoo throttles in bursts and the next call usually works
        now = time.time()
        with _info_lock:
            _info_cache[yf_symbol] = (now, info)
        _save_info(yf_symbol, now, info)
    return info


def _yahoo_prices(tickers: list[str], period: str) -> dict[str, pd.Series]:
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    with YF_DOWNLOAD_LOCK:
        df = yf.download(tickers, period=period, interval="1d", progress=False, auto_adjust=True, threads=True)
    if df is None or df.empty:
        return {}
    closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": tickers[0]})
    return {t: closes[t].dropna() for t in tickers if t in closes and closes[t].notna().sum()}


def _naive(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return pd.Series(s.to_numpy(dtype=float), index=idx.normalize())


def _ret(s: pd.Series, days: int) -> Optional[float]:
    if s.empty or (s.index[-1] - s.index[0]).days < days * 0.97:
        return None
    past = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
    return float(s.iloc[-1] / past.iloc[-1] - 1) * 100 if len(past) else None


def _metric_value(info: dict, key: Optional[str], kind: str, label: str) -> Optional[float]:
    if label == "Analyst target upside":
        target, price = _f(info.get("targetMeanPrice")), info_price(info)
        return (target / price - 1) * 100 if target and price else None
    v = _f(info.get(key)) if key else None
    if v is None:
        return None
    if key in ("grossMargins", "operatingMargins") and v == 0:
        return None  # Yahoo reports 0 for banks and insurers, where margins do not apply
    if kind == "pct":
        return v * 100
    if key == "debtToEquity":
        return v / 100  # Yahoo reports D/E in percent
    return v


def compare(items: list[tuple[str, str]], period: str = "1y",
            info_fetch: InfoFetch = _yahoo_info, price_fetch: PriceFetch = _yahoo_prices) -> dict:
    """items: [(symbol, market)]. Raises ValueError on bad input."""
    from .analysis_run import MARKET_INDICES, yahoo_symbol

    items = list(dict.fromkeys((s.strip().upper(), m.strip().lower()) for s, m in items if s.strip()))
    if not 2 <= len(items) <= MAX_SYMBOLS:
        raise ValueError(f"Pick between 2 and {MAX_SYMBOLS} symbols")
    if period not in PERIODS:
        raise ValueError(f"period must be one of {', '.join(PERIODS)}")

    ticker = {(s, m): yahoo_symbol(s, m) for s, m in items}
    bench = {m: (MARKET_INDICES.get(m) or MARKET_INDICES["us"])[0] for _, m in items}
    fetch_period = "5y" if period in ("3y", "5y") else "2y"  # extra history so 1Y/3Y returns resolve
    with ThreadPoolExecutor(max_workers=6) as pool:
        infos_f = {k: pool.submit(info_fetch, t) for k, t in ticker.items() if k[1] != "crypto"}
        prices = price_fetch(list(dict.fromkeys([*ticker.values(), *(b[0] for b in bench.values())])), fetch_period)
        infos = {k: f.result() for k, f in infos_f.items()}

    out_items, series, warnings = [], {}, []
    for key in items:
        s, m = key
        info = infos.get(key, {})
        raw = prices.get(ticker[key])
        if raw is None or len(raw) < 20:
            warnings.append(f"{s}: no price history, left out of the chart and risk numbers.")
        else:
            series[key] = _naive(raw)
        out_items.append({
            "symbol": s, "market": m, "yahoo": ticker[key],
            "name": info.get("shortName") or info.get("longName") or s,
            "currency": info.get("currency") or ("USD" if m == "crypto" else None),
            "sector": info.get("sector"), "industry": info.get("industry"),
            "price": info_price(info) or (float(series[key].iloc[-1]) if key in series else None),
        })
    currencies = {i["currency"] for i in out_items if i["currency"]}
    if len(currencies) > 1:
        warnings.append("Different currencies: returns are compared in each stock's own currency.")

    start = pd.Timestamp.today().normalize() - pd.Timedelta(days=PERIODS[period])
    chart: dict[str, dict[str, float]] = {}
    risk, daily = {}, {}
    for key, s in series.items():
        label = key[0]
        win = s[s.index >= start]
        if len(win) < 2:
            continue
        for d, v in (win / win.iloc[0] * 100).items():
            chart.setdefault(str(d.date()), {})[label] = round(float(v), 3)
        r = win.pct_change().dropna()
        daily[label] = r
        curve = (1 + r).cumprod()
        b = prices.get(bench[key[1]][0])
        beta = None
        if b is not None and len(r) > 30:
            br = _naive(b).pct_change().dropna()
            j = pd.concat([r, br], axis=1, join="inner").dropna()
            if len(j) > 30 and j.iloc[:, 1].var() > 0:
                beta = float(j.iloc[:, 0].cov(j.iloc[:, 1]) / j.iloc[:, 1].var())
        days_per_year = 365 if key[1] == "crypto" else 252
        vol = float(r.std() * math.sqrt(days_per_year))
        years = max((win.index[-1] - win.index[0]).days / 365.25, 1e-9)
        cagr = float((win.iloc[-1] / win.iloc[0]) ** (1 / years) - 1)
        risk[label] = {
            "volatility": vol * 100,
            "max_drawdown": float((curve / curve.cummax() - 1).min()) * 100,
            "beta": beta, "benchmark": bench[key[1]][1],
            "return_period": float(win.iloc[-1] / win.iloc[0] - 1) * 100,
            "sharpe_like": cagr / vol if vol else None,
        }

    returns = [{"window": w, "values": {k[0]: _ret(s, d) for k, s in series.items()}} for w, d in RETURN_WINDOWS]
    returns = [r for r in returns if any(v is not None for v in r["values"].values())]

    corr = None
    if len(daily) >= 2:
        c = pd.DataFrame(daily).dropna().corr()
        corr = {"symbols": list(c.columns), "matrix": [[_f(v) for v in row] for row in c.to_numpy()]}

    metrics = []
    for label, key, kind, higher, group in METRICS:
        vals = {i["symbol"]: _metric_value(infos.get((i["symbol"], i["market"]), {}), key, kind, label) for i in out_items}
        if all(v is None for v in vals.values()):
            continue
        best = None
        ranked = {k: v for k, v in vals.items() if v is not None and not (label.startswith("P/") and v <= 0)}
        if kind == "money" and len(currencies) > 1:
            ranked = {}  # amounts in different currencies are not comparable
        if higher is not None and len(ranked) >= 2:
            best = (max if higher else min)(ranked, key=ranked.get)
        metrics.append({"label": label, "kind": "pct" if kind == "pct_raw" else kind, "group": group,
                        "values": vals, "best": best, "higher_better": higher})

    return {
        "period": period,
        "items": out_items,
        "chart": [{"time": d, **v} for d, v in sorted(chart.items())],
        "returns": returns,
        "risk": risk,
        "correlation": corr,
        "metrics": metrics,
        "warnings": warnings,
    }


def peers(symbol: str, market: str, limit: int = 6, info_fetch: InfoFetch = _yahoo_info,
          rows: Optional[list[dict]] = None) -> dict:
    """Same-market stocks in the same sector, nearest in market cap, preferring Yahoo's same industry."""
    from .analysis_run import yahoo_symbol

    symbol, market = symbol.upper(), market.lower()
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows(market)
    stocks = [r for r in rows if r.get("type") == "stock" and r.get("market_cap")]
    me = next((r for r in stocks if r["symbol"].upper() == symbol), None)
    my_info = info_fetch(yahoo_symbol(symbol, market))
    industry, sector = my_info.get("industry"), my_info.get("sector")
    cap = (me or {}).get("market_cap") or _f(my_info.get("marketCap"))
    group_key = "category" if me and me.get("category") else "sector"
    group_val = (me or {}).get(group_key)
    if not cap or not group_val:
        return {"symbol": symbol, "market": market, "peers": [], "basis": None,
                "note": "Not enough sector or size data to find peers."}

    pool_rows = [r for r in stocks if r.get(group_key) == group_val and r["symbol"].upper() != symbol]
    pool_rows.sort(key=lambda r: abs(math.log(r["market_cap"] / cap)))
    candidates = pool_rows[:24]
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(lambda r: info_fetch(yahoo_symbol(r["symbol"], market)), candidates))
    same_ind = [(r, i) for r, i in zip(candidates, infos) if industry and i.get("industry") == industry]
    if len(same_ind) >= 3:
        chosen, basis = same_ind[:limit], f"Same industry: {industry}"
    else:
        same_sec = [(r, i) for r, i in zip(candidates, infos) if sector and i.get("sector") == sector]
        chosen = (same_ind + [x for x in same_sec if x not in same_ind])[:limit] or list(zip(candidates, infos))[:limit]
        basis = f"Same sector: {sector or group_val}, closest in size"
    return {
        "symbol": symbol, "market": market, "industry": industry, "sector": sector, "basis": basis,
        "peers": [{"symbol": r["symbol"], "name": r.get("name"), "market_cap": r["market_cap"],
                   "industry": i.get("industry"), "price": r.get("price"),
                   "change_percent": r.get("change_percent"),
                   "pe": _f(i.get("trailingPE")), "currency": r.get("currency")} for r, i in chosen],
    }
