"""NSE F&O lot sizes from brokers' public instrument files.

NSE only publishes lot sizes as a PDF and revises them every few months,
so they're read from Upstox's public instrument dump (Kite's as a
fallback), cached on disk for a day. Lot sizes can differ by expiry around
a revision, hence {symbol: {expiry: lot}}."""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from src.core.home import app_home

logger = logging.getLogger(__name__)

UPSTOX_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
KITE_URL = "https://api.kite.trade/instruments/NFO"
MAX_AGE = 24 * 3600
IST = ZoneInfo("Asia/Kolkata")

_lock = threading.Lock()
_memory: Optional[tuple[float, dict]] = None


def _cache_path() -> Path:
    return app_home() / "cache" / "fo_lots.json"


def _from_upstox() -> dict[str, dict[str, int]]:
    import requests

    r = requests.get(UPSTOX_URL, timeout=30)
    r.raise_for_status()
    out: dict[str, dict[str, int]] = {}
    for d in json.loads(gzip.decompress(r.content)):
        if d.get("segment") != "NSE_FO" or not d.get("lot_size"):
            continue
        sym = (d.get("underlying_symbol") or d.get("name") or "").upper()
        exp = datetime.fromtimestamp(d["expiry"] / 1000, IST).date().isoformat() if d.get("expiry") else ""
        out.setdefault(sym, {})[exp] = int(d["lot_size"])
    return out


def _from_kite() -> dict[str, dict[str, int]]:
    import requests

    r = requests.get(KITE_URL, timeout=30)
    r.raise_for_status()
    out: dict[str, dict[str, int]] = {}
    for row in csv.DictReader(io.StringIO(r.text)):
        if row.get("lot_size") and row.get("name"):
            out.setdefault(row["name"].upper(), {})[row.get("expiry", "")] = int(float(row["lot_size"]))
    return out


def load(force: bool = False) -> dict[str, dict[str, int]]:
    global _memory
    with _lock:
        if not force and _memory and time.time() - _memory[0] < MAX_AGE:
            return _memory[1]
        path = _cache_path()
        if not force and path.exists() and time.time() - path.stat().st_mtime < MAX_AGE:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                _memory = (path.stat().st_mtime, data)
                return data
            except ValueError:
                pass
        data: dict = {}
        for source in (_from_upstox, _from_kite):
            try:
                data = source()
                if data:
                    break
            except Exception as exc:
                logger.warning("Lot sizes from %s failed: %s", source.__name__, exc)
        if data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            _memory = (time.time(), data)
            return data
        if path.exists():  # stale beats nothing
            return json.loads(path.read_text(encoding="utf-8"))
        return {}


def lot_size(symbol: str, expiry: Optional[date] = None, data: Optional[dict] = None) -> Optional[int]:
    """Lot for `symbol` at `expiry` (or its nearest listed expiry)."""
    by_expiry = (data if data is not None else load()).get(symbol.upper())
    if not by_expiry:
        return None
    if expiry is not None and expiry.isoformat() in by_expiry:
        return by_expiry[expiry.isoformat()]
    dated = sorted(k for k in by_expiry if k)
    if not dated:
        return next(iter(by_expiry.values()))
    target = (expiry or date.today()).isoformat()
    upcoming = [k for k in dated if k >= target]
    return by_expiry[(upcoming or dated)[0] if upcoming else dated[-1]]
