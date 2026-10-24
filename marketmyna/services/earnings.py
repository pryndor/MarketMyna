"""Earnings preview and review for one stock (the equity-research "earnings
preview" / "earnings reviewer" workflow, on free data).

Before the report:
  - next date and time, consensus EPS / revenue and how estimates moved
    (services/estimates.py)
  - beat / miss record and how the stock really moved on past report days:
    last close before the announcement to the first close after it, so a
    pre-open and an after-close report are both measured on the right day
  - the move the options market prices in (at-the-money straddle on the first
    expiry after the date), where an option chain is available
  - what to watch: the metrics that move this kind of business

After the report: actual vs estimated EPS, the surprise and the price
reaction, for the "results are out" view and message.

Every figure carries its source (Yahoo Finance; options from the exchange or
Yahoo). Nothing here is a recommendation.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from ..core.numbers import finite

logger = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600
RECENT_DAYS = 4  # a report this many days old still counts as "just out"
# An estimate or actual this many times off the company's usual quarterly EPS
# means Yahoo mixed up periods (annual vs quarterly, a split), not a real miss:
# shown, but flagged and left out of the averages.
OFF_SCALE = 2.5
CLOSE = {"india": (15, 30, "Asia/Kolkata"), "us": (16, 0, "America/New_York"),
         "hong_kong": (16, 0, "Asia/Hong_Kong"), "china_a": (15, 0, "Asia/Shanghai")}

# What moves each kind of business on results day (beyond revenue, EPS,
# margins and guidance, which matter everywhere).
WATCH = {
    "Technology": ["Revenue growth in constant currency and deal wins / bookings",
                   "Operating margin and wage or cloud-cost pressure",
                   "Full-year revenue guidance (raised, held or cut)",
                   "Headcount, attrition and utilisation (IT services)"],
    "Financial Services": ["Net interest margin (NIM)", "Asset quality: gross / net NPA and slippages",
                           "Loan and deposit growth, CASA ratio", "Credit cost and provisions",
                           "Fee income and cost-to-income ratio"],
    "Consumer Defensive": ["Volume growth (not just price-led growth)", "Rural vs urban demand",
                           "Gross margin vs input costs (palm oil, crude, milk...)", "Ad spend as a share of sales"],
    "Consumer Cyclical": ["Volumes and average selling price", "Same-store sales growth (retail)",
                          "EBITDA margin vs raw-material costs", "Inventory and dealer stock levels"],
    "Healthcare": ["US generics pricing and new launches (pharma)", "Specialty / branded mix",
                   "R&D spend as a share of sales", "Regulatory status: FDA observations or warning letters"],
    "Energy": ["Refining margins (GRM) and crude realisations", "Production volumes",
               "Marketing margins on fuel", "Capex plans and debt"],
    "Industrials": ["Order inflow and order book (book-to-bill)", "Execution: revenue from the order book",
                    "Margins on fixed-price contracts", "Working capital and receivables"],
    "Basic Materials": ["Realisation per tonne vs cost per tonne", "Sales volume and capacity use",
                        "Energy and raw-material costs", "Capex and net debt"],
    "Communication Services": ["Average revenue per user (ARPU)", "Subscriber additions and churn",
                               "Capex intensity", "Advertising revenue (media)"],
    "Utilities": ["Plant load factor / generation", "Regulated equity and tariff orders",
                  "Receivables from state utilities", "Renewable capacity additions"],
    "Real Estate": ["Pre-sales / bookings and collections", "New launches", "Net debt", "Rental income (offices, malls)"],
}
COMMON = ["Revenue vs consensus", "EPS vs consensus", "Operating / EBITDA margin vs last year",
          "Guidance or management commentary for the next quarter"]

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()

Fetch = Callable[[str], dict]


def _yahoo(yf_symbol: str) -> dict:
    """Raw inputs: earnings dates table, 2 years of daily closes, sector."""
    import yfinance as yf

    t = yf.Ticker(yf_symbol)
    out: dict = {}
    try:
        out["dates"] = t.get_earnings_dates(limit=16)
    except Exception as exc:
        logger.info("Earnings dates for %s unavailable: %s", yf_symbol, exc)
        out["dates"] = None
    try:
        hist = t.history(period="3y", interval="1d", auto_adjust=True)
        out["closes"] = hist["Close"] if not hist.empty else None
    except Exception:
        out["closes"] = None
    try:
        info = t.info or {}
        out["sector"], out["industry"] = info.get("sector"), info.get("industry")
        out["currency"] = info.get("currency")
    except Exception:
        out["sector"] = out["industry"] = out["currency"] = None
    return out


def events(dates: Optional[pd.DataFrame]) -> list[dict]:
    """Yahoo's earnings table -> [{at (UTC datetime), estimate, actual, surprise}], newest first."""
    if dates is None or dates.empty:
        return []
    out = []
    for at, row in dates.iterrows():
        ts = pd.Timestamp(at)
        ts = ts.tz_localize("America/New_York") if ts.tzinfo is None else ts
        out.append({"at": ts.tz_convert("UTC").to_pydatetime(),
                    "estimate": finite(row.get("EPS Estimate")), "actual": finite(row.get("Reported EPS")),
                    "surprise": finite(row.get("Surprise(%)"))})
    out.sort(key=lambda e: e["at"], reverse=True)
    return out


def _close_times(closes: pd.Series, market: str) -> pd.Series:
    """Daily closes re-indexed by the moment each session closed (UTC)."""
    hour, minute, tz = CLOSE.get(market, CLOSE["us"])
    days = pd.DatetimeIndex(closes.index)
    days = days.tz_localize(None) if days.tz is not None else days
    stamps = [datetime(d.year, d.month, d.day, hour, minute, tzinfo=ZoneInfo(tz)).astimezone(timezone.utc) for d in days]
    return pd.Series(closes.values, index=pd.DatetimeIndex(stamps)).dropna()


def reaction(at: datetime, closes_utc: pd.Series) -> Optional[dict]:
    """Move from the last close before the announcement to the first close after it."""
    before = closes_utc[closes_utc.index <= at]
    after = closes_utc[closes_utc.index > at]
    if before.empty or after.empty or (after.index[0] - at) > timedelta(days=6):
        return None
    return {"move": float(after.iloc[0] / before.iloc[-1] - 1) * 100,
            "from": str(before.index[-1].date()), "to": str(after.index[0].date())}


def mark_unusual(evs: list[dict]) -> None:
    """Flag events whose estimate or actual is off the scale of the others."""
    sizes = sorted(abs(e["estimate"]) for e in evs if e.get("estimate"))
    usual = sizes[len(sizes) // 2] if sizes else None
    for e in evs:
        e["unusual"] = False
        if not usual or usual < 0.05:  # tiny or loss-making EPS: ratios mean nothing
            continue
        for v in (e.get("estimate"), e.get("actual")):
            if v and (abs(v) > usual * OFF_SCALE or abs(v) < usual / OFF_SCALE):
                e["unusual"] = True


def unusual(e: dict) -> bool:
    return bool(e.get("unusual"))


def history_stats(past: list[dict]) -> Optional[dict]:
    moves = [e["reaction"]["move"] for e in past if e.get("reaction")]
    if not moves:
        return None
    beats = [e for e in past if e.get("surprise") is not None and not unusual(e)]
    on_beat = [e["reaction"]["move"] for e in beats if e["surprise"] > 0 and e.get("reaction")]
    on_miss = [e["reaction"]["move"] for e in beats if e["surprise"] < 0 and e.get("reaction")]
    avg = lambda v: sum(v) / len(v) if v else None  # noqa: E731
    return {"reports": len(moves), "avg_abs_move": avg([abs(m) for m in moves]),
            "biggest_up": max(moves), "biggest_down": min(moves), "up_days": sum(1 for m in moves if m > 0),
            "beats": sum(1 for e in beats if e["surprise"] > 0), "misses": sum(1 for e in beats if e["surprise"] < 0),
            "avg_move_on_beat": avg(on_beat), "avg_move_on_miss": avg(on_miss)}


def implied_move(symbol: str, market: str, report_day: datetime) -> Optional[dict]:
    """At-the-money straddle on the first expiry on / after the report, as a % of spot."""
    from ..trading import options

    try:
        exps = options.expiries(symbol, market)
    except Exception as exc:
        logger.info("No option expiries for %s: %s", symbol, exc)
        return None
    day = report_day.date()
    after = sorted((options._parse_expiry(e), e) for e in exps if options._parse_expiry(e) >= day)
    if not after or (after[0][0] - day).days > 35:
        return None
    try:
        ch = options.chain(symbol, market, after[0][1])
    except Exception as exc:
        logger.info("Option chain for %s unavailable: %s", symbol, exc)
        return None
    spot, rows = (ch.get("summary") or {}).get("spot") or 0, ch.get("rows") or []
    if not spot or not rows:
        return None
    atm = min(rows, key=lambda r: abs(r["strike"] - spot))

    def mid(leg: Optional[dict]) -> Optional[float]:
        if not leg:
            return None
        bid, ask = finite(leg.get("bid")), finite(leg.get("ask"))
        if bid and ask and ask >= bid:
            return (bid + ask) / 2
        return finite(leg.get("ltp"))

    call, put = mid(atm.get("call")), mid(atm.get("put"))
    if not call or not put:
        return None
    return {"move": (call + put) / spot * 100, "expiry": after[0][1], "strike": atm["strike"]}


def watch_for(sector: Optional[str]) -> list[str]:
    return COMMON + WATCH.get(sector or "", [])


def _estimates(yf_symbol: str) -> Optional[dict]:
    from . import estimates

    return estimates.build(yf_symbol)


def build(symbol: str, market: str, fetch: Fetch = _yahoo, with_options: bool = True,
          now: Optional[datetime] = None, use_cache: bool = True,
          estimates_fetch: Callable[[str], Optional[dict]] = _estimates) -> dict:
    from .analysis_run import yahoo_symbol

    key = f"{symbol}:{market}"
    if use_cache:
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    now = now or datetime.now(timezone.utc)
    raw = fetch(yahoo_symbol(symbol, market))
    evs = events(raw.get("dates"))
    mark_unusual(evs)
    closes = raw.get("closes")
    closes_utc = _close_times(closes, market) if closes is not None and len(closes) else None

    upcoming = [e for e in evs if e["actual"] is None and e["at"] > now - timedelta(days=1)]
    past = [e for e in evs if e["actual"] is not None]
    for e in past:
        e["reaction"] = reaction(e["at"], closes_utc) if closes_utc is not None else None
    nxt = upcoming[-1] if upcoming else None  # the soonest still-unreported date
    next_out = _event_out(nxt, market) if nxt else None

    latest = None
    if past and (now - past[0]["at"]).days <= RECENT_DAYS:
        latest = _event_out(past[0], market)
    estimates = None
    try:
        estimates = estimates_fetch(yahoo_symbol(symbol, market))
    except Exception as exc:
        logger.info("Estimates for %s unavailable: %s", symbol, exc)

    out = {
        "symbol": symbol, "market": market, "currency": raw.get("currency"),
        "sector": raw.get("sector"), "industry": raw.get("industry"),
        "next": next_out,
        "days_to_next": (date.fromisoformat(next_out["date"]) - now.date()).days if next_out else None,
        "implied": implied_move(symbol, market, nxt["at"]) if nxt and with_options and market in ("us", "india") else None,
        "latest": latest,
        "history": [_event_out(e, market) for e in past[:12]],
        "stats": history_stats(past[:12]),
        "consensus": _consensus(estimates),
        "watch": watch_for(raw.get("sector")),
        "available": bool(evs),
        "source": "Market data feed (earnings dates, EPS estimates and actuals, prices)",
    }
    if use_cache:
        with _lock:
            _cache[key] = (time.time(), out)
    return out


def _event_out(e: dict, market: str) -> dict:
    """`date` is the day on the exchange's own calendar (a 4 pm New York report is that day,
    even though it is already the next morning in India)."""
    tz = ZoneInfo(CLOSE.get(market, CLOSE["us"])[2])
    return {"date": e["at"].astimezone(tz).strftime("%Y-%m-%d"),
            "at": e["at"].astimezone(timezone.utc).isoformat(),
            "estimate": e.get("estimate"), "actual": e.get("actual"), "surprise": e.get("surprise"),
            "reaction": e.get("reaction"), "unusual": unusual(e)}


def _consensus(est: Optional[dict]) -> Optional[dict]:
    """The current-quarter consensus and how it moved, from services/estimates."""
    if not est or not est.get("periods"):
        return None
    q = next((p for p in est["periods"] if p["key"] == "0q"), est["periods"][0])
    return {"period": q["label"], "eps": q["eps"], "revenue": q["revenue"], "trend": q["trend"],
            "revisions": q["revisions"], "momentum": est.get("momentum")}


def results_line(symbol: str, data: dict) -> Optional[str]:
    """One message line once results are out: actual vs estimate and the move."""
    e = data.get("latest")
    if not e or e.get("actual") is None:
        return None
    parts = [f"{symbol} results: EPS {e['actual']:.2f}"]
    if e.get("estimate") is not None:
        parts.append(f"vs {e['estimate']:.2f} expected")
    if e.get("surprise") is not None:
        parts.append(f"({'beat' if e['surprise'] > 0 else 'missed' if e['surprise'] < 0 else 'in line'} by {abs(e['surprise']):.1f}%)")
    line = " ".join(parts)
    if e.get("reaction"):
        line += f"; stock {e['reaction']['move']:+.1f}% on the day"
    return line
