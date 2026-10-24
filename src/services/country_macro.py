"""Country macro from the IMF World Economic Outlook (DataMapper API, no key).

Real GDP growth, inflation, unemployment, government debt and fiscal balance,
current account, GDP and GDP per capita for any of about 200 economies, as
last year / this year / next year, where this year and later are IMF
projections. One request per indicator returns every country, so the whole
set is fetched at most once a day and kept on disk; a failed refresh serves
the saved copy marked stale.

India's figures are fiscal years (April to March), as the IMF reports them.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from src.core.home import app_home

logger = logging.getLogger(__name__)

API = "https://www.imf.org/external/datamapper/api/v1"
REFRESH_SECONDS = 24 * 3600

# IMF code, label, unit, note
INDICATORS = [
    ("NGDP_RPCH", "GDP growth", "%", "Real GDP, change on the year before"),
    ("PCPIPCH", "Inflation", "%", "Average consumer prices, change on the year before"),
    ("LUR", "Unemployment", "%", "Share of the labour force"),
    ("GGXWDG_NGDP", "Govt debt", "% of GDP", "General government gross debt"),
    ("GGXCNL_NGDP", "Fiscal balance", "% of GDP", "General government net lending (+) / borrowing (-)"),
    ("BCA_NGDPD", "Current account", "% of GDP", "Surplus (+) or deficit (-) with the rest of the world"),
    ("NGDPD", "GDP", "US$ bn", "Nominal GDP in current US dollars"),
    ("NGDPDPC", "GDP per person", "US$", "Nominal GDP per capita in current US dollars"),
]
DEFAULT_COUNTRIES = ["IND", "USA", "CHN", "JPN", "DEU", "GBR", "FRA", "KOR", "IDN", "BRA", "SAU", "ARE", "AUS", "CAN"]
FISCAL_YEAR = {"IND": "April-March fiscal years"}

Fetch = Callable[[str], dict]

_lock = threading.Lock()
_state: dict[str, object] = {}


def _dir() -> Path:
    path = app_home() / "imf"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get(path: str) -> dict:
    # The IMF's bot filter answers 403 to some clients (browser-like user
    # agents from scripts); curl_cffi (installed with yfinance) presents a
    # real browser handshake and is let through.
    from curl_cffi import requests as cffi

    r = cffi.get(f"{API}/{path}", timeout=30, impersonate="chrome")
    r.raise_for_status()
    return r.json() or {}


def _download(fetch: Fetch) -> dict:
    def one(code: str):
        return code, ((fetch(code).get("values") or {}).get(code)) or {}

    with ThreadPoolExecutor(max_workers=2) as pool:
        values = dict(pool.map(one, [c for c, *_ in INDICATORS]))
    if not any(values.values()):
        raise ValueError("IMF returned no data")
    names = {k: v.get("label") for k, v in ((fetch("countries").get("countries")) or {}).items() if v.get("label")}
    return {"values": values, "countries": names, "fetched": time.time()}


def _data(fetch: Fetch, now: Optional[float] = None) -> tuple[dict, bool]:
    """(data, stale). Memory, then disk, then the IMF once a day."""
    now = now or time.time()
    with _lock:
        data = _state.get("data")
    if data is None:
        try:
            data = json.loads((_dir() / "weo.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
    if data is not None and now - data.get("fetched", 0) < REFRESH_SECONDS:
        with _lock:
            _state["data"] = data
        return data, False
    try:
        fresh = _download(fetch)
    except Exception as exc:  # noqa: BLE001 - keep serving the saved copy
        logger.warning("IMF DataMapper fetch failed: %s", exc)
        if data is None:
            raise
        return data, True
    try:
        (_dir() / "weo.json").write_text(json.dumps(fresh), encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not save IMF data: %s", exc)
    with _lock:
        _state["data"] = fresh
    return fresh, False


def build(countries: Optional[list[str]] = None, fetch: Fetch = _get, today: Optional[date] = None) -> dict:
    year = (today or date.today()).year
    years = [year - 1, year, year + 1]
    data, stale = _data(fetch)
    names: dict = data.get("countries") or {}
    codes = [c.upper() for c in (countries or DEFAULT_COUNTRIES) if c.upper() in names][:30]
    rows = []
    for code in codes:
        row = {"code": code, "name": names[code], "fiscal_year": FISCAL_YEAR.get(code)}
        for ind, *_ in INDICATORS:
            series = (data["values"].get(ind) or {}).get(code) or {}
            row[ind] = [series.get(str(y)) for y in years]
            # a 5-year look back for the growth / inflation sparkline
            row[f"{ind}_trend"] = [{"year": y, "value": series.get(str(y))} for y in range(year - 6, year + 2)
                                   if series.get(str(y)) is not None]
        rows.append(row)
    return {
        "years": years,
        "projection_from": year,
        "indicators": [{"key": c, "label": label, "unit": unit, "note": note} for c, label, unit, note in INDICATORS],
        "rows": rows,
        "countries": sorted(({"code": k, "name": v} for k, v in names.items()), key=lambda c: c["name"]),
        "stale": stale,
        "as_of": time.strftime("%Y-%m-%d", time.localtime(data.get("fetched", time.time()))),
        "source": "IMF World Economic Outlook (DataMapper)",
    }
