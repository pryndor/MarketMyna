"""Health check for the mutual funds in a portfolio.

Works without factsheet PDFs: fund stock lists have no free source, so overlap is estimated
from how closely the funds' daily NAV returns move together, plus funds that
sit in the same SEBI category. Category labels come from mfapi.in, e.g.
"Equity Scheme - Mid Cap Fund".
"""

from __future__ import annotations

import pandas as pd

# Indian equity funds mostly correlate 0.85-0.93 with each other, so only near-identical
# daily moves count as overlap; the related band is listed but not penalised.
SIMILAR = 0.95
RELATED = 0.85


_DEBT_WORDS = ("gilt", "bond", "sdl", "debt", "g-sec", "gsec", "liquid", "money market", "psu", "crisil ibx", "t-bill")


def asset_class(category: str, name: str = "") -> str:
    c, n = (category or "").lower(), (name or "").lower()
    if c.startswith("equity"):
        return "Equity"
    if c.startswith("debt"):
        return "Debt"
    if c.startswith("hybrid"):
        return "Hybrid"
    if "index" in c or "etf" in c:  # SEBI files index funds under "Other"; the name tells equity from debt
        if any(w in n for w in _DEBT_WORDS):
            return "Debt"
        if "gold" in n or "silver" in n:
            return "Commodity"
        return "Equity"
    if "fof" in c or "fund of funds" in c:
        return "Fund of funds"
    if c.startswith("solution"):
        return "Solution oriented"
    return "Other"


def sub_category(category: str) -> str:
    """'Equity Scheme - Mid Cap Fund' -> 'Mid Cap Fund'."""
    return (category or "").split(" - ", 1)[-1].strip() or "Unknown"


def insights(funds: list[dict], navs: dict[str, pd.Series]) -> dict:
    """funds: [{symbol, name, category, market_value}]; navs: symbol -> NAV series."""
    funds = [f for f in funds if (f.get("market_value") or 0) > 0]
    total = sum(float(f["market_value"]) for f in funds)
    if not funds or total <= 0:
        return {"funds": 0}

    def short(f: dict) -> str:
        return (f.get("name") or f["symbol"]).split(" - ")[0]

    by_class: dict[str, float] = {}
    by_sub: dict[str, list[dict]] = {}
    for f in funds:
        w = float(f["market_value"]) / total
        cls = asset_class(f.get("category", ""), f.get("name", ""))
        by_class[cls] = by_class.get(cls, 0) + w
        by_sub.setdefault(sub_category(f.get("category", "")), []).append(f)

    issues: list[str] = []
    kinds: list[str] = []  # parallel to issues, for the portfolio review
    score = 100

    top_class, top_w = max(by_class.items(), key=lambda kv: kv[1])
    if len(funds) >= 3 and top_w > 0.9 and top_class not in ("Hybrid", "Fund of funds"):
        score -= 10
        kinds.append("one_asset_class")
        issues.append(f"{top_w:.0%} is in {top_class} funds. Fine for a long horizon, "
                      "but there is no cushion from debt or hybrid funds.")

    same = [(sub, fs) for sub, fs in by_sub.items() if len(fs) > 1 and sub != "Unknown"]
    for sub, fs in same:
        score -= 8
        kinds.append("same_category")
        issues.append(f"{len(fs)} funds in the same category ({sub}): {', '.join(short(f) for f in fs)}. "
                      "They likely hold similar stocks; one may be enough.")

    pairs = []
    rets = pd.DataFrame({s: v.pct_change() for s, v in navs.items() if s in {f["symbol"] for f in funds}}).dropna()
    if rets.shape[1] >= 2 and len(rets) >= 60:
        corr = rets.corr()
        names = {f["symbol"]: short(f) for f in funds}
        cols = list(corr.columns)
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                c = float(corr.loc[a, b])
                if c >= RELATED:
                    pairs.append({"a": a, "b": b, "a_name": names[a], "b_name": names[b], "correlation": c})
        pairs.sort(key=lambda p: -p["correlation"])
        similar = [p for p in pairs if p["correlation"] >= SIMILAR]
        if similar:
            score -= min(24, 6 * len(similar))
            p = similar[0]
            kinds.append("lockstep")
            issues.append(f"{len(similar)} fund pair{'s move' if len(similar) > 1 else ' moves'} almost in lockstep "
                          f"(e.g. {p['a_name']} and {p['b_name']}, correlation {p['correlation']:.2f}), "
                          "so they add little diversification.")

    regular = [f for f in funds if "regular" in (f.get("name") or "").lower()]
    if regular:
        score -= 5 * len(regular)
        kinds.append("regular_plan")
        issues.append(f"{len(regular)} Regular-plan fund{'s' if len(regular) > 1 else ''} "
                      f"({', '.join(short(f) for f in regular)}). Direct plans of the same fund "
                      "charge less (often 0.5-1% a year), which compounds.")

    idcw = [f for f in funds if any(k in (f.get("name") or "").lower() for k in ("idcw", "dividend"))]
    if idcw:
        kinds.append("idcw")
        issues.append(f"{len(idcw)} IDCW / dividend option fund{'s' if len(idcw) > 1 else ''}: payouts are taxed "
                      "at your slab rate; Growth options usually suit long-term investing better.")

    score = max(0, min(100, score))
    return {
        "funds": len(funds),
        "total_value": total,
        "score": score,
        "grade": "Good" if score >= 80 else "Fair" if score >= 60 else "Needs attention",
        "asset_classes": [{"name": k, "weight": v} for k, v in sorted(by_class.items(), key=lambda kv: -kv[1])],
        "categories": [{"name": k, "weight": sum(float(f["market_value"]) for f in fs) / total, "count": len(fs)}
                       for k, fs in sorted(by_sub.items(), key=lambda kv: -sum(float(f["market_value"]) for f in kv[1]))],
        "similar_pairs": pairs[:10],
        "issues": issues,
        "issue_kinds": kinds,
        "method": "Overlap is estimated from 1 year of daily NAV moves and shared categories, not from fund stock lists.",
    }
