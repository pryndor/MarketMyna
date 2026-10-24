"""Three-statement analysis for one company: income statement, balance
sheet and cash flow statement. Indian shares use the company's own XBRL
filings on NSE (marketmyna/data/india_filings.py), falling back to Yahoo Finance;
everything else comes from Yahoo Finance, and US companies Yahoo has no
statements for fall back to their SEC XBRL filings (marketmyna/data/sec_facts.py).

For each statement this returns the key line items across the available
periods (normally 4-5 years, or the last 4-5 quarters), derived ratios,
and rule-based findings - each tagged good / bad / neutral - that roll up
into a per-statement verdict and a plain-English summary of the whole
company. An optional AI narrative (ai_summary) reads the same numbers.

Everything is best-effort: banks publish no gross profit or current
assets, many Indian filings lack some rows, so each missing value is None
and each finding is only emitted when its inputs exist.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from ..core.numbers import finite as _num
from ..core.numbers import ratio as _div

logger = logging.getLogger(__name__)

# (key, label, candidate yfinance row names in priority order)
INCOME_ROWS = [
    ("revenue", "Total revenue", ["Total Revenue", "Operating Revenue"]),
    ("cost_of_revenue", "Cost of revenue", ["Cost Of Revenue", "Reconciled Cost Of Revenue"]),
    ("gross_profit", "Gross profit", ["Gross Profit"]),
    ("operating_expense", "Operating expenses", ["Operating Expense"]),
    ("sga", "Selling, general & admin", ["Selling General And Administration"]),
    ("operating_income", "Operating income", ["Operating Income", "Total Operating Income As Reported"]),
    ("ebitda", "EBITDA", ["EBITDA", "Normalized EBITDA"]),
    ("interest_expense", "Interest expense", ["Interest Expense", "Interest Expense Non Operating"]),
    ("pretax_income", "Pre-tax income", ["Pretax Income"]),
    ("tax", "Tax", ["Tax Provision"]),
    ("net_income", "Net income", ["Net Income", "Net Income Common Stockholders"]),
    ("eps", "Diluted EPS", ["Diluted EPS", "Basic EPS"]),
]

BALANCE_ROWS = [
    ("total_assets", "Total assets", ["Total Assets"]),
    ("current_assets", "Current assets", ["Current Assets"]),
    ("cash", "Cash & short-term investments", ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"]),
    ("long_term_investments", "Long-term investments", ["Investments And Advances", "Long Term Equity Investment"]),
    ("receivables", "Receivables", ["Accounts Receivable", "Receivables"]),
    ("inventory", "Inventory", ["Inventory"]),
    ("ppe", "Property, plant & equipment", ["Net PPE"]),
    ("total_liabilities", "Total liabilities", ["Total Liabilities Net Minority Interest"]),
    ("current_liabilities", "Current liabilities", ["Current Liabilities"]),
    ("total_debt", "Total debt", ["Total Debt"]),
    ("net_debt", "Net debt", ["Net Debt"]),
    ("equity", "Shareholders' equity", ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"]),
    ("retained_earnings", "Retained earnings", ["Retained Earnings"]),
    ("goodwill", "Goodwill & intangibles", ["Goodwill And Other Intangible Assets", "Goodwill"]),
    ("shares", "Shares outstanding", ["Ordinary Shares Number", "Share Issued"]),
]

CASHFLOW_ROWS = [
    ("operating_cf", "Operating cash flow", ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]),
    ("capex", "Capital expenditure", ["Capital Expenditure", "Purchase Of PPE"]),
    ("sbc", "Stock-based compensation", ["Stock Based Compensation"]),
    ("free_cf", "Free cash flow", ["Free Cash Flow"]),
    ("investing_cf", "Investing cash flow", ["Investing Cash Flow", "Cash Flow From Continuing Investing Activities"]),
    ("financing_cf", "Financing cash flow", ["Financing Cash Flow", "Cash Flow From Continuing Financing Activities"]),
    ("dividends", "Dividends paid", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
    ("buybacks", "Share buybacks", ["Repurchase Of Capital Stock", "Common Stock Payments"]),
    ("debt_issued", "Debt issued", ["Issuance Of Debt", "Long Term Debt Issuance"]),
    ("debt_repaid", "Debt repaid", ["Repayment Of Debt", "Long Term Debt Payments"]),
    ("sbc", "Stock-based compensation", ["Stock Based Compensation"]),
    ("depreciation", "Depreciation & amortization", ["Depreciation And Amortization", "Depreciation Amortization Depletion", "Reconciled Depreciation"]),
    ("net_change_cash", "Net change in cash", ["Changes In Cash"]),
]

# Row keys shown as money; the rest (EPS, share count) are plain numbers.
_PLAIN_KEYS = {"eps", "shares"}


def _growth(new, old) -> Optional[float]:
    """Percent change; None when the base is missing or not positive
    (growth off a loss is not meaningful)."""
    if new is None or old is None or old <= 0:
        return None
    return (new / old - 1) * 100


def _cagr(new, old, years) -> Optional[float]:
    if new is None or old is None or old <= 0 or new <= 0 or years <= 0:
        return None
    return ((new / old) ** (1 / years) - 1) * 100


def _extract(df, rows, periods: list) -> dict[str, list[Optional[float]]]:
    """{key: [value per period, newest first]} from a yfinance statement."""
    out = {}
    for key, _, candidates in rows:
        values = [None] * len(periods)
        if df is not None and not df.empty:
            for name in candidates:
                if name in df.index:
                    series = df.loc[name]
                    values = [_num(series.get(p)) for p in periods]
                    if any(v is not None for v in values):
                        break
        out[key] = values
    return out


def _periods(*frames) -> list:
    """Union of statement columns, newest first, dropping periods where
    every statement is empty (yfinance pads with all-NaN columns)."""
    cols = set()
    for df in frames:
        if df is not None and not df.empty:
            for col in df.columns:
                if df[col].notna().sum() >= 2:
                    cols.add(col)
    return sorted(cols, reverse=True)


def _table(rows, values: dict) -> list[dict]:
    return [
        {"key": key, "label": label, "kind": "number" if key in _PLAIN_KEYS else "money", "values": values[key]}
        for key, label, _ in rows
        if any(v is not None for v in values[key])
    ]


def _finding(tone: str, text: str) -> dict:
    return {"tone": tone, "text": text}


def _verdict(findings: list[dict]) -> dict:
    """0-100 score: good findings count fully, neutral ones half, bad none
    ("info" notes are context, not scored)."""
    findings = [f for f in findings if f["tone"] != "info"]
    good = sum(f["tone"] == "good" for f in findings)
    bad = sum(f["tone"] == "bad" for f in findings)
    neutral = len(findings) - good - bad
    score = round(100 * (good + 0.5 * neutral) / len(findings)) if findings else None
    label = "n/a" if score is None else "strong" if score >= 65 else "weak" if score < 40 else "mixed"
    return {"score": score, "label": label, "good": good, "bad": bad, "neutral": neutral}


def _fmt_money(v: Optional[float]) -> str:
    if v is None:
        return "n/a"
    a = abs(v)
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= size:
            return f"{v / size:.2f}{suffix}"
    return f"{v:.0f}"


# ------------------------------------------------------------------ analysis


def _compact(values: dict, periods: list, core: str) -> tuple[dict, list]:
    """Keep only the periods where this statement actually reports its core
    row. Indian filers publish quarterly P&L but half-yearly balance sheets
    and cash flows, so each statement gets its own timeline."""
    keep = [i for i, v in enumerate(values[core]) if v is not None]
    return {k: [vals[i] for i in keep] for k, vals in values.items()}, [periods[i] for i in keep]


def _compare(dates: list, quarterly: bool) -> tuple[Optional[int], str]:
    """Index of the period to compare the latest against, by date: same
    quarter a year earlier when present, else the prior quarter/year."""
    if len(dates) < 2:
        return None, ""
    for i, d in enumerate(dates[1:], start=1):
        if 300 <= (dates[0] - d).days <= 430:
            return i, "same quarter last year" if quarterly else "prior year"
    if quarterly and (dates[0] - dates[1]).days <= 200:
        return 1, "prior period"
    return None, ""


def _years_between(a, b) -> float:
    return (a - b).days / 365.25


def _lookup(values: dict, periods: list):
    """Cross-statement lookup by period date: at('net_income', date)."""
    index = {p: i for i, p in enumerate(periods)}
    return lambda key, date: values[key][index[date]] if date in index else None


def _analyze_income(v: dict, dates: list, quarterly: bool) -> tuple[dict, list[dict]]:
    n = len(dates)
    rev, ni, op, gp = v["revenue"], v["net_income"], v["operating_income"], v["gross_profit"]
    j, vs = _compare(dates, quarterly)

    margins = {
        "gross_margin": [_div(g, r) and _div(g, r) * 100 for g, r in zip(gp, rev)],
        "operating_margin": [_div(o, r) and _div(o, r) * 100 for o, r in zip(op, rev)],
        "net_margin": [_div(x, r) and _div(x, r) * 100 for x, r in zip(ni, rev)],
    }
    ebit = v["operating_income"][0] if n else None
    interest = abs(v["interest_expense"][0]) if n and v["interest_expense"][0] else None
    span = _years_between(dates[0], dates[-1]) if n > 1 else 0
    metrics = {
        "revenue_growth": _growth(rev[0], rev[j]) if j else None,
        "net_income_growth": _growth(ni[0], ni[j]) if j else None,
        "eps_growth": _growth(v["eps"][0], v["eps"][j]) if j else None,
        "revenue_cagr": _cagr(rev[0], rev[-1], span) if span >= 1.5 else None,
        "gross_margin": margins["gross_margin"][0] if n else None,
        "operating_margin": margins["operating_margin"][0] if n else None,
        "net_margin": margins["net_margin"][0] if n else None,
        "interest_coverage": _div(ebit, interest),
        "effective_tax_rate": _div(v["tax"][0], v["pretax_income"][0]) and _div(v["tax"][0], v["pretax_income"][0]) * 100 if n else None,
        "compare_label": vs or None,
    }

    f = []
    g = metrics["revenue_growth"]
    if g is not None:
        if g >= 10:
            f.append(_finding("good", f"Revenue grew {g:.1f}% vs {vs} to {_fmt_money(rev[0])}."))
        elif g >= 0:
            f.append(_finding("neutral", f"Revenue grew a modest {g:.1f}% vs {vs}."))
        else:
            f.append(_finding("bad", f"Revenue fell {abs(g):.1f}% vs {vs}."))
    cagr = metrics["revenue_cagr"]
    if cagr is not None:
        tone = "good" if cagr >= 8 else "bad" if cagr < 0 else "neutral"
        f.append(_finding(tone, f"{round(span)}-year revenue CAGR is {cagr:.1f}%."))
    if n and ni[0] is not None:
        if ni[0] < 0:
            f.append(_finding("bad", f"The company is loss-making: net loss of {_fmt_money(abs(ni[0]))}."))
        elif metrics["net_income_growth"] is not None:
            ng = metrics["net_income_growth"]
            tone = "good" if ng >= 10 else "bad" if ng < -10 else "neutral"
            f.append(_finding(tone, f"Net profit {'rose' if ng >= 0 else 'fell'} {abs(ng):.1f}% vs {vs}."))
        elif j and ni[j] is not None and ni[j] < 0:
            f.append(_finding("good", "Returned to profit after a loss."))
    nm = metrics["net_margin"]
    if nm is not None:
        tone = "good" if nm >= 15 else "bad" if nm < 5 else "neutral"
        f.append(_finding(tone, f"Net margin is {nm:.1f}% (profit kept from each unit of revenue)."))
    if j is not None and margins["operating_margin"][j] is not None and metrics["operating_margin"] is not None:
        delta = metrics["operating_margin"] - margins["operating_margin"][j]
        if abs(delta) >= 1:
            f.append(_finding("good" if delta > 0 else "bad",
                              f"Operating margin {'expanded' if delta > 0 else 'contracted'} {abs(delta):.1f} pts to {metrics['operating_margin']:.1f}%."))
    ic = metrics["interest_coverage"]
    if ic is not None:
        if ic >= 8:
            f.append(_finding("good", f"Interest is covered {ic:.1f}x by operating profit - debt service is easy."))
        elif ic < 3:
            f.append(_finding("bad", f"Interest coverage is only {ic:.1f}x - earnings leave a thin cushion over interest costs."))
        else:
            f.append(_finding("neutral", f"Interest coverage is {ic:.1f}x."))
    return {**metrics, "margins": margins}, f


def _analyze_balance(v: dict, dates: list, inc_at, quarterly: bool, financial: bool) -> tuple[dict, list[dict]]:
    n = len(dates)
    get = lambda k, i=0: v[k][i] if n > i else None  # noqa: E731
    equity, debt, cash = get("equity"), get("total_debt"), get("cash")
    ca, cl = get("current_assets"), get("current_liabilities")
    inventory = get("inventory") or 0
    avg_equity = equity
    if n > 1 and equity is not None and v["equity"][1] is not None and not quarterly:
        avg_equity = (equity + v["equity"][1]) / 2
    net_income = inc_at("net_income", dates[0]) if n else None
    ebitda = inc_at("ebitda", dates[0]) if n else None

    metrics = {
        "current_ratio": _div(ca, cl),
        "quick_ratio": _div(ca - inventory, cl) if ca is not None else None,
        "debt_to_equity": _div(debt, equity) if equity and equity > 0 else None,
        "debt_to_assets": _div(debt, get("total_assets")),
        "net_debt": get("net_debt") if get("net_debt") is not None else (debt - cash if debt is not None and cash is not None else None),
        "working_capital": ca - cl if ca is not None and cl is not None else None,
        "roe": None if quarterly else (_div(net_income, avg_equity) * 100 if _div(net_income, avg_equity) is not None and avg_equity > 0 else None),
        "roa": None if quarterly else (_div(net_income, get("total_assets")) and _div(net_income, get("total_assets")) * 100),
        "book_value_per_share": _div(equity, get("shares")),
        "equity_growth": _growth(equity, v["equity"][1]) if n > 1 else None,
        "share_change": _growth(get("shares"), v["shares"][-1]) if n > 1 else None,
        "goodwill_to_assets": _div(get("goodwill"), get("total_assets")) and _div(get("goodwill"), get("total_assets")) * 100,
    }

    f = []
    if financial:
        f.append(_finding("info", "Lender/insurer: borrowing is its raw material, so debt/equity and liquidity ratios aren't comparable with other industries."))
    cr = None if financial else metrics["current_ratio"]
    if cr is not None:
        if cr >= 1.5:
            f.append(_finding("good", f"Current ratio {cr:.2f} - short-term assets comfortably cover short-term bills."))
        elif cr < 1:
            f.append(_finding("bad", f"Current ratio {cr:.2f} - current liabilities exceed current assets."))
        else:
            f.append(_finding("neutral", f"Current ratio {cr:.2f} - adequate liquidity."))
    de = metrics["debt_to_equity"]
    if equity is not None and equity <= 0:
        f.append(_finding("bad", "Shareholders' equity is negative - liabilities exceed assets on the books."))
    elif de is not None and not financial:
        if de <= 0.5:
            f.append(_finding("good", f"Low leverage: debt is {de:.2f}x equity."))
        elif de >= 2:
            f.append(_finding("bad", f"High leverage: debt is {de:.2f}x equity."))
        else:
            f.append(_finding("neutral", f"Moderate leverage: debt is {de:.2f}x equity."))
    nd = metrics["net_debt"]
    if financial:
        pass
    elif cash is not None and debt is not None and cash > debt:
        f.append(_finding("good", f"Net cash position: cash {_fmt_money(cash)} exceeds debt {_fmt_money(debt)}."))
    elif nd is not None and nd > 0 and ebitda and ebitda > 0 and not quarterly:
        lev = nd / ebitda
        tone = "good" if lev < 1.5 else "bad" if lev > 3.5 else "neutral"
        f.append(_finding(tone, f"Net debt is {lev:.1f}x annual EBITDA."))
    roe = metrics["roe"]
    if roe is not None:
        tone = "good" if roe >= 15 else "bad" if roe < 8 else "neutral"
        f.append(_finding(tone, f"Return on equity is {roe:.1f}%."))
    eg = metrics["equity_growth"]
    if eg is not None and abs(eg) >= 3:
        f.append(_finding("good" if eg > 0 else "bad",
                          f"Shareholders' equity {'grew' if eg > 0 else 'shrank'} {abs(eg):.1f}% vs the prior period."))
    sc = metrics["share_change"]
    if sc is not None and abs(sc) >= 2:
        years = _years_between(dates[0], dates[-1])
        span = f"over {years:.1f} years" if years >= 1 else "over the periods shown"
        f.append(_finding("good" if sc < 0 else "bad",
                          f"Share count {'fell' if sc < 0 else 'rose'} {abs(sc):.1f}% {span} ({'buybacks' if sc < 0 else 'dilution'})."))
    gw = metrics["goodwill_to_assets"]
    if gw is not None and gw >= 30:
        f.append(_finding("bad", f"Goodwill & intangibles are {gw:.0f}% of assets - acquisition-heavy balance sheet."))
    return metrics, f


def _analyze_cashflow(v: dict, dates: list, inc_at, quarterly: bool, financial: bool) -> tuple[dict, list[dict]]:
    n = len(dates)
    # Indian filers publish half-year cash flows next to quarterly P&Ls;
    # dividing one by the other would halve or double every ratio.
    mismatched = quarterly and n > 1 and (dates[0] - dates[1]).days > 120
    ocf = v["operating_cf"]
    fcf = [f if f is not None else (o + c if o is not None and c is not None else None)
           for f, o, c in zip(v["free_cf"], ocf, v["capex"])]
    rev = [None if mismatched else inc_at("revenue", d) for d in dates]
    ni = [None if mismatched else inc_at("net_income", d) for d in dates]
    get = lambda series, i=0: series[i] if len(series) > i else None  # noqa: E731

    metrics = {
        "free_cf": fcf[0] if fcf else None,
        "fcf_margin": _div(get(fcf), get(rev)) and _div(get(fcf), get(rev)) * 100,
        "cash_conversion": _div(get(ocf), get(ni)) if get(ni) and get(ni) > 0 else None,
        "capex_to_revenue": _div(abs(get(v["capex"]) or 0), get(rev)) and _div(abs(get(v["capex"])), get(rev)) * 100 if get(v["capex"]) else None,
        "shareholder_returns": sum(abs(x) for x in (get(v["dividends"]), get(v["buybacks"])) if x) or None,
        "sbc_to_revenue": _div(get(v["sbc"]), get(rev)) and _div(get(v["sbc"]), get(rev)) * 100,
        "positive_fcf_periods": sum(1 for x in fcf if x is not None and x > 0),
        "fcf_periods": sum(1 for x in fcf if x is not None),
    }
    payout = _div(metrics["shareholder_returns"], get(fcf)) if get(fcf) and get(fcf) > 0 else None
    metrics["fcf_payout"] = payout and payout * 100

    f = []
    if financial:
        f.append(_finding("info", "Lender/insurer: loans and deposits run through operating cash flow, so free cash flow swings with lending and says little about profitability."))
        return metrics, f
    if get(ocf) is not None:
        if get(ocf) > 0:
            f.append(_finding("good", f"Operations generated {_fmt_money(get(ocf))} of cash."))
        else:
            f.append(_finding("bad", f"Operations burned {_fmt_money(abs(get(ocf)))} of cash."))
    if get(fcf) is not None:
        fm = metrics["fcf_margin"]
        extra = f" ({fm:.1f}% of revenue)" if fm is not None else ""
        f.append(_finding("good" if get(fcf) > 0 else "bad",
                          f"Free cash flow {'was' if get(fcf) > 0 else 'was negative at'} {_fmt_money(get(fcf))}{extra} after capex."))
    pos, tot = metrics["positive_fcf_periods"], metrics["fcf_periods"]
    if tot >= 3:
        unit = "periods" if quarterly else "years"
        if pos == tot:
            f.append(_finding("good", f"Free cash flow positive in all {tot} {unit} shown - consistent cash generator."))
        elif pos <= tot // 2:
            f.append(_finding("bad", f"Free cash flow positive in only {pos} of {tot} {unit}."))
    cc = metrics["cash_conversion"]
    if cc is not None:
        if cc >= 1:
            f.append(_finding("good", f"Operating cash flow is {cc:.2f}x net income - earnings are backed by cash."))
        elif cc < 0.7:
            f.append(_finding("bad", f"Operating cash flow is only {cc:.2f}x net income - profits aren't fully turning into cash."))
        else:
            f.append(_finding("neutral", f"Operating cash flow is {cc:.2f}x net income."))
    j, vs = _compare(dates, quarterly)
    if j is not None and get(ocf) is not None and get(ocf, j) is not None:
        g = _growth(get(ocf), get(ocf, j))
        if g is not None and abs(g) >= 10:
            f.append(_finding("good" if g > 0 else "bad", f"Operating cash flow {'rose' if g > 0 else 'fell'} {abs(g):.1f}% vs {vs}."))
    payout = metrics["fcf_payout"]
    if payout is not None:
        if payout > 100:
            f.append(_finding("bad", f"Dividends + buybacks ({_fmt_money(metrics['shareholder_returns'])}) are {payout:.0f}% of free cash flow - funded partly by cash reserves or debt."))
        elif metrics["shareholder_returns"]:
            f.append(_finding("neutral", f"Returned {_fmt_money(metrics['shareholder_returns'])} to shareholders ({payout:.0f}% of free cash flow)."))
    sbc = metrics["sbc_to_revenue"]
    if sbc is not None and sbc >= 10:
        f.append(_finding("bad", f"Stock-based compensation is {sbc:.1f}% of revenue - a real cost that cash flow excludes."))
    return metrics, f


def _summary(name: str, income: dict, balance: dict, cashflow: dict, overall: dict, period: str, financial: bool) -> str:
    """A few plain sentences a retail investor can read in 10 seconds."""
    m_i, m_b, m_c = income["metrics"], balance["metrics"], cashflow["metrics"]
    parts = []
    g = m_i.get("revenue_growth")
    nm = m_i.get("net_margin")
    if g is not None or nm is not None:
        bits = []
        if g is not None:
            bits.append(f"revenue {'up' if g >= 0 else 'down'} {abs(g):.1f}% vs {m_i['compare_label'] or 'prior period'}")
        if nm is not None:
            bits.append(f"a {nm:.1f}% net margin")
        parts.append(f"Income statement ({income['verdict']['label']}): " + " with ".join(bits) + ".")
    bs = []
    if m_b.get("debt_to_equity") is not None and not financial:
        bs.append(f"debt/equity {m_b['debt_to_equity']:.2f}")
    if m_b.get("current_ratio") is not None:
        bs.append(f"current ratio {m_b['current_ratio']:.2f}")
    if m_b.get("roe") is not None:
        bs.append(f"ROE {m_b['roe']:.1f}%")
    if bs:
        parts.append(f"Balance sheet ({balance['verdict']['label']}): " + ", ".join(bs) + ".")
    fcf = m_c.get("free_cf")
    cs = []
    if fcf is not None:
        cs.append(f"free cash flow {_fmt_money(fcf)}")
    if m_c.get("cash_conversion") is not None:
        cs.append(f"cash conversion {m_c['cash_conversion']:.2f}x")
    if cs and not financial:
        parts.append(f"Cash flow ({cashflow['verdict']['label']}): " + ", ".join(cs) + ".")
    lead = {
        "strong": f"{name} looks financially strong on its latest {period} filings.",
        "weak": f"{name} shows financial weakness on its latest {period} filings.",
        "mixed": f"{name} has a mixed financial picture on its latest {period} filings.",
    }.get(overall["label"], f"Limited {period} statement data is published for {name}.")
    return " ".join([lead, *parts])


def _statement(rows, values, periods, core, metrics, findings) -> dict:
    dates = _compact(values, periods, core)[1]
    return {
        "as_of": str(dates[0])[:10] if dates else None,
        "rows": _table(rows, values),
        "metrics": metrics,
        "findings": findings,
        "verdict": _verdict(findings),
    }


def build_financials(symbol: str, market: str, period: str = "annual") -> dict:
    import yfinance as yf

    from .analysis_run import yahoo_symbol

    if market == "crypto":
        raise ValueError("Financial statements are not applicable to crypto")
    quarterly = period == "quarterly"
    yf_symbol = yahoo_symbol(symbol, market)
    ticker = yf.Ticker(yf_symbol)
    source = "Reported financial statements (market data feed)"
    filed = _india_filings(symbol, market, quarterly)
    if filed is not None:
        inc_df, bal_df, cf_df = filed
        source = "Company filings on NSE (XBRL)"
    elif quarterly:
        inc_df, bal_df, cf_df = ticker.quarterly_income_stmt, ticker.quarterly_balance_sheet, ticker.quarterly_cashflow
    else:
        inc_df, bal_df, cf_df = ticker.income_stmt, ticker.balance_sheet, ticker.cashflow

    periods = _periods(inc_df, bal_df, cf_df)
    if not periods and market == "us":
        sec = _sec_filings(symbol, quarterly)
        if sec is not None:
            inc_df, bal_df, cf_df = sec
            source = "Company filings with the SEC (XBRL)"
            periods = _periods(inc_df, bal_df, cf_df)
    if not periods:
        raise ValueError(f"No financial statements published for {yf_symbol}")

    inc_v = _extract(inc_df, INCOME_ROWS, periods)
    bal_v = _extract(bal_df, BALANCE_ROWS, periods)
    cf_v = _extract(cf_df, CASHFLOW_ROWS, periods)

    info = {}
    try:
        info = ticker.info or {}
    except Exception as exc:
        logger.info("Financials info for %s failed: %s", yf_symbol, exc)
    name = info.get("longName") or info.get("shortName") or symbol
    # Banks/insurers: no gross profit or current assets on the statements.
    financial = info.get("sector") == "Financial Services" or (
        all(x is None for x in inc_v["gross_profit"]) and all(x is None for x in bal_v["current_assets"])
    )

    inc_at = _lookup(inc_v, periods)
    inc_m, inc_f = _analyze_income(*_compact(inc_v, periods, "revenue"), quarterly)
    bal_m, bal_f = _analyze_balance(*_compact(bal_v, periods, "total_assets"), inc_at, quarterly, financial)
    cf_m, cf_f = _analyze_cashflow(*_compact(cf_v, periods, "operating_cf"), inc_at, quarterly, financial)

    income = _statement(INCOME_ROWS, inc_v, periods, "revenue", inc_m, inc_f)
    balance = _statement(BALANCE_ROWS, bal_v, periods, "total_assets", bal_m, bal_f)
    cashflow = _statement(CASHFLOW_ROWS, cf_v, periods, "operating_cf", cf_m, cf_f)
    # Derived FCF fills the row when Yahoo omits "Free Cash Flow".
    derived_fcf = [o + c if o is not None and c is not None else None for o, c in zip(cf_v["operating_cf"], cf_v["capex"])]
    if not any(r["key"] == "free_cf" for r in cashflow["rows"]) and any(x is not None for x in derived_fcf):
        cashflow["rows"].insert(2, {"key": "free_cf", "label": "Free cash flow", "kind": "money", "values": derived_fcf})

    overall = _verdict(inc_f + bal_f + cf_f)

    # NSE filings are always in rupees; Yahoo's financialCurrency describes Yahoo's own
    # statements (USD for Infosys, Wipro and other US-listed Indian companies).
    if source.startswith("Company filings on NSE"):
        currency = "INR"
    else:
        currency = info.get("financialCurrency") or info.get("currency") or (
            "USD" if source.startswith("Company filings with the SEC") else None)

    quality = None
    if not quarterly:
        from .quality_scores import compute

        # Market value only when the price and the filings share a currency
        same_ccy = not currency or currency == info.get("currency")
        quality = compute(inc_v, bal_v, cf_v, sector=info.get("sector"),
                          market_cap=info.get("marketCap") if same_ccy else None, financial=financial)

    return {
        "symbol": symbol,
        "market": market,
        "name": name,
        "period": "quarterly" if quarterly else "annual",
        "currency": currency,
        "sector": info.get("sector"),
        "financial_sector": financial,
        "periods": [str(p)[:10] for p in periods],
        "income": income,
        "balance": balance,
        "cashflow": cashflow,
        "overall": overall,
        "summary": _summary(name, income, balance, cashflow, overall, "quarterly" if quarterly else "annual", financial),
        "source": source,
        "quality": quality,
    }


_built: dict[tuple[str, str, str], tuple[float, dict]] = {}
_built_lock = threading.Lock()
BUILT_SECONDS = 6 * 3600


def cached_financials(symbol: str, market: str, period: str = "annual") -> dict:
    """build_financials, kept 6 hours: the statements card, the DCF card and the
    investor checklists all read the same filings (which change quarterly)."""
    key = (symbol, market, period)
    with _built_lock:
        hit = _built.get(key)
    if hit and time.time() - hit[0] < BUILT_SECONDS:
        return hit[1]
    data = build_financials(symbol, market, period)
    with _built_lock:
        if len(_built) > 500:
            _built.clear()
        _built[key] = (time.time(), data)
    return data


def _sec_filings(symbol: str, quarterly: bool):
    """(income, balance, cashflow) from SEC company facts when Yahoo has none,
    or None (not an SEC filer, SEC_USER_AGENT unset, SEC unreachable)."""
    from ..data import sec_facts

    try:
        return sec_facts.statements(symbol, quarterly=quarterly, max_periods=5)
    except Exception as exc:
        logger.info("SEC filings for %s unavailable: %s", symbol, exc)
        return None


def _india_filings(symbol: str, market: str, quarterly: bool):
    """(income, balance, cashflow) from NSE filings for an Indian share, or
    None (other markets, indices, banks' layout, NSE unreachable...)."""
    if market != "india" or symbol.startswith("^"):
        return None
    from ..data import india_filings

    base = symbol.upper().removesuffix(".NS").removesuffix(".BO")
    try:
        return india_filings.statements(base, quarterly=quarterly)
    except Exception as exc:
        logger.info("NSE filings for %s unavailable, using Yahoo: %s", base, exc)
        return None


def ai_summary(data: dict, config) -> Optional[str]:
    """LLM narrative over the computed statements. None when no LLM is
    configured or the call fails - the rule-based summary still stands."""
    from ..llm.channels import llm_configured

    if config is None or not llm_configured(config):
        return None
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig

    lines = [f"Company: {data['name']} ({data['symbol']}, {data['market']}), {data['period']} filings, "
             f"currency {data.get('currency') or 'n/a'}. Periods (newest first): {', '.join(data['periods'])}."]
    for key, title in (("income", "INCOME STATEMENT"), ("balance", "BALANCE SHEET"), ("cashflow", "CASH FLOW STATEMENT")):
        st = data[key]
        lines.append(f"\n{title}")
        for row in st["rows"]:
            vals = ", ".join(_fmt_money(x) if row["kind"] == "money" else ("n/a" if x is None else f"{x:.2f}") for x in row["values"])
            lines.append(f"- {row['label']}: {vals}")
        lines.append("Findings: " + " ".join(f["text"] for f in st["findings"]))

    system = (
        "You are a sell-side equity analyst writing for a retail investor. Using ONLY the numbers given, "
        "write a concise analysis in Markdown with these sections: '### Income statement', "
        "'### Balance sheet', '### Cash flow', '### Bottom line'. Each section 2-4 sentences: what "
        "changed, why it matters, and any red flags (e.g. profits not backed by cash, rising leverage, "
        "dilution). The bottom line gives an overall financial-health verdict (strong / mixed / weak) "
        "and the 2-3 things to watch next. Consider the industry (a bank has no gross margin or current "
        "ratio). No price targets, no buy/sell advice, no disclaimers."
    )
    try:
        result = create_generation_backend(config).generate(
            "\n".join(lines), GenerationConfig(max_tokens=900, timeout=110), system_prompt=system
        )
        return (result.text or "").strip() or None
    except Exception as exc:
        logger.warning("Financials AI summary unavailable: %s", exc)
        return None
