"""US financial statements from SEC XBRL company facts (data.sec.gov, no key).

companyfacts holds every number a company has tagged in its 10-K / 10-Q
filings since about 2009. This turns the common US-GAAP tags into the same
three DataFrames yfinance returns (rows named like Yahoo's, columns = period
end dates, newest first), so marketmyna/services/financials.py and the quality
scores can use either source. Used when Yahoo has no statements and for
longer histories (Yahoo keeps 4-5 years).

Total debt excludes lease liabilities (Yahoo includes them).
Annual = 10-K full-year figures. Quarterly = three-month figures; the fourth
quarter, which companies do not file separately, is the year minus the first
three quarters. Flows that are outflows (capex, dividends, buybacks, debt
repaid) are made negative, as Yahoo shows them. SEC needs SEC_USER_AGENT
(a name and contact email), see marketmyna/services/sec_mdna.py.
"""

from __future__ import annotations

import threading
import time
from datetime import date
from typing import Optional

import pandas as pd

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
CACHE_SECONDS = 12 * 3600

# Yahoo row name -> US-GAAP tags, first one with data wins
INCOME = {
    "Total Revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
                      "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet",
                      "RevenuesNetOfInterestExpense"],
    "Cost Of Revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
    "Gross Profit": ["GrossProfit"],
    "Operating Expense": ["OperatingExpenses"],
    "Selling General And Administration": ["SellingGeneralAndAdministrativeExpense"],
    "Operating Income": ["OperatingIncomeLoss"],
    "Interest Expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "Pretax Income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "Tax Provision": ["IncomeTaxExpenseBenefit"],
    "Net Income": ["NetIncomeLoss", "ProfitLoss"],
    "Diluted EPS": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    "Basic EPS": ["EarningsPerShareBasic"],
    "Diluted Average Shares": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
BALANCE = {
    "Total Assets": ["Assets"],
    "Current Assets": ["AssetsCurrent"],
    "Cash And Cash Equivalents": ["CashAndCashEquivalentsAtCarryingValue", "Cash"],
    "Short Term Investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "Accounts Receivable": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
    "Inventory": ["InventoryNet"],
    "Net PPE": ["PropertyPlantAndEquipmentNet"],
    "Total Liabilities Net Minority Interest": ["Liabilities"],
    "Current Liabilities": ["LiabilitiesCurrent"],
    "Long Term Debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "Current Debt": ["LongTermDebtCurrent", "DebtCurrent"],
    "Commercial Paper": ["CommercialPaper", "ShortTermBorrowings"],
    "Stockholders Equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "Retained Earnings": ["RetainedEarningsAccumulatedDeficit"],
    "Goodwill": ["Goodwill"],
    "Other Intangible Assets": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
    "Ordinary Shares Number": ["CommonStockSharesOutstanding"],
}
CASHFLOW = {
    "Operating Cash Flow": ["NetCashProvidedByUsedInOperatingActivities",
                            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "Capital Expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "Investing Cash Flow": ["NetCashProvidedByUsedInInvestingActivities",
                            "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"],
    "Financing Cash Flow": ["NetCashProvidedByUsedInFinancingActivities",
                            "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"],
    "Cash Dividends Paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "Repurchase Of Capital Stock": ["PaymentsForRepurchaseOfCommonStock"],
    "Issuance Of Debt": ["ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt"],
    "Repayment Of Debt": ["RepaymentsOfLongTermDebt", "RepaymentsOfDebt"],
    "Stock Based Compensation": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "Depreciation And Amortization": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                                      "DepreciationAmortizationAndAccretionNet"],
    "Changes In Cash": ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
                        "CashAndCashEquivalentsPeriodIncreaseDecrease"],
}
OUTFLOWS = {"Capital Expenditure", "Cash Dividends Paid", "Repurchase Of Capital Stock", "Repayment Of Debt"}
PER_SHARE = {"Diluted EPS", "Basic EPS"}
# Not sums over time: no quarter is derived from year-to-date or full-year figures
NON_ADDITIVE = PER_SHARE | {"Diluted Average Shares"}

_cache: dict[int, tuple[float, dict]] = {}
_lock = threading.Lock()


def company_facts(symbol: str) -> dict:
    from ..services.sec_mdna import _get, cik_for

    cik = cik_for(symbol)
    with _lock:
        hit = _cache.get(cik)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    facts = _get(FACTS_URL.format(cik=cik)).json()
    with _lock:
        _cache[cik] = (time.time(), facts)
    return facts


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _entries(facts: dict, tag: str) -> list[dict]:
    node = ((facts.get("facts") or {}).get("us-gaap") or {}).get(tag) or {}
    units = node.get("units") or {}
    for unit in ("USD", "USD/shares", "shares"):
        if unit in units:
            return units[unit]
    return next(iter(units.values()), [])


def _latest_by_end(rows: list[dict]) -> dict[str, float]:
    """end date -> value, keeping the most recently filed figure (restatements win)."""
    best: dict[str, tuple[str, float]] = {}
    for r in rows:
        end, filed = r.get("end"), r.get("filed") or ""
        if end and (end not in best or filed >= best[end][0]):
            best[end] = (filed, float(r["val"]))
    return {end: v for end, (_, v) in best.items()}


def _flow_one(facts: dict, tag: str, quarterly: bool, additive: bool = True) -> dict[str, float]:
    entries = [e for e in _entries(facts, tag) if e.get("start") and e.get("end")]
    if not entries:
        return {}
    yearly = [e for e in entries if 350 <= _days(e["start"], e["end"]) <= 380]
    annual = _latest_by_end([e for e in yearly if (e.get("form") or "").startswith("10-K")])
    if not quarterly:
        return annual
    quarters = _latest_by_end([e for e in entries if 80 <= _days(e["start"], e["end"]) <= 100])
    if not additive:
        return quarters
    # Cash-flow statements in a 10-Q are year to date (6 or 9 months): a quarter
    # is the year-to-date figure minus the one before it from the same start.
    by_start: dict[str, dict[str, float]] = {}
    for e in entries:
        by_start.setdefault(e["start"], {})
    for start in by_start:
        by_start[start] = _latest_by_end([e for e in entries if e["start"] == start])
    for start, ytd in by_start.items():
        ends = sorted(ytd)
        for prev, end in zip(ends, ends[1:]):
            if end not in quarters and 80 <= _days(prev, end) <= 100:
                quarters[end] = ytd[end] - ytd[prev]
    # Q4 = year minus the three quarters inside it
    for end, total in annual.items():
        if end in quarters:
            continue
        start = next(e["start"] for e in yearly if e["end"] == end)
        inside = [v for q_end, v in quarters.items() if start < q_end < end]
        if len(inside) == 3:
            quarters[end] = round(total - sum(inside), 4)
    return quarters


def _instant_one(facts: dict, tag: str, quarterly: bool) -> dict[str, float]:
    entries = [e for e in _entries(facts, tag) if e.get("end") and not e.get("start")]
    if not quarterly:
        entries = [e for e in entries if (e.get("form") or "").startswith("10-K") and e.get("fp") == "FY"]
    return _latest_by_end(entries)


def _merge(series: list[dict[str, float]]) -> dict[str, float]:
    """Companies switch tags over the years (Apple's revenue moved from Revenues to
    RevenueFromContractWithCustomer... in 2018): each period takes the first tag,
    in priority order, that has it."""
    out: dict[str, float] = {}
    for values in series:
        for end, v in values.items():
            out.setdefault(end, v)
    return out


def flow_series(facts: dict, tags: list[str], quarterly: bool, additive: bool = True) -> dict[str, float]:
    """Figures over a period (income, cash flow) by period end."""
    return _merge([_flow_one(facts, t, quarterly, additive) for t in tags])


def instant_series(facts: dict, tags: list[str], quarterly: bool) -> dict[str, float]:
    """Balances at a date (balance sheet), from 10-K (annual) or any filing (quarterly)."""
    return _merge([_instant_one(facts, t, quarterly) for t in tags])


def _frame(series: dict[str, dict[str, float]], periods: list[str]) -> pd.DataFrame:
    cols = [pd.Timestamp(p) for p in periods]
    data = {name: [values.get(p) for p in periods] for name, values in series.items() if values}
    return pd.DataFrame.from_dict(data, orient="index", columns=cols) if data else pd.DataFrame(columns=cols)


def statements(symbol: str, quarterly: bool = False, max_periods: Optional[int] = None,
               facts: Optional[dict] = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(income, balance, cashflow) like yfinance's, newest period first."""
    facts = facts if facts is not None else company_facts(symbol)
    limit = max_periods or (5 if quarterly else 10)

    income = {name: flow_series(facts, tags, quarterly, name not in NON_ADDITIVE) for name, tags in INCOME.items()}
    cash = {name: flow_series(facts, tags, quarterly) for name, tags in CASHFLOW.items()}
    balance = {name: instant_series(facts, tags, quarterly) for name, tags in BALANCE.items()}
    for name in OUTFLOWS:
        cash[name] = {k: -abs(v) for k, v in cash[name].items()}

    # Revenue or net income: banks stop tagging quarterly revenue under one tag for years
    periods = sorted(set(income["Total Revenue"]) | set(income["Net Income"]), reverse=True)[:limit]
    if not periods:
        raise ValueError(f"No SEC financial statements tagged for {symbol}")

    # Balance sheets dated a few days off the income period end are matched to it.
    def align(values: dict[str, float]) -> dict[str, float]:
        out = {}
        for p in periods:
            if p in values:
                out[p] = values[p]
                continue
            near = [d for d in values if abs(_days(d, p)) <= 7]
            if near:
                out[p] = values[min(near, key=lambda d: abs(_days(d, p)))]
        return out

    balance = {k: align(v) for k, v in balance.items()}
    cash = {k: align(v) for k, v in cash.items()}

    # Derived rows Yahoo also shows
    def combine(*rows: dict[str, float]) -> dict[str, float]:
        return {p: sum(r[p] for r in rows if p in r) for p in periods if any(p in r for r in rows)}

    if not income["Gross Profit"] and income["Total Revenue"] and income["Cost Of Revenue"]:
        income["Gross Profit"] = {p: income["Total Revenue"][p] - income["Cost Of Revenue"][p]
                                  for p in periods if p in income["Total Revenue"] and p in income["Cost Of Revenue"]}
    if income["Operating Income"] and cash["Depreciation And Amortization"]:
        income["EBITDA"] = combine(income["Operating Income"], cash["Depreciation And Amortization"])
    balance["Total Debt"] = combine(balance.pop("Long Term Debt"), balance.pop("Current Debt"),
                                    balance.pop("Commercial Paper"))
    balance["Cash Cash Equivalents And Short Term Investments"] = combine(
        balance["Cash And Cash Equivalents"], balance.pop("Short Term Investments"))
    if balance["Total Debt"]:
        balance["Net Debt"] = {p: balance["Total Debt"][p] - balance["Cash And Cash Equivalents"].get(p, 0)
                               for p in balance["Total Debt"]}
    balance["Goodwill And Other Intangible Assets"] = combine(balance["Goodwill"], balance.pop("Other Intangible Assets"))
    if cash["Operating Cash Flow"] and cash["Capital Expenditure"]:
        cash["Free Cash Flow"] = combine(cash["Operating Cash Flow"], cash["Capital Expenditure"])

    return _frame(income, periods), _frame(balance, periods), _frame(cash, periods)
