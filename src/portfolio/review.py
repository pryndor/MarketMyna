"""Portfolio review: what in the current mix could be changed, why, and how.

Turns numbers the app already computes (weights, sectors, risk share,
correlation, beta / drawdown from analytics.py, the fund health check from
mf_insights.py) into a ranked list of findings. Each finding says what we see,
why it matters and which levers the user has, and points at the section of the
Portfolio page that shows the detail.

Wording follows src/core/compliance.py: a finding states facts, the user's
own limits and general levers, never "sell X, buy Y", an amount to trim or a
target allocation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# The user's own limits (percent). Bounds keep a typo from switching a check off.
DEFAULT_LIMITS = {"max_holding": 20.0, "max_sector": 35.0, "max_cash": 20.0, "loss_review": 25.0, "min_holdings": 5}
LIMIT_BOUNDS = {"max_holding": (5, 100), "max_sector": (10, 100), "max_cash": (0, 100), "loss_review": (5, 90),
                "min_holdings": (1, 50)}

SEVERITY_COST = {"high": 15, "medium": 8, "low": 3}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# Sections on the Portfolio page a finding links to (Card ids).
HOLDINGS, ANALYTICS, FUNDS, FUND_HEALTH, TRANSACTIONS = (
    "section-holdings", "section-analytics", "section-funds", "section-fund-health", "section-transactions")


def clean_limits(values: Optional[dict]) -> dict:
    out = dict(DEFAULT_LIMITS)
    for key, raw in (values or {}).items():
        if key not in DEFAULT_LIMITS or raw is None:
            continue
        lo, hi = LIMIT_BOUNDS[key]
        v = float(raw)
        if not lo <= v <= hi:
            raise ValueError(f"{key.replace('_', ' ')} must be between {lo} and {hi}")
        out[key] = int(v) if key == "min_holdings" else v
    return out


def _money(v: float, currency: str) -> str:
    return f"{currency} {v:,.0f}"


def _pct(v: float, digits: int = 0) -> str:
    return f"{v:.{digits}f}%"


def _finding(id_: str, severity: str, title: str, fact: str, why: str, levers: list[str],
             section: str, rule: Optional[str] = None, symbols: Optional[list[str]] = None) -> dict:
    return {"id": id_, "severity": severity, "title": title, "fact": fact, "why": why, "levers": levers,
            "section": section, "rule": rule, "symbols": symbols or []}


def _first_buys(transactions: list[dict]) -> dict[str, datetime]:
    out: dict[str, datetime] = {}
    for t in transactions or []:
        if str(t.get("transaction_type", "")).lower() != "buy" or not t.get("date"):
            continue
        try:
            d = datetime.fromisoformat(str(t["date"])[:19])
        except ValueError:
            continue
        s = t.get("symbol")
        if s and (s not in out or d < out[s]):
            out[s] = d
    return out


def build(summary: dict, *, analytics: Optional[dict] = None, funds: Optional[dict] = None,
          sectors: Optional[dict[str, str]] = None, limits: Optional[dict] = None,
          names: Optional[dict[str, str]] = None, now: Optional[datetime] = None) -> dict:
    """summary: PortfolioManager summary; analytics: analytics.analyze() output;
    funds: mf_insights.insights() output; sectors: symbol -> broad sector for
    stocks / ETFs; names: display names (fund codes -> scheme names)."""
    from ..services.mf_insights import asset_class

    limits = clean_limits(limits)
    names = names or {}
    sectors = sectors or {}
    cur = summary.get("currency") or ""
    holdings = [h for h in (summary.get("holdings") or {}).values() if (h.get("market_value") or 0) > 0]
    invested = sum(float(h["market_value"]) for h in holdings)
    cash = float(summary.get("cash_balance") or 0)
    total = invested + max(cash, 0)
    label = lambda s: names.get(s, s)  # noqa: E731
    is_fund = lambda h: (h.get("market") or "").lower() == "mf"  # noqa: E731

    findings: list[dict] = []
    good: list[str] = []
    if not holdings or invested <= 0:
        return {"score": None, "grade": None, "findings": [], "good": [], "limits": limits,
                "summary": "Add holdings to get a review."}

    weights = {h["symbol"]: float(h["market_value"]) / invested for h in holdings}
    by_symbol = {h["symbol"]: h for h in holdings}

    # 1. One holding too big
    cap = limits["max_holding"] / 100
    big = sorted(((s, w) for s, w in weights.items() if w > cap), key=lambda x: -x[1])
    # A diversified fund spreads its own money; only flag funds well past the cap.
    big = [(s, w) for s, w in big if not is_fund(by_symbol[s]) or w > max(cap, 0.5)]
    if big:
        s, w = big[0]
        others = f" (also {', '.join(f'{label(x)} {_pct(y * 100)}' for x, y in big[1:3])})" if len(big) > 1 else ""
        levers = ["Reduce the position, or add to other holdings so its share falls.",
                  "Direct new money elsewhere until it is back under your limit.",
                  "Or raise your limit if the size is deliberate."]
        findings.append(_finding(
            "concentration", "high" if w > cap * 1.5 else "medium", "One holding is a big share of the portfolio",
            f"{label(s)} is {_pct(w * 100)} of what you hold{others}.",
            f"A 20% fall in {label(s)} alone would cut the whole portfolio by about {_pct(w * 20, 1)}.",
            levers, HOLDINGS, rule=f"Your limit: {_pct(limits['max_holding'])} per holding",
            symbols=[x for x, _ in big]))
    else:
        good.append(f"No holding is above your {_pct(limits['max_holding'])} limit.")

    # 2. One sector too big (stocks / ETFs with a known sector)
    by_sector: dict[str, float] = {}
    for h in holdings:
        sec = sectors.get(h["symbol"])
        if sec and sec != "Other" and not is_fund(h):
            by_sector[sec] = by_sector.get(sec, 0) + weights[h["symbol"]]
    if by_sector:
        sec, w = max(by_sector.items(), key=lambda kv: kv[1])
        members = [label(h["symbol"]) for h in holdings if sectors.get(h["symbol"]) == sec]
        if w > limits["max_sector"] / 100:
            findings.append(_finding(
                "sector", "high" if w > 0.6 else "medium", "Heavy in one sector",
                f"{_pct(w * 100)} is in {sec} ({', '.join(members[:5])}{'…' if len(members) > 5 else ''}).",
                "Stocks in one sector tend to fall together on the same news (rates, regulation, a demand slump).",
                ["Add holdings from sectors you don't own yet.",
                 f"Put new money outside {sec} for a while.",
                 "A broad index fund or ETF spreads money across all sectors in one step."],
                HOLDINGS, rule=f"Your limit: {_pct(limits['max_sector'])} per sector", symbols=members))
        elif len(by_sector) >= 3:
            good.append(f"Stocks are spread over {len(by_sector)} sectors; the largest, {sec}, is {_pct(w * 100)}.")

    # 3-5. From the risk analytics
    if analytics:
        per = analytics.get("holdings") or []
        risky = [h for h in per if (h.get("risk_contribution") or 0) > max(h["weight"] * 1.5, h["weight"] + 0.1)
                 and (h.get("risk_contribution") or 0) >= 0.2]
        if risky and len(per) > 1:
            h = max(risky, key=lambda x: x["risk_contribution"])
            findings.append(_finding(
                "risk_share", "medium", "One holding drives most of the swings",
                f"{label(h['symbol'])} is {_pct(h['weight'] * 100)} of the value but {_pct(h['risk_contribution'] * 100)} "
                f"of the portfolio's ups and downs (volatility {_pct((h.get('volatility') or 0) * 100)} a year).",
                "Your day-to-day result mostly depends on this one position, more than its size suggests.",
                ["A smaller position would bring its risk share closer to its weight.",
                 "Steadier holdings that move differently lower its effect.",
                 "Or keep it, knowing where the risk sits."],
                ANALYTICS, symbols=[h["symbol"]]))

        corr = analytics.get("correlation") or {}
        syms, matrix = corr.get("symbols") or [], corr.get("matrix") or []
        fund_syms = {h["symbol"] for h in holdings if is_fund(h)}
        pairs = [(syms[i], syms[j], matrix[i][j]) for i in range(len(syms)) for j in range(i + 1, len(syms))
                 if matrix[i][j] is not None and matrix[i][j] >= 0.8
                 and not (syms[i] in fund_syms and syms[j] in fund_syms)]  # fund pairs: fund check below
        if pairs:
            a, b, c = max(pairs, key=lambda p: p[2])
            more = f" ({len(pairs) - 1} more pair{'s' if len(pairs) > 2 else ''} like this)" if len(pairs) > 1 else ""
            findings.append(_finding(
                "correlation", "medium" if c >= 0.9 else "low", "Holdings that move together",
                f"{label(a)} and {label(b)} have moved almost in step over the last year (correlation {c:.2f}){more}.",
                "Two holdings that rise and fall together give you the risk of one bigger position, not two.",
                ["Keep the one you prefer and put the rest elsewhere.",
                 "Add something that moved differently (another sector, bonds, gold)."],
                ANALYTICS, symbols=[a, b]))

        m = analytics.get("metrics") or {}
        beta, dd = m.get("beta"), m.get("max_drawdown")
        bench = (analytics.get("benchmark") or {}).get("name") or "the index"
        if (beta is not None and beta > 1.2) or (dd is not None and dd < -0.25):
            parts = []
            if beta is not None:
                parts.append(f"beta {beta:.2f} (moves about {beta:.1f}x {bench})")
            if dd is not None:
                parts.append(f"worst fall in the last year {_pct(dd * 100)}")
            findings.append(_finding(
                "market_risk", "medium", "Swings more than the market",
                f"The current mix has {' and '.join(parts)}.",
                f"In a market fall this mix would likely drop more than {bench}; the question is whether you could hold through that.",
                ["Add lower-beta or defensive holdings, or a debt / hybrid fund as a cushion.",
                 "Keep some cash so you never have to sell in a fall.",
                 "If your horizon is long and you accept the swings, no change is needed."],
                ANALYTICS))
        elif beta is not None:
            good.append(f"Overall swings are close to or below the market (beta {beta:.2f}).")

    # 6. Asset mix: everything in equity
    equity = sum(weights[h["symbol"]] for h in holdings
                 if not is_fund(h) or asset_class(h.get("category", ""), h.get("name", "")) == "Equity")
    if len(holdings) >= 3 and equity > 0.95 and cash / total < 0.05:
        findings.append(_finding(
            "asset_mix", "low", "All in equity",
            f"{_pct(equity * 100)} is in stocks or equity funds, with little cash.",
            "Equity is the growth engine but has no cushion: a 30% market fall hits almost all of it.",
            ["If you need part of this money within 3-5 years, keep that part in debt funds or deposits.",
             "Gold or a hybrid fund can soften falls.",
             "For a long horizon and steady income, all-equity can be a deliberate choice."],
            HOLDINGS))

    # 7. Number of positions
    stocks = [h for h in holdings if not is_fund(h)]
    n_funds = len(holdings) - len(stocks)
    if stocks and not n_funds and len(stocks) < limits["min_holdings"]:
        findings.append(_finding(
            "few_holdings", "medium", "Few holdings",
            f"The portfolio has {len(stocks)} stock{'s' if len(stocks) != 1 else ''} and no funds.",
            "With few positions, one bad result (a fraud, a profit warning) can do lasting damage.",
            [f"Build up to at least {limits['min_holdings']} holdings from different sectors over time.",
             "Or hold an index fund / ETF alongside your picks as the diversified core."],
            HOLDINGS, rule=f"Your minimum: {limits['min_holdings']} holdings"))
    tiny = [h["symbol"] for h in holdings if weights[h["symbol"]] < 0.02]
    if len(tiny) >= 3:
        findings.append(_finding(
            "tiny", "low", "Many very small positions",
            f"{len(tiny)} holdings are under 2% each ({', '.join(label(s) for s in tiny[:5])}{'…' if len(tiny) > 5 else ''}).",
            "Positions this small barely move the result but still need tracking.",
            ["Build up the ones you believe in to a size that matters.",
             "Close or merge the rest to simplify."],
            HOLDINGS, symbols=tiny))

    # 8. Idle cash
    if total > 0 and cash / total * 100 > limits["max_cash"]:
        findings.append(_finding(
            "cash", "low", "A lot of cash waiting",
            f"Cash is {_money(cash, cur)}, {_pct(cash / total * 100)} of the portfolio.",
            "Cash is safe but loses to inflation over time.",
            ["Invest it in steps (e.g. monthly) rather than all at once.",
             "Park it in a liquid fund or sweep deposit while you decide.",
             "Keep it if it is your emergency fund or earmarked for a near-term need."],
            HOLDINGS, rule=f"Your limit: {_pct(limits['max_cash'])} in cash"))

    # 9. Big losers
    first = _first_buys(summary.get("transactions") or [])
    now = now or datetime.now()
    losers = sorted(((h["symbol"], float(h.get("unrealized_gain_percent") or 0)) for h in holdings
                     if (h.get("unrealized_gain_percent") or 0) <= -limits["loss_review"]), key=lambda x: x[1])
    if losers:
        def age(s: str) -> str:
            d = first.get(s)
            if not d:
                return ""
            months = (now - d).days // 30
            return f", held {months // 12}y {months % 12}m" if months >= 12 else f", held {months}m"
        loss_value = sum(float(h.get("unrealized_gain") or 0) for h in holdings if h["symbol"] in {s for s, _ in losers})
        findings.append(_finding(
            "losers", "medium", "Positions well below what you paid",
            "; ".join(f"{label(s)} {_pct(p, 1)}{age(s)}" for s, p in losers[:4]) + f". Unrealized loss {_money(-loss_value, cur)}.",
            "A big loss is worth a fresh look: is the reason you bought still true, or are you waiting to get even?",
            ["Re-check the original reason for owning it (results, debt, management, sector).",
             "Booked losses can offset gains for tax; check the rules for your country or ask a tax adviser.",
             "If the reason still holds, you may keep it; set a review date so it is a decision, not a habit."],
            HOLDINGS, rule=f"Your review level: {_pct(limits['loss_review'])} below cost", symbols=[s for s, _ in losers]))

    # 10. Mutual fund health (overlap, plan costs, options)
    if funds and funds.get("funds"):
        kinds = funds.get("issue_kinds") or []
        texts = funds.get("issues") or []
        fund_levers = {
            "same_category": ("Funds doing the same job", "medium",
                              "Two funds in one category usually own many of the same stocks; you pay twice for one exposure.",
                              ["Keep the one with the better long-term record and lower cost.",
                               "Stop new SIPs in the other first; switch out later with exit load and tax in mind."]),
            "lockstep": ("Funds moving in lockstep", "medium",
                         "Funds that move together add cost and paperwork, not diversification.",
                         ["Consolidate into fewer funds.",
                          "Use the slot for something different (mid/small cap, international, debt)."]),
            "regular_plan": ("Paying for Regular plans", "medium",
                             "Regular plans pay a distributor commission every year, usually 0.5-1% more than Direct.",
                             ["Switch future SIPs to the Direct plan of the same fund.",
                              "Move existing units when exit load and capital gains tax make it worth it."]),
            "idcw": ("Dividend (IDCW) options", "low",
                     "IDCW payouts are taxed at your income slab every year and stop compounding.",
                     ["Growth option of the same fund suits long-term goals better.",
                      "Need regular income? A planned withdrawal (SWP) from Growth is usually more tax-efficient."]),
            "one_asset_class": ("Funds all in one asset class", "low",
                                "No debt or hybrid cushion among your funds.",
                                ["Add a debt or hybrid fund for money you may need sooner."]),
        }
        for kind, text in zip(kinds, texts):
            if kind == "one_asset_class" and any(f["id"] == "asset_mix" for f in findings):
                continue
            title, sev, why, levers = fund_levers.get(kind, ("Mutual fund check", "low", "", []))
            findings.append(_finding(f"fund_{kind}", sev, title, text, why, levers, FUND_HEALTH))
        if not kinds:
            good.append("Mutual funds: no overlap, plan-cost or option issues found.")

    findings.sort(key=lambda f: SEVERITY_ORDER[f["severity"]])
    score = max(0, 100 - sum(SEVERITY_COST[f["severity"]] for f in findings))
    grade = "Good" if score >= 80 else "Fair" if score >= 60 else "Needs attention"
    return {
        "score": score,
        "grade": grade,
        "findings": findings,
        "good": good,
        "limits": limits,
        "summary": (f"{len(findings)} thing{'s' if len(findings) != 1 else ''} worth a look"
                    if findings else "Nothing stands out against your limits."),
        "as_of": (analytics or {}).get("as_of"),
    }


# ------------------------------------------------------------- one call for API and bot

def for_portfolio(manager, name: str, config) -> dict:
    """Builds the portfolio review from the summary, risk analytics, fund
    health check, stock sectors and the user's own limits."""
    from ..data.listings import get_store
    from ..services.mf_holdings import MARKET, latest
    from ..services.mf_insights import insights
    from .analytics import MF_PREFIX, _download_closes, analyze

    summary = manager.get_portfolio_summary(name)
    for h in summary.get("holdings", {}).values():  # scheme name / category on fund holdings
        if (h.get("market") or "").lower() == MARKET and (info := latest(h["symbol"])):
            h.update(name=info["name"], category=info["category"])
    holdings = list(summary["holdings"].values())
    try:
        risk = analyze(holdings)
    except ValueError:
        risk = None
    funds = [h for h in holdings if (h.get("market") or "").lower() == MARKET]
    fund_check = None
    if funds:
        closes = _download_closes([MF_PREFIX + f["symbol"] for f in funds])
        fund_check = insights(funds, {k[len(MF_PREFIX):]: v for k, v in closes.items()})
    keys = [((h.get("market") or "us").lower(), kind, h["symbol"]) for h in holdings
            if (h.get("market") or "").lower() != MARKET for kind in ("stock", "etf")]
    try:
        rows = get_store().lookup(keys) if keys else {}
    except Exception:  # sectors are a nice-to-have; the store may be cold
        rows = {}
    sectors = {sym: r.get("category") for (_, _, sym), r in rows.items() if r.get("category")}
    names = {h["symbol"]: h["name"].split(" - ")[0] for h in funds if h.get("name")}
    return build(summary, analytics=risk, funds=fund_check, sectors=sectors, names=names,
                 limits=get_limits(config, name))


# ------------------------------------------------------------- the user's limits

def get_limits(config, name: str) -> dict:
    from ..services.mf_lumpsum import _portfolio
    from ..storage import DatabaseManager, PortfolioReviewRuleRecord, get_db_url

    with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
        p = _portfolio(session, name)
        row = session.query(PortfolioReviewRuleRecord).filter_by(portfolio_id=p.id).first()
        saved = dict(row.limits or {}) if row else {}
    return clean_limits(saved)


def set_limits(config, name: str, values: dict) -> dict:
    from ..services.mf_lumpsum import _portfolio
    from ..storage import DatabaseManager, PortfolioReviewRuleRecord, get_db_url

    limits = clean_limits(values)
    with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
        p = _portfolio(session, name)
        row = session.query(PortfolioReviewRuleRecord).filter_by(portfolio_id=p.id).first()
        row = row or PortfolioReviewRuleRecord(portfolio_id=p.id)
        row.limits = limits
        session.add(row)
    return limits


# ------------------------------------------------------------- AI write-up

def ai_summary(review: dict, config) -> Optional[dict]:
    """A short analyst-style read of the review: an explanation without buy /
    sell advice (src/core/compliance.py)."""
    from ..llm.backend_factory import create_generation_backend
    from ..llm.json_reply import parse_object
    from ..llm.protocol import GenerationConfig

    system = (
        "You explain portfolio data to retail investors for an analytics tool that is not a registered "
        "adviser. Using only the findings given, explain which ones matter most and why, and what the user "
        "could look into. Never tell them to buy, sell, hold or switch a specific security and give no target "
        "allocation. Reply with ONLY a JSON object: "
        '{"summary": "2-3 sentences", "priorities": ["up to 3 points to look into, most important first"], '
        '"keep": "one thing that looks fine"}'
    )
    lines = [f"Score {review.get('score')}/100 ({review.get('grade')})."]
    for f in review.get("findings") or []:
        lines.append(f"- [{f['severity']}] {f['title']}: {f['fact']} {f.get('rule') or ''}")
    for g in review.get("good") or []:
        lines.append(f"+ {g}")
    try:
        result = create_generation_backend(config).generate(
            "\n".join(lines), GenerationConfig(max_tokens=600, timeout=90), system_prompt=system)
    except Exception as exc:
        logger.warning("Portfolio AI review unavailable: %s", exc)
        raise
    data = parse_object(result.text)
    if not data or not data.get("summary"):
        return None
    return {"summary": str(data["summary"]),
            "priorities": [str(p) for p in (data.get("priorities") or [])][:3],
            "keep": data.get("keep")}
