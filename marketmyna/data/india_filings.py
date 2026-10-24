"""Indian financial statements from the companies' own XBRL filings on NSE.

Every listed company files its results with the exchange in XBRL (SEBI's
Ind-AS taxonomy), so these are the official numbers, the same ones data
sites compile from. Two NSE feeds cover the history:

- corporates-financial-results (Quarterly / Annual): 2005 to Dec 2024;
- integrated-filing-results (Financials): SEBI's integrated filing, 2025 on.

Quarterly filings carry the profit and loss for the quarter; the March
filing also carries the full year, the year-end balance sheet and the
year's cash flows (the September one the half-year balance sheet).

statements() returns three DataFrames shaped like yfinance's statements
(rows named as yfinance names them, one column per period end, newest
first), so services/financials.py analyses them unchanged. Filings never
change once published, so each parsed file is cached on disk for good;
the filing lists are cached for a few hours. Anything unreadable raises,
and the caller falls back to Yahoo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

import pandas as pd
import requests

from marketmyna.core.home import app_home

logger = logging.getLogger(__name__)

API = "https://www.nseindia.com/api"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "application/json, text/plain, */*",
}
_TIMEOUT = 25
LIST_TTL = 6 * 3600
QUARTERS = 8
PARSE_VERSION = 2
YEARS = 5

_lock = threading.Lock()
_lists: dict[str, tuple[float, list[dict]]] = {}


def _cache_dir() -> Path:
    path = app_home() / "india_filings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get(url: str) -> requests.Response:
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp


# ------------------------------------------------------------------ filing lists


def _day(text: str) -> Optional[date]:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(text.strip().title(), fmt).date()
        except (AttributeError, ValueError):
            continue
    return None


def filings(symbol: str) -> list[dict]:
    """[{end, consolidated, url}] for every results filing, newest first."""
    symbol = symbol.upper()
    with _lock:
        hit = _lists.get(symbol)
        if hit and time.time() - hit[0] < LIST_TTL:
            return hit[1]
    out: dict[tuple, dict] = {}

    def add(end: Optional[date], consolidated: str, url: Optional[str]):
        if end and url and url.endswith(".xml"):
            key = (end, consolidated.lower().startswith("consolidated"))
            out.setdefault(key, {"end": end, "consolidated": key[1], "url": url})

    errors = []
    try:
        data = _get(f"{API}/integrated-filing-results?symbol={symbol}&type=Integrated%20Filing-%20Financials").json()
        for r in data.get("data") or []:
            add(_day(r.get("qe_Date") or ""), r.get("consolidated") or "", r.get("xbrl"))
    except Exception as exc:
        errors.append(exc)
    for period in ("Annual", "Quarterly"):
        try:
            for r in _get(f"{API}/corporates-financial-results?index=equities&symbol={symbol}&period={period}").json():
                add(_day(r.get("toDate") or ""), r.get("consolidated") or "", r.get("xbrl"))
        except Exception as exc:
            errors.append(exc)
    if not out:
        raise RuntimeError(f"No NSE results filings for {symbol}: {errors[:1]}")
    rows = sorted(out.values(), key=lambda r: r["end"], reverse=True)
    with _lock:
        _lists[symbol] = (time.time(), rows)
    return rows


# ------------------------------------------------------------------ XBRL


def parse(xml: bytes) -> list[tuple[str, Optional[str], str, float]]:
    """[(tag, start or None for an instant, end, value)] for the facts with
    no dimension (the company totals, not segments or breakdowns)."""
    root = ET.fromstring(xml)
    periods: dict[str, tuple[Optional[str], str]] = {}
    for ctx in root:
        if not ctx.tag.endswith("context"):
            continue
        if any(el.tag.endswith(("explicitMember", "typedMember")) for el in ctx.iter()):
            continue
        start = ctx.find(".//{*}startDate")
        end = ctx.find(".//{*}endDate")
        instant = ctx.find(".//{*}instant")
        if instant is not None and instant.text:
            periods[ctx.get("id")] = (None, instant.text.strip())
        elif start is not None and end is not None and start.text and end.text:
            begin, stop = start.text.strip(), end.text.strip()
            if ctx.get("id") == "FourD":
                # "FourD" is the year to date. Filings before 2025 give it the
                # quarter's dates by mistake; it always starts on 1 April.
                last = date.fromisoformat(stop)
                begin = date(last.year if last.month >= 4 else last.year - 1, 4, 1).isoformat()
            periods[ctx.get("id")] = (begin, stop)
    facts = []
    for el in root:
        ref = el.get("contextRef")
        text = (el.text or "").strip()
        if ref not in periods or not re.fullmatch(r"-?\d+(\.\d+)?", text):
            continue
        start, end = periods[ref]
        facts.append((el.tag.split("}")[-1], start, end, float(text)))
    return facts


def _facts(url: str) -> list[tuple]:
    # The version prefix retires cached parses when parse() changes.
    path = _cache_dir() / (hashlib.sha256(f"{PARSE_VERSION}:{url}".encode()).hexdigest()[:24] + ".json")
    try:
        return [tuple(f) for f in json.loads(path.read_text(encoding="utf-8"))]
    except (OSError, ValueError):
        pass
    facts = parse(_get(url).content)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(facts), encoding="utf-8")
    tmp.replace(path)
    return facts


# ------------------------------------------------------------------ statements

# yfinance row name -> how to read it from one period's facts {tag: value}.
def _sum(v: dict, *tags: str) -> Optional[float]:
    vals = [v[t] for t in tags if t in v]
    return sum(vals) if vals else None


def _first(v: dict, *tags: str) -> Optional[float]:
    return next((v[t] for t in tags if t in v), None)


def _minus(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return a - b if a is not None and b is not None else None


def _income(v: dict) -> dict:
    revenue = v.get("RevenueFromOperations")
    cost = _sum(v, "CostOfMaterialsConsumed", "PurchasesOfStockInTrade",
                "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade")
    pbt_before_exceptional = _first(v, "ProfitBeforeExceptionalItemsAndTax", "ProfitBeforeTax")
    finance = v.get("FinanceCosts")
    operating = None
    if pbt_before_exceptional is not None:
        operating = pbt_before_exceptional + (finance or 0) - (v.get("OtherIncome") or 0)
    depreciation = v.get("DepreciationDepletionAndAmortisationExpense")
    return {
        "Total Revenue": revenue,
        "Cost Of Revenue": cost,
        "Gross Profit": _minus(revenue, cost),
        "Operating Income": operating,
        "EBITDA": operating + depreciation if operating is not None and depreciation is not None else None,
        "Interest Expense": finance,
        # Overheads: Ind-AS has no SG&A line; staff plus other expenses stand in
        "Selling General And Administration": _sum(v, "EmployeeBenefitExpense", "OtherExpenses"),
        "Pretax Income": v.get("ProfitBeforeTax"),
        "Tax Provision": v.get("TaxExpense"),
        "Net Income": _first(v, "ProfitOrLossAttributableToOwnersOfParent", "ProfitLossForPeriod"),
        "Diluted EPS": _first(v, "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                              "DilutedEarningsLossPerShareFromContinuingOperations"),
        "Basic EPS": _first(v, "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                            "BasicEarningsLossPerShareFromContinuingOperations"),
    }


def _balance(v: dict) -> dict:
    debt = _sum(v, "BorrowingsNoncurrent", "BorrowingsCurrent")
    cash = v.get("CashAndCashEquivalents")
    paid_up, face = v.get("PaidUpValueOfEquityShareCapital") or v.get("EquityShareCapital"), v.get("FaceValueOfEquityShareCapital")
    return {
        "Total Assets": v.get("Assets"),
        "Current Assets": v.get("CurrentAssets"),
        "Cash And Cash Equivalents": cash,
        "Accounts Receivable": v.get("TradeReceivablesCurrent"),
        "Inventory": v.get("Inventories"),
        "Total Liabilities Net Minority Interest": v.get("Liabilities"),
        "Current Liabilities": v.get("CurrentLiabilities"),
        "Total Debt": debt,
        "Net Debt": _minus(debt, cash),
        "Stockholders Equity": _first(v, "EquityAttributableToOwnersOfParent", "Equity"),
        "Goodwill And Other Intangible Assets": _sum(v, "Goodwill", "OtherIntangibleAssets"),
        "Net PPE": v.get("PropertyPlantAndEquipment"),
        # Ind-AS "other equity" is reserves and surplus, mostly retained earnings
        "Retained Earnings": _first(v, "RetainedEarnings", "OtherEquity"),
        "Ordinary Shares Number": paid_up / face if paid_up and face else None,
    }


def _cashflow(v: dict) -> dict:
    operating = v.get("CashFlowsFromUsedInOperatingActivities")
    purchase = v.get("PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")
    capex = -abs(purchase) if purchase is not None else None
    dividends = v.get("DividendsPaidClassifiedAsFinancingActivities")
    return {
        "Operating Cash Flow": operating,
        "Capital Expenditure": capex,
        "Free Cash Flow": operating + capex if operating is not None and capex is not None else None,
        "Investing Cash Flow": v.get("CashFlowsFromUsedInInvestingActivities"),
        "Depreciation And Amortization": _first(v, "AdjustmentsForDepreciationAndAmortisationExpense",
                                                "DepreciationDepletionAndAmortisationExpense"),
        "Financing Cash Flow": v.get("CashFlowsFromUsedInFinancingActivities"),
        "Cash Dividends Paid": -abs(dividends) if dividends is not None else None,
    }


def _span_days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _period_values(facts: list[tuple], end: date, span: tuple[int, int]) -> tuple[dict, dict]:
    """(duration facts covering `span` days and ending at `end`, instant facts at `end`)."""
    iso = end.isoformat()
    durations, instants = {}, {}
    for tag, start, stop, value in facts:
        if stop != iso:
            continue
        if start is None:
            instants.setdefault(tag, value)
        elif span[0] <= _span_days(start, stop) <= span[1]:
            durations.setdefault(tag, value)
    return durations, instants


QUARTER_DAYS = (80, 100)
YEAR_DAYS = (350, 380)


def _frame(columns: dict[date, dict]) -> pd.DataFrame:
    """yfinance-shaped: rows = line items, columns = period ends (newest first)."""
    if not columns:
        return pd.DataFrame()
    df = pd.DataFrame({pd.Timestamp(d): col for d, col in columns.items()})
    df = df[sorted(df.columns, reverse=True)]
    return df.dropna(how="all")


def statements(symbol: str, quarterly: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(income, balance, cashflow) from NSE filings, consolidated when the
    company files consolidated results, else standalone."""
    rows = filings(symbol)
    consolidated = any(r["consolidated"] for r in rows[:4])
    rows = [r for r in rows if r["consolidated"] == consolidated]
    if quarterly:
        rows = rows[:QUARTERS]
        span = QUARTER_DAYS
    else:
        rows = [r for r in rows if r["end"].month == 3 and r["end"].day == 31][:YEARS]
        span = YEAR_DAYS
    if not rows:
        raise RuntimeError(f"No {'quarterly' if quarterly else 'annual'} filings for {symbol}")

    income, balance, cashflow = {}, {}, {}
    shares: dict[date, float] = {}
    for r in rows:
        try:
            facts = _facts(r["url"])
        except Exception as exc:
            logger.info("NSE filing %s unreadable: %s", r["url"], exc)
            continue
        durations, instants = _period_values(facts, r["end"], span)
        if durations.get("RevenueFromOperations") is not None:
            income[r["end"]] = _income(durations)
            count = _share_count({**instants, **durations})
            if count:
                shares[r["end"]] = count
        if instants.get("Assets") is not None:
            balance[r["end"]] = _balance(instants)
        if durations.get("CashFlowsFromUsedInOperatingActivities") is not None:
            cashflow[r["end"]] = _cashflow(durations)
    if len(income) < 2:
        # Banks and insurers file a different layout (interest earned, ...): leave them to Yahoo.
        raise RuntimeError(f"NSE filings for {symbol} have no readable income statement")
    _restate_eps(income, shares)
    return _frame(income), _frame(balance), _frame(cashflow)


def _share_count(v: dict) -> Optional[float]:
    paid_up = v.get("PaidUpValueOfEquityShareCapital") or v.get("EquityShareCapital")
    face = v.get("FaceValueOfEquityShareCapital")
    return paid_up / face if paid_up and face else None


def _restate_eps(income: dict[date, dict], shares: dict[date, float]) -> None:
    """Filings report EPS on the share count of their day; a later bonus or
    split would read as an earnings collapse. Restate each period's EPS onto
    the latest share count (as Yahoo does)."""
    if not shares:
        return
    latest = shares[max(shares)]
    for end, row in income.items():
        count = shares.get(end)
        if not count or abs(count / latest - 1) < 0.01:
            continue
        for key in ("Diluted EPS", "Basic EPS"):
            if row.get(key) is not None:
                row[key] = round(row[key] * count / latest, 2)
