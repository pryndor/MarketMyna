"""What a mutual fund costs you and how its gains are taxed.

Direct vs Regular: the two plans of a scheme hold the same portfolio; the
Regular plan pays a distributor commission out of its expense ratio, so its
NAV grows a little slower every year. The gap is measured from the two
plans' own NAV histories (no expense-ratio file needed) and turned into
rupees over 10 years.

Tax: the rules in force for redemptions since 23 July 2024 (Budget 2024 /
Finance Act 2025), by how the fund is taxed:
  equity   (>= 65% in Indian shares; also arbitrage, equity savings,
            aggressive hybrid): held up to 12 months 20%; longer 12.5% on
            gains above Rs 1.25 lakh a year
  debt     ("specified" funds, mostly bonds) bought on / after 1 Apr 2023:
            your slab rate however long you hold
  other    (gold, international, balanced / multi-asset not run as equity):
            held over 24 months 12.5%, otherwise your slab rate
Health & education cess of 4% applies on top; surcharge is left out. A
guide, not tax advice.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

RULES_DATE = "2024-07-23"
EQUITY_WORDS = ("large cap", "mid cap", "small cap", "large & mid", "flexi cap", "multi cap", "elss", "focused",
                "value", "contra", "dividend yield", "sectoral", "thematic", "equity", "aggressive hybrid",
                "arbitrage", "growth (close ended)")
DEBT_WORDS = ("liquid", "overnight", "money market", "ultra short", "low duration", "short duration", "short term",
              "medium", "long duration", "long term", "dynamic bond", "dynamic term", "corporate bond", "credit risk",
              "banking and psu", "gilt", "floater", "floating", "income", "debt", "conservative hybrid",
              "fixed maturity", "interval")
INDEX_DEBT_WORDS = ("gilt", "bond", "sdl", "g-sec", "gsec", "debt", "liquid", "t-bill", "crisil", "psu")
INDEX_OTHER_WORDS = ("gold", "silver", "nasdaq", "s&p", "us ", "global", "international", "hang seng")


def tax_class(category: Optional[str], name: str = "") -> str:
    """equity | debt | other, from the SEBI category (and the name for index funds / ETFs)."""
    cat, nm = (category or "").lower(), (name or "").lower()
    if "index" in cat or "etf" in cat or "fund of funds" in cat or cat.startswith("fof"):
        if any(w in nm for w in INDEX_OTHER_WORDS):
            return "other"
        if any(w in nm for w in INDEX_DEBT_WORDS):
            return "debt"
        return "equity" if ("index" in cat or "equity" in cat) else "other"
    if any(w in cat for w in DEBT_WORDS):
        return "debt"
    if any(w in cat for w in EQUITY_WORDS):
        return "equity"
    return "other"


RULES = {
    "equity": {"label": "Equity fund", "short_months": 12, "short_rate": 20.0, "long_rate": 12.5,
               "exemption": 125000, "short_slab": False, "long_slab": False,
               "text": "Held up to 12 months: 20%. Longer: 12.5% on gains above ₹1.25 lakh a year "
                       "(the ₹1.25 lakh is shared by all your equity gains in the year)."},
    "debt": {"label": "Debt fund", "short_months": None, "short_rate": None, "long_rate": None,
             "exemption": 0, "short_slab": True, "long_slab": True,
             "text": "Bought on or after 1 April 2023: taxed at your income-tax slab rate however long you hold. "
                     "(Units bought earlier and held over 24 months: 12.5%.)"},
    "other": {"label": "Other fund (gold, international, hybrid)", "short_months": 24, "short_rate": None,
              "long_rate": 12.5, "exemption": 0, "short_slab": True, "long_slab": False,
              "text": "Held over 24 months: 12.5%. Otherwise your slab rate."},
}
CESS = 4.0
# Return assumed for the rupee illustration (a plain long-run guess, not the fund's past return)
ASSUMED_RETURN = {"equity": 12.0, "debt": 7.0, "other": 9.0}


def base_name(name: str) -> str:
    return (name or "").split(" - ")[0].strip().lower()


def sibling(row: dict, rows: list[dict]) -> Optional[dict]:
    """The other plan (Direct <-> Regular) of the same scheme and option."""
    want = "Regular" if row.get("plan") == "Direct" else "Direct"
    key, amc, option = base_name(row["name"]), row.get("amc"), (row.get("option") or "").lower()
    same = [r for r in rows if r.get("type") == "mf" and r.get("plan") == want and r.get("amc") == amc
            and base_name(r["name"]) == key]
    exact = [r for r in same if (r.get("option") or "").lower() == option]
    return (exact or [r for r in same if "growth" in (r.get("option") or "").lower()] or [None])[0]


def plan_gap(direct: pd.Series, regular: pd.Series, years: int = 3) -> Optional[dict]:
    """Annualised return of each plan over the same last `years` and the gap."""
    a, b = direct.sort_index(), regular.sort_index()
    end = min(a.index.max(), b.index.max())
    start = end - pd.DateOffset(years=years)
    if max(a.index.min(), b.index.min()) > start + pd.Timedelta(days=10):
        return None

    def cagr(s: pd.Series) -> Optional[float]:
        s0, s1 = s[s.index <= start], s[s.index <= end]
        if s0.empty or s1.empty or s0.iloc[-1] <= 0:
            return None
        return ((s1.iloc[-1] / s0.iloc[-1]) ** (1 / years) - 1) * 100

    d, r = cagr(a), cagr(b)
    if d is None or r is None:
        return None
    return {"years": years, "direct": d, "regular": r, "gap": d - r, "from": str(start.date()), "to": str(end.date())}


def cost_in_rupees(rate: float, gap: float, years: int = 10, lumpsum: float = 100000, sip: float = 10000) -> dict:
    """What the gap costs: lumpsum and monthly SIP grown at the Direct rate vs Direct minus the gap."""
    def grow(r):
        return lumpsum * (1 + r / 100) ** years

    def sip_value(r):
        m = (1 + r / 100) ** (1 / 12) - 1
        n = years * 12
        return sip * (((1 + m) ** n - 1) / m) * (1 + m) if m else sip * n

    return {"years": years, "lumpsum": lumpsum, "sip": sip,
            "lumpsum_direct": grow(rate), "lumpsum_regular": grow(rate - gap),
            "sip_direct": sip_value(rate), "sip_regular": sip_value(rate - gap)}


def build(code: str, rows: Optional[list[dict]] = None, nav=None) -> dict:
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows("india")
    if nav is None:
        from .fund_peers import nav
    row = next((r for r in rows if r.get("type") == "mf" and str(r["symbol"]) == str(code)), None)
    if row is None:
        return {"status": "unknown", "note": "No such scheme."}
    cls = tax_class(row.get("sector"), row.get("name", ""))
    out = {"status": "ok", "code": str(code), "plan": row.get("plan"), "tax_class": cls,
           "tax": {**RULES[cls], "cess": CESS, "rules_from": RULES_DATE}, "plans": None, "cost": None}
    sib = sibling(row, rows)
    if sib:
        direct, regular = (row, sib) if row.get("plan") == "Direct" else (sib, row)
        dn, rn = nav(str(direct["symbol"])), nav(str(regular["symbol"]))
        if dn is not None and rn is not None and len(dn) and len(rn):
            gap = plan_gap(dn, rn, 3) or plan_gap(dn, rn, 1)
            if gap:
                out["plans"] = {**gap, "direct_code": str(direct["symbol"]), "regular_code": str(regular["symbol"]),
                                "direct_name": direct["name"], "regular_name": regular["name"]}
                out["cost"] = {**cost_in_rupees(ASSUMED_RETURN[cls], max(gap["gap"], 0.0)),
                               "assumed_return": ASSUMED_RETURN[cls]}
    return out
