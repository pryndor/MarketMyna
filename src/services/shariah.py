"""Full Shariah screen for one stock: business activity + financial ratios.

Methodology (the common ground of the major Islamic index providers):

* Business screen - the core business must not be interest-based finance,
  insurance, alcohol, tobacco, pork, gambling, adult entertainment or
  weapons. Mixed businesses (hotels, media, REITs) are flagged doubtful.
* Financial screens - S&P / Dow Jones Islamic style, the basis of the
  Nifty / BSE Shariah indices that Indian "Ethical" funds track:
      interest-bearing debt          < 33% of 36-month average market cap
      cash + interest-bearing assets < 33% of 36-month average market cap
      receivables + cash             < 49% of 36-month average market cap
  AAOIFI uses a stricter 30% for the first two; a stock between 30% and
  33% passes S&P but not AAOIFI and is reported as doubtful.
* Non-permissible income - interest income must stay under 5% of revenue.
  That share of any dividend (or gain) should be given to charity
  ("purification").

Market cap falls back to total assets (MSCI / FTSE style) when Yahoo has
no price history. Everything comes from Yahoo Finance and is best-effort:
this is a screening aid, not a fatwa.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from src.data.shariah import DOUBTFUL, HALAL, HARAM, UNKNOWN, business_status, screen_row

from .financials import BALANCE_ROWS, _div, _extract, _num, _periods

logger = logging.getLogger(__name__)

LIMIT_DEBT = 33.0
LIMIT_CASH = 33.0
LIMIT_RECEIVABLES = 49.0
LIMIT_AAOIFI = 30.0
LIMIT_INTEREST_INCOME = 5.0

_INTEREST_INCOME_ROWS = [("interest_income", "Interest income", ["Interest Income Non Operating", "Interest Income"])]
_REVENUE_ROWS = [("revenue", "Total revenue", ["Total Revenue", "Operating Revenue"])]

_TTL = 6 * 3600
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_lock = threading.Lock()

VERDICT_LABELS = {
    HALAL: "Ethical",
    DOUBTFUL: "Doubtful",
    HARAM: "Not ethical",
    UNKNOWN: "Not enough data",
}


def _check(key: str, label: str, value: Optional[float], limit: float, basis: str, strict: Optional[float] = None) -> dict:
    """One ratio test. status: pass | fail | borderline (passes S&P, fails AAOIFI) | unknown."""
    if value is None:
        status = "unknown"
    elif value >= limit:
        status = "fail"
    elif strict is not None and value >= strict:
        status = "borderline"
    else:
        status = "pass"
    return {"key": key, "label": label, "value": value, "limit": limit, "strict_limit": strict, "basis": basis, "status": status}


def _avg_market_cap(ticker, info: dict) -> tuple[Optional[float], str]:
    """36-month average market cap in the reporting currency.

    Scales today's market cap by (average monthly close / last close), so
    share-class and ADR ratios stay right, then converts from the trading
    currency to the currency the statements are published in."""
    mcap = _num(info.get("marketCap"))
    if not mcap:
        return None, ""
    basis = "current market cap"
    try:
        hist = ticker.history(period="3y", interval="1mo")
        closes = hist["Close"].dropna() if hist is not None and not hist.empty else None
        if closes is not None and len(closes) >= 6 and closes.iloc[-1] > 0:
            mcap = mcap * float(closes.mean()) / float(closes.iloc[-1])
            basis = f"{len(closes)}-month average market cap"
    except Exception as exc:
        logger.info("Shariah: price history failed: %s", exc)

    trade_ccy = info.get("currency")
    fin_ccy = info.get("financialCurrency")
    if trade_ccy and fin_ccy and trade_ccy != fin_ccy:
        import yfinance as yf

        from ..data import ecb_fx

        pair = f"{trade_ccy}{fin_ccy}=X"
        try:
            fx = ecb_fx.guarded(lambda: {pair: yf.Ticker(pair).history(period="5d")["Close"].dropna()},
                                [pair], days=14)[pair]
            mcap = mcap * float(fx.iloc[-1])
            basis += f" (converted {trade_ccy}→{fin_ccy})"
        except Exception as exc:
            logger.info("Shariah: FX %s->%s failed: %s", trade_ccy, fin_ccy, exc)
            return None, ""
    return mcap, basis


def _latest(values: list[Optional[float]]) -> Optional[float]:
    return next((v for v in values if v is not None), None)


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    r = _div(a, b)
    return round(r * 100, 2) if r is not None else None


def build_shariah_profile(symbol: str, market: str) -> dict:
    key = (symbol.upper(), market)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
    data = _build(symbol, market)
    with _lock:
        _cache[key] = (time.time(), data)
    return data


def _build(symbol: str, market: str) -> dict:
    import yfinance as yf

    from .analysis_run import yahoo_symbol

    if market == "crypto":
        raise ValueError("The ethical screen does not cover crypto")

    ticker = yf.Ticker(yahoo_symbol(symbol, market))
    info: dict = {}
    try:
        info = ticker.info or {}
    except Exception as exc:
        logger.info("Shariah info for %s failed: %s", symbol, exc)
    name = info.get("longName") or info.get("shortName") or symbol
    base = {
        "symbol": symbol,
        "market": market,
        "name": name,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("financialCurrency") or info.get("currency"),
        "source": "Company financial statements (market data feed)",
    }

    # Funds: the mandate decides, not balance-sheet ratios.
    if info.get("quoteType") in ("ETF", "MUTUALFUND"):
        status, reason = screen_row({"symbol": symbol, "name": name, "market": market, "type": "etf"})
        return {
            **base,
            "kind": "fund",
            "verdict": status,
            "verdict_label": VERDICT_LABELS[status],
            "business": {"status": status, "reason": reason, "flags": []},
            "checks": [],
            "purification_pct": None,
            "reasons": [reason],
        }

    bal_df = ticker.balance_sheet
    inc_df = ticker.income_stmt
    periods = _periods(bal_df, inc_df)
    if not info.get("sector") and not info.get("marketCap") and not periods:
        # Yahoo throttles or has no coverage - fail rather than cache an empty screen.
        raise RuntimeError(f"No financial data for {symbol} right now - try again shortly")

    b_status, b_reason, flags = business_status(name, info.get("sector"), info.get("industry"), info.get("longBusinessSummary") or "")

    bal = _extract(bal_df, BALANCE_ROWS, periods) if periods else {}
    inc = _extract(inc_df, _INTEREST_INCOME_ROWS + _REVENUE_ROWS, periods) if periods else {}

    debt = _latest(bal.get("total_debt", []))
    cash = _latest(bal.get("cash", []))
    receivables = _latest(bal.get("receivables", []))
    assets = _latest(bal.get("total_assets", []))
    revenue = _latest(inc.get("revenue", []))
    interest_income = _latest(inc.get("interest_income", []))
    if debt is None and assets is not None and bal_df is not None and not bal_df.empty and "Total Debt" not in bal_df.index:
        debt = 0.0  # No debt line at all means no borrowings were reported.

    mcap, basis = _avg_market_cap(ticker, info)
    denom = mcap
    if not denom:
        denom, basis = assets, "total assets"

    recv_cash = receivables + cash if receivables is not None and cash is not None else None
    checks = [
        _check("debt", "Interest-bearing debt", _pct(debt, denom), LIMIT_DEBT, basis, LIMIT_AAOIFI),
        _check("cash", "Cash & interest-bearing securities", _pct(cash, denom), LIMIT_CASH, basis, LIMIT_AAOIFI),
        _check("receivables", "Receivables + cash", _pct(recv_cash, denom), LIMIT_RECEIVABLES, basis),
        _check("interest_income", "Interest income", _pct(interest_income, revenue), LIMIT_INTEREST_INCOME, "revenue"),
    ]
    if revenue and interest_income is None:
        # Yahoo omits the line for many companies; treat as not reported rather than failing the stock.
        checks[-1]["note"] = "Not reported separately - read the annual report's 'other income' note"

    reasons: list[str] = []
    if b_status == HARAM:
        verdict = HARAM
        reasons.append(b_reason)
    else:
        failed = [c for c in checks if c["status"] == "fail"]
        borderline = [c for c in checks if c["status"] == "borderline"]
        missing = [c for c in checks[:2] if c["status"] == "unknown"]
        for c in failed:
            reasons.append(f"{c['label']} is {c['value']:.1f}% of {c['basis']} (limit {c['limit']:.0f}%)")
        for c in borderline:
            reasons.append(f"{c['label']} is {c['value']:.1f}% - within the standard {c['limit']:.0f}% limit but above the stricter {c['strict_limit']:.0f}%")
        if b_status in (DOUBTFUL, UNKNOWN):
            reasons.append(b_reason)
        if missing:
            reasons.append("Missing balance-sheet data: " + ", ".join(c["label"].lower() for c in missing))
        if failed:
            verdict = HARAM
        elif borderline or b_status == DOUBTFUL:
            verdict = DOUBTFUL
        elif missing or b_status == UNKNOWN:
            verdict = UNKNOWN if len(missing) == 2 else DOUBTFUL
        else:
            verdict = HALAL
            reasons.append(b_reason)
            reasons.append("Debt, cash and receivables are all within the standard and the stricter limits")

    # Purification only applies to a stock one may hold.
    purification = _pct(interest_income, revenue) if verdict != HARAM else None
    return {
        **base,
        "kind": "stock",
        "verdict": verdict,
        "verdict_label": VERDICT_LABELS[verdict],
        "business": {"status": b_status, "reason": b_reason, "flags": flags},
        "checks": checks,
        "market_cap_basis": basis or None,
        "period": str(periods[0])[:10] if periods else None,
        "purification_pct": purification,
        "reasons": reasons,
    }
