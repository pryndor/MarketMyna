"""Analyst estimates and how they are moving (OpenBB equity.estimates).

From Yahoo: consensus EPS and revenue for the current / next quarter and year,
the EPS consensus 7-90 days ago (so you see revisions), the count of analysts
revising up vs down, and the last four quarters of actual vs estimated EPS.
Rising estimates often lead a stock; repeated beats show a company that guides
conservatively.
"""

from __future__ import annotations

from typing import Callable, Optional

import pandas as pd

from ..core.numbers import finite as _f

PERIOD_LABELS = {"0q": "Current quarter", "+1q": "Next quarter", "0y": "Current year", "+1y": "Next year"}
TABLES = ("earnings_estimate", "revenue_estimate", "eps_trend", "eps_revisions", "earnings_history")

TickerFetch = Callable[[str], dict]


def _yahoo(yf_symbol: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(yf_symbol)
    out = {}
    for name in TABLES:
        try:
            df = getattr(t, name)
            out[name] = df if isinstance(df, pd.DataFrame) else None
        except Exception:
            out[name] = None
    try:
        info = t.info or {}
        out["currency"] = info.get("financialCurrency") or info.get("currency")
    except Exception:
        out["currency"] = None
    return out


def _row(df: Optional[pd.DataFrame], period: str) -> dict:
    if df is None or df.empty or period not in df.index:
        return {}
    return {k: _f(v) for k, v in df.loc[period].items()}


def _chg(now: Optional[float], then: Optional[float]) -> Optional[float]:
    return (now / then - 1) * 100 if now is not None and then not in (None, 0) else None


def build(yf_symbol: str, fetch: TickerFetch = _yahoo) -> dict:
    raw = fetch(yf_symbol)
    eps_df, rev_df = raw.get("earnings_estimate"), raw.get("revenue_estimate")
    trend_df, rev_cnt_df = raw.get("eps_trend"), raw.get("eps_revisions")

    periods = []
    for key, label in PERIOD_LABELS.items():
        e, r, tr, rv = _row(eps_df, key), _row(rev_df, key), _row(trend_df, key), _row(rev_cnt_df, key)
        if not (e or r):
            continue
        cur = tr.get("current", e.get("avg"))
        periods.append({
            "key": key, "label": label,
            "eps": {"avg": e.get("avg"), "low": e.get("low"), "high": e.get("high"),
                    "year_ago": e.get("yearAgoEps"), "growth": _pct(e.get("growth")),
                    "analysts": e.get("numberOfAnalysts")},
            "revenue": {"avg": r.get("avg"), "low": r.get("low"), "high": r.get("high"),
                        "year_ago": r.get("yearAgoRevenue"), "growth": _pct(r.get("growth")),
                        "analysts": r.get("numberOfAnalysts")},
            "trend": {"current": cur, "d7": tr.get("7daysAgo"), "d30": tr.get("30daysAgo"),
                      "d60": tr.get("60daysAgo"), "d90": tr.get("90daysAgo"),
                      "change_30d": _chg(cur, tr.get("30daysAgo")), "change_90d": _chg(cur, tr.get("90daysAgo"))},
            "revisions": {"up_7d": rv.get("upLast7days"), "up_30d": rv.get("upLast30days"),
                          "down_7d": rv.get("downLast7Days"), "down_30d": rv.get("downLast30days")},
        })

    history = []
    hist_df = raw.get("earnings_history")
    if hist_df is not None and not hist_df.empty:
        for q, row in hist_df.iterrows():
            actual, est = _f(row.get("epsActual")), _f(row.get("epsEstimate"))
            if actual is None and est is None:
                continue
            history.append({"quarter": str(pd.Timestamp(q).date()) if not isinstance(q, str) else q,
                             "actual": actual, "estimate": est,
                             "surprise": _pct(_f(row.get("surprisePercent")))})

    # Revision momentum on the yearly EPS consensus over 90 days
    yearly = [p["trend"]["change_90d"] for p in periods if p["key"] in ("0y", "+1y") and p["trend"]["change_90d"] is not None]
    momentum = None
    if yearly:
        avg = sum(yearly) / len(yearly)
        momentum = {"change_90d": avg,
                    "label": "rising" if avg >= 1 else "falling" if avg <= -1 else "steady"}
    beats = [h for h in history if h["surprise"] is not None]
    return {
        "currency": raw.get("currency"),
        "periods": periods,
        "history": history,
        "momentum": momentum,
        "beats": {"beat": sum(1 for h in beats if h["surprise"] > 0), "total": len(beats)} if beats else None,
        "available": bool(periods or history),
    }


def _pct(v: Optional[float]) -> Optional[float]:
    return v * 100 if v is not None else None
