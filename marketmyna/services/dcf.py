"""Discounted cash flow, reverse DCF and the Graham number for one stock.

DCF: free cash flow (operating cash flow minus capital expenditure and
stock-based compensation, latest annual filing) grows at the chosen rate for
5 years, fades in a straight line to the terminal rate over the next 5, then
grows at the terminal rate for ever (Gordon growth). Each year is discounted
at the chosen rate; net cash (cash, short-term and long-term investments,
minus debt) is added and the total divided by the share count.

Stock-based compensation is a real cost paid in shares instead of cash, so
it is taken off; leaving it in flatters companies that pay staff in stock.

Reverse DCF: the growth rate in years 1-5 that makes the model value equal
today's price, with the same discount and terminal rates. It answers "what
does the price assume?" rather than "what is it worth?".

Graham number: sqrt(22.5 x EPS x book value per share), Benjamin Graham's
ceiling for a defensive investor (P/E 15 x P/B 1.5).

The page lets the viewer change growth, discount and terminal rates and
recomputes the same formula in the browser (frontend/src/lib/dcf.ts).
Defaults are plain starting points, not forecasts. Banks and insurers get
no DCF (their cash flow statement mixes in lending), only the Graham number.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

HIGH_YEARS, TOTAL_YEARS = 5, 10
CACHE_SECONDS = 6 * 3600

# currency -> (discount rate, terminal growth): long-run government yield plus
# an equity risk premium, terminal growth near long-run nominal GDP growth
DEFAULTS = {"INR": (0.12, 0.05), "USD": (0.09, 0.025)}
OTHER = (0.10, 0.03)

_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_lock = threading.Lock()


def model_value(fcf: float, growth: float, discount: float, terminal: float,
                net_cash: float, shares: float) -> Optional[float]:
    """Per-share value; None when discount <= terminal (no finite answer)."""
    if discount <= terminal or shares <= 0:
        return None
    pv, cash = 0.0, fcf
    for year in range(1, TOTAL_YEARS + 1):
        if year <= HIGH_YEARS:
            g = growth
        else:  # straight-line fade from the high-growth rate to the terminal rate
            g = growth + (terminal - growth) * (year - HIGH_YEARS) / (TOTAL_YEARS - HIGH_YEARS)
        cash *= 1 + g
        pv += cash / (1 + discount) ** year
    tv = cash * (1 + terminal) / (discount - terminal)
    pv += tv / (1 + discount) ** TOTAL_YEARS
    return (pv + net_cash) / shares


def implied_growth(price: float, fcf: float, discount: float, terminal: float,
                   net_cash: float, shares: float) -> Optional[float]:
    """Years 1-5 growth that the price implies (bisection), None if outside -50%..+100%."""
    lo, hi = -0.5, 1.0

    def gap(g):
        v = model_value(fcf, g, discount, terminal, net_cash, shares)
        return None if v is None else v - price

    a, b = gap(lo), gap(hi)
    if a is None or b is None or a > 0 or b < 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if gap(mid) < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def graham_number(eps: Optional[float], bvps: Optional[float]) -> Optional[float]:
    if not eps or not bvps or eps <= 0 or bvps <= 0:
        return None
    return math.sqrt(22.5 * eps * bvps)


def _cagr(newest: Optional[float], oldest: Optional[float], years: int) -> Optional[float]:
    if not newest or not oldest or newest <= 0 or oldest <= 0 or years <= 0:
        return None
    return (newest / oldest) ** (1 / years) - 1


def _row(statement: dict, key: str) -> list[Optional[float]]:
    return next((r["values"] for r in statement.get("rows", []) if r["key"] == key), [])


def _fx(from_ccy: str, to_ccy: str) -> Optional[float]:
    """Units of to_ccy per from_ccy: Yahoo's pair, else the ECB reference
    rate (the ECB has no TWD, SAR and a few others)."""
    from ..data import ecb_fx
    from ..data.yahoo_price import info_price
    from .compare import _yahoo_info

    pair = f"{from_ccy}{to_ccy}=X"
    try:
        rate = info_price(_yahoo_info(pair))
        if rate and rate > 0:
            return float(rate)
    except Exception as exc:
        logger.info("Yahoo FX %s for DCF failed: %s", pair, exc)
    try:
        s = ecb_fx.series([pair], days=14).get(pair)
        return float(s.iloc[-1]) if s is not None and len(s) else None
    except Exception as exc:
        logger.info("FX %s for DCF failed: %s", pair, exc)
        return None


def build(symbol: str, market: str, *, financials: Optional[dict] = None, info: Optional[dict] = None,
          use_cache: bool = True) -> dict:
    from ..data.yahoo_price import info_price
    from .analysis_run import yahoo_symbol
    from .compare import _yahoo_info

    if market == "crypto":
        raise ValueError("A DCF does not apply to crypto")
    key = (symbol, market)
    if use_cache and financials is None:
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]

    if info is None:
        info = _yahoo_info(yahoo_symbol(symbol, market))
    if financials is None:
        from .financials import cached_financials

        financials = cached_financials(symbol, market, "annual")

    price = info_price(info)
    price_ccy = info.get("currency") or financials.get("currency")
    fin_ccy = financials.get("currency") or info.get("financialCurrency") or price_ccy
    rate = 1.0
    if fin_ccy and price_ccy and fin_ccy != price_ccy:
        rate = _fx(fin_ccy, price_ccy) or 0.0
    discount, terminal = DEFAULTS.get(price_ccy or "", OTHER)

    out: dict = {
        "symbol": symbol, "market": market, "name": financials.get("name") or symbol,
        "currency": price_ccy, "price": price, "periods": financials.get("periods", []),
        "dcf": None, "graham": None, "note": None,
        "source": f"Annual figures: {financials.get('source') or 'reported financial statements'}; price: market data feed",
    }

    # Graham number on Yahoo's trailing EPS and book value per share (same currency as the price
    # only when the filings are in that currency)
    if fin_ccy == price_ccy:
        eps, bvps = info.get("trailingEps"), info.get("bookValue")
        g = graham_number(eps, bvps)
        if g:
            out["graham"] = {"value": round(g, 2), "eps": eps, "book_value_per_share": bvps,
                             "vs_price_pct": round((price / g - 1) * 100, 1) if price else None}

    if financials.get("financial_sector"):
        out["note"] = "No DCF for banks and insurers: their cash flow statement mixes lending in with operations."
    else:
        ocf, capex = _row(financials["cashflow"], "operating_cf"), _row(financials["cashflow"], "capex")
        sbc = _row(financials["cashflow"], "sbc")
        sbc = sbc + [None] * (len(ocf) - len(sbc))
        # Not reported (many Indian filers): counted as zero.
        fcf_hist = [o + c - (s or 0.0) if o is not None and c is not None else None for o, c, s in zip(ocf, capex, sbc)]
        cash = next((v for v in _row(financials["balance"], "cash") if v is not None), 0.0)
        long_term = next((v for v in _row(financials["balance"], "long_term_investments") if v is not None), 0.0)
        debt = next((v for v in _row(financials["balance"], "total_debt") if v is not None), 0.0)
        shares = info.get("sharesOutstanding") or next((v for v in _row(financials["balance"], "shares") if v), None)
        recent = [v for v in fcf_hist[:3] if v is not None]
        base = fcf_hist[0] if fcf_hist and fcf_hist[0] and fcf_hist[0] > 0 else None
        base_label = "latest year"
        if base is None and recent and sum(recent) / len(recent) > 0:
            base, base_label = sum(recent) / len(recent), f"{len(recent)}-year average (latest year negative)"
        # Default growth: revenue growth over the filings shown (steadier than free
        # cash flow, which swings with capex), else free cash flow growth
        rev = [v for v in _row(financials["income"], "revenue") if v is not None]
        growth = _cagr(rev[0], rev[-1], len(rev) - 1) if len(rev) >= 3 else None
        known = [(i, v) for i, v in enumerate(fcf_hist) if v is not None]
        if growth is None and len(known) >= 3:
            growth = _cagr(known[0][1], known[-1][1], known[-1][0] - known[0][0])
        growth = min(max(growth if growth is not None else 0.06, 0.0), 0.15)

        if base is None or not shares or not price or not rate:
            out["note"] = ("No DCF: free cash flow has been negative" if base is None
                           else "No DCF: share count, price or currency conversion unavailable")
        else:
            base, net_cash = base * rate, (cash + long_term - debt) * rate
            value = model_value(base, growth, discount, terminal, net_cash, shares)
            implied = implied_growth(price, base, discount, terminal, net_cash, shares)
            out["dcf"] = {
                "base_fcf": base, "base_label": base_label, "net_cash": net_cash, "shares": shares,
                "sbc": sbc[0] * rate if sbc and sbc[0] is not None else None,
                "long_term_investments": long_term * rate,
                "fcf_history": [v * rate if v is not None else None for v in fcf_hist],
                "converted_from": fin_ccy if rate != 1.0 else None,
                "defaults": {"growth": round(growth, 4), "discount": discount, "terminal": terminal,
                             "high_years": HIGH_YEARS, "total_years": TOTAL_YEARS},
                "value": round(value, 2) if value is not None else None,
                "vs_price_pct": round((price / value - 1) * 100, 1) if value and value > 0 else None,
                "implied_growth": round(implied, 4) if implied is not None else None,
            }

    if use_cache:
        with _lock:
            _cache[key] = (time.time(), out)
    return out
