"""Lumpsum window check for a mutual fund: is today's dip unusual for this
fund, and what happened after similar dips before?

No fixed threshold: every condition is measured against the fund's own
history (up to 10 years of daily NAV from mfapi.in).

Conditions (each pass / fail, shown with its numbers):
- dip: NAV is further below its highest NAV than on 75% of past days;
- trend: NAV is under its 200-day average;
- history: after past dips at least this deep, the median 1-year return was
  better than the fund's median 1-year return from any day;
- market: the Nifty 50 is also further below its high than on 60% of past days.

A "turning" note says whether the NAV has started to rise again (10-day
change above zero while still below its average). The level is the number of
conditions met: 3-4 including an unusual dip of the fund itself is strong, 2 or
more is watch, otherwise none. Wording (lumpsum
"opportunity" vs a neutral "dip check") is chosen by the caller from the
compliance mode; this module only reports facts.

Equity, hybrid and index/ETF equity funds only: debt and liquid NAVs barely
dip, so the check would say nothing useful there.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np
import pandas as pd

from marketmyna.core.home import app_home

logger = logging.getLogger(__name__)

YEARS = 10
TRADING_DAYS = 252
DIP_PCTL = 75  # deeper than this share of past days = an unusual dip
MARKET_PCTL = 60
MIN_DIP = -0.03  # under 3% below the high is not a dip worth checking
CACHE_SECONDS = 6 * 3600
CHECKED_CLASSES = ("Equity", "Hybrid")

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _drawdown(s: pd.Series) -> pd.Series:
    return s / s.cummax() - 1.0


def _rsi(s: pd.Series, n: int = 14) -> Optional[float]:
    d = s.diff().dropna()
    if len(d) < n + 1:
        return None
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    return 100.0 if down == 0 else float(100 - 100 / (1 + up / down))


def _recovery_days(nav: pd.Series, depth: float) -> Optional[float]:
    """Median trading days from first reaching `depth` below the high to
    getting back to that high, over past completed episodes that deep."""
    dd = _drawdown(nav).to_numpy()
    days, start, hit = [], None, None
    for i, v in enumerate(dd):
        if v < 0 and start is None:
            start = i
        if start is not None and hit is None and v <= depth:
            hit = i
        if v >= 0 and start is not None:
            if hit is not None:
                days.append(i - hit)
            start, hit = None, None
    return float(np.median(days)) if days else None


def dip_stats(series: pd.Series) -> Optional[dict]:
    """Drawdown now and how unusual it is for this series."""
    s = series.dropna()
    if len(s) < TRADING_DAYS:
        return None
    dd = _drawdown(s)
    now = float(dd.iloc[-1])
    deeper_than = float((dd > now).mean() * 100)  # % of past days that were shallower
    return {"below_high": now, "deeper_than_pct": deeper_than, "high": float(s.cummax().iloc[-1])}


def assess(nav: pd.Series, market: Optional[pd.Series] = None) -> dict:
    from .sip_days import clean

    nav = clean(nav)
    nav = nav[nav.index >= nav.index[-1] - pd.DateOffset(years=YEARS)] if len(nav) else nav
    if len(nav) < 2 * TRADING_DAYS:
        return {"status": "short", "reason": "Needs at least 2 years of NAV history."}

    stats = dip_stats(nav)
    below_52w = float(nav.iloc[-1] / nav.iloc[-TRADING_DAYS:].max() - 1.0)  # for the user's own % alerts
    sma200 = float(nav.rolling(200).mean().iloc[-1])
    price = float(nav.iloc[-1])
    below_avg = price / sma200 - 1.0
    change_10d = float(nav.iloc[-1] / nav.iloc[-11] - 1.0)

    # What happened after past dips at least this deep (days with a full year after them).
    fwd = (nav.shift(-TRADING_DAYS) / nav - 1.0).dropna()
    dd = _drawdown(nav).reindex(fwd.index)
    depth = min(stats["below_high"], MIN_DIP)
    similar = fwd[dd <= depth]
    if len(similar) < 20:  # a record dip: compare with dips at least 3/4 as deep
        depth = depth * 0.75
        similar = fwd[dd <= depth]
    typical = float(fwd.median())
    after_dips = float(similar.median()) if len(similar) >= 20 else None
    win_rate = float((similar > 0).mean() * 100) if len(similar) >= 20 else None

    conditions = [
        {"key": "dip", "label": "Unusual dip for this fund",
         "pass": stats["below_high"] <= MIN_DIP and stats["deeper_than_pct"] >= DIP_PCTL,
         "detail": f"{-stats['below_high'] * 100:.1f}% below its highest NAV, deeper than "
                   f"{stats['deeper_than_pct']:.0f}% of days in the last {YEARS} years"},
        {"key": "trend", "label": "Below its 200-day average",
         "pass": below_avg < 0, "detail": f"NAV {below_avg * 100:+.1f}% vs its 200-day average"},
        {"key": "history", "label": "Past dips like this paid off",
         "pass": after_dips is not None and after_dips > typical,
         "detail": (f"1 year after dips of {-depth * 100:.0f}% or more: median {after_dips * 100:+.1f}% "
                    f"(positive {win_rate:.0f}% of the time) vs {typical * 100:+.1f}% from any day")
         if after_dips is not None else "Not enough past dips this deep to compare"},
    ]
    if market is not None:
        m = dip_stats(market.dropna())
        if m:
            conditions.append({
                "key": "market", "label": "Market also in a dip",
                "pass": m["below_high"] <= MIN_DIP and m["deeper_than_pct"] >= MARKET_PCTL,
                "detail": f"Nifty 50 {-m['below_high'] * 100:.1f}% below its high, deeper than "
                          f"{m['deeper_than_pct']:.0f}% of days"})
    met = sum(c["pass"] for c in conditions)
    own_dip = conditions[0]["pass"]
    # Strong needs the fund's own dip to be unusual, not just a falling market.
    level = "strong" if met >= 3 and own_dip else "watch" if met >= 2 else "none"
    if stats["below_high"] > MIN_DIP:
        level = "none"  # near the high: nothing to time
    return {
        "status": "ok",
        "level": level,
        "met": met,
        "total": len(conditions),
        "conditions": conditions,
        "nav": price,
        "below_high": stats["below_high"],
        "below_52w_high": below_52w,
        "deeper_than_pct": stats["deeper_than_pct"],
        "below_200d": below_avg,
        "change_10d": change_10d,
        "turning": below_avg < 0 and change_10d > 0,
        "rsi": _rsi(nav),
        "after_dips_1y": after_dips,
        "typical_1y": typical,
        "win_rate": win_rate,
        "recovery_days": _recovery_days(nav, depth),
        "as_of": str(nav.index[-1].date()),
    }


def nifty_history() -> Optional[pd.Series]:
    with _lock:
        hit = _cache.get("^NSEI")
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1].get("series")
    try:
        import yfinance as yf

        h = yf.Ticker("^NSEI").history(period=f"{YEARS + 1}y")
        s = h["Close"].dropna()
        s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    except Exception as exc:
        logger.info("Nifty history unavailable: %s", exc)
        return None
    with _lock:
        _cache["^NSEI"] = (time.time(), {"series": s})
    return s


def assess_fund(code: str, category: str = "", name: str = "") -> dict:
    """assess() for one AMFI scheme, cached for a few hours."""
    from .mf_insights import asset_class
    from .sip_days import mf_nav

    if asset_class(category, name) not in CHECKED_CLASSES:
        return {"status": "skipped", "reason": "Debt and liquid funds barely dip, so there is nothing to time."}
    with _lock:
        hit = _cache.get(code)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    nav = mf_nav(code)
    out = assess(nav, nifty_history()) if nav is not None and len(nav) else {"status": "short", "reason": "No NAV history."}
    with _lock:
        _cache[code] = (time.time(), out)
    return out


def _xirr_pct(flows) -> Optional[float]:
    from .sip import xirr

    flows = sorted(flows)
    if len(flows) < 2:
        return None
    r = xirr(flows)
    return r * 100 if r is not None else None


def portfolio_funds(summary: dict) -> dict:
    """Mutual fund view of a portfolio summary: per fund invested, value,
    gain, personal XIRR, category, best SIP day and the lumpsum window check."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date, datetime

    from . import sip_days
    from .mf_holdings import MARKET, latest
    from .mf_insights import asset_class, sub_category

    funds = [h for h in summary.get("holdings", {}).values()
             if (h.get("market") or "").lower() == MARKET and h.get("quantity")]
    txs = summary.get("transactions", [])
    best_days = sip_days.load("india")
    today = date.today()

    def row(h: dict) -> dict:
        code = str(h["symbol"])
        info = latest(code) or {}
        name, category = info.get("name") or h.get("name") or code, info.get("category") or ""
        flows, all_flows = [], []
        for t in txs:
            if str(t.get("symbol")) != code or not t.get("date"):
                continue
            d = datetime.fromisoformat(t["date"]).date()
            amount = float(t["quantity"]) * float(t["price"])
            kind = t.get("transaction_type")
            if kind == "buy":
                flows.append((d, -(amount + float(t.get("fees") or 0))))
            elif kind in ("sell", "dividend"):
                flows.append((d, amount - float(t.get("fees") or 0)))
        value = float(h.get("market_value") or 0)
        if flows:
            all_flows = flows + [(today, value)]
        best = best_days.get(code) or {}
        return {
            "code": code, "name": name, "amc": info.get("amc"), "category": sub_category(category),
            "asset_class": asset_class(category, name),
            "units": h.get("quantity"), "nav": info.get("nav") or h.get("current_price"), "nav_date": info.get("nav_date"),
            "invested": h.get("cost_basis"), "value": value, "gain": h.get("unrealized_gain"),
            "gain_pct": h.get("unrealized_gain_percent"),
            "xirr_pct": _xirr_pct(all_flows) if all_flows and all_flows[0][0] < today else None,
            "best_sip_day": best.get("best_day"), "sip_edge": best.get("edge"),
            "lumpsum": assess_fund(code, category, name),
            "_flows": flows,
        }

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(row, funds))
    every = [f for r in rows for f in r.pop("_flows")]
    invested = sum(float(r["invested"] or 0) for r in rows)
    value = sum(r["value"] for r in rows)
    rows.sort(key=lambda r: -r["value"])
    from ..core.compliance import mode

    return {
        "funds": rows,
        "total": {"invested": invested, "value": value, "gain": value - invested,
                  "xirr_pct": _xirr_pct(every + [(today, value)]) if every else None},
        "compliance": mode(),
    }


# ------------------------------------------------------------ dip alerts

LEVEL_RANK = {"none": 0, "watch": 1, "strong": 2}
REMIND_DAYS = 7
ALERT_EVERY = 6 * 3600


def _state_path():

    p = app_home() / "mf_dip_alerts.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_state() -> dict:
    import json

    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(state: dict) -> None:
    import json

    tmp = _state_path().with_suffix(".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    tmp.replace(_state_path())


def held_funds(config) -> list[str]:
    """AMFI codes of mutual funds held in the current scope's portfolios."""
    from ..storage import DatabaseManager, HoldingRecord, PortfolioRecord, get_db_url

    with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
        rows = (session.query(HoldingRecord.portfolio_id, HoldingRecord.symbol, HoldingRecord.market,
                              HoldingRecord.quantity)
                .join(PortfolioRecord, HoldingRecord.portfolio_id == PortfolioRecord.id).all())
    return sorted({str(sym) for _pid, sym, market, qty in rows if (market or "").lower() == "mf" and (qty or 0) > 0})


def alert_text(name: str, a: dict) -> tuple[str, str]:
    """(title, message) for one fund's dip: facts, no "opportunity" (marketmyna/core/compliance.py)."""
    below = -a["below_high"] * 100
    lines = []
    title = f"📉 Dip check {a['met']} of {a['total']}: {name}"
    lines.append(title)
    lines.append(f"{below:.1f}% below its highest NAV, deeper than {a['deeper_than_pct']:.0f}% of days in the last {YEARS} years.")
    if a.get("after_dips_1y") is not None:
        lines.append(f"1 year after past dips this deep: median {a['after_dips_1y'] * 100:+.1f}% "
                     f"(vs {a['typical_1y'] * 100:+.1f}% from any day).")
    if a.get("turning"):
        lines.append("The NAV has started rising again over the last 10 days.")
    lines.append("Facts about past behaviour, not investment advice.")
    return title, "\n".join(lines)


def check_dips(config, state: dict, user_key: str, dispatcher=None, today=None) -> list[str]:
    """Alerts for the current scope's funds that reached (or rose to) watch /
    strong; updates `state`. Returns the codes alerted."""
    from datetime import date

    from ..notifiers.dispatcher import NotificationDispatcher
    from .mf_holdings import latest

    today = today or date.today()
    mine = state.setdefault(user_key, {})
    sent = []
    for code in held_funds(config):
        info = latest(code) or {}
        a = assess_fund(code, info.get("category") or "", info.get("name") or "")
        if a.get("status") != "ok":
            continue
        level, prev = a["level"], mine.get(code) or {}
        if level == "none":
            mine.pop(code, None)  # reset, so the next dip alerts again
            continue
        rose = LEVEL_RANK[level] > LEVEL_RANK.get(prev.get("level", "none"), 0)
        stale = prev.get("date") and (today - date.fromisoformat(prev["date"])).days >= REMIND_DAYS
        if not (rose or (level == "strong" and stale)):
            continue
        title, message = alert_text(info.get("name") or code, a)
        (dispatcher or NotificationDispatcher(config)).send_all(message, title=title, purpose="alert")
        mine[code] = {"level": level, "date": today.isoformat()}
        sent.append(code)
    return sent


def alert_loop(config, first_delay: int = 900, every: int = ALERT_EVERY) -> None:
    """Background thread: dip alerts for every user's mutual funds."""
    from ..core import tenant
    from .accounts import for_each_user

    time.sleep(first_delay)
    while True:
        try:
            state = _load_state()

            def run():
                uid = tenant.current_user_id() if tenant.enabled() else None
                key = str(uid) if uid is not None else "owner"
                check_dips(config, state, key)
                check_levels(config, state, key)

            for_each_user(config, run, "Fund dip alerts")
            _save_state(state)
        except Exception as exc:  # never kill the thread
            logger.warning("Fund dip alerts: %s", exc)
        time.sleep(every)


# ------------------------------------------------------------ AI review

def _review_prompt(name: str, category: str, a: dict) -> str:
    lines = [f"Fund: {name} ({category}). NAV data as of {a.get('as_of')}."]
    for c in a.get("conditions", []):
        lines.append(f"- {c['label']}: {'yes' if c['pass'] else 'no'} ({c['detail']})")
    lines.append(f"- NAV {'has started rising' if a.get('turning') else 'has not turned up'} over the last 10 days; "
                 f"RSI {a.get('rsi') and round(a['rsi'])}.")
    if a.get("recovery_days"):
        lines.append(f"- Past dips this deep took a median {round(a['recovery_days'] / 21)} months to regain the high.")
    return "\n".join(lines)


def ai_review(code: str, config) -> Optional[dict]:
    """AI read of one fund's dip: an explanation without a recommendation.
    None when no AI is available or the reply can't be parsed."""
    from ..llm.backend_factory import create_generation_backend
    from ..llm.json_reply import parse_object
    from ..llm.protocol import GenerationConfig
    from .mf_holdings import latest

    info = latest(code) or {}
    name, category = info.get("name") or code, info.get("category") or ""
    a = assess_fund(code, category, name)
    if a.get("status") != "ok":
        return {"summary": a.get("reason") or "No dip check for this fund.", "reasons": [], "risk": None, "view": None}
    system = (
        "You explain mutual fund data to retail investors for an analytics tool that is not a registered "
        "adviser. Using only the figures given, explain how unusual today's dip is for this fund, what "
        "happened after similar past dips, and the main risks. Never recommend investing, adding money, "
        "a lumpsum, buying, holding or selling, and give no timing advice. Reply with ONLY a JSON object: "
        '{"summary": "2-3 sentences", "reasons": ["2-3 short factual points"], "risk": "one risk to keep in mind"}'
    )
    try:
        result = create_generation_backend(config).generate(
            _review_prompt(name, category, a), GenerationConfig(max_tokens=500, timeout=90), system_prompt=system)
    except Exception as exc:
        logger.warning("Fund AI review unavailable: %s", exc)
        raise
    data = parse_object(result.text)
    if not data or not data.get("summary"):
        return None
    return {"view": None,  # no timing view (marketmyna/core/compliance.py)
            "summary": str(data["summary"]), "reasons": [str(r) for r in (data.get("reasons") or [])][:4],
            "risk": data.get("risk")}


# ------------------------------------------------- the user's own % alerts

LEVEL_CHOICES = [3.0, 5.0, 7.5, 10.0, 15.0, 20.0]  # % below the 52-week high
RESET_NEAR_HIGH = -0.015  # back within 1.5% of the high: the ladder re-arms


def _clean_levels(values) -> list[float]:
    out = sorted({float(v) for v in (values or [])})
    bad = [v for v in out if v not in LEVEL_CHOICES]
    if bad:
        raise ValueError(f"Choose levels from {', '.join(f'{c:g}%' for c in LEVEL_CHOICES)}.")
    return out


def _portfolio(session, name: str):
    from ..storage import PortfolioRecord

    p = session.query(PortfolioRecord).filter_by(name=name).first()
    if p is None:
        raise LookupError(f"Portfolio '{name}' not found")
    return p


def get_rules(config, name: str) -> dict:
    from ..storage import DatabaseManager, FundDipRuleRecord, get_db_url

    with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
        p = _portfolio(session, name)
        rows = session.query(FundDipRuleRecord).filter_by(portfolio_id=p.id).all()
    default = next((r.levels for r in rows if r.fund_code is None), None) or []
    return {"levels": default, "overrides": {r.fund_code: r.levels or [] for r in rows if r.fund_code},
            "choices": LEVEL_CHOICES}


def set_rules(config, name: str, levels, overrides: Optional[dict] = None) -> dict:
    """levels: the portfolio default; overrides: fund code -> its own levels
    ([] = no % alerts for that fund). A code left out uses the default."""
    from ..storage import DatabaseManager, FundDipRuleRecord, get_db_url

    wanted = {None: _clean_levels(levels)}
    for code, lv in (overrides or {}).items():
        wanted[str(code)] = _clean_levels(lv)
    with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
        p = _portfolio(session, name)
        existing = {r.fund_code: r for r in session.query(FundDipRuleRecord).filter_by(portfolio_id=p.id)}
        for code, row in existing.items():
            if code not in wanted:
                session.delete(row)
        for code, lv in wanted.items():
            row = existing.get(code) or FundDipRuleRecord(portfolio_id=p.id, fund_code=code)
            row.levels = lv
            session.add(row)
    return get_rules(config, name)


def held_with_levels(config) -> list[dict]:
    """[{portfolio_id, portfolio, code, levels}] for every mutual fund held in
    the current scope that has % alert levels."""
    from ..storage import (
        DatabaseManager,
        FundDipRuleRecord,
        HoldingRecord,
        PortfolioRecord,
        get_db_url,
    )
    with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
        holdings = (session.query(PortfolioRecord.id, PortfolioRecord.name, HoldingRecord.symbol,
                                  HoldingRecord.market, HoldingRecord.quantity)
                    .join(HoldingRecord, HoldingRecord.portfolio_id == PortfolioRecord.id).all())
        rules = {(r.portfolio_id, r.fund_code): r.levels or [] for r in session.query(FundDipRuleRecord)}
    out = []
    for pid, pname, code, market, qty in holdings:
        if (market or "").lower() != "mf" or (qty or 0) <= 0:
            continue
        levels = rules.get((pid, str(code)), rules.get((pid, None), []))
        if levels:
            out.append({"portfolio_id": pid, "portfolio": pname, "code": str(code), "levels": levels})
    return out


def level_text(name: str, a: dict, level: float) -> tuple[str, str]:
    below = -a["below_52w_high"] * 100
    title = f"📉 {name}: {below:.1f}% below its 52-week high"
    lines = [title, f"Your {level:g}% dip alert was reached."]
    if a.get("level") in ("watch", "strong"):
        lines.append(f"Dip check: {a['met']} of {a['total']} conditions met.")
    if a.get("after_dips_1y") is not None:
        lines.append(f"1 year after past dips like this: median {a['after_dips_1y'] * 100:+.1f}%.")
    lines.append("Your own alert rule; facts, not investment advice.")
    return title, "\n".join(lines)


def check_levels(config, state: dict, user_key: str, dispatcher=None) -> list[tuple[str, float]]:
    """The user's own % alerts: one alert per level as a fund falls through it
    (once per dip), re-armed when it gets back near its 52-week high."""
    from ..notifiers.dispatcher import NotificationDispatcher
    from .mf_holdings import latest

    ladder = state.setdefault(user_key, {}).setdefault("_ladder", {})
    sent = []
    for h in held_with_levels(config):
        info = latest(h["code"]) or {}
        a = assess_fund(h["code"], info.get("category") or "", info.get("name") or "")
        dip = a.get("below_52w_high")
        if a.get("status") != "ok" or dip is None:
            continue
        key = f"{h['portfolio_id']}:{h['code']}"
        fired = ladder.get(key, [])
        if dip > RESET_NEAR_HIGH:
            ladder.pop(key, None)
            continue
        crossed = [lv for lv in h["levels"] if dip <= -lv / 100 and lv not in fired]
        if not crossed:
            continue
        deepest = max(crossed)
        title, message = level_text(info.get("name") or h["code"], a, deepest)
        (dispatcher or NotificationDispatcher(config)).send_all(message, title=title, purpose="alert")
        ladder[key] = sorted(set(fired) | set(crossed))
        sent.append((h["code"], deepest))
    return sent


def send_test_alert(config, name: str, dispatcher=None) -> dict:
    """A sample dip alert for the first fund in the portfolio, to see how it
    looks and that it arrives. Says clearly that it is a test."""
    from ..notifiers.dispatcher import NotificationDispatcher
    from .mf_holdings import latest

    funds = [h for h in held_with_levels(config) if h["portfolio"] == name] or \
        [{"code": c, "levels": [5.0]} for c in _codes_in(config, name)]
    if not funds:
        raise LookupError("Add a mutual fund to this portfolio first.")
    code = funds[0]["code"]
    info = latest(code) or {}
    a = assess_fund(code, info.get("category") or "", info.get("name") or "")
    if a.get("status") != "ok":
        a = {"below_52w_high": -0.05, "level": "none", "met": 0, "total": 4}
    level = min(funds[0]["levels"] or [5.0])
    title, message = level_text(info.get("name") or code, a, level)
    delivery = (dispatcher or NotificationDispatcher(config)).send_all(
        "TEST - this is how your dip alert will look.\n" + message, title="Test: " + title, purpose="alert")
    return {"sent": delivery, "fund": info.get("name") or code}


def _codes_in(config, name: str) -> list[str]:
    from ..storage import DatabaseManager, HoldingRecord, get_db_url

    with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
        p = _portfolio(session, name)
        rows = session.query(HoldingRecord).filter_by(portfolio_id=p.id).all()
        return [str(r.symbol) for r in rows if (r.market or "").lower() == "mf" and (r.quantity or 0) > 0]
