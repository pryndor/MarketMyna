"""Mutual fund holdings in the web portfolio: CAS import and live NAVs.

A fund holding is an ordinary portfolio holding with market "mf" and the AMFI
scheme code as its symbol, so the existing transaction ledger, gains and
delete/replay logic all apply. NAV, name and category come from mfapi.in.

CAS import uses casparser (CAMS / KFintech / MFCentral statements, usually
locked with the investor's PAN). The PDF and password stay in memory only, and
nothing personal (PAN, email, address) is returned or stored.
"""

from __future__ import annotations

import io
import threading
import time
from datetime import date, datetime

import requests

MARKET = "mf"
_TTL = 15 * 60
_cache: dict[int, tuple[float, dict | None]] = {}
_lock = threading.Lock()


def latest(code: int | str) -> dict | None:
    """Latest NAV plus scheme name / AMC / category, cached 15 minutes."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return None
    with _lock:
        hit = _cache.get(code)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    info = None
    try:
        r = requests.get(f"https://api.mfapi.in/mf/{code}/latest", timeout=10)
        r.raise_for_status()
        data = r.json()
        meta, rows = data.get("meta") or {}, data.get("data") or []
        if rows:
            info = {
                "name": meta.get("scheme_name") or str(code),
                "amc": meta.get("fund_house") or "",
                "category": meta.get("scheme_category") or "",
                "nav": float(rows[0]["nav"]),
                "nav_date": datetime.strptime(rows[0]["date"], "%d-%m-%Y").date().isoformat(),
            }
    except Exception:
        if hit:  # keep serving the stale value rather than zeroing the holding
            return hit[1]
    with _lock:
        _cache[code] = (time.monotonic(), info)
    return info


_HIST_TTL = 6 * 3600
_hist: dict[int, tuple[float, list[tuple[date, float]]]] = {}


def nav_on(code: int | str, day: date) -> dict | None:
    """Official NAV of a scheme on `day`, or the last one published before it
    (weekends and holidays have none). History cached a few hours per scheme."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return None
    with _lock:
        hit = _hist.get(code)
    if hit and time.monotonic() - hit[0] < _HIST_TTL:
        rows = hit[1]
    else:
        try:
            r = requests.get(f"https://api.mfapi.in/mf/{code}", timeout=15)
            r.raise_for_status()
            rows = sorted(
                (datetime.strptime(x["date"], "%d-%m-%Y").date(), float(x["nav"]))
                for x in (r.json().get("data") or [])
            )
        except Exception:
            if not hit:
                return None
            rows = hit[1]
        with _lock:
            _hist[code] = (time.monotonic(), rows)
    before = [(d, nav) for d, nav in rows if d <= day]
    if not before:
        return None
    d, nav = before[-1]
    return {"nav": nav, "nav_date": d.isoformat()}


class CASError(ValueError):
    """The statement could not be read (wrong password, not a CAS, ...)."""


def parse_cas(pdf: bytes, password: str) -> dict:
    """Read a CAS PDF into per-scheme holdings (aggregated across folios)."""
    import casparser
    from casparser.exceptions import IncorrectPasswordError, ParserException

    try:
        cas = casparser.read_cas_pdf(io.BytesIO(pdf), password)
    except IncorrectPasswordError as exc:
        raise CASError("Wrong password. CAS statements are usually locked with your PAN in capitals.") from exc
    except ParserException as exc:
        raise CASError(f"Could not read this statement: {exc}") from exc
    except Exception as exc:  # malformed PDF etc
        raise CASError(f"Could not read this file as a CAS statement ({type(exc).__name__}).") from exc
    if not hasattr(cas, "folios"):
        raise CASError("Depository (NSDL / CDSL) statements are not supported yet. "
                       "Use the CAMS / KFintech CAS from camsonline.com or MFCentral.")
    return summarise(cas)


def summarise(cas) -> dict:
    """CASData -> holdings rows; split out so tests can feed a fake statement."""
    rows: dict[str, dict] = {}
    skipped: list[dict] = []
    for folio in cas.folios:
        for s in folio.schemes:
            units = max(float(s.close or 0), 0.0)  # 0 = fully redeemed, still syncs a sale
            if not s.amfi:
                if units <= 0:
                    continue
                skipped.append({"scheme": s.scheme, "reason": "No AMFI code, cannot price it"})
                continue
            v = s.valuation
            cost = float(v.cost) if v.cost is not None else None
            row = rows.setdefault(s.amfi, {
                "amfi": str(s.amfi), "isin": s.isin, "scheme": s.scheme, "amc": folio.amc,
                "folios": 0, "units": 0.0, "cost": 0.0, "cost_known": True,
                "value": 0.0, "nav": float(v.nav), "date": _iso(v.date),
            })
            row["folios"] += 1
            row["units"] += units
            row["value"] += float(v.value)
            if cost is None:
                row["cost_known"] = False
            else:
                row["cost"] += cost
    holdings = sorted((r for r in rows.values()), key=lambda r: (r["units"] <= 0, -r["value"]))
    for r in holdings:
        if not r["cost_known"]:
            r["cost"] = None
    period = getattr(cas, "statement_period", None)
    return {
        "statement_to": getattr(period, "to", None),
        "cas_type": str(getattr(cas, "cas_type", "") or ""),
        "holdings": holdings,
        "skipped": skipped,
        "total_value": sum(r["value"] for r in holdings),
        "warnings": list(getattr(cas, "parse_warnings", []) or []),
    }


def plan_import(held: dict[str, float], rows: list[dict]) -> list[dict]:
    """Transactions that bring each scheme's units to the statement's balance.

    New scheme: one BUY at the statement cost (or NAV when cost is unknown).
    Already held: BUY / SELL only the unit difference at the statement NAV, so a
    monthly re-import stays in sync without double counting.
    """
    out = []
    for r in rows:
        code, units = str(r["amfi"]), float(r["units"])
        have = float(held.get(code, 0.0))
        diff = -have if units <= 1e-6 else units - have  # full exit sells exactly what is held
        if abs(diff) < 1e-3:
            continue
        when = r.get("date") or date.today().isoformat()
        if have <= 0 and r.get("cost") and units > 0:
            price = float(r["cost"]) / units
        else:
            price = float(r["nav"])
        out.append({
            "symbol": code,
            "type": "buy" if diff > 0 else "sell",
            "quantity": round(diff, 6) if diff > 0 else min(-diff, have),
            "price": price,
            "date": when,
            "notes": f"CAS import: {r.get('scheme', code)}"[:200],
        })
    return out


def _iso(d) -> str | None:
    if d is None:
        return None
    if isinstance(d, (date, datetime)):
        return d.isoformat()[:10]
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(d), fmt).date().isoformat()
        except ValueError:
            continue
    return None
