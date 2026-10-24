"""SIP backtest on a fund's real NAV history, plus a step-up projection.

Answers three questions for one scheme: what would a monthly SIP over the last
N years be worth today, would a lumpsum of the same total have done better, and
does the SIP day of the month matter. Pure functions over a NAV series so they
test offline; the step-up maths reuses SIPOptimizer (src/analysis/sip_optimizer.py).
"""

from __future__ import annotations

from datetime import date

import pandas as pd

SIP_DAYS = (1, 5, 10, 15, 20, 25)


def xirr(flows: list[tuple[date, float]]) -> float | None:
    """Annualised internal rate of return for dated cash flows (bisection)."""
    if len(flows) < 2 or not any(v > 0 for _, v in flows) or not any(v < 0 for _, v in flows):
        return None
    t0 = flows[0][0]

    def npv(rate: float) -> float:
        return sum(v / (1 + rate) ** ((d - t0).days / 365.0) for d, v in flows)

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _buy_dates(nav: pd.Series, start: pd.Timestamp, day: int) -> list[pd.Timestamp]:
    """First NAV date on or after `day` of each month from `start` (next trading day)."""
    out: list[pd.Timestamp] = []
    month = pd.Timestamp(start.year, start.month, 1)
    end = nav.index[-1]
    while month <= end:
        target = month + pd.Timedelta(days=day - 1)
        pos = nav.index.searchsorted(target)
        if pos < len(nav) and nav.index[pos] >= start and (nav.index[pos].year, nav.index[pos].month) == (target.year, target.month):
            out.append(nav.index[pos])
        month += pd.offsets.MonthBegin(1)
    return out


def simulate(nav: pd.Series, monthly: float, start: pd.Timestamp, day: int) -> dict | None:
    """Monthly SIP of `monthly` from `start` on `day`, valued at the last NAV."""
    dates = _buy_dates(nav, start, day)
    if len(dates) < 2:
        return None
    units = sum(monthly / float(nav[d]) for d in dates)
    invested = monthly * len(dates)
    last_date, last_nav = nav.index[-1], float(nav.iloc[-1])
    value = units * last_nav
    flows = [(d.date(), -monthly) for d in dates] + [(last_date.date(), value)]
    return {
        "day": day,
        "installments": len(dates),
        "invested": invested,
        "units": units,
        "avg_cost": invested / units,
        "value": value,
        "gain_pct": (value / invested - 1) * 100,
        "xirr_pct": _pct(xirr(flows)),
    }


def backtest(nav: pd.Series, monthly: float, years: int, day: int) -> dict:
    """SIP vs lumpsum vs SIP day, over the last `years` of NAV history."""
    nav = nav.dropna().sort_index()
    if len(nav) < 30:
        return {"error": "Not enough NAV history"}
    end = nav.index[-1]
    start = max(end - pd.DateOffset(years=years), nav.index[0])
    note = None
    if start > end - pd.DateOffset(years=years) + pd.Timedelta(days=31):
        note = f"Fund history starts {nav.index[0].date()}, so the backtest is shorter than {years} years."

    sip = simulate(nav, monthly, start, day)
    if sip is None:
        return {"error": "Not enough NAV history"}

    first = _buy_dates(nav, start, day)[0]
    lump_nav = float(nav[first])
    lump_value = sip["invested"] / lump_nav * float(nav.iloc[-1])
    span = (end - first).days / 365.0
    lump = {
        "date": str(first.date()),
        "invested": sip["invested"],
        "value": lump_value,
        "gain_pct": (lump_value / sip["invested"] - 1) * 100,
        "cagr_pct": ((lump_value / sip["invested"]) ** (1 / span) - 1) * 100 if span > 0 else None,
    }

    # Rank days by XIRR, not end value: a later day can buy one instalment fewer
    by_day = [r for d in SIP_DAYS if (r := simulate(nav, monthly, start, d))]
    ranked = [r for r in by_day if r["xirr_pct"] is not None]
    spread = None
    if ranked:
        best = max(ranked, key=lambda r: r["xirr_pct"])
        worst = min(ranked, key=lambda r: r["xirr_pct"])
        spread = {"best_day": best["day"], "worst_day": worst["day"],
                  "diff_pts": best["xirr_pct"] - worst["xirr_pct"]}

    return {
        "start": str(start.date()),
        "end": str(end.date()),
        "monthly": monthly,
        "sip": sip,
        "lumpsum": lump,
        "winner": "sip" if sip["value"] >= lump_value else "lumpsum",
        "by_day": by_day,
        "day_spread": spread,
        "note": note,
    }


def step_up(monthly: float, step_pct: float, years: int, expected_pct: float) -> dict:
    """Projected corpus for a SIP that rises `step_pct` each year, vs a flat SIP."""
    from src.analysis.sip_optimizer import SIPOptimizer

    opt = SIPOptimizer(data_fetcher=object())  # projections need no data
    stepped = opt.calculate_step_up_sip(monthly, step_pct, years, expected_pct)
    flat = opt.calculate_step_up_sip(monthly, 0, years, expected_pct)
    return {
        "monthly": monthly,
        "step_pct": step_pct,
        "years": years,
        "expected_pct": expected_pct,
        "invested": stepped.total_invested,
        "corpus": stepped.projected_corpus,
        "flat_invested": flat.total_invested,
        "flat_corpus": flat.projected_corpus,
        "yearly": [{"year": y["year"], "monthly_sip": y["monthly_sip"], "corpus": y["year_end_corpus"],
                    "flat_corpus": f["year_end_corpus"]}
                   for y, f in zip(stepped.yearly_breakdown, flat.yearly_breakdown)],
    }


def _pct(v: float | None) -> float | None:
    return None if v is None else v * 100
