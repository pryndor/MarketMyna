"""India institutional flows: FII / DII cash-market buying and selling, and
how each participant group is positioned in index derivatives.

Cash flows: NSE's daily provisional FII/FPI and DII figures (buy, sell, net,
in ₹ crore; NSE publishes only the latest session, so every session fetched
is saved under ~/.marketmyna/india/fii_dii.json and the history builds up
from there - a background thread saves each evening's figures even with no
visitors; a failed fetch serves the saved copy, marked).

Positioning: NSE's participant-wise open interest file (one CSV per session
in nsearchives, so the last 30 sessions are fetched directly and each file
is kept on disk for good). Shows FII / DII / client / pro long and short
index futures and index options in contracts, and the FII index-futures
long share, the number Indian traders watch most.

Figures as published; a reading of positioning, not a forecast.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import requests

from .india_rates import _dir  # same ~/.marketmyna/india folder

logger = logging.getLogger(__name__)

NSE = "https://www.nseindia.com"
ARCHIVE = "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/reports/fii-dii",
}
SESSIONS = 30
CACHE_SECONDS = 30 * 60
GROUPS = ("FII", "DII", "Client", "Pro")

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _num(x) -> Optional[float]:
    try:
        return float(str(x).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ cash flows

def _fetch_cash() -> list[dict]:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(f"{NSE}/reports/fii-dii", timeout=15)  # cookies the API wants
    r = s.get(f"{NSE}/api/fiidiiTradeReact", timeout=15)
    r.raise_for_status()
    return r.json()


def parse_cash(rows: list[dict]) -> Optional[dict]:
    """NSE rows -> {"date": "YYYY-MM-DD", "fii": {...}, "dii": {...}} in ₹ crore."""
    out: dict = {}
    for r in rows or []:
        cat = (r.get("category") or "").upper()
        key = "fii" if cat.startswith("FII") else "dii" if cat.startswith("DII") else None
        if not key:
            continue
        out[key] = {"buy": _num(r.get("buyValue")), "sell": _num(r.get("sellValue")), "net": _num(r.get("netValue"))}
        try:
            out["date"] = datetime.strptime(r.get("date", ""), "%d-%b-%Y").date().isoformat()
        except ValueError:
            pass
    return out if "date" in out and ("fii" in out or "dii" in out) else None


def _history_file() -> Path:
    return _dir() / "fii_dii.json"


def load_history() -> dict[str, dict]:
    try:
        return json.loads(_history_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_session(day: dict) -> dict[str, dict]:
    hist = load_history()
    hist[day["date"]] = {"fii": day.get("fii"), "dii": day.get("dii")}
    path = _history_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(dict(sorted(hist.items())), indent=0), encoding="utf-8")
    tmp.replace(path)
    return hist


def cash(fetch: Callable[[], list[dict]] = _fetch_cash) -> dict:
    stale = None
    try:
        day = parse_cash(fetch())
        if not day:
            raise ValueError("NSE returned no FII/DII rows")
        hist = save_session(day)
    except Exception as exc:
        logger.warning("FII/DII fetch failed: %s", exc)
        hist = load_history()
        stale = f"Live fetch failed ({type(exc).__name__}); showing the saved figures"
    dates = sorted(hist)
    series = [{"date": d, "fii": (hist[d].get("fii") or {}).get("net"), "dii": (hist[d].get("dii") or {}).get("net")} for d in dates]

    def total(key: str, rows: list[dict]) -> Optional[float]:
        vals = [r[key] for r in rows if r[key] is not None]
        return round(sum(vals), 2) if vals else None

    latest = dates[-1] if dates else None
    month = latest[:7] if latest else None
    mtd = [r for r in series if month and r["date"].startswith(month)]
    last5 = series[-5:]
    return {
        "latest": {"date": latest, **hist[latest]} if latest else None,
        "series": series[-120:],
        "sessions_saved": len(dates),
        "five_day": {"fii": total("fii", last5), "dii": total("dii", last5), "sessions": len(last5)},
        "month_to_date": {"fii": total("fii", mtd), "dii": total("dii", mtd), "sessions": len(mtd)},
        "stale": stale,
    }


# ------------------------------------------------------------------ positioning

def _archive_file(d: date) -> Path:
    path = _dir() / "participant_oi"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{d:%Y%m%d}.csv"


def _fetch_archive(d: date) -> Optional[str]:
    """One session's CSV, from disk if fetched before; None on holidays / not yet out."""
    path = _archive_file(d)
    if path.exists():
        return path.read_text(encoding="utf-8") or None  # empty file = no session that day (holiday)
    r = requests.get(ARCHIVE.format(d=d), headers={"User-Agent": HEADERS["User-Agent"]}, timeout=20)
    if r.status_code == 404 or "Participant" not in r.text[:200]:
        if r.status_code == 404 and d < date.today() - timedelta(days=3):
            path.write_text("", encoding="utf-8")
        return None
    r.raise_for_status()
    path.write_text(r.text, encoding="utf-8")
    return r.text


def parse_participants(text: str) -> dict[str, dict]:
    rows = list(csv.reader(io.StringIO(text)))
    head_i = next(i for i, r in enumerate(rows) if r and r[0].strip().lower() == "client type")
    head = [h.strip() for h in rows[head_i]]
    out = {}
    for r in rows[head_i + 1:]:
        if not r or not r[0].strip():
            continue
        vals = {h: _num(v) for h, v in zip(head[1:], r[1:])}
        out[r[0].strip()] = vals
    return out


def _summarise(groups: dict[str, dict]) -> dict:
    out = {}
    for g in GROUPS:
        v = groups.get(g)
        if not v:
            continue
        fl, fs = v.get("Future Index Long") or 0, v.get("Future Index Short") or 0
        cl, cs = v.get("Option Index Call Long") or 0, v.get("Option Index Call Short") or 0
        pl, ps = v.get("Option Index Put Long") or 0, v.get("Option Index Put Short") or 0
        out[g] = {
            "index_futures_long": fl, "index_futures_short": fs, "index_futures_net": fl - fs,
            "index_futures_long_pct": round(fl / (fl + fs) * 100, 1) if fl + fs else None,
            # bullish option exposure: calls bought + puts sold, minus puts bought + calls sold
            "index_options_net": (cl - cs) - (pl - ps),
            "stock_futures_net": (v.get("Future Stock Long") or 0) - (v.get("Future Stock Short") or 0),
        }
    return out


def positioning(fetch: Callable[[date], Optional[str]] = _fetch_archive, today: Optional[date] = None,
                sessions: int = SESSIONS) -> Optional[dict]:
    today = today or date.today()
    days = [today - timedelta(days=i) for i in range(int(sessions * 1.6) + 5)]
    days = [d for d in days if d.weekday() < 5]

    def one(d):
        try:
            text = fetch(d)
            return (d, _summarise(parse_participants(text))) if text else None
        except Exception as exc:
            logger.info("Participant OI %s unavailable: %s", d, exc)
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        got = [x for x in pool.map(one, days) if x and x[1].get("FII")]
    got.sort(key=lambda x: x[0])
    got = got[-sessions:]
    if not got:
        return None
    latest_day, latest = got[-1]
    prev = got[-2][1] if len(got) > 1 else None
    fii_pct = [x[1]["FII"]["index_futures_long_pct"] for x in got]
    lows_highs = [v for v in fii_pct if v is not None]
    return {
        "date": latest_day.isoformat(),
        "groups": latest,
        "previous": prev,
        "fii_long_pct_series": [{"date": d.isoformat(), "pct": g["FII"]["index_futures_long_pct"],
                                 "net": g["FII"]["index_futures_net"]} for d, g in got],
        "fii_long_pct_range": [min(lows_highs), max(lows_highs)] if lows_highs else None,
        "sessions": len(got),
    }


def snapshot_loop(check_seconds: int = 3600) -> None:
    """Background thread: save each session's FII/DII figures in the evening
    (NSE posts them around 18:00-19:30 IST) and fetch the day's participant
    file, so the history builds without visitors."""
    from zoneinfo import ZoneInfo

    time.sleep(240)  # let start-up traffic settle
    while True:
        try:
            now = datetime.now(ZoneInfo("Asia/Kolkata"))
            if now.weekday() < 5 and now.hour >= 19 and now.date().isoformat() not in load_history():
                cash()
                positioning()
        except Exception as exc:  # noqa: BLE001 - never kill the thread
            logger.info("FII/DII snapshot failed: %s", exc)
        time.sleep(check_seconds)


def build(use_cache: bool = True) -> dict:
    if use_cache:
        with _lock:
            hit = _cache.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        c = pool.submit(cash)
        p = pool.submit(positioning)
        out = {"cash": c.result(), "positioning": p.result(),
               "source": "NSE provisional FII/DII cash-market figures (₹ crore) and participant-wise open interest "
                         "in equity derivatives (contracts)"}
    if use_cache and (out["positioning"] or (out["cash"] and out["cash"]["latest"])):
        with _lock:
            _cache["all"] = (time.time(), out)
    return out
