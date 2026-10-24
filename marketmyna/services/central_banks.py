"""Central-bank policy rates for about 40 economies (BIS, no key).

From the BIS daily policy-rate series: today's rate, when it last changed
and from what, the change over a year, and the real rate against the IMF's
inflation projection for this year (marketmyna/services/country_macro.py). Kept
on disk for 12 hours; a failed refresh serves the saved copy marked stale.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

import requests

from marketmyna.core.home import app_home

logger = logging.getLogger(__name__)

URL = "https://stats.bis.org/api/v1/data/WS_CBPOL/D./all"
REFRESH_SECONDS = 12 * 3600

# BIS area -> (IMF code, central bank)
AREAS = {
    "US": ("USA", "Federal Reserve"), "XM": ("", "European Central Bank"), "GB": ("GBR", "Bank of England"),
    "JP": ("JPN", "Bank of Japan"), "CN": ("CHN", "People's Bank of China"), "IN": ("IND", "Reserve Bank of India"),
    "CA": ("CAN", "Bank of Canada"), "AU": ("AUS", "Reserve Bank of Australia"), "CH": ("CHE", "Swiss National Bank"),
    "KR": ("KOR", "Bank of Korea"), "BR": ("BRA", "Central Bank of Brazil"), "MX": ("MEX", "Bank of Mexico"),
    "ID": ("IDN", "Bank Indonesia"), "ZA": ("ZAF", "South African Reserve Bank"), "TR": ("TUR", "Central Bank of Türkiye"),
    "RU": ("RUS", "Bank of Russia"), "SA": ("SAU", "Saudi Central Bank"), "HK": ("HKG", "Hong Kong Monetary Authority"),
    "SE": ("SWE", "Riksbank"), "NO": ("NOR", "Norges Bank"), "DK": ("DNK", "Danmarks Nationalbank"),
    "NZ": ("NZL", "Reserve Bank of New Zealand"), "PL": ("POL", "National Bank of Poland"),
    "CZ": ("CZE", "Czech National Bank"), "HU": ("HUN", "Magyar Nemzeti Bank"), "RO": ("ROU", "National Bank of Romania"),
    "IL": ("ISR", "Bank of Israel"), "TH": ("THA", "Bank of Thailand"), "MY": ("MYS", "Bank Negara Malaysia"),
    "PH": ("PHL", "Bangko Sentral ng Pilipinas"), "CL": ("CHL", "Central Bank of Chile"),
    "CO": ("COL", "Central Bank of Colombia"), "PE": ("PER", "Central Reserve Bank of Peru"),
    "AR": ("ARG", "Central Bank of Argentina"), "IS": ("ISL", "Central Bank of Iceland"),
    "KW": ("KWT", "Central Bank of Kuwait"), "MA": ("MAR", "Bank Al-Maghrib"), "RS": ("SRB", "National Bank of Serbia"),
    "MK": ("MKD", "National Bank of North Macedonia"),
}
FIRST = ["IN", "US", "XM", "GB", "JP", "CN"]  # shown first; the rest by name

Fetch = Callable[[str], str]

_lock = threading.Lock()
_state: dict[str, object] = {}


def _dir() -> Path:
    path = app_home() / "bis"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get(start: str) -> str:
    r = requests.get(URL, params={"startPeriod": start, "format": "csv"}, timeout=60)
    r.raise_for_status()
    return r.text


def parse(text: str) -> dict[str, dict]:
    """{area: {"name": ..., "points": [(date, rate), ...]}} oldest first, gaps dropped."""
    out: dict[str, dict] = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            value = float(row["OBS_VALUE"])
        except (TypeError, ValueError):
            continue
        if value != value:  # NaN
            continue
        area = row["REF_AREA"]
        title = (row.get("TITLE") or "").split(" - ")
        item = out.setdefault(area, {"name": title[1].strip() if len(title) > 1 else area, "points": []})
        item["points"].append((row["TIME_PERIOD"], value))
    for item in out.values():
        item["points"].sort()
    return out


def _data(fetch: Fetch, today: date) -> tuple[dict, bool]:
    with _lock:
        data = _state.get("data")
    if data is None:
        try:
            data = json.loads((_dir() / "policy-rates.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
    if data is not None and time.time() - data.get("fetched", 0) < REFRESH_SECONDS:
        with _lock:
            _state["data"] = data
        return data, False
    try:
        areas = parse(fetch((today - timedelta(days=730)).isoformat()))
        if not areas:
            raise ValueError("BIS returned no rates")
        fresh = {"areas": areas, "fetched": time.time()}
    except Exception as exc:  # noqa: BLE001 - serve the saved copy
        logger.warning("BIS policy rates failed: %s", exc)
        if data is None:
            raise
        return data, True
    try:
        (_dir() / "policy-rates.json").write_text(json.dumps(fresh), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not save policy rates: %s", exc)
    with _lock:
        _state["data"] = fresh
    return fresh, False


def _inflation(year: int) -> dict[str, float]:
    """IMF inflation projection for this year by IMF code, if already loaded (never blocks on the IMF)."""
    try:
        from . import country_macro

        with country_macro._lock:
            data = country_macro._state.get("data")
        if data is None:
            data = json.loads((country_macro._dir() / "weo.json").read_text(encoding="utf-8"))
        series = (data.get("values") or {}).get("PCPIPCH") or {}
        return {code: v[str(year)] for code, v in series.items() if v.get(str(year)) is not None}
    except Exception:  # noqa: BLE001 - the real rate is an extra
        return {}


def _rbi_repo() -> Optional[tuple[str, float]]:
    """(date, repo rate) from the RBI page snapshot marketmyna/services/india_rates.py
    keeps; the BIS series for India can lag the RBI by months."""
    try:
        from . import india_rates

        path = india_rates._dir() / "rbi.json"
        if not path.exists() or time.time() - path.stat().st_mtime > 86400:
            india_rates.build()  # refreshes the snapshot (it has its own cache and fallback)
        data = json.loads(path.read_text(encoding="utf-8"))
        repo = next(p["value"] for p in data.get("policy") or [] if p.get("key") == "repo")
        return str(data.get("fetched_at") or "")[:10], float(repo)
    except Exception:  # noqa: BLE001 - BIS alone is fine
        return None


def with_rbi(points: list, rbi: Optional[tuple[str, float]]) -> list:
    """Append the RBI's own reading when it is newer than the BIS series."""
    if rbi and rbi[0] and (not points or rbi[0] > points[-1][0]):
        return [*points, rbi]
    return points


def summarise(area: str, name: str, points: list, today: date, inflation: dict[str, float]) -> Optional[dict]:
    if not points:
        return None
    as_of, rate = points[-1]
    changed, previous = None, None
    for when, value in reversed(points):
        if value != rate:
            previous = value
            break
        changed = when
    year_ago = [v for d, v in points if d <= (today - timedelta(days=365)).isoformat()]
    imf, bank = AREAS.get(area, ("", ""))
    infl = inflation.get(imf) if imf else None
    monthly: dict[str, float] = {}
    for when, value in points:
        monthly[when[:7]] = value  # month-end value
    return {
        "area": area, "name": name, "bank": bank, "rate": rate, "as_of": as_of,
        "last_change": changed if previous is not None else None, "previous": previous,
        "direction": None if previous is None else ("cut" if rate < previous else "hike"),
        "change_1y": round(rate - year_ago[-1], 3) if year_ago else None,
        "inflation": infl, "real_rate": round(rate - infl, 2) if infl is not None else None,
        "spark": [{"month": m, "rate": v} for m, v in monthly.items()],
    }


def build(fetch: Fetch = _get, today: Optional[date] = None) -> dict:
    today = today or date.today()
    data, stale = _data(fetch, today)
    inflation = _inflation(today.year)
    rbi = _rbi_repo()
    rows = []
    for area, item in (data.get("areas") or {}).items():
        points = [tuple(p) for p in item["points"]]
        bis_last = points[-1] if points else None
        if area == "IN":
            points = with_rbi(points, rbi)
        if r := summarise(area, item["name"], points, today, inflation):
            if bis_last and points[-1] != bis_last and points[-1][1] != bis_last[1]:
                # moved between the last BIS day and the RBI reading: exact date unknown
                r["last_change"], r["changed_between"] = None, [bis_last[0], points[-1][0]]
            rows.append(r)
    rows.sort(key=lambda r: (FIRST.index(r["area"]) if r["area"] in FIRST else len(FIRST), r["name"]))
    return {"rows": rows, "stale": stale,
            "as_of": time.strftime("%Y-%m-%d", time.localtime(data.get("fetched", time.time()))),
            "source": "BIS central bank policy rates (India: RBI's own page when newer); real rate uses the IMF inflation projection for "
                      f"{today.year}"}
