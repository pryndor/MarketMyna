"""How expensive the whole market is, against its own history.

US: S&P 500 P/E, Shiller P/E (CAPE), dividend yield and earnings yield,
monthly since 1871, from multpl.com tables (no key). Each reading is placed
as a percentile of its full history and of the years since 1990.

India: P/E, P/B and dividend yield of the main Nifty indices from NSE's
allIndices feed (current values only). One snapshot a day is kept under
~/.marketmyna/valuation/, so a percentile appears once a year of history
has built up; until then the card shows the reading and the date the
history starts. Failed fetches serve the last good copy marked stale.

Readings are descriptive (where today sits in the record), not a forecast.
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

import requests

from src.core.home import app_home

logger = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600
MIN_HISTORY_DAYS = 250  # trading days of India snapshots before a percentile is shown

US_SERIES = [
    ("shiller-pe", "Shiller P/E (CAPE)", "Price over 10-year average inflation-adjusted earnings"),
    ("s-p-500-pe-ratio", "S&P 500 P/E", "Price over trailing 12-month earnings"),
    ("s-p-500-earnings-yield", "Earnings yield", "Trailing earnings over price, %"),
    ("s-p-500-dividend-yield", "Dividend yield", "Trailing dividends over price, %"),
]
INDIA_INDICES = ["NIFTY 50", "NIFTY NEXT 50", "NIFTY 500", "NIFTY BANK", "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100"]
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _dir() -> Path:
    path = app_home() / "valuation"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read(name: str):
    try:
        return json.loads((_dir() / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(name: str, data) -> None:
    try:
        tmp = _dir() / f".{name}.tmp"
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(_dir() / name)
    except OSError as exc:
        logger.warning("Could not save %s: %s", name, exc)


# ---------------------------------------------------------------- US (multpl)


def parse_multpl(page: str) -> list[tuple[str, float, bool]]:
    """(ISO date, value, estimated) rows, newest first, from a /table/by-month page."""
    rows = []
    for when, cell in re.findall(r"<td>([A-Z][a-z]{2} \d{1,2}, \d{4})</td>\s*<td>(.*?)</td>", page, re.S):
        text = re.sub(r"<[^>]+>|\s", "", html.unescape(cell)).replace(" ", "")
        estimated = "†" in text  # dagger: multpl's estimate marker
        try:
            value = float(text.replace("†", "").replace("%", ""))
        except ValueError:
            continue
        rows.append((datetime.strptime(when, "%b %d, %Y").date().isoformat(), value, estimated))
    return rows


def _multpl(slug: str) -> str:
    r = requests.get(f"https://www.multpl.com/{slug}/table/by-month", headers=_UA, timeout=20)
    r.raise_for_status()
    return r.text


def percentile(values: list[float], value: float) -> Optional[float]:
    """Share of the history at or below `value`, 0-100."""
    if not values:
        return None
    return round(sum(v <= value for v in values) / len(values) * 100, 1)


def _median(values: list[float]) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def us_series(slug: str, label: str, note: str, rows: list[tuple[str, float, bool]]) -> Optional[dict]:
    if not rows:
        return None
    when, value, estimated = rows[0]
    history = [v for _, v, _ in rows[1:]]  # the monthly record, excluding today's reading
    since_1990 = [v for d, v, _ in rows[1:] if d >= "1990-01-01"]
    spark = [{"date": d, "value": v} for d, v, _ in reversed(rows[:241])]  # about 20 years, monthly
    return {
        "key": slug, "label": label, "note": note, "value": value, "date": when, "estimated": estimated,
        "percentile_all": percentile(history, value), "percentile_1990": percentile(since_1990, value),
        "median_all": _median(history), "median_1990": _median(since_1990),
        "since": rows[-1][0], "spark": spark,
    }


def _us(fetch: Callable[[str], str]) -> dict:
    out, failed = [], []
    for slug, label, note in US_SERIES:
        try:
            rows = parse_multpl(fetch(slug))
            if not rows:
                raise ValueError("no rows")
            _write(f"multpl-{slug}.json", rows)
            stale = False
        except Exception as exc:  # noqa: BLE001 - fall back to the last good copy
            logger.info("multpl %s failed: %s", slug, exc)
            rows, stale = [tuple(r) for r in (_read(f"multpl-{slug}.json") or [])], True
        item = us_series(slug, label, note, rows)
        if item:
            item["stale"] = stale
            out.append(item)
        else:
            failed.append(label)
    return {"series": out, "failed": failed, "source": "multpl.com (S&P 500 data back to 1871)"}


# ------------------------------------------------------------------ India (NSE)


def _nse_indices() -> list[dict]:
    from ..trading.options import _nse

    return (_nse._get("allIndices", {}) or {}).get("data") or []


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _india(fetch: Callable[[], list[dict]], today: Optional[date] = None) -> dict:
    today = today or date.today()
    history: dict[str, dict] = _read("nse-history.json") or {}
    stale = False
    try:
        rows = {r.get("index"): r for r in fetch()}
        snap = {name: {"pe": _num(r.get("pe")), "pb": _num(r.get("pb")), "dy": _num(r.get("dy")),
                       "last": _num(r.get("last"))}
                for name in INDIA_INDICES if (r := rows.get(name)) and _num(r.get("pe"))}
        if not snap:
            raise ValueError("NSE returned no index valuations")
        history[today.isoformat()] = snap
        _write("nse-history.json", history)
    except Exception as exc:  # noqa: BLE001 - serve the latest saved day
        logger.info("NSE allIndices failed: %s", exc)
        stale = True
    if not history:
        return {"indices": [], "stale": True, "source": "NSE"}

    days = sorted(history)
    latest_day = days[-1]
    out = []
    for name in INDIA_INDICES:
        now = history[latest_day].get(name)
        if not now:
            continue
        item = {"index": name, "date": latest_day, "last": now.get("last"), "history_from": days[0],
                "history_days": len(days)}
        for metric in ("pe", "pb", "dy"):
            past = [history[d][name][metric] for d in days[:-1] if history[d].get(name, {}).get(metric)]
            item[metric] = now.get(metric)
            item[f"{metric}_percentile"] = (percentile(past, now[metric])
                                            if now.get(metric) and len(past) >= MIN_HISTORY_DAYS else None)
        year_ago = [d for d in days if d <= (today.replace(year=today.year - 1)).isoformat()]
        item["pe_year_ago"] = history[year_ago[-1]][name]["pe"] if year_ago and name in history[year_ago[-1]] else None
        out.append(item)
    return {"indices": out, "stale": stale, "as_of": latest_day,
            "source": "NSE index P/E, P/B and dividend yield; daily snapshots kept from " + days[0]}


def build(fetch_us: Callable[[str], str] = _multpl, fetch_india: Callable[[], list[dict]] = _nse_indices,
          use_cache: bool = True) -> dict:
    if use_cache:
        with _lock:
            hit = _cache.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    out = {"us": _us(fetch_us), "india": _india(fetch_india), "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if use_cache and (out["us"]["series"] or out["india"]["indices"]):
        with _lock:
            _cache["all"] = (time.time(), out)
    return out


def snapshot_loop(check_seconds: int = 3 * 3600) -> None:
    """Background thread: save today's NSE valuations once, after the close
    (16:00 IST), on weekdays, so the history builds without visitors."""
    from zoneinfo import ZoneInfo

    time.sleep(180)  # let start-up traffic settle
    while True:
        try:
            now = datetime.now(ZoneInfo("Asia/Kolkata"))
            saved = _read("nse-history.json") or {}
            if now.weekday() < 5 and now.hour >= 16 and now.date().isoformat() not in saved:
                _india(_nse_indices, today=now.date())
        except Exception as exc:  # noqa: BLE001 - never kill the thread
            logger.info("Valuation snapshot failed: %s", exc)
        time.sleep(check_seconds)
