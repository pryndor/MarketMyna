"""Mutual-fund NAV snapshots for the scheduled report (Indian AMFI schemes
via mfapi.in, free and keyless - the same source daily_stock_analysis's
MF_LIST uses)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_MFAPI = "https://api.mfapi.in/mf/{code}"


def _return_since(points: list[tuple[datetime, float]], days: int) -> Optional[float]:
    """% change from the last NAV on/before `days` ago to the latest NAV."""
    if len(points) < 2:
        return None
    latest_date, latest_nav = points[0]
    cutoff = latest_date - timedelta(days=days)
    past = next((nav for day, nav in points if day <= cutoff), None)
    if not past:
        return None
    return (latest_nav - past) / past * 100


def fund_snapshot(code: str) -> Optional[dict]:
    """Latest NAV, day change and 1M/1Y returns for one scheme code."""
    try:
        resp = requests.get(_MFAPI.format(code=code.strip()), timeout=15)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        logger.warning("NAV for scheme %s unavailable: %s", code, exc)
        return None

    points = []
    for row in payload.get("data") or []:
        try:
            points.append((datetime.strptime(row["date"], "%d-%m-%Y"), float(row["nav"])))
        except (KeyError, ValueError):
            continue
    if not points:
        return None
    points.sort(key=lambda p: p[0], reverse=True)
    latest_date, nav = points[0]
    previous = points[1][1] if len(points) > 1 else None
    meta = payload.get("meta") or {}
    return {
        "code": str(code).strip(),
        "name": meta.get("scheme_name") or str(code),
        "category": meta.get("scheme_category"),
        "nav": nav,
        "nav_date": latest_date.date().isoformat(),
        "change_percent": (nav - previous) / previous * 100 if previous else None,
        "return_1m": _return_since(points, 30),
        "return_1y": _return_since(points, 365),
    }


def fund_snapshots(codes) -> list[dict]:
    out = []
    for code in dict.fromkeys(str(c).strip() for c in codes or [] if str(c).strip()):
        snap = fund_snapshot(code)
        if snap:
            out.append(snap)
    return out
