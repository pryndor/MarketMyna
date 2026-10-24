"""Times and time zones for scheduled reports, and how many stocks a run
analyses in parallel."""

from __future__ import annotations

import os
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Kolkata"


def workers(config) -> int:
    """Parallel analyses in a run: SCHEDULER_WORKERS, else up to 4 by CPU count."""
    n = getattr(config, "scheduler_workers", None)
    return max(1, int(n)) if n else max(1, min(4, os.cpu_count() or 1))


def zone(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def valid_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return "/" in name or name == "UTC"
    except (ZoneInfoNotFoundError, ValueError):
        return False


def parse_time(value: str) -> tuple[int, int]:
    """"HH:MM" in 24-hour time; ValueError otherwise."""
    hour, minute = (int(p) for p in str(value).strip().split(":", 1))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(value)
    return hour, minute
