"""Event calendar for the symbols people follow: upcoming earnings,
ex-dividend and dividend payment dates across every watchlist and portfolio,
plus a once-a-day reminder digest sent from the alert monitor loop.

Dates come from Yahoo's per-ticker calendar (the same source as the stock
overview's "upcoming events"); for Indian stocks the exchange's own board
meetings and corporate actions (services/nse_events.py) replace Yahoo's
estimates and add splits, bonus issues and the like. Market holidays and
sessions come from services/market_calendar.py. Modeled on OpenBB's
equity.calendar (Apache 2.0).
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

KINDS = {"earnings": "Earnings", "ex_dividend": "Ex-dividend", "dividend": "Dividend payment"}  # Yahoo's fields
ORDER = ["earnings", "board_meeting", "corporate_action", "ex_dividend", "dividend"]  # same-day order
DEFAULTS = {"notify": True, "days_before": 1, "notify_hour": 8, "timezone": "Asia/Kolkata"}
CACHE_SECONDS = 6 * 3600

# Every event type a user can turn on / off: key, group, name, what it actually is.
EVENT_TYPES = [
    ("earnings", "stocks", "Earnings", "The company reports its quarterly results (revenue, profit, guidance). "
     "The biggest single-day mover for a stock; the EPS estimate is what analysts expect."),
    ("ex_dividend", "stocks", "Ex-dividend date", "Buy before this date to get the next dividend. "
     "The share price usually drops by about the dividend amount on this day."),
    ("dividend", "stocks", "Dividend payment", "The day the declared dividend is paid into shareholders' accounts."),
    ("board_meeting", "stocks", "Board meeting", "Indian stocks: the board meets on fund raising, a split, a bonus "
     "or other business, as filed with the exchange. Results meetings show as Earnings."),
    ("corporate_action", "stocks", "Split, bonus, rights, buyback", "Indian stocks: the ex-date of a split, bonus "
     "issue, rights issue or buyback. Buy before it to be entitled; the price adjusts on the day."),
    ("fed", "us", "Fed rate decision", "The US Federal Reserve sets its policy interest rate, 8 times a year. "
     "Moves global markets, the dollar and foreign money flows into India."),
    ("us_cpi", "us", "US inflation (CPI)", "Monthly change in US consumer prices. The main number the Fed watches "
     "before deciding rates."),
    ("us_pce", "us", "US PCE inflation", "Another US inflation measure, from consumer spending data. "
     "The Fed's own preferred gauge."),
    ("us_jobs", "us", "US jobs report", "Jobs added and the unemployment rate, first Friday of the month. "
     "Shows how strong the US economy is."),
    ("us_gdp", "us", "US GDP", "How fast the US economy grew last quarter (first estimate, then revisions)."),
    ("us_ppi", "us", "US producer prices (PPI)", "Prices businesses get at the wholesale level; an early hint of "
     "where consumer inflation is heading."),
    ("us_retail", "us", "US retail sales", "Monthly change in what US shoppers spend in stores and online."),
    ("rbi", "india", "RBI rate decision", "The Reserve Bank of India's MPC sets the repo rate, about every "
     "2 months. Drives loan and deposit rates and rate-sensitive stocks."),
    ("in_cpi", "india", "India inflation (CPI)", "Monthly retail inflation from MoSPI, around the 12th. "
     "RBI aims to keep it between 2% and 6%."),
    ("in_gdp", "india", "India GDP", "How fast India's economy grew last quarter, from MoSPI at the end of "
     "Feb / May / Aug / Nov."),
    ("market_holiday", "markets", "Market holidays", "Days the India, US, Hong Kong or China exchanges are shut, "
     "with the stocks of yours that won't trade and when the market reopens."),
    ("short_day", "markets", "Short trading days", "US 1 pm closes (around Thanksgiving, Christmas, 4 July) and "
     "Hong Kong half days on the eves of Christmas, New Year and Lunar New Year."),
    ("special_session", "markets", "Special sessions", "Muhurat trading on Diwali and Union Budget day, when "
     "Indian markets open even on a weekend."),
    ("expiry", "markets", "F&O expiry", "Monthly expiry of Nifty, Sensex, Hang Seng and CSI 300 futures and "
     "options, US options expiry and quarterly quad witching: heavy volume and late swings."),
    ("index_rebalance", "markets", "Index reviews", "MSCI's quarterly index changes take effect: big foreign "
     "fund flows into or out of the stocks added or removed."),
    ("clock_change", "markets", "US clock changes", "US daylight saving starts or ends: the US session moves an "
     "hour in India and the rest of Asia."),
    ("custom", "mine", "My own events", "Dates you add yourself: SIP day, IPO listing, AGM, results you are "
     "waiting for, a bill due - one-off or repeating every month / year."),
]
REPEATS = ("none", "monthly", "yearly")
EVENT_KEYS = {k for k, *_ in EVENT_TYPES}
WORKERS = 8

Fetch = Callable[[str], dict]

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _as_date(value) -> Optional[date]:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _yf_calendar(yf_symbol: str) -> dict:
    """{kind: date, eps_estimate, revenue_estimate} from Yahoo, cached."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(yf_symbol)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    import yfinance as yf

    try:
        cal = yf.Ticker(yf_symbol).calendar or {}
    except Exception as exc:
        logger.info("Calendar for %s unavailable: %s", yf_symbol, exc)
        cal = {}
    out = {
        "earnings": _as_date(cal.get("Earnings Date")),
        "ex_dividend": _as_date(cal.get("Ex-Dividend Date")),
        "dividend": _as_date(cal.get("Dividend Date")),
        "eps_estimate": cal.get("Earnings Average"),
        "revenue_estimate": cal.get("Revenue Average"),
    }
    with _cache_lock:
        _cache[yf_symbol] = (now, out)
    return out


def list_sources(config=None, catalog: Optional[dict] = None) -> list[dict]:
    """Every watchlist / portfolio a user can pick for events: [{id, kind, name, count}]."""
    from .schedule_config import source_catalog

    cat = catalog or source_catalog(config)
    return ([{"id": f"p:{p['id']}", "kind": "portfolio", "name": p["name"], "count": len(p["symbols"])}
             for p in cat["portfolios"]]
            + [{"id": f"w:{w['id']}", "kind": "watchlist", "name": w["name"], "count": len(w["symbols"])}
               for w in cat["watchlists"]])


def clean_symbols(items) -> list[dict]:
    """[{symbol, market}] de-duplicated, upper-cased, crypto and blanks dropped."""
    out, seen = [], set()
    for i in items or []:
        sym = str((i or {}).get("symbol", "")).strip().upper()[:40]
        market = str((i or {}).get("market", "us")).strip().lower()[:32] or "us"
        if sym and market != "crypto" and (sym, market) not in seen:
            seen.add((sym, market))
            out.append({"symbol": sym, "market": market})
    return out


def followed_symbols(config=None, sources: Optional[list] = None, extra: Optional[list] = None,
                     catalog: Optional[dict] = None) -> dict[tuple[str, str], list[str]]:
    """(symbol, market) -> where it is followed ("Portfolio: X", "Watchlist: Y").
    `sources` limits it to some lists ("w:<id>" / "p:<id>"; None = all of them),
    `extra` adds stocks followed just for events."""
    from .schedule_config import source_catalog

    cat = catalog or source_catalog(config)
    want = None if sources is None else set(sources)
    out: dict[tuple[str, str], list[str]] = {}
    for p in cat["portfolios"]:
        if want is None or f"p:{p.get('id')}" in want:
            for s in p["symbols"]:
                out.setdefault((s["symbol"], s["market"]), []).append(f"Portfolio: {p['name']}")
    for w in cat["watchlists"]:
        if want is None or f"w:{w['id']}" in want:
            for s in w["symbols"]:
                out.setdefault((s["symbol"], s["market"]), []).append(f"Watchlist: {w['name']}")
    for s in clean_symbols(extra):
        out.setdefault((s["symbol"], s["market"]), []).append("Added for events")
    return {k: v for k, v in out.items() if k[1] != "crypto"}


def my_symbols(config, settings: Optional[dict] = None, catalog: Optional[dict] = None) -> dict[tuple[str, str], list[str]]:
    """The user's "My events list": their chosen lists plus extra stocks."""
    settings = settings if settings is not None else load_settings(config)
    return followed_symbols(config, settings.get("sources"), settings.get("extra_symbols"), catalog)


def _nse() -> dict:
    from .nse_events import india_events

    return india_events()


def exchange_events(symbols: dict[tuple[str, str], list[str]], start: date, end: date, data: dict) -> list[dict]:
    """Board meetings and corporate actions from the exchange for the
    followed Indian stocks: results meetings come as "earnings"."""
    india = {s for s, m in symbols if m == "india"}
    out = []
    for r in data.get("meetings") or []:
        d = date.fromisoformat(r["date"])
        if r["symbol"] not in india or not (start <= d <= end):
            continue
        results = "results" in r["topics"]
        out.append({"kind": "earnings" if results else "board_meeting",
                    "label": "Earnings" if results else "Board meeting", "symbol": r["symbol"], "date": d,
                    "detail": ("Board meeting: " + ", ".join(r["topics"])) if r["topics"] else "Board meeting",
                    "confirmed": True})
    for r in data.get("actions") or []:
        d = date.fromisoformat(r["date"])
        if r["symbol"] not in india or not (start <= d <= end):
            continue
        dividend = r["label"] == "Dividend"
        out.append({"kind": "ex_dividend" if dividend else "corporate_action",
                    "label": "Ex-dividend" if dividend else r["label"], "symbol": r["symbol"], "date": d,
                    "detail": r["subject"], "confirmed": True})
    return out


def collect(symbols: dict[tuple[str, str], list[str]], start: date, days: int, fetch: Fetch = _yf_calendar,
            exchange: Optional[Callable[[], dict]] = None) -> list[dict]:
    """Events dated start..start+days for the given symbols, soonest first.
    `exchange` returns NSE's meetings / actions (nse_events.india_events);
    by default it is used together with the live Yahoo fetch only."""
    from .analysis_run import yahoo_symbol

    if exchange is None and fetch is _yf_calendar:
        exchange = _nse

    end = start + timedelta(days=days)
    keys = list(symbols)

    def one(key):
        try:
            return key, fetch(yahoo_symbol(*key))
        except Exception as exc:
            logger.info("Calendar for %s failed: %s", key[0], exc)
            return key, {}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(one, keys))

    official = []
    if exchange and any(m == "india" for _, m in keys):
        try:
            official = exchange_events(symbols, start, end, exchange())
        except Exception as exc:
            logger.info("Exchange events unavailable: %s", exc)
    # the exchange's date wins over Yahoo's for the same stock and kind
    replaced = {(o["symbol"], o["kind"]) for o in official if o["kind"] in KINDS}
    estimates = {symbol: cal for (symbol, market), cal in results if market == "india"}

    events = []
    for (symbol, market), cal in results:
        for kind in KINDS:
            when = cal.get(kind)
            if when and start <= when <= end and not (market == "india" and (symbol, kind) in replaced):
                event = {"symbol": symbol, "market": market, "kind": kind, "label": KINDS[kind],
                         "date": when.isoformat(), "days_away": (when - start).days,
                         "followed_in": symbols[(symbol, market)]}
                if kind == "earnings":
                    event["eps_estimate"] = cal.get("eps_estimate")
                    event["revenue_estimate"] = cal.get("revenue_estimate")
                events.append(event)
    for o in official:
        when = o.pop("date")
        event = {**o, "market": "india", "date": when.isoformat(), "days_away": (when - start).days,
                 "followed_in": symbols[(o["symbol"], "india")]}
        if o["kind"] == "earnings":
            cal = estimates.get(o["symbol"]) or {}
            event["eps_estimate"] = cal.get("eps_estimate")
            event["revenue_estimate"] = cal.get("revenue_estimate")
        events.append(event)
    events.sort(key=lambda e: (e["date"], ORDER.index(e["kind"]), e["symbol"]))
    return events


# ------------------------------------------------------------------ settings


def _db(config):
    from ..storage import DatabaseManager, get_db_url

    return DatabaseManager.instance(get_db_url(config=config))


def load_settings(config) -> dict:
    from ..storage import CalendarSettingsRecord

    with _db(config).get_session() as s:
        rec = s.query(CalendarSettingsRecord).order_by(CalendarSettingsRecord.id).first()  # one row per user
        if rec is None:
            return {**DEFAULTS, "notified_day": None}
        return {c.name: getattr(rec, c.name) for c in rec.__table__.columns if c.name not in ("id", "user_id")}


def hidden(settings: dict) -> set[str]:
    """Event type keys the user turned off."""
    return {k for k in (settings.get("hidden_events") or "").split(",") if k in EVENT_KEYS}


def visible(items: list[dict], off: set[str], key: str) -> list[dict]:
    return [e for e in items if e.get(key) not in off]


def save_settings(config, **changes) -> dict:
    from ..storage import CalendarSettingsRecord

    with _db(config).get_session() as s:
        rec = s.query(CalendarSettingsRecord).order_by(CalendarSettingsRecord.id).first()  # one row per user
        if rec is None:
            rec = CalendarSettingsRecord(**DEFAULTS)
            s.add(rec)
        for k, v in changes.items():
            setattr(rec, k, v)
    return load_settings(config)


# ------------------------------------------------------------------ custom events


def _add_months(d: date, months: int) -> date:
    import calendar as pycal

    m = d.year * 12 + d.month - 1 + months
    y, mo = m // 12, m % 12 + 1
    return date(y, mo, min(d.day, pycal.monthrange(y, mo)[1]))


def occurrences(rec: dict, start: date, days: int) -> list[date]:
    """Dates of a custom event inside start..start+days (repeats roll forward;
    the 31st falls on the month's last day, 29 Feb on 28 Feb)."""
    try:
        first = date.fromisoformat(rec["date"])
    except (TypeError, ValueError):
        return []
    end = start + timedelta(days=days)
    step = {"monthly": 1, "yearly": 12}.get(rec.get("repeat") or "none")
    if not step:
        return [first] if start <= first <= end else []
    out, n = [], 0
    if first < start:  # jump close to the window instead of walking from the first date
        n = max(0, ((start.year - first.year) * 12 + start.month - first.month) // step - 1)
    while (d := _add_months(first, n * step)) <= end:
        if d >= start:
            out.append(d)
        n += 1
    return out


def list_custom(config) -> list[dict]:
    from ..storage import CustomEventRecord

    with _db(config).get_session() as s:
        return [{"id": r.id, "title": r.title, "date": r.date, "repeat": r.repeat or "none", "note": r.note or ""}
                for r in s.query(CustomEventRecord).order_by(CustomEventRecord.date, CustomEventRecord.id)]


def save_custom(config, event_id: Optional[int] = None, **fields) -> Optional[dict]:
    """Create (no id) or update a custom event; None if that id is not the user's."""
    from ..storage import CustomEventRecord

    with _db(config).get_session() as s:
        if event_id is None:
            rec = CustomEventRecord(repeat="none")
            s.add(rec)
        else:
            rec = s.query(CustomEventRecord).filter(CustomEventRecord.id == event_id).first()
            if rec is None:
                return None
        for k in ("title", "date", "repeat", "note"):
            if k in fields:
                setattr(rec, k, fields[k])
        s.flush()
        return {"id": rec.id, "title": rec.title, "date": rec.date, "repeat": rec.repeat or "none", "note": rec.note or ""}


def delete_custom(config, event_id: int) -> bool:
    from ..storage import CustomEventRecord

    with _db(config).get_session() as s:
        return bool(s.query(CustomEventRecord).filter(CustomEventRecord.id == event_id).delete())


def custom_events(records: list[dict], start: date, days: int) -> list[dict]:
    """Custom events falling in the window, one row per occurrence, soonest first."""
    out = []
    for r in records:
        for d in occurrences(r, start, days):
            out.append({**r, "first_date": r["date"], "date": d.isoformat(), "days_away": (d - start).days,
                        "kind": "custom"})
    out.sort(key=lambda e: (e["date"], e["title"]))
    return out


# ------------------------------------------------------------------ reminders


def _when(e: dict) -> str:
    return "today" if e["days_away"] == 0 else "tomorrow" if e["days_away"] == 1 else e["date"]


def digest(events: list[dict], economic: Optional[list[dict]] = None, custom: Optional[list[dict]] = None) -> str:
    lines = []
    if custom:
        lines.append("📌 Your events")
        for e in custom[:20]:
            note = f" - {e['note']}" if e.get("note") else ""
            lines.append(f"• {e['title']}: {_when(e)}{note}")
    if events:
        if lines:
            lines.append("")
        lines.append(f"📅 {len(events)} upcoming event{'s' if len(events) != 1 else ''} for stocks you follow")
        for e in events[:25]:
            extra = f" (EPS est. {e['eps_estimate']:.2f})" if e.get("eps_estimate") is not None else ""
            detail = f" - {e['detail']}" if e.get("detail") and e["kind"] != "earnings" else ""
            lines.append(f"• {e['symbol']}: {e['label']} {_when(e)}{extra}{detail}")
        if len(events) > 25:
            lines.append(f"…and {len(events) - 25} more (open Watchlist → Upcoming events)")
    markets = [e for e in economic or [] if e.get("kind") == "market"]
    economic = [e for e in economic or [] if e.get("kind") != "market"]
    if markets:
        if lines:
            lines.append("")
        lines.append("🏛 Markets")
        for e in markets[:15]:
            at = f" {e['local_time']}" if e.get("local_time") else ""
            lines.append(f"• {e['title']}: {_when(e)}{at}")
            if e.get("note"):
                lines.append(f"  {e['note']}")
            if e.get("exposure") and e.get("key") in ("market_holiday", "short_day"):
                shown = ", ".join(e["exposure"][:6]) + (f" +{len(e['exposure']) - 6} more" if len(e["exposure"]) > 6 else "")
                lines.append(f"  Your stocks there: {shown}")
    if economic:
        if lines:
            lines.append("")
        lines.append("🌐 Economic calendar")
        for e in economic[:10]:
            at = f" {e['local_time']}" if e.get("local_time") else ""
            lines.append(f"• {e['title']} ({e['region']}): {_when(e)}{at}")
            if e.get("last"):
                lines.append(f"  Last: {e['last']}")
            if e.get("why"):
                lines.append(f"  Why it matters: {e['why']}")
            if e.get("exposure"):
                shown = ", ".join(e["exposure"][:4]) + (f" +{len(e['exposure']) - 4} more" if len(e["exposure"]) > 4 else "")
                lines.append(f"  Your {e['region']} stocks: {shown}")
    return "\n".join(lines)


def _economic(start: date, days: int, tz: str, followed: Optional[dict] = None,
              off: frozenset = frozenset()) -> list[dict]:
    """Macro and market events (holidays, sessions, expiries) for the reminder
    window that the user has on, with their last reading and why they matter;
    never raises."""
    try:
        from . import econ_calendar

        events = econ_calendar.collect(start, days)["events"] + _markets(start, days)
        events.sort(key=lambda e: (e["date"], e["time"] or "", e["title"]))
        for e in events:
            e["local_time"] = econ_calendar.local_time(e, tz)
        return visible(econ_calendar.enrich(events, followed), off, "key")
    except Exception as exc:
        logger.info("Economic calendar for reminders failed: %s", exc)
        return []


def _markets(start: date, days: int) -> list[dict]:
    try:
        from . import market_calendar

        return market_calendar.collect(start, days)["events"]
    except Exception as exc:
        logger.info("Market calendar failed: %s", exc)
        return []


def _tz(settings: dict) -> ZoneInfo:
    try:
        return ZoneInfo(settings.get("timezone") or DEFAULTS["timezone"])
    except Exception:
        return ZoneInfo(DEFAULTS["timezone"])


def _local(now: Optional[datetime], tz: ZoneInfo) -> datetime:
    if now is None:
        return datetime.now(tz)
    # a naive `now` is read as already in the settings' timezone
    return now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)


def gather(config, day: date, window: int, followed: dict, off: set, tz: str, fetch: Fetch = _yf_calendar,
           economic_fetch: Optional[Callable] = _economic, custom_fetch: Optional[Callable] = list_custom) -> dict:
    """Everything due day..day+window for these stocks, minus the event types in `off`."""
    events = visible(collect(followed, day, window, fetch), off, "kind") if followed else []
    economic = economic_fetch(day, window, tz, followed, frozenset(off)) if economic_fetch else []
    custom = custom_events(custom_fetch(config), day, window) if custom_fetch and "custom" not in off else []
    return {"events": events, "economic": economic, "custom": custom}


def _send(config, dispatcher, found: dict, title: str) -> dict:
    if not (found["events"] or found["economic"] or found["custom"]):
        return {}
    try:
        from ..notifiers.dispatcher import NotificationDispatcher

        dispatcher = dispatcher or NotificationDispatcher(config)
        return dispatcher.send_all(digest(found["events"], found["economic"], found["custom"]),
                                   title=title, purpose="alert")
    except Exception as exc:
        logger.error("%s failed: %s", title, exc)
        return {}


def check_reminders(config, now: Optional[datetime] = None, dispatcher=None, fetch: Fetch = _yf_calendar,
                    force: bool = False, economic_fetch: Optional[Callable] = _economic,
                    custom_fetch: Optional[Callable] = list_custom) -> Optional[dict]:
    """Monitor hook: once a day, after `notify_hour`, send one digest of events
    due within `days_before` days. `force` sends now (the "Send test" button)."""
    settings = load_settings(config)
    if not settings.get("notify") and not force:
        return None
    tz = _tz(settings)
    local = _local(now, tz)
    today = local.strftime("%Y-%m-%d")
    if not force and (settings.get("notified_day") == today or local.hour < int(settings.get("notify_hour") or 0)):
        return None

    window = int(settings.get("days_before") or 1)
    found = gather(config, local.date(), window, my_symbols(config, settings), hidden(settings), str(tz),
                   fetch, economic_fetch, custom_fetch)
    delivery = _send(config, dispatcher, found, "Upcoming events")
    if not force:
        save_settings(config, notified_day=today)
    return {**found, "delivery": delivery}


# ------------------------------------------------------------------ named event alerts

ALERT_FIELDS = ("name", "enabled", "sources", "symbols", "event_types", "days_before", "notify_hour")


def _alert_dict(r) -> dict:
    return {"id": r.id, "name": r.name, "enabled": bool(r.enabled), "sources": r.sources,
            "symbols": r.symbols or [], "event_types": r.event_types, "days_before": r.days_before or 0,
            "notify_hour": r.notify_hour if r.notify_hour is not None else 8, "notified_day": r.notified_day}


def list_alerts(config) -> list[dict]:
    from ..storage import EventAlertRecord

    with _db(config).get_session() as s:
        return [_alert_dict(r) for r in s.query(EventAlertRecord).order_by(EventAlertRecord.id)]


def save_alert(config, alert_id: Optional[int] = None, **changes) -> Optional[dict]:
    """Create (no id) or update an alert; None if that id is not the user's."""
    from ..storage import EventAlertRecord

    if "symbols" in changes:
        changes["symbols"] = clean_symbols(changes["symbols"])
    if changes.get("event_types") is not None:
        changes["event_types"] = sorted(set(changes["event_types"]) & EVENT_KEYS)
    with _db(config).get_session() as s:
        if alert_id is None:
            rec = EventAlertRecord(name="Event alert", enabled=True, days_before=1, notify_hour=8)
            s.add(rec)
        else:
            rec = s.query(EventAlertRecord).filter(EventAlertRecord.id == alert_id).first()
            if rec is None:
                return None
        for k, v in changes.items():
            if k in ALERT_FIELDS or k == "notified_day":
                setattr(rec, k, v)
        if {"days_before", "notify_hour", "event_types", "sources", "symbols"} & set(changes) and "notified_day" not in changes:
            rec.notified_day = None  # a changed alert may go out again today
        s.flush()
        return _alert_dict(rec)


def delete_alert(config, alert_id: int) -> bool:
    from ..storage import EventAlertRecord

    with _db(config).get_session() as s:
        return bool(s.query(EventAlertRecord).filter(EventAlertRecord.id == alert_id).delete())


def alert_off(alert: dict) -> set:
    types = alert.get("event_types")
    return set() if types is None else EVENT_KEYS - set(types)


def run_alert(config, alert: dict, local: datetime, dispatcher=None, fetch: Fetch = _yf_calendar,
              economic_fetch: Optional[Callable] = _economic, custom_fetch: Optional[Callable] = list_custom) -> dict:
    followed = followed_symbols(config, alert.get("sources"), alert.get("symbols"))
    found = gather(config, local.date(), int(alert.get("days_before") or 0), followed, alert_off(alert),
                   str(local.tzinfo), fetch, economic_fetch, custom_fetch)
    return {**found, "delivery": _send(config, dispatcher, found, alert.get("name") or "Event alert")}


def check_event_alerts(config, now: Optional[datetime] = None, dispatcher=None, fetch: Fetch = _yf_calendar,
                       economic_fetch: Optional[Callable] = _economic,
                       custom_fetch: Optional[Callable] = list_custom) -> list[str]:
    """Monitor hook: each enabled alert goes out once a day after its hour; returns the names sent."""
    alerts = [a for a in list_alerts(config) if a["enabled"]]
    if not alerts:
        return []
    local = _local(now, _tz(load_settings(config)))
    today, ran = local.strftime("%Y-%m-%d"), []
    for a in alerts:
        if a["notified_day"] == today or local.hour < a["notify_hour"]:
            continue
        try:
            run_alert(config, a, local, dispatcher, fetch, economic_fetch, custom_fetch)
        except Exception as exc:
            logger.error("Event alert %s failed: %s", a["name"], exc)
        save_alert(config, a["id"], notified_day=today)
        ran.append(a["name"])
    return ran


def result_message(done: list[dict]) -> str:
    lines = []
    for e in done:
        lines.append(f"📊 {e['title']} is out: {e['result']}")
        if e.get("verdict"):
            lines.append(f"  {e['verdict']}")
        if e.get("exposure"):
            shown = ", ".join(e["exposure"][:4]) + (f" +{len(e['exposure']) - 4} more" if len(e["exposure"]) > 4 else "")
            lines.append(f"  Your {e['region']} stocks: {shown}")
    return "\n".join(lines)


def _today_economic(day: date) -> list[dict]:
    from . import econ_calendar

    return econ_calendar.collect(day, 0)["events"]


def _fresh_points() -> dict:
    from . import econ_calendar

    return econ_calendar.points(max_age=15 * 60)  # shared by every user, re-read at most every 15 min


def check_results(config, now: Optional[datetime] = None, dispatcher=None,
                  today_events: Callable[[date], list[dict]] = _today_economic,
                  fetch_points: Callable[[], dict] = _fresh_points) -> Optional[list[dict]]:
    """Monitor hook: once a US data release the user has on is out, send its
    actual number against the one before - one message per release."""
    settings = load_settings(config)
    if not settings.get("notify"):
        return None
    local = _local(now, _tz(settings))
    today = local.strftime("%Y-%m-%d")
    sent = _sent_keys(settings, local.date())
    off = hidden(settings)

    from . import econ_calendar

    try:
        events = [e for e in today_events(local.date()) if (e.get("key") or "") not in off | sent]
        done = econ_calendar.results(events, local, fetch_points)
    except Exception as exc:
        logger.info("Release results check failed: %s", exc)
        return None
    done = [e for e in done if e["key"] not in off | sent]
    if not done:
        return None
    econ_calendar.enrich(done, my_symbols(config, settings), read=dict)
    try:
        from ..notifiers.dispatcher import NotificationDispatcher

        dispatcher = dispatcher or NotificationDispatcher(config)
        dispatcher.send_all(result_message(done), title="Economic data is out", purpose="alert")
    except Exception as exc:
        logger.error("Release result message failed: %s", exc)
    save_settings(config, results_sent=f"{today}:{','.join(sorted(sent | {e['key'] for e in done}))}")
    return done


# ------------------------------------------------------------------ company results

STOCK_KEEP_DAYS = 7  # "e:SYMBOL:date" sent-markers outlive the day; economic ones don't
EARNINGS_RECHECK = 30 * 60  # look for a fresh actual EPS at most this often per stock
_earnings_checked: dict[str, float] = {}


def _sent_keys(settings: dict, today: date) -> set[str]:
    """Release / results markers already sent: today's economic keys plus
    company results from the last STOCK_KEEP_DAYS."""
    day, _, raw = (settings.get("results_sent") or "").partition(":")
    keys = set(raw.split(",")) - {""}
    keep = set()
    for k in keys:
        if k.startswith("e:"):
            try:
                if (today - date.fromisoformat(k.rsplit(":", 1)[1])).days <= STOCK_KEEP_DAYS:
                    keep.add(k)
            except ValueError:
                continue
        elif day == today.isoformat():
            keep.add(k)
    return keep


def _recent_reports(config, followed: dict, day: date, fetch: Fetch = _yf_calendar) -> list[tuple[str, str]]:
    """Followed stocks whose earnings date was in the last two days."""
    return [(e["symbol"], e["market"]) for e in collect(followed, day - timedelta(days=2), 2, fetch)
            if e["kind"] == "earnings" and e["days_away"] <= 2]


def check_earnings_results(config, now: Optional[datetime] = None, dispatcher=None,
                           reports: Optional[Callable] = None, build: Optional[Callable] = None) -> Optional[list[str]]:
    """Monitor hook: once a stock in the user's events list has reported and
    Yahoo has the actual EPS, send actual vs expected and the price move - once."""
    settings = load_settings(config)
    off = hidden(settings)
    if not settings.get("notify") or "earnings" in off:
        return None
    local = _local(now, _tz(settings))
    sent = _sent_keys(settings, local.date())
    try:
        candidates = (reports or _recent_reports)(config, my_symbols(config, settings), local.date())
    except Exception as exc:
        logger.info("Earnings results check failed: %s", exc)
        return None
    if build is None:
        from .earnings import build
    from .earnings import results_line

    lines, new_keys = [], set()
    clock = time.time()
    for symbol, market in candidates:
        if any(k.startswith(f"e:{symbol}:") for k in sent):
            continue
        if clock - _earnings_checked.get(f"{symbol}:{market}", 0) < EARNINGS_RECHECK:
            continue
        _earnings_checked[f"{symbol}:{market}"] = clock
        try:
            data = build(symbol, market, with_options=False, use_cache=False)
        except Exception as exc:
            logger.info("Earnings for %s unavailable: %s", symbol, exc)
            continue
        line = results_line(symbol, data)
        if line:
            lines.append(f"• {line}")
            new_keys.add(f"e:{symbol}:{data['latest']['date']}")
    if not lines:
        return None
    try:
        from ..notifiers.dispatcher import NotificationDispatcher

        dispatcher = dispatcher or NotificationDispatcher(config)
        dispatcher.send_all("📊 Results are out\n" + "\n".join(lines), title="Results are out", purpose="alert")
    except Exception as exc:
        logger.error("Earnings results message failed: %s", exc)
    save_settings(config, results_sent=f"{local.date().isoformat()}:{','.join(sorted(sent | new_keys))}")
    return lines
