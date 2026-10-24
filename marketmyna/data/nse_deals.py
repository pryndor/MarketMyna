"""NSE bulk and block deals: large trades by named clients (funds, promoters,
brokers) that the exchange publishes daily.

NSE's archive CSVs (the same host the listings use, which works from cloud
servers) only hold the latest trading day, so every fetch is also saved to
~/.marketmyna/deals/<date>.json (the app data volume) and history is built
from those files. The alert monitor refreshes hourly in the evening so days
are collected even when nobody opens the page.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from marketmyna.core.home import app_home

logger = logging.getLogger(__name__)

URLS = {"bulk": "https://nsearchives.nseindia.com/content/equities/bulk.csv",
        "block": "https://nsearchives.nseindia.com/content/equities/block.csv"}
CACHE_SECONDS = 1800

Fetch = Callable[[str], str]

_last: dict[str, float] = {}
_lock = threading.Lock()


def _dir() -> Path:
    path = app_home() / "deals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _http(url: str) -> str:
    import requests

    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    return resp.text


def _num(v) -> Optional[float]:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def parse(text: str, kind: str) -> list[dict]:
    rows = []
    for r in csv.DictReader(io.StringIO(text.strip())):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        try:
            day = datetime.strptime(r["Date"], "%d-%b-%Y").date().isoformat()
        except (KeyError, ValueError):
            continue
        qty, price = _num(r.get("Quantity Traded")), _num(r.get("Trade Price / Wght. Avg. Price"))
        rows.append({"date": day, "kind": kind, "symbol": r.get("Symbol", "").upper(), "name": r.get("Security Name"),
                     "client": r.get("Client Name"), "side": (r.get("Buy/Sell") or "").lower(), "qty": qty, "price": price,
                     "value": qty * price if qty and price else None,
                     "remarks": None if r.get("Remarks") in (None, "", "-") else r.get("Remarks")})
    return rows


def refresh(fetch: Fetch = _http, force: bool = False) -> int:
    """Fetch today's files (at most every 30 min) and merge them into the per-day store."""
    with _lock:
        if not force and time.time() - _last.get("fetch", 0) < CACHE_SECONDS:
            return 0
        _last["fetch"] = time.time()
    fresh: list[dict] = []
    for kind, url in URLS.items():
        try:
            fresh += parse(fetch(url), kind)
        except Exception as exc:
            logger.warning("NSE %s deals unavailable: %s", kind, exc)
    by_day: dict[str, list[dict]] = {}
    for r in fresh:
        by_day.setdefault(r["date"], []).append(r)
    for day, rows in by_day.items():
        path = _dir() / f"{day}.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        seen = {json.dumps(r, sort_keys=True) for r in existing}
        merged = existing + [r for r in rows if json.dumps(r, sort_keys=True) not in seen]
        path.write_text(json.dumps(merged), encoding="utf-8")
    return len(fresh)


def recent(days: int = 30, symbol: Optional[str] = None, today: Optional[date] = None, fetch: Fetch = _http) -> dict:
    refresh(fetch)
    today = today or date.today()
    since = (today - timedelta(days=days)).isoformat()
    rows: list[dict] = []
    stored = sorted(p.stem for p in _dir().glob("*.json"))
    for day in stored:
        if day >= since:
            rows += json.loads((_dir() / f"{day}.json").read_text(encoding="utf-8"))
    if symbol:
        rows = [r for r in rows if r["symbol"] == symbol.upper()]
    rows = _merge_kinds(rows)
    rows.sort(key=lambda r: (r["date"], r.get("value") or 0), reverse=True)
    return {"days": days, "history_from": stored[0] if stored else None, "latest": stored[-1] if stored else None,
            "count": len(rows), "deals": rows[:300]}


def _merge_kinds(rows: list[dict]) -> list[dict]:
    """A block trade large enough to be a bulk deal is listed in both files:
    keep one row, kind "block & bulk"."""
    merged: dict[tuple, dict] = {}
    for r in rows:
        key = (r["date"], r["symbol"], r.get("client"), r["side"], r.get("qty"), r.get("price"))
        if key in merged and merged[key]["kind"] != r["kind"]:
            merged[key] = {**merged[key], "kind": "block & bulk", "remarks": merged[key].get("remarks") or r.get("remarks")}
        else:
            merged.setdefault(key, r)
    return list(merged.values())


def maybe_refresh(now: Optional[datetime] = None) -> None:
    """Alert-loop hook: NSE posts the files after the close; refresh hourly 16:00-21:59 IST."""
    from zoneinfo import ZoneInfo

    local = (now or datetime.now(ZoneInfo("Asia/Kolkata"))).astimezone(ZoneInfo("Asia/Kolkata"))
    with _lock:
        due = time.time() - _last.get("loop", 0) >= 3600
    if 16 <= local.hour < 22 and local.weekday() < 5 and due:
        with _lock:
            _last["loop"] = time.time()
        refresh(force=True)
