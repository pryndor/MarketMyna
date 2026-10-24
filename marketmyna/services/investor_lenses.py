"""Investor checklists: one company run through the published rules of five
well-known investing styles, each rule pass / fail with its number.

Rules are taken from the investors' own books and letters, with the
thresholds they gave; where a rule needs more history than the filings
shown (Graham's ten years of earnings), it is scaled to the years available
and says so. These are checklists of public criteria applied to published
figures. They do not say what any of these investors would do, and they are
not advice.

- Graham, defensive investor (The Intelligent Investor, ch. 14)
- Buffett-style quality (Berkshire letters: durable high returns on equity,
  little debt, owner earnings)
- Lynch (One Up on Wall Street: PEG, dividend-adjusted PEG, debt, inventories)
- Greenblatt magic formula (The Little Book That Beats the Market: earnings
  yield and return on capital; the book ranks a whole market, fixed
  thresholds stand in for the ranking here)
- Marks-style risk check (Howard Marks' memos: avoid fragile balance sheets,
  prefer buying after prices have fallen)
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from ..core.numbers import ratio as _div

logger = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600
# Graham's "adequate size" (sales of $100m in 1972), in today's money
MIN_SALES = {"USD": 700e6, "INR": 5_000e7}  # ₹5,000 crore

_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_lock = threading.Lock()


def _row(fin: dict, statement: str, key: str) -> list[Optional[float]]:
    return next((r["values"] for r in fin.get(statement, {}).get("rows", []) if r["key"] == key), [])


def _first(values: list) -> Optional[float]:
    return values[0] if values and values[0] is not None else None


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _cagr(newest, oldest, years) -> Optional[float]:
    if newest is None or oldest is None or newest <= 0 or oldest <= 0 or years <= 0:
        return None
    return (newest / oldest) ** (1 / years) - 1


def _pct(x: Optional[float], digits: int = 1) -> str:
    return f"{x * 100:.{digits}f}%" if x is not None else "n/a"


def _x(x: Optional[float], digits: int = 2) -> str:
    return f"{x:.{digits}f}" if x is not None else "n/a"


def rule(key: str, label: str, ok: Optional[bool], value: str, why: str) -> dict:
    return {"key": key, "label": label, "pass": ok, "value": value, "why": why}


def _lens(key: str, name: str, source: str, rules: list[dict], note: Optional[str] = None) -> dict:
    tested = [r for r in rules if r["pass"] is not None]
    passed = sum(1 for r in tested if r["pass"])
    return {"key": key, "name": name, "source": source, "rules": rules, "passed": passed,
            "tested": len(tested), "total": len(rules), "note": note}


def evaluate(fin: dict, info: dict) -> dict:
    """All five lenses from financials.py's annual payload and Yahoo's info."""
    financial = bool(fin.get("financial_sector"))
    ccy = fin.get("currency") or info.get("financialCurrency")
    years = len(fin.get("periods") or [])

    revenue = _row(fin, "income", "revenue")
    ni = _row(fin, "income", "net_income")
    eps = _row(fin, "income", "eps")
    gp = _row(fin, "income", "gross_profit")
    ebit_row = _row(fin, "income", "operating_income")
    interest = _row(fin, "income", "interest_expense")
    ebitda = _first(_row(fin, "income", "ebitda"))
    equity = _row(fin, "balance", "equity")
    ca, cl = _first(_row(fin, "balance", "current_assets")), _first(_row(fin, "balance", "current_liabilities"))
    debt = _first(_row(fin, "balance", "total_debt"))
    cash = _first(_row(fin, "balance", "cash"))
    inventory = _row(fin, "balance", "inventory")
    ppe = _first(_row(fin, "balance", "ppe"))
    ocf, capex = _row(fin, "cashflow", "operating_cf"), _row(fin, "cashflow", "capex")
    dividends = _row(fin, "cashflow", "dividends")

    pe = _num(info.get("trailingPE"))
    pb = _num(info.get("priceToBook"))
    beta = _num(info.get("beta"))
    price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    high = _num(info.get("fiftyTwoWeekHigh"))
    dy = _num(info.get("dividendYield"))
    dy = dy / 100 if dy is not None and dy > 1 else dy  # Yahoo now reports percent
    shares = _num(info.get("sharesOutstanding"))

    ebit = _first(ebit_row)
    cur_ratio = _div(ca, cl)
    de = _div(debt, _first(equity))
    known_eps = [(i, v) for i, v in enumerate(eps) if v is not None]
    eps_growth = (_cagr(known_eps[0][1], known_eps[-1][1], known_eps[-1][0] - known_eps[0][0])
                  if len(known_eps) >= 2 else None)
    growth_basis = "EPS"
    if eps_growth is None:  # some filings carry no EPS history: net income instead
        known_ni = [(i, v) for i, v in enumerate(ni) if v is not None]
        if len(known_ni) >= 2:
            eps_growth = _cagr(known_ni[0][1], known_ni[-1][1], known_ni[-1][0] - known_ni[0][0])
            growth_basis = "net income"
    ni_known = [v for v in ni if v is not None]
    fcf = [o + c for o, c in zip(ocf, capex) if o is not None and c is not None]

    # ---------------------------------------------------------------- Graham
    min_sales = MIN_SALES.get(ccy or "")
    wc = ca - cl if ca is not None and cl is not None else None
    if financial or debt is None or wc is None:
        debt_wc_ok, debt_wc_text = None, "n/a"
    elif wc <= 0:
        debt_wc_ok, debt_wc_text = debt <= 0, "working capital negative"
    else:
        debt_wc_ok, debt_wc_text = debt <= wc, f"debt {debt / wc:.2f}x working capital"
    graham = [
        rule("size", "Adequate size", None if min_sales is None or not revenue or revenue[0] is None else revenue[0] >= min_sales,
             f"sales {revenue[0] / 1e9:.1f}bn {ccy}" if revenue and revenue[0] else "n/a",
             "Large enough to weather bad years (sales of $100m in 1972, about $700m / ₹5,000 cr today)"),
        rule("current", "Current ratio at least 2", None if financial or cur_ratio is None else cur_ratio >= 2,
             _x(cur_ratio), "Current assets at least twice current liabilities"),
        rule("debt_wc", "Debt no more than working capital", debt_wc_ok, debt_wc_text,
             "Long-term debt should not exceed net current assets"),
        rule("stable", f"Profit in each of the {len(ni_known)} years shown", None if len(ni_known) < 3 else all(v > 0 for v in ni_known),
             f"{sum(1 for v in ni_known if v > 0)} of {len(ni_known)} profitable", "Graham asked for 10 years without a loss"),
        rule("dividend", "Dividend paid each year shown", None if not dividends else all((v or 0) != 0 for v in dividends),
             f"{sum(1 for v in dividends if v)} of {len(dividends)} years" if dividends else "n/a",
             "Graham asked for an unbroken dividend record of 20 years"),
        rule("growth", "Earnings growth of 3%+ a year", None if eps_growth is None else eps_growth >= 0.029,
             f"{growth_basis} {_pct(eps_growth)} a year", "A third over ten years, about 2.9% a year"),
        rule("pe", "P/E at most 15", None if pe is None else pe <= 15, _x(pe, 1), "Price no more than 15 times earnings"),
        rule("pe_pb", "P/E x P/B at most 22.5", None if pe is None or pb is None else pe * pb <= 22.5,
             _x(pe * pb if pe is not None and pb is not None else None, 1), "Allows a higher P/E when the price is close to book value"),
    ]

    # ---------------------------------------------------------------- Buffett
    roes = [_div(n, e) for n, e in zip(ni, equity) if n is not None and e not in (None, 0) and e > 0]
    roe_avg = sum(roes) / len(roes) if roes else None
    margin = _div(_first(ni), _first(revenue))
    gross = _div(_first(gp), _first(revenue))
    if gross is not None and gross >= 0.999:
        gross = None  # no cost of goods reported
    eps_steps = [a > b for (_, a), (_, b) in zip(known_eps, known_eps[1:])]
    capex_ratio = None
    cap_vals = [abs(c) for c in capex if c is not None]
    if cap_vals and ni_known and sum(ni_known) > 0:
        capex_ratio = sum(cap_vals[:len(ni_known)]) / sum(ni_known)
    buffett = [
        rule("roe", "Return on equity 15%+ on average", None if roe_avg is None else roe_avg >= 0.15,
             f"{_pct(roe_avg)} average over {len(roes)} years", "Durable high returns on the owners' money"),
        rule("roe_floor", "No year below 10% return on equity", None if len(roes) < 3 else min(roes) >= 0.10,
             f"lowest {_pct(min(roes)) if roes else 'n/a'}", "Consistency matters more than one good year"),
        rule("debt", "Debt under half of equity", None if financial or de is None else de <= 0.5, _x(de), "Little borrowing"),
        rule("margin", "Net margin 10%+", None if margin is None else margin >= 0.10, _pct(margin), "Pricing power shows up in margins"),
        rule("gross", "Gross margin 40%+", None if financial or gross is None else gross >= 0.40, _pct(gross),
             "A moat usually means a high gross margin"),
        rule("eps_steady", "Earnings rose in every year shown", None if len(eps_steps) < 2 else all(eps_steps),
             f"{sum(eps_steps)} of {len(eps_steps)} years up" if eps_steps else "n/a", "Predictable, growing earnings"),
        rule("fcf", "Free cash flow positive each year", None if financial or len(fcf) < 3 else all(v > 0 for v in fcf),
             f"{sum(1 for v in fcf if v > 0)} of {len(fcf)} years" if fcf else "n/a", "Owner earnings: cash left after keeping the business going"),
        rule("capex", "Capital spending under half of profits", None if financial or capex_ratio is None else capex_ratio <= 0.5,
             _pct(capex_ratio, 0), "The business does not eat its own earnings"),
    ]

    # ---------------------------------------------------------------- Lynch
    growth_pct = eps_growth * 100 if eps_growth is not None else None
    peg = pe / growth_pct if pe is not None and growth_pct and growth_pct > 0 else None
    yield_pct = dy * 100 if dy is not None else 0.0
    adj = (growth_pct + yield_pct) / pe if pe and growth_pct is not None else None
    inv_growth = _div(inventory[0], inventory[1]) if len(inventory) > 1 and inventory[0] is not None and inventory[1] else None
    sales_growth = _div(revenue[0], revenue[1]) if len(revenue) > 1 and revenue[0] is not None and revenue[1] else None
    net_cash_ps = (cash - debt) / shares if cash is not None and debt is not None and shares else None
    lynch = [
        rule("peg", "PEG at most 1", None if peg is None else peg <= 1, _x(peg),
             f"P/E {_x(pe, 1)} against {growth_basis} growth of {_x(growth_pct, 1)}% a year"),
        rule("adj_peg", "(Growth + dividend yield) / P/E at least 1", None if adj is None else adj >= 1, _x(adj),
             "Lynch's dividend-adjusted test: 1 is okay, 2 is very good"),
        rule("debt", "Debt at most a third of equity", None if financial or de is None else de <= 0.33, _x(de),
             "A normal balance sheet is about 75% equity, 25% debt"),
        rule("inventory", "Inventories not growing faster than sales", None if inv_growth is None or sales_growth is None else inv_growth <= sales_growth * 1.02,
             f"inventory {_pct(inv_growth - 1 if inv_growth else None)}, sales {_pct(sales_growth - 1 if sales_growth else None)}",
             "Piling-up stock is a warning sign"),
        rule("net_cash", "Net cash on the balance sheet", None if financial or net_cash_ps is None else net_cash_ps > 0,
             f"{net_cash_ps:.2f} a share" if net_cash_ps is not None else "n/a", "Cash minus debt per share: a cushion"),
    ]

    # ---------------------------------------------------------------- Greenblatt
    ev = _num(info.get("enterpriseValue"))
    if ev is None and info.get("marketCap") and debt is not None and cash is not None:
        ev = float(info["marketCap"]) + debt - cash
    ey = _div(ebit, ev) if ev and ev > 0 else None
    capital = (ca - cl + ppe) if ca is not None and cl is not None and ppe is not None else None
    roc = _div(ebit, capital) if capital and capital > 0 else None
    same_ccy = not ccy or ccy == info.get("currency")  # the filings' currency, not Yahoo's
    greenblatt = [
        rule("ey", "Earnings yield (EBIT / EV) 8%+", None if financial or ey is None or not same_ccy else ey >= 0.08, _pct(ey),
             "Cheap: operating profit against the whole firm's price"),
        rule("roc", "Return on capital 25%+", None if financial or roc is None else roc >= 0.25, _pct(roc),
             "Good: operating profit against working capital plus fixed assets"),
    ]
    g_note = "The book excludes banks, insurers and utilities." if financial else \
        "The magic formula ranks every stock on both measures; fixed cut-offs stand in for the ranking here."

    # ---------------------------------------------------------------- Marks
    int_cover = _div(ebit, abs(_first(interest))) if _first(interest) else None
    nd_ebitda = _div((debt or 0) - (cash or 0), ebitda) if ebitda and ebitda > 0 and debt is not None else None
    off_high = 1 - price / high if price and high else None
    marks = [
        rule("cover", "Interest covered 5 times", None if financial else (True if int_cover is None and debt == 0 else None if int_cover is None else int_cover >= 5),
             _x(int_cover, 1) + "x" if int_cover is not None else ("no debt" if debt == 0 else "n/a"), "Can pay its lenders in a bad year"),
        rule("leverage", "Net debt under 2 years of EBITDA", None if financial or nd_ebitda is None else nd_ebitda <= 2, _x(nd_ebitda, 1),
             "Room to survive a downturn"),
        rule("liquidity", "Current ratio 1.5+", None if financial or cur_ratio is None else cur_ratio >= 1.5, _x(cur_ratio), "Short-term bills covered"),
        rule("beta", "Moves less than the market (beta under 1)", None if beta is None else beta < 1, _x(beta), "Lower volatility"),
        rule("fallen", "At least 15% below the 52-week high", None if off_high is None else off_high >= 0.15, _pct(off_high),
             "Buying after prices fall, when others are fearful"),
    ]

    lenses = [
        _lens("graham", "Graham: defensive investor", "The Intelligent Investor, chapter 14", graham,
              f"{years} years of filings shown; Graham's tests ask for 10-20." if years and years < 10 else None),
        _lens("buffett", "Buffett-style quality", "Berkshire Hathaway shareholder letters", buffett),
        _lens("lynch", "Lynch", "One Up on Wall Street", lynch),
        _lens("greenblatt", "Greenblatt: magic formula", "The Little Book That Beats the Market", greenblatt, g_note),
        _lens("marks", "Marks-style risk check", "Howard Marks' memos to Oaktree clients", marks),
    ]
    return {"lenses": lenses, "financial_sector": financial, "currency": ccy}


def build(symbol: str, market: str, use_cache: bool = True) -> dict:
    from .analysis_run import yahoo_symbol
    from .compare import _yahoo_info
    from .financials import cached_financials

    if market == "crypto":
        raise ValueError("Investor checklists apply to companies, not crypto")
    key = (symbol, market)
    if use_cache:
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    fin = cached_financials(symbol, market, "annual")
    info = _yahoo_info(yahoo_symbol(symbol, market))
    out = {"symbol": symbol, "market": market, "name": fin.get("name") or symbol, **evaluate(fin, info),
           "source": f"Annual figures: {fin.get('source') or 'reported financial statements'}; price and ratios: market data feed"}
    if use_cache:
        with _lock:
            _cache[key] = (time.time(), out)
    return out
