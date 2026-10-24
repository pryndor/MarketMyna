"""Event calendar: upcoming earnings / dividend dates for followed symbols,
economic releases, market holidays and sessions, and the daily reminder
settings (marketmyna/services/calendar.py)."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from marketmyna.api.deps import get_config_dep

router = APIRouter()


class SymbolIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    market: str = Field(default="us", max_length=32)


class CalendarSettingsIn(BaseModel):
    notify: Optional[bool] = None
    days_before: Optional[int] = Field(default=None, ge=0, le=14)
    notify_hour: Optional[int] = Field(default=None, ge=0, le=23)
    timezone: Optional[str] = None
    hidden_events: Optional[list[str]] = None
    # "My events list": the lists that count ("w:<id>" / "p:<id>"); all_lists=True goes back to every list
    sources: Optional[list[str]] = Field(default=None, max_length=200)
    all_lists: Optional[bool] = None
    extra_symbols: Optional[list[SymbolIn]] = Field(default=None, max_length=200)


class AlertIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    enabled: Optional[bool] = None
    sources: Optional[list[str]] = Field(default=None, max_length=200)
    all_lists: Optional[bool] = None  # back to every list (sources = null)
    symbols: Optional[list[SymbolIn]] = Field(default=None, max_length=200)
    event_types: Optional[list[str]] = None
    all_types: Optional[bool] = None
    days_before: Optional[int] = Field(default=None, ge=0, le=14)
    notify_hour: Optional[int] = Field(default=None, ge=0, le=23)


class CustomIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    date: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    repeat: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=500)


MAX_ALERTS = 20
MAX_CUSTOM = 200
_last_send: dict[str, float] = {}


def _throttle(request: Request, what: str) -> None:
    """One manual send a minute per user (they go to real channels)."""
    from marketmyna.core import tenant

    key = f"{tenant.current_user_id() or request.client.host if request.client else ''}:{what}"
    now = time.time()
    if now - _last_send.get(key, 0) < 60:
        raise HTTPException(status_code=429, detail="Sent a moment ago - try again in a minute.")
    _last_send[key] = now


def _check_types(keys: list[str]) -> None:
    from marketmyna.services.calendar import EVENT_KEYS

    unknown = set(keys) - EVENT_KEYS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown event types: {', '.join(sorted(unknown))}")


def _public(settings: dict) -> dict:
    from marketmyna.services.calendar import hidden

    out = {k: settings[k] for k in ("notify", "days_before", "notify_hour", "timezone")}
    return {**out, "hidden_events": sorted(hidden(settings)), "sources": settings.get("sources"),
            "extra_symbols": settings.get("extra_symbols") or []}


@router.get("/calendar")
def upcoming_events(days: int = Query(default=30, ge=1, le=120), config=Depends(get_config_dep)) -> dict:
    from marketmyna.services import econ_calendar, market_calendar
    from marketmyna.services.calendar import (
        EVENT_TYPES,
        _fresh_points,
        collect,
        custom_events,
        hidden,
        list_alerts,
        list_custom,
        list_sources,
        load_settings,
        my_symbols,
        visible,
    )
    from marketmyna.services.schedule_config import source_catalog

    settings = load_settings(config)
    catalog = source_catalog(config)
    symbols = my_symbols(config, settings, catalog)
    tz = settings.get("timezone") or "Asia/Kolkata"
    today = datetime.now(ZoneInfo(tz)).date()
    econ = econ_calendar.collect(today, days)
    markets = market_calendar.collect(today, days)
    econ["events"] = sorted(econ["events"] + markets["events"], key=lambda e: (e["date"], e["time"] or "", e["title"]))
    econ["warnings"] += markets["warnings"]
    for e in econ["events"]:
        e["local_time"] = econ_calendar.local_time(e, tz)
    econ_calendar.enrich(econ["events"], symbols)
    now = datetime.now(ZoneInfo(tz))
    for done in econ_calendar.results([e for e in econ["events"] if e["days_away"] == 0], now, _fresh_points):
        for e in econ["events"]:
            if e["date"] == done["date"] and e["key"] == done["key"]:
                e["result"], e["verdict"] = done["result"], done["verdict"]
    off = hidden(settings)
    custom = list_custom(config)
    return {"from": today.isoformat(), "days": days, "symbols": len(symbols),
            "events": visible(collect(symbols, today, days), off, "kind"),
            "economic": visible(econ["events"], off, "key"),
            "custom": custom_events(custom, today, days) if "custom" not in off else [],
            "custom_all": custom,
            "economic_warnings": econ["warnings"], "settings": _public(settings),
            "lists": list_sources(config, catalog), "alerts": list_alerts(config),
            "event_types": [{"key": k, "group": g, "name": n, "about": a} for k, g, n, a in EVENT_TYPES]}


@router.put("/calendar/settings")
def update_settings(body: CalendarSettingsIn, config=Depends(get_config_dep)) -> dict:
    from marketmyna.services.calendar import clean_symbols, save_settings

    changes = body.model_dump(exclude_none=True)
    if "hidden_events" in changes:
        _check_types(changes["hidden_events"])
        changes["hidden_events"] = ",".join(sorted(set(changes["hidden_events"]))) or None
    if "timezone" in changes:
        try:
            ZoneInfo(changes["timezone"])
        except Exception:
            raise HTTPException(status_code=400, detail=f"Unknown timezone '{changes['timezone']}'")
    if changes.pop("all_lists", False):
        changes["sources"] = None
    if "extra_symbols" in changes:
        changes["extra_symbols"] = clean_symbols(changes["extra_symbols"])
    return _public(save_settings(config, **changes))


@router.post("/calendar/remind-now")
def remind_now(request: Request, config=Depends(get_config_dep)) -> dict:
    """Send today's digest right away (does not count as the daily one)."""
    from marketmyna.services.calendar import check_reminders

    _throttle(request, "digest")
    result = check_reminders(config, force=True) or {"events": [], "delivery": {}}
    count = len(result["events"]) + len(result.get("economic", [])) + len(result.get("custom", []))
    return {"sent": bool(count), "count": count, "delivery": result["delivery"]}


# ------------------------------------------------------------------ named event alerts


def _alert_changes(body: AlertIn) -> dict:
    changes = body.model_dump(exclude_none=True)
    if "event_types" in changes:
        _check_types(changes["event_types"])
    if changes.pop("all_types", False):
        changes["event_types"] = None
    if changes.pop("all_lists", False):
        changes["sources"] = None
    return changes


@router.post("/calendar/alerts", status_code=201)
def create_alert(body: AlertIn, config=Depends(get_config_dep)) -> dict:
    from marketmyna.services.calendar import list_alerts, save_alert

    if len(list_alerts(config)) >= MAX_ALERTS:
        raise HTTPException(status_code=400, detail=f"Up to {MAX_ALERTS} event alerts.")
    return save_alert(config, None, **_alert_changes(body))


@router.put("/calendar/alerts/{alert_id}")
def update_alert(alert_id: int, body: AlertIn, config=Depends(get_config_dep)) -> dict:
    from marketmyna.services.calendar import save_alert

    out = save_alert(config, alert_id, **_alert_changes(body))
    if out is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return out


@router.delete("/calendar/alerts/{alert_id}", status_code=204)
def remove_alert(alert_id: int, config=Depends(get_config_dep)) -> None:
    from marketmyna.services.calendar import delete_alert

    if not delete_alert(config, alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")


@router.post("/calendar/alerts/{alert_id}/send-now")
def send_alert_now(alert_id: int, request: Request, config=Depends(get_config_dep)) -> dict:
    """Run one alert right away (does not count as its daily run)."""
    from marketmyna.services.calendar import _local, _tz, list_alerts, load_settings, run_alert

    alert = next((a for a in list_alerts(config) if a["id"] == alert_id), None)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    _throttle(request, f"alert{alert_id}")
    result = run_alert(config, alert, _local(None, _tz(load_settings(config))))
    count = len(result["events"]) + len(result["economic"]) + len(result["custom"])
    return {"sent": bool(count), "count": count, "delivery": result["delivery"]}


# ------------------------------------------------------------------ custom events


def _custom_fields(body: CustomIn) -> dict:
    from datetime import date as _date

    from marketmyna.services.calendar import REPEATS

    fields = body.model_dump(exclude_none=True)
    if "date" in fields:
        try:
            _date.fromisoformat(fields["date"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Not a real date")
    if "repeat" in fields and fields["repeat"] not in REPEATS:
        raise HTTPException(status_code=400, detail="Repeat must be none, monthly or yearly")
    if "title" in fields:
        fields["title"] = fields["title"].strip()
    return fields


@router.post("/calendar/custom-events", status_code=201)
def create_custom(body: CustomIn, config=Depends(get_config_dep)) -> dict:
    from marketmyna.services.calendar import list_custom, save_custom

    fields = _custom_fields(body)
    if not fields.get("title") or not fields.get("date"):
        raise HTTPException(status_code=400, detail="A title and a date are needed")
    if len(list_custom(config)) >= MAX_CUSTOM:
        raise HTTPException(status_code=400, detail=f"Up to {MAX_CUSTOM} of your own events.")
    return save_custom(config, None, **fields)


@router.put("/calendar/custom-events/{event_id}")
def update_custom(event_id: int, body: CustomIn, config=Depends(get_config_dep)) -> dict:
    from marketmyna.services.calendar import save_custom

    out = save_custom(config, event_id, **_custom_fields(body))
    if out is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return out


@router.delete("/calendar/custom-events/{event_id}", status_code=204)
def remove_custom(event_id: int, config=Depends(get_config_dep)) -> None:
    from marketmyna.services.calendar import delete_custom

    if not delete_custom(config, event_id):
        raise HTTPException(status_code=404, detail="Event not found")
