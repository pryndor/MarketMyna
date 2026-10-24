"""Daily risk rules: loss limit, open risk, trades per day.

Status "stop" means today's net P&L (realized + open positions) has hit
the daily loss limit: the Trade page shows a stop banner and one alert is
sent. Nothing is blocked - MarketMyna never touches orders."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional

from .journal import trade_pnl

logger = logging.getLogger(__name__)

DEFAULTS = {
    "market": "india",
    "capital": 100000.0,
    "daily_loss_limit_pct": 2.0,
    "max_open_risk_pct": 5.0,
    "max_trades_per_day": 5,
    "notify": True,
}


def _db(config):
    from ..storage import DatabaseManager, get_db_url

    return DatabaseManager.instance(get_db_url(config=config))


def load_settings(config) -> dict:
    from ..storage import TradeRiskSettingsRecord

    with _db(config).get_session() as s:
        rec = s.query(TradeRiskSettingsRecord).order_by(TradeRiskSettingsRecord.id).first()  # one row per user
        if rec is None:
            return {**DEFAULTS, "notified_day": None}
        return {c.name: getattr(rec, c.name) for c in rec.__table__.columns if c.name not in ("id", "user_id")}


def save_settings(config, **changes) -> dict:
    from ..storage import TradeRiskSettingsRecord

    with _db(config).get_session() as s:
        rec = s.query(TradeRiskSettingsRecord).order_by(TradeRiskSettingsRecord.id).first()  # one row per user
        if rec is None:
            rec = TradeRiskSettingsRecord(**DEFAULTS)
            s.add(rec)
        for k, v in changes.items():
            setattr(rec, k, v)
    return load_settings(config)


def compute(trades: list[dict], settings: dict, quotes: dict[str, float], now: datetime) -> dict:
    """Pure: today's risk picture from journal trades (dicts) and live prices."""
    day = now.date()
    mine = [t for t in trades if t["market"] == settings["market"]]
    closed_today = [t for t in mine if t.get("exit_price") is not None and t.get("exit_at") and t["exit_at"].date() == day]
    opened_today = [t for t in mine if t.get("entry_at") and t["entry_at"].date() == day]
    open_trades = [t for t in mine if t.get("exit_price") is None]

    realized = sum(trade_pnl(t) for t in closed_today)
    unrealized, open_risk, no_stop, positions = 0.0, 0.0, [], []
    for t in open_trades:
        sign = -1 if t.get("side") == "short" else 1
        price = quotes.get(t["symbol"])
        pnl = (price - t["entry_price"]) * t["quantity"] * sign if price is not None else None
        if pnl is not None:
            unrealized += pnl
        if t.get("stop"):
            # Risk left = distance from the current price (or entry) to the stop.
            ref = price if price is not None else t["entry_price"]
            open_risk += max(0.0, (ref - t["stop"]) * sign) * t["quantity"]
        else:
            no_stop.append(t["symbol"])
        positions.append({"id": t["id"], "symbol": t["symbol"], "side": t.get("side"), "quantity": t["quantity"],
                          "entry_price": t["entry_price"], "stop": t.get("stop"), "price": price,
                          "pnl": round(pnl, 2) if pnl is not None else None})

    capital = settings["capital"] or 0
    limit = capital * (settings["daily_loss_limit_pct"] or 0) / 100
    max_open = capital * (settings["max_open_risk_pct"] or 0) / 100
    day_pnl = realized + unrealized
    reasons, status = [], "ok"
    if limit and day_pnl <= -limit:
        status = "stop"
        reasons.append(f"Daily loss limit hit: {day_pnl:,.2f} vs limit -{limit:,.2f}. Stop trading for today.")
    else:
        if limit and day_pnl <= -0.75 * limit:
            reasons.append(f"{abs(day_pnl) / limit * 100:.0f}% of today's loss limit used.")
        if max_open and open_risk > max_open:
            reasons.append(f"Open risk {open_risk:,.2f} is above the {settings['max_open_risk_pct']}% cap ({max_open:,.2f}).")
        if settings["max_trades_per_day"] and len(opened_today) >= settings["max_trades_per_day"]:
            reasons.append(f"{len(opened_today)} trades today: at the daily maximum of {settings['max_trades_per_day']}.")
        if no_stop:
            reasons.append(f"No stop set on {', '.join(no_stop)}.")
        if reasons:
            status = "warn"
    return {
        "status": status,
        "reasons": reasons,
        "day_pnl": round(day_pnl, 2),
        "realized": round(realized, 2),
        "unrealized": round(unrealized, 2),
        "loss_limit": round(limit, 2),
        "limit_used_pct": round(max(0.0, -day_pnl) / limit * 100, 1) if limit else None,
        "open_risk": round(open_risk, 2),
        "open_risk_pct": round(open_risk / capital * 100, 2) if capital else None,
        "max_open_risk": round(max_open, 2),
        "trades_today": len(opened_today),
        "closed_today": len(closed_today),
        "positions": positions,
    }


def _trades(config) -> list[dict]:
    from ..storage import TradeRecord

    with _db(config).get_session() as s:
        return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in s.query(TradeRecord)]


def _default_quote(symbol: str, market: str) -> Optional[float]:
    from ..agent.agents import _resolve_fetcher
    from ..utils.deadline import call_with_deadline

    try:
        return (call_with_deadline(_resolve_fetcher(market).get_quote, 15, symbol) or {}).get("price")
    except Exception as exc:
        logger.warning("Quote for %s failed: %s", symbol, exc)
        return None


def status(config, now: Optional[datetime] = None, quote_fn: Callable[[str, str], Optional[float]] = _default_quote) -> dict:
    settings = load_settings(config)
    trades = _trades(config)
    open_symbols = {t["symbol"] for t in trades if t["market"] == settings["market"] and t.get("exit_price") is None}
    quotes = {sym: q for sym in open_symbols if (q := quote_fn(sym, settings["market"])) is not None}
    return {"settings": settings, **compute(trades, settings, quotes, now or datetime.now())}


def check_daily_limit(config, now: Optional[datetime] = None, dispatcher=None, quote_fn=_default_quote) -> Optional[dict]:
    """Monitor hook: one alert per day when the loss limit is hit (only
    while the market is open and there is trading activity)."""
    from .market_hours import is_open

    now = now or datetime.now()
    settings = load_settings(config)
    if not settings.get("notify"):
        return None
    aware = now.astimezone() if now.tzinfo is None else now
    if not is_open(settings["market"], aware):
        return None
    today = now.strftime("%Y-%m-%d")
    if settings.get("notified_day") == today:
        return None
    result = status(config, now.replace(tzinfo=None), quote_fn)
    if result["status"] != "stop":
        return result
    try:
        from ..notifiers.dispatcher import NotificationDispatcher

        dispatcher = dispatcher or NotificationDispatcher(config)
        dispatcher.send_all("🛑 " + result["reasons"][0], title="Daily loss limit", purpose="alert")
    except Exception as exc:
        logger.error("Risk alert failed: %s", exc)
    save_settings(config, notified_day=today)
    return result
