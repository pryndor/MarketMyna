"""Accounting quality scores from a company's last three annual statements,
rebuilt from the published papers:

- Piotroski F-score (Piotroski 2000): nine pass / fail tests on profitability,
  leverage / liquidity and efficiency, latest year against the one before.
- Altman Z-score (Altman 1968) for manufacturers, which needs the market
  value of equity; Z'' (Altman 1995) for everyone else, on book equity.
  Banks and insurers are skipped by all three scores: lending shows up as
  operating cash flow, and they have no gross margin or current ratio.
- Beneish M-score (Beneish 1999, 8 ratios): how far the statements look like
  those of companies later found to have overstated earnings. Above -1.78 is
  the paper's flag. A ratio that cannot be worked out is set to 1 (no change)
  and listed.

Input is financials.py's {key: [value per year, newest first]} for the
income statement, balance sheet and cash flow. The scores describe the
filings; they are not a rating or advice.
"""

from __future__ import annotations

from typing import Optional

from ..core.numbers import ratio as _div

# Sectors scored with Altman's original model (built on listed manufacturers,
# needs market value); the rest (services, real estate, utilities, telecom,
# media) get Z'' on book equity
MANUFACTURING = {"Industrials", "Basic Materials", "Consumer Cyclical", "Consumer Defensive", "Energy",
                 "Healthcare", "Technology"}


def _v(series: dict, key: str, i: int) -> Optional[float]:
    vals = series.get(key) or []
    return vals[i] if i < len(vals) else None


def _r(x: Optional[float], digits: int = 3) -> Optional[float]:
    return round(x, digits) if x is not None else None


# ------------------------------------------------------------------ Piotroski

def piotroski(inc: dict, bal: dict, cf: dict, financial: bool = False) -> Optional[dict]:
    if financial:
        return None
    ni0, ni1 = _v(inc, "net_income", 0), _v(inc, "net_income", 1)
    ta0, ta1, ta2 = (_v(bal, "total_assets", i) for i in range(3))
    if ni0 is None or ta0 is None or ta1 is None:
        return None
    cfo = _v(cf, "operating_cf", 0)
    # ROA on assets at the start of the year (the paper's definition)
    roa0 = _div(ni0, ta1)
    roa1 = _div(ni1, ta2 if ta2 is not None else ta1)

    def ratio(num_key: str, den_key: str, i: int):
        return _div(_v(bal, num_key, i), _v(bal, den_key, i))

    lev0, lev1 = ratio("total_debt", "total_assets", 0), ratio("total_debt", "total_assets", 1)
    cr0, cr1 = ratio("current_assets", "current_liabilities", 0), ratio("current_assets", "current_liabilities", 1)
    sh0, sh1 = _v(bal, "shares", 0), _v(bal, "shares", 1)
    gm0 = _div(_v(inc, "gross_profit", 0), _v(inc, "revenue", 0))
    gm1 = _div(_v(inc, "gross_profit", 1), _v(inc, "revenue", 1))
    if gm0 is not None and gm1 is not None and gm0 >= 0.999 and gm1 >= 0.999:
        gm0 = gm1 = None  # no cost of goods reported (services): margin untestable
    at0 = _div(_v(inc, "revenue", 0), ta1)
    at1 = _div(_v(inc, "revenue", 1), ta2 if ta2 is not None else ta1)

    def test(key, label, ok, detail):
        return {"key": key, "label": label, "pass": ok, "detail": detail}

    def pct(x):
        return f"{x * 100:.1f}%" if x is not None else "n/a"

    tests = [
        test("roa", "Profitable (return on assets above 0)", None if roa0 is None else roa0 > 0, f"ROA {pct(roa0)}"),
        test("cfo", "Cash from operations above 0", None if cfo is None else cfo > 0, "positive" if cfo and cfo > 0 else "zero or negative" if cfo is not None else "n/a"),
        test("roa_up", "Return on assets improved", None if roa0 is None or roa1 is None else roa0 > roa1, f"{pct(roa1)} to {pct(roa0)}"),
        test("accruals", "Cash from operations above net income", None if cfo is None else cfo > ni0, "earnings backed by cash" if cfo is not None and cfo > ni0 else "earnings ahead of cash" if cfo is not None else "n/a"),
        test("leverage", "Debt to assets fell", None if lev0 is None or lev1 is None else lev0 <= lev1, f"{pct(lev1)} to {pct(lev0)}"),
        test("liquidity", "Current ratio improved", None if cr0 is None or cr1 is None else cr0 > cr1,
             f"{cr1:.2f} to {cr0:.2f}" if cr0 is not None and cr1 is not None else "n/a"),
        test("dilution", "No new shares issued", None if sh0 is None or sh1 is None else sh0 <= sh1 * 1.001,
             f"{(sh0 / sh1 - 1) * 100:+.1f}% shares" if sh0 and sh1 else "n/a"),
        test("margin", "Gross margin improved", None if gm0 is None or gm1 is None else gm0 > gm1, f"{pct(gm1)} to {pct(gm0)}"),
        test("turnover", "Asset turnover improved", None if at0 is None or at1 is None else at0 > at1,
             f"{at1:.2f}x to {at0:.2f}x" if at0 is not None and at1 is not None else "n/a"),
    ]
    tested = [t for t in tests if t["pass"] is not None]
    if len(tested) < 5:
        return None
    score = sum(1 for t in tested if t["pass"])
    if len(tested) == 9:
        label = "strong" if score >= 7 else "weak" if score <= 3 else "average"
    else:
        share = score / len(tested)
        label = "strong" if share >= 0.75 else "weak" if share <= 0.35 else "average"
    return {"score": score, "out_of": len(tested), "label": label, "tests": tests}


# ------------------------------------------------------------------ Altman

def altman(inc: dict, bal: dict, sector: Optional[str], market_cap: Optional[float],
           financial: bool = False) -> Optional[dict]:
    if financial:
        return None
    ta = _v(bal, "total_assets", 0)
    tl = _v(bal, "total_liabilities", 0)
    ca, cl = _v(bal, "current_assets", 0), _v(bal, "current_liabilities", 0)
    re_ = _v(bal, "retained_earnings", 0)
    ebit = _v(inc, "operating_income", 0)
    if ebit is None and _v(inc, "pretax_income", 0) is not None:
        ebit = _v(inc, "pretax_income", 0) + (abs(_v(inc, "interest_expense", 0) or 0))
    sales = _v(inc, "revenue", 0)
    equity = _v(bal, "equity", 0)
    if not ta or not tl or ca is None or cl is None or re_ is None or ebit is None:
        return None
    x1, x2, x3 = (ca - cl) / ta, re_ / ta, ebit / ta

    if sector in MANUFACTURING and market_cap and sales is not None:
        x4, x5 = market_cap / tl, sales / ta
        z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5
        model, safe, distress = "Z (manufacturers)", 2.99, 1.81
        parts = {"working_capital": x1, "retained_earnings": x2, "ebit": x3, "market_value_to_liabilities": x4, "sales": x5}
    else:
        if equity is None:
            return None
        x4 = equity / tl
        z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
        model, safe, distress = "Z'' (non-manufacturers, book equity)", 2.6, 1.1
        parts = {"working_capital": x1, "retained_earnings": x2, "ebit": x3, "book_equity_to_liabilities": x4}
    zone = "safe" if z > safe else "distress" if z < distress else "grey"
    return {"score": round(z, 2), "model": model, "zone": zone, "safe_above": safe, "distress_below": distress,
            "parts": {k: _r(v) for k, v in parts.items()}}


# ------------------------------------------------------------------ Beneish

def beneish(inc: dict, bal: dict, cf: dict, financial: bool = False) -> Optional[dict]:
    if financial:
        return None
    s0, s1 = _v(inc, "revenue", 0), _v(inc, "revenue", 1)
    ta0, ta1 = _v(bal, "total_assets", 0), _v(bal, "total_assets", 1)
    ni0, cfo0 = _v(inc, "net_income", 0), _v(cf, "operating_cf", 0)
    if not s0 or not s1 or not ta0 or not ta1 or ni0 is None or cfo0 is None:
        return None

    def at(key, i, src=bal):
        return _v(src, key, i)

    rec0, rec1 = at("receivables", 0), at("receivables", 1)
    gm0, gm1 = _div(at("gross_profit", 0, inc), s0), _div(at("gross_profit", 1, inc), s1)
    ppe0, ppe1 = at("ppe", 0), at("ppe", 1)
    ca0, ca1 = at("current_assets", 0), at("current_assets", 1)
    dep0, dep1 = abs(at("depreciation", 0, cf) or 0) or None, abs(at("depreciation", 1, cf) or 0) or None
    sga0, sga1 = at("sga", 0, inc), at("sga", 1, inc)
    tl0, tl1 = at("total_liabilities", 0), at("total_liabilities", 1)

    def quality(ca, ppe, ta):
        return 1 - (ca + ppe) / ta if ca is not None and ppe is not None else None

    def dep_rate(dep, ppe):
        return dep / (dep + ppe) if dep is not None and ppe is not None and dep + ppe else None

    ratios = {
        "DSRI": _div(_div(rec0, s0), _div(rec1, s1)),       # receivables growing faster than sales
        "GMI": _div(gm1, gm0),                               # gross margin falling
        "AQI": _div(quality(ca0, ppe0, ta0), quality(ca1, ppe1, ta1)),  # more soft assets
        "SGI": s0 / s1,                                      # sales growth
        "DEPI": _div(dep_rate(dep1, ppe1), dep_rate(dep0, ppe0)),  # slower depreciation
        "SGAI": _div(_div(sga0, s0), _div(sga1, s1)),        # overheads per sale
        "LVGI": _div(_div(tl0, ta0), _div(tl1, ta1)),        # more leverage
        "TATA": (ni0 - cfo0) / ta0,                          # accruals
    }
    if ratios["DSRI"] is None:
        return None
    neutral = [k for k, v in ratios.items() if v is None]
    vals = {k: (1.0 if v is None else v) for k, v in ratios.items()}
    m = (-4.84 + 0.920 * vals["DSRI"] + 0.528 * vals["GMI"] + 0.404 * vals["AQI"] + 0.892 * vals["SGI"]
         + 0.115 * vals["DEPI"] - 0.172 * vals["SGAI"] + 4.679 * vals["TATA"] - 0.327 * vals["LVGI"])
    return {"score": round(m, 2), "flag": m > -1.78, "threshold": -1.78,
            "ratios": {k: _r(v) for k, v in ratios.items()}, "neutral": neutral}


def compute(inc: dict, bal: dict, cf: dict, *, sector: Optional[str] = None,
            market_cap: Optional[float] = None, financial: bool = False) -> Optional[dict]:
    out = {
        "piotroski": piotroski(inc, bal, cf, financial),
        "altman": altman(inc, bal, sector, market_cap, financial),
        "beneish": beneish(inc, bal, cf, financial),
    }
    if financial:
        return {**out, "financial_sector": True,
                "note": "Not scored: these models are built for non-financial companies. Banks and insurers "
                        "book lending as operating cash flow and have no gross margin or current ratio."}
    if not any(out.values()):
        return None
    out["financial_sector"] = False
    return out
