"""Ethical screen for one stock: what the business does, plus the debt,
cash and interest-income numbers.

Owner's rule: no verdict. We never call a stock halal / haram / compliant
or pass / fail. The business gets a factual tag (see src/data/shariah.py)
and each ratio is shown with the reference levels index providers use, so
the investor can decide:
      interest-bearing debt          vs 33% (stricter 30%) of average market cap
      cash + interest-bearing assets vs 33% (stricter 30%) of average market cap
      receivables + cash             vs 49% of average market cap
      interest income                vs 5% of revenue

Market cap falls back to total assets when there is no price history.
Best-effort data from company statements.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from marketmyna.data.shariah import (
    ETHICAL,
    EXCLUDED,
    INTEREST,
    MIXED,
    UNKNOWN,
    business_status,
    screen_row,
)

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

TAG_LABELS = {
    ETHICAL: "Ethical business",
    INTEREST: "Interest-based business",
    MIXED: "Mixed activity",
    EXCLUDED: "Excluded activity",
    UNKNOWN: "Not classified",
}


def _check(key: str, label: str, value: Optional[float], limit: float, basis: str, strict: Optional[float] = None) -> dict:
    """One ratio with its reference levels - a number, never a pass / fail."""
    return {"key": key, "label": label, "value": value, "reference": limit, "strict_reference": strict, "basis": basis}


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
        logger.info("Ethical screen: price history failed: %s", exc)

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
            logger.info("Ethical screen: FX %s->%s failed: %s", trade_ccy, fin_ccy, exc)
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
        logger.info("Ethical screen info for %s failed: %s", symbol, exc)
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
            "business": {"status": status, "label": TAG_LABELS[status], "reason": reason, "flags": []},
            "checks": [],
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

    return {
        **base,
        "kind": "stock",
        "business": {"status": b_status, "label": TAG_LABELS[b_status], "reason": b_reason, "flags": flags},
        "checks": checks,
        "market_cap_basis": basis or None,
        "period": str(periods[0])[:10] if periods else None,
    }
