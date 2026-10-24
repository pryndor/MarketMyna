"""Delivery % for NSE shares: of the shares traded in a session, how many
were taken for delivery (kept) rather than squared off intraday.

The exchange publishes one file per session after the close
(sec_bhavdata_full_DDMMYYYY.csv, ~400 KB, every symbol). It is fetched in
the background at most once per CHECK_SECONDS and saved to disk, so a page
never waits on the exchange and a restart doesn't fetch it again.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.core.home import app_home

logger = logging.getLogger(__name__)

URL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{day:%d%m%Y}.csv"
CHECK_SECONDS = 30 * 60  # look for a newer session file at most this often
DAYS_BACK = 7  # weekends + holidays
IST = ZoneInfo("Asia/Kolkata")

_lock = threading.Lock()
_state: dict = {"date": None, "rows": {}, "checked": 0.0, "busy": False}


def _cache_file() -> Path:
    base = Path(os.environ.get("DELIVERY_CACHE_DIR") or app_home() / "cache")
    return base / "nse_delivery.json"


def _num(text: str) -> Optional[float]:
    try:
        return float(text.strip().replace(",", ""))
    except (AttributeError, ValueError):
        return None


def parse(text: str) -> dict[str, dict]:
    """Symbol -> session figures, normal (EQ / BE) series only."""
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [f.strip() for f in reader.fieldnames or []]
    out: dict[str, dict] = {}
    for r in reader:
        r = {k: (v or "").strip() for k, v in r.items() if k}
        sym, series = r.get("SYMBOL", "").upper(), r.get("SERIES", "")
        if not sym or series not in ("EQ", "BE", "BZ", "SM", "ST"):
            continue
        if sym in out and series != "EQ":
            continue
        out[sym] = {
            "traded": _num(r.get("TTL_TRD_QNTY", "")),
            "delivered": _num(r.get("DELIV_QTY", "")),
            "percent": _num(r.get("DELIV_PER", "")),
            "trades": _num(r.get("NO_OF_TRADES", "")),
            "avg_price": _num(r.get("AVG_PRICE", "")),
        }
    return out


def _download() -> tuple[str, dict[str, dict]]:
    from ..data.listings import _get

    day = datetime.now(IST)
    last_error: Optional[Exception] = None
    for _ in range(DAYS_BACK):
        try:
            rows = parse(_get(URL.format(day=day)).text)
            if rows:
                return day.date().isoformat(), rows
        except Exception as exc:  # 404 before the close and on holidays
            last_error = exc
        day -= timedelta(days=1)
    raise RuntimeError(f"No delivery file in the last {DAYS_BACK} days: {last_error}")


def _load_disk() -> None:
    try:
        saved = json.loads(_cache_file().read_text(encoding="utf-8"))
        _state.update(date=saved["date"], rows=saved["rows"])
    except (OSError, ValueError, KeyError, TypeError):
        pass


def _refresh() -> None:
    try:
        date, rows = _download()
        with _lock:
            _state.update(date=date, rows=rows)
        try:
            path = _cache_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"date": date, "rows": rows}), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            logger.debug("Could not save the delivery file: %s", exc)
    except Exception as exc:
        logger.info("Delivery file not loaded: %s", exc)
    finally:
        with _lock:
            _state["busy"] = False


def _newer_due(date: Optional[str], now: Optional[datetime] = None) -> bool:
    """A newer file can exist: none saved yet, or the saved one is older than
    the latest weekday session whose file is out (published by ~18:00 IST).
    Holidays only cost a recheck every CHECK_SECONDS that day."""
    if not date:
        return True
    now = now or datetime.now(IST)
    session = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    while session.weekday() >= 5:  # Saturday / Sunday
        session -= timedelta(days=1)
    return date < session.isoformat()


def get(symbol: str) -> dict:
    """Last session's delivery figures for one NSE symbol. Starts a
    background fetch when due; never blocks."""
    with _lock:
        if not _state["rows"] and not _state["checked"]:
            _load_disk()
        start = (not _state["busy"] and time.monotonic() - _state["checked"] >= CHECK_SECONDS
                 and (_newer_due(_state["date"]) or not _state["checked"]))
        if start:
            _state.update(busy=True, checked=time.monotonic())
        row = _state["rows"].get(symbol.upper())
        date, loading = _state["date"], _state["busy"]
    if start:
        threading.Thread(target=_refresh, name="nse-delivery", daemon=True).start()
    return {"date": date, "loading": loading and not row, **(row or {})}
