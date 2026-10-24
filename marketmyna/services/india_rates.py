"""India rates and bullion: RBI policy / money-market rates, T-bill and G-sec
yields (an India yield curve), and IBJA benchmark gold / silver prices.

Sources, both free and public, scraped from their HTML:
- rbi.org.in home page "Current Rates" box: policy rates, CRR / SLR, FBIL
  reference FX, call money, T-bill cut-offs and benchmark G-sec yields.
- ibjarates.com: India Bullion and Jewellers Association daily AM / PM rates
  (Rs per 10 g gold, per kg silver, before GST and making charges), the
  benchmark most Indian jewellers and gold loans quote. MCX itself blocks
  scripted access (HTTP 403), so it is not used.

Either site may block cloud IPs or change layout. Every good fetch is saved
under ~/.marketmyna/india/, and a failed fetch serves that last copy marked
stale, so the card degrades instead of disappearing.
"""

from __future__ import annotations

import html as htmllib
import json
import logging
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from marketmyna.core.home import app_home

logger = logging.getLogger(__name__)

RBI_URL = "https://www.rbi.org.in/"
IBJA_URL = "https://ibjarates.com/"
CACHE_SECONDS = 3600
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

Fetch = Callable[[str], str]

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _http(url: str) -> str:
    import requests

    r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"}, timeout=20)
    r.raise_for_status()
    return r.text


def _dir() -> Path:
    path = app_home() / "india"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pct(text: str) -> Optional[float]:
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(m.group(0)) if m else None


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# ------------------------------------------------------------------ RBI

POLICY = {
    "Policy Repo Rate": ("repo", "Repo rate", "What banks pay to borrow from RBI; the main policy rate"),
    "Standing Deposit Facility Rate": ("sdf", "SDF rate", "Standing deposit facility: floor of the overnight corridor"),
    "Marginal Standing Facility Rate": ("msf", "MSF rate", "Marginal standing facility: ceiling of the overnight corridor"),
    "Bank Rate": ("bank_rate", "Bank rate", "Long-term lending rate to banks"),
    "CRR": ("crr", "CRR", "Cash reserve ratio: deposits banks must park with RBI, unpaid"),
    "SLR": ("slr", "SLR", "Statutory liquidity ratio: deposits banks must hold in government bonds"),
}


def parse_rbi(page: str) -> dict:
    """Pull the rate table rows from the RBI home page."""
    rows = [(_text(k), _text(v).lstrip(": ").strip())
            for k, v in re.findall(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", page, re.S)]
    out: dict = {"policy": [], "tbills": [], "gsecs": [], "fx": [], "lending": [], "call_rate": None}
    for key, val in rows:
        if key in POLICY:
            k, label, note = POLICY[key]
            out["policy"].append({"key": k, "label": label, "value": _pct(val), "note": note})
        elif m := re.match(r"(\d+) day T-bills", key):
            out["tbills"].append({"days": int(m.group(1)), "years": int(m.group(1)) / 365, "yield": _pct(val)})
        elif m := re.match(r"(\d+(?:\.\d+)?)% GS (\d{4})", key):
            out["gsecs"].append({"name": key, "coupon": float(m.group(1)), "maturity_year": int(m.group(2)),
                                 "yield": _pct(val)})
        elif m := re.match(r"INR / (\d+) (\w+)", key):
            out["fx"].append({"pair": f"{m.group(2)}/INR", "per": int(m.group(1)), "value": _pct(val)})
        elif key in ("Base Rate", "MCLR (Overnight)", "Savings Deposit Rate", "Term Deposit Rate > 1 Year"):
            out["lending"].append({"label": key, "value": val})
    if m := re.search(r"Call Rates\s*</[^>]+>.*?:\s*([\d.]+)%\s*-\s*([\d.]+)%", page, re.S):
        out["call_rate"] = {"low": float(m.group(1)), "high": float(m.group(2))}
    if m := re.search(r"As at[^)]*?of\s+([A-Za-z]+ \d{1,2}, \d{4})", _text(page)):
        out["fx_as_of"] = m.group(1)
    if m := re.search(r"Government Securities Market.*?as on\s*([A-Za-z]+ \d{1,2}, \d{4})", _text(page)):
        out["gsec_as_of"] = m.group(1)
    if not out["policy"]:
        raise ValueError("RBI page layout not recognised (no policy rates found)")
    out["curve"] = _curve(out["tbills"], out["gsecs"])
    return out


def _curve(tbills: list[dict], gsecs: list[dict]) -> list[dict]:
    """T-bills + benchmark G-secs as one curve, x = years to maturity (G-secs approximate,
    mid-year maturity assumed since the page gives only the year)."""
    today = date.today()
    pts = [{"label": f"{t['days']}D", "years": round(t["years"], 3), "yield": t["yield"]} for t in tbills]
    for g in gsecs:
        yrs = max(g["maturity_year"] + 0.5 - (today.year + today.timetuple().tm_yday / 365), 0.1)
        pts.append({"label": str(g["maturity_year"]), "years": round(yrs, 2), "yield": g["yield"]})
    return sorted((p for p in pts if p["yield"] is not None), key=lambda p: p["years"])


# ------------------------------------------------------------------ IBJA

IBJA_FIELDS = {
    "Gold999": ("gold_999", "Gold 999 (24K)", "₹/10g"),
    "Gold995": ("gold_995", "Gold 995", "₹/10g"),
    "Gold916": ("gold_916", "Gold 916 (22K)", "₹/10g"),
    "Gold750": ("gold_750", "Gold 750 (18K)", "₹/10g"),
    "Silver999": ("silver_999", "Silver 999", "₹/kg"),
    "Platinum999": ("platinum_999", "Platinum 999", "₹/10g"),
}


def parse_ibja(page: str) -> dict:
    def label(id_):
        m = re.search(rf'id="{id_}"[^>]*>([^<]*)<', page)
        return _pct(m.group(1)) if m and m.group(1).strip() else None

    items = []
    for field, (key, name, unit) in IBJA_FIELDS.items():
        am, pm = label(f"lbl{field}_AM"), label(f"lbl{field}_PM")
        if am is None and pm is None:
            continue
        items.append({"key": key, "label": name, "unit": unit, "am": am, "pm": pm,
                      "latest": pm if pm is not None else am, "session": "PM" if pm is not None else "AM"})
    # The headline table holds today's rates; dated tables below it are past days.
    as_of = _ist_today()

    def series(hidden: str, value_key: str) -> list[dict]:
        m = re.search(rf'id="{hidden}"[^>]*value="([^"]*)"', page) or re.search(rf'value="([^"]*)"[^>]*id="{hidden}"', page)
        if not m:
            return []
        try:
            data = json.loads(htmllib.unescape(m.group(1)))
            return [{"date": datetime.strptime(d, "%d/%m/%Y").date().isoformat(), "value": float(v)}
                    for d, v in zip(data.get("labels", []), data.get(value_key, [])) if v]
        except (ValueError, TypeError):
            return []

    hist = {"gold_999": series("HdnGold", "purity999"), "silver_999": series("HdnSilver", "silverRate")}
    if not items:  # before the morning fix is published: fall back to the last PM close
        for key, (name, unit) in {"gold_999": ("Gold 999 (24K)", "₹/10g"), "silver_999": ("Silver 999", "₹/kg")}.items():
            if hist[key]:
                last = hist[key][-1]
                items.append({"key": key, "label": name, "unit": unit, "am": None, "pm": last["value"],
                              "latest": last["value"], "session": "PM"})
                as_of = last["date"]
    if not items:
        raise ValueError("IBJA page layout not recognised (no rates found)")
    for i in items:  # change vs the previous day's PM close
        prev = [h for h in hist.get(i["key"], []) if h["date"] < as_of]
        i["change_pct"] = (i["latest"] / prev[-1]["value"] - 1) * 100 if prev and i["latest"] else None
    return {"items": items, "as_of": as_of, "history": hist}


def _ist_today() -> str:
    from datetime import timedelta, timezone

    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat()


# ------------------------------------------------------------------ fetch with fallback


def _load(name: str, fetch: Fetch, url: str, parser) -> dict:
    path = _dir() / f"{name}.json"
    try:
        data = parser(fetch(url))
        data["fetched_at"] = datetime.now().isoformat(timespec="seconds")
        data["stale"] = False
        try:
            path.write_text(json.dumps(data), encoding="utf-8")
            _append_history(name, data)
        except OSError as exc:
            logger.info("Could not save %s snapshot: %s", name, exc)
        return data
    except Exception as exc:
        logger.warning("%s fetch failed: %s", name.upper(), exc)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["stale"] = True
            data["error"] = f"Live fetch failed; showing the copy from {data.get('fetched_at', 'earlier')}."
            return data
        return {"error": f"{name.upper()} unavailable right now", "stale": True}


def _append_history(name: str, data: dict) -> None:
    """One snapshot per day of the headline numbers, so trends build up over time."""
    path = _dir() / f"{name}_history.json"
    hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    day = date.today().isoformat()
    if name == "rbi":
        snap = {p["key"]: p["value"] for p in data.get("policy", [])}
        snap.update({f"tbill_{t['days']}": t["yield"] for t in data.get("tbills", [])})
        snap.update({f"gs_{g['maturity_year']}": g["yield"] for g in data.get("gsecs", [])})
    else:
        snap = {i["key"]: i["latest"] for i in data.get("items", [])}
    hist[day] = snap
    path.write_text(json.dumps(dict(sorted(hist.items())[-1500:])), encoding="utf-8")


def history(name: str) -> dict:
    path = _dir() / f"{name}_history.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def build(fetch: Fetch = _http, use_cache: bool = True) -> dict:
    if use_cache:
        with _lock:
            hit = _cache.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        rbi = pool.submit(_load, "rbi", fetch, RBI_URL, parse_rbi)
        ibja = pool.submit(_load, "ibja", fetch, IBJA_URL, parse_ibja)
        out = {"rbi": rbi.result(), "ibja": ibja.result()}
    out["sources"] = {"rbi": RBI_URL, "ibja": IBJA_URL}
    if use_cache and not (out["rbi"].get("stale") and out["ibja"].get("stale")):
        with _lock:
            _cache["all"] = (time.time(), out)
    return out


def context_lines(data: Optional[dict] = None) -> list[str]:
    """Short lines for LLM prompts."""
    data = data or build()
    lines = []
    rbi = data.get("rbi", {})
    for p in rbi.get("policy", []):
        if p["key"] in ("repo", "crr") and p["value"] is not None:
            lines.append(f"RBI {p['label']}: {p['value']:.2f}%")
    for t in rbi.get("tbills", []):
        if t["days"] == 364 and t["yield"] is not None:
            lines.append(f"India 364-day T-bill: {t['yield']:.2f}%")
    for i in data.get("ibja", {}).get("items", []):
        if i["key"] in ("gold_999", "silver_999") and i["latest"]:
            lines.append(f"IBJA {i['label']}: Rs {i['latest']:,.0f} {i['unit'].replace('₹', '')}")
    return lines
