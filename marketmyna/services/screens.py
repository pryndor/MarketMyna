"""Ready-made fundamental screens (OpenBB equity.discovery: undervalued large
caps, growth at a reasonable price, ...) built on free data.

The universe is the largest stocks of a market by market cap from our own
listings; each is enriched with Yahoo fundamentals (shared 6-hour cache with
the Compare page) and checked against the preset's rules. The first run of a
market takes ~20-40 s; later presets reuse the cache.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from ..core.numbers import finite as _f
from ..core.numbers import median as _median

UNIVERSE = 200
LARGE = 100  # "large cap" = top 100 by market cap in that market

# field -> (yahoo key, transform)
FIELDS: dict[str, tuple[str, Callable[[float], float]]] = {
    "pe": ("trailingPE", lambda v: v),
    "forward_pe": ("forwardPE", lambda v: v),
    "pb": ("priceToBook", lambda v: v),
    "peg": ("trailingPegRatio", lambda v: v),
    "roe": ("returnOnEquity", lambda v: v * 100),
    "debt_equity": ("debtToEquity", lambda v: v / 100),
    "dividend_yield": ("dividendYield", lambda v: v),  # Yahoo already gives percent
    "payout": ("payoutRatio", lambda v: v * 100),
    "earnings_growth": ("earningsGrowth", lambda v: v * 100),
    "revenue_growth": ("revenueGrowth", lambda v: v * 100),
    "operating_margin": ("operatingMargins", lambda v: v * 100),
    # Extra fields for custom screens (the presets don't use them).
    "ps": ("priceToSalesTrailing12Months", lambda v: v),
    "ev_ebitda": ("enterpriseToEbitda", lambda v: v),
    "ev_revenue": ("enterpriseToRevenue", lambda v: v),
    "roa": ("returnOnAssets", lambda v: v * 100),
    "gross_margin": ("grossMargins", lambda v: v * 100),
    "ebitda_margin": ("ebitdaMargins", lambda v: v * 100),
    "profit_margin": ("profitMargins", lambda v: v * 100),
    "earnings_q_growth": ("earningsQuarterlyGrowth", lambda v: v * 100),
    "avg_dividend_yield_5y": ("fiveYearAvgDividendYield", lambda v: v),  # percent already
    "current_ratio": ("currentRatio", lambda v: v),
    "quick_ratio": ("quickRatio", lambda v: v),
    "beta": ("beta", lambda v: v),
    "change_52w": ("52WeekChange", lambda v: v * 100),
    "analyst_rating": ("recommendationMean", lambda v: v),
    "analysts": ("numberOfAnalystOpinions", lambda v: v),
    "insiders": ("heldPercentInsiders", lambda v: v * 100),
    "institutions": ("heldPercentInstitutions", lambda v: v * 100),
}

LABELS = {
    "pe": "P/E", "forward_pe": "Fwd P/E", "pb": "P/B", "peg": "PEG", "roe": "ROE %", "debt_equity": "Debt/Eq",
    "dividend_yield": "Div yield %", "payout": "Payout %", "earnings_growth": "EPS growth %",
    "revenue_growth": "Rev growth %", "operating_margin": "Op margin %", "from_high": "From 52w high %",
    "from_low": "Above 52w low %",
    "sector": "Sector", "sector_pe": "Sector P/E", "pe_vs_sector": "P/E × sector", "pb_vs_sector": "P/B × sector",
    "peg_calc": "PEG", "growth_short": "earnings growth too low for the P/E (PEG > 2 or shrinking)",
    "ps": "P/S", "ev_ebitda": "EV/EBITDA", "ev_revenue": "EV/Revenue", "earnings_yield": "Earnings yield %",
    "fcf_yield": "FCF yield %", "roa": "ROA %", "gross_margin": "Gross margin %", "ebitda_margin": "EBITDA margin %",
    "profit_margin": "Net margin %", "earnings_q_growth": "Quarterly EPS growth %", "forward_eps_growth": "Fwd EPS growth %",
    "avg_dividend_yield_5y": "5y avg div yield %", "current_ratio": "Current ratio", "quick_ratio": "Quick ratio",
    "beta": "Beta", "change_52w": "1y return %", "market_cap": "Market cap", "price": "Price",
    "target_upside": "Target upside %", "analyst_rating": "Analyst rating", "analysts": "Analysts",
    "insiders": "Insiders %", "institutions": "Institutions %",
}

# Custom-screen catalogue: group -> metrics, with a hint for the builder.
CATALOGUE: list[tuple[str, list[tuple[str, str]]]] = [
    ("Valuation", [("pe", "Price / trailing earnings per share"), ("forward_pe", "Price / next year's expected earnings"),
                   ("pb", "Price / book value per share"), ("ps", "Market cap / yearly revenue"),
                   ("peg", "P/E / expected earnings growth"), ("ev_ebitda", "Enterprise value / EBITDA"),
                   ("ev_revenue", "Enterprise value / revenue"), ("earnings_yield", "Earnings / price, the P/E upside down"),
                   ("fcf_yield", "Free cash flow / market cap")]),
    ("Profitability", [("roe", "Profit / shareholders' equity"), ("roa", "Profit / total assets"),
                       ("gross_margin", "Gross profit / revenue"), ("operating_margin", "Operating profit / revenue"),
                       ("ebitda_margin", "EBITDA / revenue"), ("profit_margin", "Net profit / revenue")]),
    ("Growth", [("revenue_growth", "Latest quarter vs the same quarter a year earlier"),
                ("earnings_growth", "Latest quarter EPS vs a year earlier"),
                ("earnings_q_growth", "Latest quarter net profit vs a year earlier"),
                ("forward_eps_growth", "Next year's expected EPS vs the last 12 months")]),
    ("Dividends", [("dividend_yield", "Yearly dividend / price"), ("avg_dividend_yield_5y", "Average yield over 5 years"),
                   ("payout", "Share of profit paid as dividends")]),
    ("Balance sheet", [("debt_equity", "Total debt / equity"), ("current_ratio", "Current assets / current liabilities"),
                       ("quick_ratio", "Current assets minus stock / current liabilities")]),
    ("Price & size", [("market_cap", "In the listing's currency"), ("price", "Last price"),
                      ("change_52w", "Price change over the past year"), ("from_high", "Distance below the 52-week high (negative)"),
                      ("from_low", "Distance above the 52-week low"), ("beta", "Moves vs the market: 1 = same, above 1 = swings more")]),
    ("Analysts", [("target_upside", "Average target price vs the current price"),
                  ("analyst_rating", "1 = strong buy, 3 = hold, 5 = sell"), ("analysts", "Analysts covering the stock")]),
    ("Ownership", [("insiders", "Shares held by promoters / insiders"), ("institutions", "Shares held by institutions")]),
]
CUSTOM_FIELDS = {k for _, items in CATALOGUE for k, _ in items}
# Ratios whose sector median only means something over positive values.
POSITIVE_ONLY = {"pe", "forward_pe", "pb", "ps", "peg", "ev_ebitda", "ev_revenue"}
CUSTOM_OPS = (">", "<", "between", "top", "bottom", "below_sector", "above_sector")
MAX_RULES = 12

# Ratios the feed works out from statements in the reporting currency against
# a price in the listing currency (TSM: TWD accounts, USD shares), so they are
# wrong by the exchange rate whenever the two differ.
MIXED_CURRENCY = ("pb", "ps", "ev_ebitda", "ev_revenue", "fcf_yield")

SECTOR_MIN_PEERS = 5  # profitable companies a sector needs before its median means anything

# key: title, description, large caps only?, [(field, op, value)], sort (field, descending), columns
PRESETS = {
    "undervalued_large": ("Low-multiple large caps", "Large, profitable companies with P/E under 18 and P/B under 3",
                          True, [("pe", "between", (0, 18)), ("pb", "<", 3), ("roe", ">", 12), ("earnings_growth", ">", 0)],
                          ("pe", False), ["pe", "pb", "roe", "earnings_growth", "dividend_yield"]),
    "garp": ("Growth at a modest P/E", "EPS growth over 15% and revenue growth over 8% with P/E under 30",
             False, [("earnings_growth", ">", 15), ("revenue_growth", ">", 8), ("pe", "between", (0, 30)), ("roe", ">", 15),
                     ("debt_equity", "<", 1)],
             ("earnings_growth", True), ["pe", "earnings_growth", "revenue_growth", "roe", "debt_equity"]),
    "dividend": ("High dividend, low debt", "Dividend yield over 3%, debt under half of equity, payout under 85%",
                 False, [("dividend_yield", ">", 3), ("debt_equity", "<", 0.5), ("payout", "between", (0, 85))],
                 ("dividend_yield", True), ["dividend_yield", "payout", "debt_equity", "pe", "roe"]),
    "quality": ("High ROE, low debt", "ROE over 20%, operating margin over 18%, little debt, revenue still growing",
                False, [("roe", ">", 20), ("operating_margin", ">", 18), ("debt_equity", "<", 0.5), ("revenue_growth", ">", 8)],
                ("roe", True), ["roe", "operating_margin", "revenue_growth", "debt_equity", "pe"]),
    "debt_free": ("Debt-free and profitable", "Debt under 0.1x equity and ROE over 15%",
                  False, [("debt_equity", "<", 0.1), ("roe", ">", 15), ("pe", ">", 0)],
                  ("roe", True), ["debt_equity", "roe", "pe", "operating_margin", "dividend_yield"]),
    # Relative, not absolute: a P/E of 40 is cheap for one sector and dear for
    # another, so each stock is compared with the median of its own sector
    # among the same largest-200 universe (see _sector_relative).
    "expensive_sector": ("P/E far above sector", "P/E over 1.5x the sector median while earnings growth trails the sector",
                         False, [("pe_vs_sector", ">", 1.5), ("growth_short", "is", True)],
                         ("pe_vs_sector", True), ["sector", "pe", "sector_pe", "pe_vs_sector", "pb_vs_sector", "earnings_growth", "peg_calc"]),
    "near_low": ("Quality near 52-week low", "Profitable companies trading close to their yearly low",
                 False, [("from_low", "<", 10), ("roe", ">", 12), ("pe", ">", 0)],
                 ("from_low", False), ["from_low", "from_high", "pe", "roe", "debt_equity"]),
}

InfoFetch = Callable[[str], dict]


def metrics(info: dict) -> dict:
    out = {}
    for field, (key, fn) in FIELDS.items():
        v = _f(info.get(key))
        out[field] = fn(v) if v is not None else None
    price, hi, lo = (_f(info.get(k)) for k in ("currentPrice", "fiftyTwoWeekHigh", "fiftyTwoWeekLow"))
    out["from_high"] = (price / hi - 1) * 100 if price and hi else None
    out["from_low"] = (price / lo - 1) * 100 if price and lo else None
    pe, cap, fcf = out["pe"], _f(info.get("marketCap")), _f(info.get("freeCashflow"))
    out["earnings_yield"] = 100 / pe if pe and pe > 0 else None
    out["fcf_yield"] = fcf / cap * 100 if fcf is not None and cap else None
    fwd, trail = _f(info.get("forwardEps")), _f(info.get("trailingEps"))
    out["forward_eps_growth"] = (fwd / trail - 1) * 100 if fwd is not None and trail and trail > 0 else None
    target = _f(info.get("targetMeanPrice"))
    out["target_upside"] = (target / price - 1) * 100 if target and price else None
    books, quote = info.get("financialCurrency"), info.get("currency")
    if books and quote and books != quote:
        for field in MIXED_CURRENCY:
            out[field] = None
    return out


def _passes(m: dict, rules: list) -> bool:
    for field, op, value in rules:
        v = m.get(field)
        if v is None:
            return False
        if op == ">" and not v > value:
            return False
        if op == "<" and not v < value:
            return False
        if op == "between" and not value[0] < v < value[1]:
            return False
        if op == "is" and v is not value:
            return False
    return True


def list_presets() -> list[dict]:
    return [{"key": k, "title": p[0], "description": p[1], "large_only": p[2],
             "rules": [_rule_text(r) for r in p[3]]} for k, p in PRESETS.items()]


def _rule_text(rule) -> str:
    field, op, value = rule
    label = LABELS.get(field, field)
    if op == "between":
        return f"{label} {value[0]:g}–{value[1]:g}"
    if op == "is":
        return label[:1].upper() + label[1:]
    return f"{label} {op} {value:g}"


def _sector_relative(ms: list[dict]) -> None:
    """Adds sector_pe, pe_vs_sector, pb_vs_sector, peg_calc and growth_short
    in place. Medians use profitable companies only (P/E > 0) and need
    SECTOR_MIN_PEERS of them; otherwise the relative fields stay None."""
    by_sector: dict[str, list[dict]] = {}
    for m in ms:
        if m.get("sector") and (m.get("pe") or 0) > 0:
            by_sector.setdefault(m["sector"], []).append(m)
    for m in ms:
        pe, pb, growth = m.get("pe"), m.get("pb"), m.get("earnings_growth")
        peers = by_sector.get(m.get("sector") or "", [])
        m["sector_pe"] = m["pe_vs_sector"] = m["pb_vs_sector"] = None
        if len(peers) >= SECTOR_MIN_PEERS and pe and pe > 0:
            sector_pe = _median([p["pe"] for p in peers])
            sector_pb = _median([p["pb"] for p in peers if (p.get("pb") or 0) > 0])
            m["sector_pe"] = sector_pe
            m["pe_vs_sector"] = pe / sector_pe if sector_pe else None
            m["pb_vs_sector"] = pb / sector_pb if pb and pb > 0 and sector_pb else None
        m["peg_calc"] = pe / growth if pe and pe > 0 and growth and growth > 0 else None
        # Growth that doesn't carry the multiple: shrinking earnings, or PEG > 2.
        m["growth_short"] = (growth is not None and growth <= 0) or (m["peg_calc"] is not None and m["peg_calc"] > 2)


def _measure(market: str, large_only: bool, info_fetch: Optional[InfoFetch], rows: Optional[list[dict]]) -> list[tuple]:
    """(listing row, info, metrics) for the largest stocks of a market, with
    the sector-relative fields filled in."""
    from .analysis_run import yahoo_symbol
    from .compare import _yahoo_info

    info_fetch = info_fetch or _yahoo_info
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows(market)
    stocks = sorted((r for r in rows if r.get("type") == "stock" and r.get("market_cap")),
                    key=lambda r: -r["market_cap"])[:UNIVERSE]
    if large_only:
        stocks = stocks[:LARGE]
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = list(pool.map(lambda r: info_fetch(yahoo_symbol(r["symbol"], market)), stocks))

    measured = [(r, info, metrics(info)) for r, info in zip(stocks, infos) if info]
    for r, info, m in measured:
        m["sector"] = info.get("sector") or r.get("sector")
        m["market_cap"] = r["market_cap"]
        m["price"] = r.get("price")
    _sector_relative([m for _, _, m in measured])
    return measured


def _hits(measured: list[tuple], market: str, passes: Callable[[dict], bool], columns: list[str],
          sort_field: str, desc_sort: bool) -> list[dict]:
    hits, seen = [], set()
    for r, info, m in measured:
        company = (info.get("longName") or info.get("shortName") or r["symbol"]).lower()
        if company in seen:  # second share class of the same company (BRK-A / BRK-B)
            continue
        if passes(m):
            seen.add(company)
            hits.append({"symbol": r["symbol"], "name": r.get("name"), "market": market,
                         "market_cap": r["market_cap"], "price": r.get("price"), "currency": r.get("currency"),
                         "change_percent": r.get("change_percent"), "sector": m["sector"],
                         **{c: m.get(c) for c in columns}})
    hits.sort(key=lambda h: (h.get(sort_field) is None, -(h.get(sort_field) or 0) if desc_sort else (h.get(sort_field) or 0)))
    return hits


def run(key: str, market: str, info_fetch: Optional[InfoFetch] = None, rows: Optional[list[dict]] = None) -> dict:
    if key not in PRESETS:
        raise ValueError(f"Unknown screen '{key}'")
    title, desc, large_only, rules, (sort_field, desc_sort), columns = PRESETS[key]
    measured = _measure(market, large_only, info_fetch, rows)
    hits = _hits(measured, market, lambda m: _passes(m, rules), columns, sort_field, desc_sort)
    return {
        "key": key, "title": title, "description": desc, "market": market,
        "rules": [_rule_text(r) for r in rules],
        "columns": [{"key": c, "label": LABELS.get(c, c)} for c in columns],
        "universe": f"Largest {LARGE if large_only else UNIVERSE} stocks by market cap",
        "scanned": len(measured),
        "results": hits,
    }


# ---- custom screens ---------------------------------------------------------

def catalogue() -> list[dict]:
    return [{"group": g, "metrics": [{"key": k, "label": LABELS[k], "hint": h} for k, h in items]} for g, items in CATALOGUE]


class RuleError(ValueError):
    """A custom-screen rule the user has to fix; the message is shown as is."""


def validate(rules: list[dict]) -> list[dict]:
    """Clean rules: known field and op, numeric values, `between` ordered.
    Raises RuleError with a message fit for the user."""
    if not rules:
        raise RuleError("Add at least one rule")
    if len(rules) > MAX_RULES:
        raise RuleError(f"At most {MAX_RULES} rules")
    out = []
    for r in rules:
        field, op = r.get("field"), r.get("op")
        if field not in CUSTOM_FIELDS:
            raise RuleError(f"Unknown metric '{field}'")
        if op not in CUSTOM_OPS:
            raise RuleError(f"Unknown operator '{op}'")
        value = _f(r.get("value"))
        if value is None and op not in ("below_sector", "above_sector"):
            raise RuleError(f"{LABELS[field]}: enter a number")
        rule = {"field": field, "op": op, "value": value}
        if op == "between":
            hi = _f(r.get("value2"))
            if hi is None:
                raise RuleError(f"{LABELS[field]}: enter both ends of the range")
            rule["value"], rule["value2"] = min(value, hi), max(value, hi)
        if op in ("top", "bottom") and not 0 < value <= 100:
            raise RuleError(f"{LABELS[field]}: top / bottom takes a percent from 1 to 100")
        if op in ("below_sector", "above_sector"):
            rule["value"] = value if value and value > 0 else 1.0
        out.append(rule)
    return out


def custom_rule_text(rule: dict) -> str:
    label, op, v = LABELS[rule["field"]], rule["op"], rule["value"]
    if op == "between":
        return f"{label} {v:g}–{rule['value2']:g}"
    if op in ("top", "bottom"):
        return f"{label} in the {op} {v:g}%"
    if op in ("below_sector", "above_sector"):
        side = "below" if op == "below_sector" else "above"
        return f"{label} {side} sector median" + (f" × {v:g}" if v != 1 else "")
    return f"{label} {op} {v:g}"


def _percentile_cut(values: list[float], pct: float, top: bool) -> float:
    """Value a stock must reach to be in the top (or bottom) `pct` percent."""
    ordered = sorted(values, reverse=top)
    n = max(1, round(len(ordered) * pct / 100))
    return ordered[min(n, len(ordered)) - 1]


def _sector_medians(ms: list[dict], field: str) -> dict[str, float]:
    by: dict[str, list[float]] = {}
    for m in ms:
        v = m.get(field)
        if m.get("sector") and v is not None and (v > 0 or field not in POSITIVE_ONLY):
            by.setdefault(m["sector"], []).append(v)
    return {s: _median(vs) for s, vs in by.items() if len(vs) >= SECTOR_MIN_PEERS}


def run_custom(market: str, rules: list[dict], sectors: Optional[list[str]] = None, sort: Optional[str] = None,
               descending: bool = True, columns: Optional[list[str]] = None, large_only: bool = False,
               info_fetch: Optional[InfoFetch] = None, rows: Optional[list[dict]] = None) -> dict:
    """Run user rules (see validate) over the same universe as the presets.
    Top / bottom % and sector medians are taken over the stocks left after
    the sector filter, so "top 10% ROE in Banks" ranks banks only."""
    rules = validate(rules)
    measured = _measure(market, large_only, info_fetch, rows)
    all_sectors = sorted({m["sector"] for _, _, m in measured if m.get("sector")})
    wanted = {s.lower() for s in sectors or []}
    if wanted:
        measured = [t for t in measured if (t[2].get("sector") or "").lower() in wanted]
    ms = [m for _, _, m in measured]

    checks: list[Callable[[dict], bool]] = []
    for rule in rules:
        field, op, v = rule["field"], rule["op"], rule["value"]
        if op in ("top", "bottom"):
            values = [m[field] for m in ms if m.get(field) is not None]
            cut = _percentile_cut(values, v, op == "top") if values else None
            checks.append(lambda m, f=field, c=cut, top=op == "top": c is not None and m.get(f) is not None
                          and (m[f] >= c if top else m[f] <= c))
        elif op in ("below_sector", "above_sector"):
            med = _sector_medians(ms, field)

            def sector_check(m, f=field, med=med, k=v, below=op == "below_sector"):
                x, base = m.get(f), med.get(m.get("sector") or "")
                if x is None or base is None or (f in POSITIVE_ONLY and x <= 0):
                    return False
                return x < base * k if below else x > base * k
            checks.append(sector_check)
        elif op == "between":
            checks.append(lambda m, f=field, lo=v, hi=rule["value2"]: m.get(f) is not None and lo <= m[f] <= hi)
        elif op == ">":
            checks.append(lambda m, f=field, x=v: m.get(f) is not None and m[f] > x)
        else:
            checks.append(lambda m, f=field, x=v: m.get(f) is not None and m[f] < x)

    used = list(dict.fromkeys([r["field"] for r in rules] + [c for c in columns or [] if c in CUSTOM_FIELDS]))
    used = [c for c in used if c not in ("market_cap", "price")]  # always shown
    sort = sort if sort in CUSTOM_FIELDS else rules[0]["field"]
    hits = _hits(measured, market, lambda m: all(c(m) for c in checks), used, sort, descending)
    text = [custom_rule_text(r) for r in rules]
    if wanted:
        text.insert(0, "Sector: " + ", ".join(s for s in all_sectors if s.lower() in wanted))
    return {
        "key": "custom", "title": "Your screen", "description": "Your own rules", "market": market,
        "rules": text,
        "columns": [{"key": c, "label": LABELS.get(c, c)} for c in used],
        "universe": f"Largest {LARGE if large_only else UNIVERSE} stocks by market cap" + (" in the chosen sectors" if wanted else ""),
        "scanned": len(measured),
        "sectors": all_sectors,
        "results": hits,
    }
