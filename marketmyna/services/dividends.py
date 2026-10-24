"""Dividend history (OpenBB equity.fundamental.dividends / trailing_dividend_yield).

Computed from the per-payment history Yahoo publishes (split-adjusted), not
its summary fields, which are often stale for Indian stocks: trailing-12-month
payout and yield, yearly totals, 5-year growth, the run of years without a
cut, and how often it pays.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

import pandas as pd

from ..core.numbers import finite as _f
from ..data.yahoo_price import fresh_price, info_price

Fetch = Callable[[str], dict]


def _yahoo(yf_symbol: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(yf_symbol)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    return {"dividends": t.dividends, "info": info, "price": fresh_price(info, t)}


def build(yf_symbol: str, fetch: Fetch = _yahoo, today: Optional[pd.Timestamp] = None) -> dict:
    raw = fetch(yf_symbol)
    s: pd.Series = raw.get("dividends")
    info = raw.get("info") or {}
    price = _f(raw.get("price")) if "price" in raw else info_price(info)
    if s is None or len(s) == 0:
        return {"pays": False, "currency": info.get("currency")}
    idx = pd.DatetimeIndex(s.index)
    s = pd.Series(s.to_numpy(dtype=float), index=idx.tz_localize(None) if idx.tz is not None else idx).sort_index()
    s = s[s > 0]
    if s.empty:
        return {"pays": False, "currency": info.get("currency")}
    today = (today or pd.Timestamp.today()).normalize()

    ttm = float(s[s.index > today - pd.Timedelta(days=365)].sum())
    yearly = s.groupby(s.index.year).sum()
    complete = yearly[yearly.index < today.year]
    if len(complete):  # years with no payment at all count as zero (a cut), not as missing
        complete = complete.reindex(range(int(complete.index.min()), today.year), fill_value=0.0)
    years = [{"year": int(y), "total": float(v), "partial": False} for y, v in complete.items() if v > 0]
    if today.year in yearly.index:
        years.append({"year": today.year, "total": float(yearly[today.year]), "partial": True})

    cagr = None
    if len(complete) >= 6 and complete.iloc[-6] > 0:
        cagr = float(((complete.iloc[-1] / complete.iloc[-6]) ** (1 / 5) - 1) * 100)

    # consecutive complete years without a cut, counting back from the latest
    streak = 0
    vals = complete.to_numpy()
    for i in range(len(vals) - 1, 0, -1):
        if vals[i - 1] > 0 and vals[i] >= vals[i - 1] * 0.995:
            streak += 1
        else:
            break

    per_year = int((s.index > today - pd.Timedelta(days=365)).sum())
    freq = {0: None, 1: "Yearly", 2: "Twice a year", 3: "Three times a year", 4: "Quarterly"}.get(per_year, "Monthly" if per_year >= 10 else f"{per_year} times a year")

    next_ex = None
    if ts := _f(info.get("exDividendDate")):
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        if pd.Timestamp(d) >= today:
            next_ex = d.isoformat()

    return {
        "pays": True,
        "currency": info.get("currency"),
        "ttm": ttm,
        "ttm_yield": ttm / price * 100 if price and ttm else None,
        "forward_rate": _f(info.get("dividendRate")),
        "forward_yield": _f(info.get("dividendRate")) / price * 100 if price and _f(info.get("dividendRate")) else None,
        "five_year_avg_yield": _f(info.get("fiveYearAvgDividendYield")),
        "payout_ratio": _f(info.get("payoutRatio")) * 100 if _f(info.get("payoutRatio")) is not None else None,
        "growth_5y": cagr,
        "years_without_cut": streak,
        "frequency": freq,
        "last": {"date": str(s.index[-1].date()), "amount": float(s.iloc[-1])},
        "next_ex_date": next_ex,
        "years": years[-12:],
        "payments": [{"date": str(d.date()), "amount": float(v)} for d, v in s.iloc[-16:].items()][::-1],
        "first_year": int(s.index[0].year),
    }
