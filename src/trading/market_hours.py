"""Regular trading sessions, for the alert monitor (no point polling a
closed market). Exchange holidays aren't modelled: on a holiday the price
just doesn't move, so alerts stay quiet anyway."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

# market -> (timezone, open, close). China/HK lunch breaks are ignored.
SESSIONS = {
    "india": ("Asia/Kolkata", time(9, 15), time(15, 30)),
    "us": ("America/New_York", time(9, 30), time(16, 0)),
    "global": ("America/New_York", time(9, 30), time(16, 0)),
    "china_a": ("Asia/Shanghai", time(9, 30), time(15, 0)),
    "hong_kong": ("Asia/Hong_Kong", time(9, 30), time(16, 0)),
}


def is_open(market: str, now: Optional[datetime] = None) -> bool:
    if market == "crypto" or market not in SESSIONS:
        return True
    tz_name, start, end = SESSIONS[market]
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz) if now else datetime.now(tz)
    return local.weekday() < 5 and start <= local.time() <= end


def timezone_of(market: str) -> str:
    return SESSIONS.get(market, ("UTC",))[0]


EXCHANGE_NAMES = {"india": "NSE", "us": "US market", "global": "US market", "china_a": "Shanghai/Shenzhen",
                  "hong_kong": "HKEX", "crypto": "Crypto"}
# How late free quotes are, for the chart's status line.
QUOTE_DELAY = {"crypto": "live", "us": "usually real-time", "global": "up to 15 min delayed",
               "india": "can be up to 15 min delayed", "china_a": "up to 15 min delayed", "hong_kong": "about 15 min delayed"}


def status(market: str, now: Optional[datetime] = None) -> dict:
    """Open/closed now, plus the next open or close in the exchange's time."""
    name = EXCHANGE_NAMES.get(market, market)
    if market == "crypto" or market not in SESSIONS:
        return {"market": market, "name": name, "open": True, "always_open": True,
                "delay": QUOTE_DELAY.get(market, "")}
    tz_name, start, end = SESSIONS[market]
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz) if now else datetime.now(tz)
    open_now = is_open(market, local)
    if open_now:
        nxt = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    else:
        day = local
        if local.weekday() < 5 and local.time() < start:
            nxt = day.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
        else:
            day = local + timedelta(days=1)
            while day.weekday() >= 5:
                day += timedelta(days=1)
            nxt = day.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    return {
        "market": market, "name": name, "open": open_now, "always_open": False, "timezone": tz_name,
        "next_change": nxt.isoformat(), "next_change_label": nxt.strftime("%a %H:%M"),
        "session": f"{start:%H:%M}–{end:%H:%M}", "delay": QUOTE_DELAY.get(market, ""),
    }
