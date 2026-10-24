"""Price / indicator alerts for traders.

AlertMonitor polls quotes for symbols with active alerts (only while their
market is open), evaluates each alert and sends the ones that fire through
the NotificationDispatcher's "alert" route (Telegram, push, ...).

Firing rules:
- one-shot alert: fires once, then status "triggered";
- repeating alert: fires, then re-arms only after the condition has been
  false again (so a price hovering on a level doesn't spam), and never
  more often than its cooldown.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

from . import indicators as ind
from ..utils.deadline import call_with_deadline
from .market_hours import is_open, timezone_of

logger = logging.getLogger(__name__)

# kind -> (label, value unit, needs daily history)
KINDS: dict[str, tuple[str, str, bool]] = {
    "price_above": ("Price rises to or above", "price", False),
    "price_below": ("Price falls to or below", "price", False),
    "pct_up": ("Up today by at least", "%", False),
    "pct_down": ("Down today by at least", "%", False),
    "rsi_above": ("Daily RSI(14) at or above", "rsi", True),
    "rsi_below": ("Daily RSI(14) at or below", "rsi", True),
    "volume_spike": ("Volume today at least", "x avg", True),
    "high_breakout": ("Breaks above the N-day high", "days", True),
    "low_breakdown": ("Breaks below the N-day low", "days", True),
}

DEFAULT_POLL_SECONDS = 60
DAILY_TTL = timedelta(minutes=30)


def _completed_days(daily: pd.DataFrame, market: str, now: datetime) -> pd.DataFrame:
    """Daily bars without today's (still forming) bar."""
    if daily.empty:
        return daily
    last = pd.DatetimeIndex(daily.index)[-1]
    today = now.astimezone(ZoneInfo(timezone_of(market))).date()
    return daily.iloc[:-1] if last.date() >= today else daily


def measure(kind: str, value: float, quote: dict, daily: Optional[pd.DataFrame], market: str,
            now: datetime) -> tuple[Optional[float], bool, str]:
    """(observed number, condition met, human description of the observation)."""
    price = quote.get("price")
    if price is None:
        return None, False, "no price"
    if kind == "price_above":
        return price, price >= value, f"price {price:,.2f}"
    if kind == "price_below":
        return price, price <= value, f"price {price:,.2f}"
    change = quote.get("change_percent")
    if kind in ("pct_up", "pct_down"):
        if change is None:
            return None, False, "no day change"
        met = change >= abs(value) if kind == "pct_up" else change <= -abs(value)
        return change, met, f"{change:+.2f}% today"
    if daily is None or daily.empty:
        return None, False, "no history"
    past = _completed_days(daily, market, now)
    if kind in ("rsi_above", "rsi_below"):
        closes = pd.concat([past["close"].astype(float), pd.Series([float(price)])], ignore_index=True)
        r = ind.rsi(closes).iloc[-1]
        if pd.isna(r):
            return None, False, "not enough history"
        met = r >= value if kind == "rsi_above" else r <= value
        return float(r), met, f"RSI {r:.1f}"
    if kind == "volume_spike":
        avg = float(past["volume"].tail(20).mean()) if "volume" in past else 0.0
        vol = quote.get("volume")
        if not avg or vol is None:
            return None, False, "no volume data"
        ratio = float(vol) / avg
        return ratio, ratio >= value, f"volume {ratio:.1f}x the 20-day average"
    if kind in ("high_breakout", "low_breakdown"):
        n = max(2, int(value))
        window = past.tail(n)
        if len(window) < n:
            return None, False, "not enough history"
        if kind == "high_breakout":
            level = float(window["high"].max())
            return price, price > level, f"price {price:,.2f} vs {n}-day high {level:,.2f}"
        level = float(window["low"].min())
        return price, price < level, f"price {price:,.2f} vs {n}-day low {level:,.2f}"
    return None, False, f"unknown alert kind {kind}"


def describe(kind: str, value: float) -> str:
    label, unit, _ = KINDS.get(kind, (kind, "", False))
    if unit == "price":
        return f"{label} {value:,.2f}"
    if unit == "%":
        return f"{label} {abs(value):g}%"
    if unit == "x avg":
        return f"{label} {value:g}x its 20-day average"
    if unit == "days":
        return label.replace("N-day", f"{int(value)}-day")
    return f"{label} {value:g}"


def step(alert: dict, met: bool, now: datetime) -> tuple[bool, dict]:
    """Pure state transition -> (fire?, field updates)."""
    updates: dict = {}
    if alert.get("expires_at") and now >= alert["expires_at"]:
        return False, {"status": "expired"}
    if met and alert.get("armed", True):
        last = alert.get("last_triggered_at")
        cooldown = timedelta(minutes=alert.get("cooldown_minutes") or 0)
        if alert.get("repeat") and last and now - last < cooldown:
            return False, updates
        updates.update(last_triggered_at=now, trigger_count=(alert.get("trigger_count") or 0) + 1)
        if alert.get("repeat"):
            updates["armed"] = False
        else:
            updates["status"] = "triggered"
        return True, updates
    if not met and alert.get("repeat") and not alert.get("armed", True):
        updates["armed"] = True
    return False, updates


def _default_quote(symbol: str, market: str) -> dict:
    from ..agent.agents import _resolve_fetcher

    return _resolve_fetcher(market).get_quote(symbol) or {}


def _default_daily(symbol: str, market: str) -> pd.DataFrame:
    from ..agent.agents import _resolve_fetcher

    df = _resolve_fetcher(market).get_history(symbol, period="6mo")
    return df.rename(columns=str.lower)


class AlertMonitor:
    def __init__(
        self,
        config,
        poll_seconds: int = DEFAULT_POLL_SECONDS,
        quote_fn: Callable[[str, str], dict] = _default_quote,
        daily_fn: Callable[[str, str], pd.DataFrame] = _default_daily,
        dispatcher=None,
    ):
        self._config = config
        self._poll = max(15, int(poll_seconds))
        self._quote_fn = quote_fn
        self._daily_fn = daily_fn
        self._dispatcher = dispatcher
        self._daily_cache: dict[tuple[str, str], tuple[datetime, pd.DataFrame]] = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ---- lifecycle
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="alert-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _loop(self) -> None:
        from ..core import tenant
        from ..services.accounts import for_each_user

        while not self._stop.wait(self._poll):
            try:
                # One pass over every user's alerts (quotes fetched once per
                # symbol); each fired alert is sent in its owner's scope.
                with tenant.system_scope():
                    self.tick()
            except Exception:
                logger.exception("Alert check failed")
            # Per-user settings and state: run once per user in accounts mode.
            try:
                from .scanner import run_saved_scans

                for_each_user(self._config, lambda: run_saved_scans(self._config, dispatcher=self._dispatcher),
                              "Saved scan run")
            except Exception:
                logger.exception("Saved scan run failed")
            try:
                from .risk import check_daily_limit

                for_each_user(self._config, lambda: check_daily_limit(self._config, dispatcher=self._dispatcher),
                              "Daily risk check")
            except Exception:
                logger.exception("Daily risk check failed")
            try:
                from ..services.calendar import check_reminders

                for_each_user(self._config, lambda: check_reminders(self._config, dispatcher=self._dispatcher),
                              "Calendar reminder")
                from ..services.calendar import check_earnings_results, check_event_alerts, check_results
                from ..services.thesis import check_alerts as check_theses

                for_each_user(self._config, lambda: check_theses(self._config, dispatcher=self._dispatcher),
                              "Thesis check")

                for_each_user(self._config, lambda: check_earnings_results(self._config, dispatcher=self._dispatcher),
                              "Results are out")

                for_each_user(self._config, lambda: check_event_alerts(self._config, dispatcher=self._dispatcher),
                              "Event alerts")

                for_each_user(self._config, lambda: check_results(self._config, dispatcher=self._dispatcher),
                              "Release results")
            except Exception:
                logger.exception("Calendar reminder failed")
            try:
                from ..data.nse_deals import maybe_refresh

                maybe_refresh()
            except Exception:
                logger.exception("NSE deals refresh failed")

    # ---- one pass
    def _db(self):
        from ..storage import DatabaseManager, get_db_url

        return DatabaseManager.instance(get_db_url(config=self._config))

    def _daily(self, symbol: str, market: str, now: datetime) -> Optional[pd.DataFrame]:
        key = (symbol, market)
        cached = self._daily_cache.get(key)
        if cached and now - cached[0] < DAILY_TTL:
            return cached[1]
        try:
            df = call_with_deadline(self._daily_fn, 30, symbol, market)
        except Exception as exc:
            logger.warning("Daily history for %s unavailable: %s", symbol, exc)
            return cached[1] if cached else None
        self._daily_cache[key] = (now, df)
        return df

    def tick(self, now: Optional[datetime] = None, force: bool = False) -> dict:
        """Check every active alert once. `force` ignores market hours (the
        "Check now" button). Returns {"checked": n, "fired": [...], "skipped_closed": n}."""
        from ..storage import PriceAlertEventRecord, PriceAlertRecord

        with self._lock:
            now = now or datetime.now()
            with self._db().get_session() as session:
                alerts = [
                    {c.name: getattr(r, c.name) for c in PriceAlertRecord.__table__.columns}
                    for r in session.query(PriceAlertRecord).filter(PriceAlertRecord.status == "active")
                ]
            groups: dict[tuple[str, str], list[dict]] = {}
            for a in alerts:
                groups.setdefault((a["symbol"], a["market"]), []).append(a)

            fired, updates, skipped = [], {}, 0
            aware_now = now.astimezone() if now.tzinfo is None else now
            for (symbol, market), items in groups.items():
                if not force and not is_open(market, aware_now):
                    skipped += len(items)
                    continue
                try:
                    quote = call_with_deadline(self._quote_fn, 20, symbol, market) or {}
                except Exception as exc:
                    logger.warning("Quote for %s (%s) failed: %s", symbol, market, exc)
                    continue
                daily = None
                if any(KINDS.get(a["kind"], ("", "", False))[2] for a in items):
                    daily = self._daily(symbol, market, now)
                for a in items:
                    observed, met, text = measure(a["kind"], a["value"], quote, daily, market, aware_now)
                    fire, change = step(a, met, now)
                    change.update(last_checked_at=now, last_value=observed)
                    updates[a["id"]] = change
                    if fire:
                        fired.append({"alert": a, "quote": quote, "observed": text})

            deliveries = [self._notify_as_owner(f) for f in fired]
            with self._db().get_session() as session:
                for alert_id, change in updates.items():
                    rec = session.get(PriceAlertRecord, alert_id)
                    if rec is not None:
                        for k, v in change.items():
                            setattr(rec, k, v)
                for f, (message, delivery) in zip(fired, deliveries):
                    a = f["alert"]
                    session.add(PriceAlertEventRecord(
                        user_id=a.get("user_id"), alert_id=a["id"], symbol=a["symbol"], market=a["market"], kind=a["kind"],
                        message=message, price=f["quote"].get("price"), delivery=delivery, created_at=now,
                    ))
            return {
                "checked": sum(len(v) for v in groups.values()) - skipped,
                "skipped_closed": skipped,
                "fired": [{"id": f["alert"]["id"], "symbol": f["alert"]["symbol"], "observed": f["observed"]} for f in fired],
            }

    def _notify_as_owner(self, f: dict) -> tuple[str, dict]:
        """In accounts mode, deliver as the alert's owner so it reaches only
        their channels (the monitor itself runs in the system scope)."""
        from ..core import tenant

        user_id = f["alert"].get("user_id")
        if not tenant.enabled() or user_id is None:
            return self._notify(f)
        with tenant.user_scope(user_id):
            return self._notify(f)

    def _notify(self, f: dict) -> tuple[str, dict]:
        from ..services.report import CURRENCY_SYMBOLS

        a, q = f["alert"], f["quote"]
        cur = CURRENCY_SYMBOLS.get(a["market"], "")
        price = q.get("price")
        change = q.get("change_percent")
        head = f"🔔 {a['symbol']}"
        if price is not None:
            head += f" {cur}{price:,.2f}"
        if change is not None:
            head += f" ({change:+.2f}%)"
        lines = [head, f"{describe(a['kind'], a['value'])}: {f['observed']}"]
        if a.get("note"):
            lines.append(f"📝 {a['note']}")
        if a.get("repeat"):
            lines.append("Repeating alert: re-arms once the condition clears.")
        message = "\n".join(lines)
        try:
            from ..notifiers.dispatcher import NotificationDispatcher

            dispatcher = self._dispatcher or NotificationDispatcher(self._config)
            delivery = dispatcher.send_all(message, title=f"Alert: {a['symbol']}", purpose="alert")
        except Exception as exc:
            logger.error("Alert notification failed: %s", exc)
            delivery = {}
        return message, delivery
