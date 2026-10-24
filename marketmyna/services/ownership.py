"""Who owns a stock and who is trading it: insider / institution split, top
holders, recent insider buys and sells, and short interest (US).

Source: Yahoo (via yfinance), which mirrors SEC Form 4 / 13F / FINRA short
interest for US listings and exchange disclosures, more sparsely, elsewhere.
Covers OpenBB's equity.ownership and equity.shorts endpoints (Apache 2.0).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import date, datetime, timedelta
from typing import Optional

import pandas as pd

from ..core.numbers import finite as _f

logger = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600
INSIDER_DAYS = 180

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _day(v) -> Optional[str]:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v).date().isoformat()
    try:
        return pd.Timestamp(v).date().isoformat()
    except (ValueError, TypeError):
        return None


def classify(text: str, transaction: str = "") -> str:
    """buy | sell | other, from Yahoo's free-text insider row."""
    t = f"{transaction} {text}".lower()
    if "sale" in t or "sell" in t or "sold" in t:
        return "sell"
    if "purchase" in t or "buy" in t or "bought" in t:
        return "buy"
    return "other"


def _holders(df) -> list[dict]:
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for _, r in df.head(10).iterrows():
        out.append({"holder": str(r.get("Holder")), "pct_held": _f(r.get("pctHeld")), "shares": _f(r.get("Shares")),
                    "value": _f(r.get("Value")), "pct_change": _f(r.get("pctChange")), "reported": _day(r.get("Date Reported"))})
    return out


def insider_activity(df, today: Optional[date] = None, days: int = INSIDER_DAYS) -> dict:
    today = today or date.today()
    since = today - timedelta(days=days)
    rows = []
    if df is not None and not getattr(df, "empty", True):
        for _, r in df.iterrows():
            when = _day(r.get("Start Date"))
            if not when or date.fromisoformat(when) < since:
                continue
            rows.append({"date": when, "insider": str(r.get("Insider") or ""), "position": str(r.get("Position") or ""),
                         "side": classify(str(r.get("Text") or ""), str(r.get("Transaction") or "")),
                         "shares": _f(r.get("Shares")), "value": _f(r.get("Value")), "text": str(r.get("Text") or "")})
    rows.sort(key=lambda x: x["date"], reverse=True)
    total = lambda side, k: sum((x[k] or 0) for x in rows if x["side"] == side)  # noqa: E731
    buys, sells = sum(x["side"] == "buy" for x in rows), sum(x["side"] == "sell" for x in rows)
    bias = None
    if buys or sells:
        bias = "net buying" if total("buy", "value") > total("sell", "value") else "net selling"
    return {"days": days, "buys": buys, "sells": sells, "buy_value": total("buy", "value"),
            "sell_value": total("sell", "value"), "bias": bias, "recent": rows[:12]}


def short_interest(info: dict) -> Optional[dict]:
    shares = _f(info.get("sharesShort"))
    if shares is None:
        return None
    prior = _f(info.get("sharesShortPriorMonth"))
    return {"shares": shares, "prior_month": prior,
            "change_pct": (shares / prior - 1) * 100 if prior else None,
            "pct_of_float": (_f(info.get("shortPercentOfFloat")) or 0) * 100 or None,
            "days_to_cover": _f(info.get("shortRatio")), "as_of": _day(info.get("dateShortInterest"))}


def _deals(symbol: str) -> Optional[dict]:
    """NSE bulk / block deals in the stock over the last 90 days."""
    try:
        from ..data.nse_deals import recent

        return recent(90, symbol)
    except Exception as exc:
        logger.info("NSE deals for %s unavailable: %s", symbol, exc)
        return None


def build(symbol: str, market: str, ticker=None) -> dict:
    from .analysis_run import yahoo_symbol

    yf_symbol = yahoo_symbol(symbol, market)
    live = ticker is None
    if live:
        with _lock:
            hit = _cache.get(yf_symbol)
            if hit and time.time() - hit[0] < CACHE_SECONDS:
                return hit[1]
        import yfinance as yf

        ticker = yf.Ticker(yf_symbol)

    def safe(attr):
        try:
            return getattr(ticker, attr)
        except Exception as exc:
            logger.info("%s %s unavailable: %s", yf_symbol, attr, exc)
            return None

    info = safe("info") or {}
    out = {
        "symbol": symbol, "market": market,
        "breakdown": {"insiders_pct": (_f(info.get("heldPercentInsiders")) or 0) * 100 or None,
                      "institutions_pct": (_f(info.get("heldPercentInstitutions")) or 0) * 100 or None,
                      "float_shares": _f(info.get("floatShares")),
                      "shares_outstanding": _f(info.get("sharesOutstanding"))},
        "institutions": _holders(safe("institutional_holders")),
        "funds": _holders(safe("mutualfund_holders")),
        "insiders": insider_activity(safe("insider_transactions")),
        "short": short_interest(info),
        "deals": _deals(symbol) if market == "india" else None,
    }
    if live:
        with _lock:
            _cache[yf_symbol] = (time.time(), out)
    return out
