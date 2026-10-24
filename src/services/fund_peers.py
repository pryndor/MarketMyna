"""A mutual fund against its competitors.

Competitors are the other schemes in the same SEBI category ("Flexi Cap
Fund", "Large Cap Fund"...), same plan (Direct / Regular) and growth option,
one per fund house - the funds an investor would really choose between.

Each is measured from its own NAV history (mfapi.in, cached 12 hours):
  returns     1Y, 3Y and 5Y (3Y / 5Y annualised)
  volatility  annualised, last 3 years of daily NAVs
  drawdown    worst peak-to-trough fall, last 3 years
  sharpe      3Y return over a 6.5% risk-free rate, per unit of volatility
  similarity  correlation of daily returns with the chosen fund (last year):
              0.95+ means the two move almost as one
  overlap     shared holdings, when both fund houses' portfolio files are
              loaded (src/services/fund_holdings.py)
The chosen fund also gets its rank and quartile in the category on each.
Facts from public NAVs; past returns don't predict future ones.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from src.core.home import app_home

from ..core.numbers import finite as _f
from .sip_days import mf_nav

logger = logging.getLogger(__name__)

NAV_TTL = 12 * 3600
RISK_FREE = 6.5  # % a year, Indian T-bill ballpark
MAX_PEERS = 60
TRADING_DAYS = 252
_EXCLUDE = re.compile(r"\b(idcw|dividend|bonus|payout|reinvest|segregated|series|fmp|fixed (term|maturity)|interval)\b", re.I)

NavFetch = Callable[[str], Optional[pd.Series]]
_mem: dict[str, tuple[float, Optional[pd.Series]]] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------- NAV cache

def _cache_dir() -> Path:
    p = app_home() / "cache" / "nav"
    p.mkdir(parents=True, exist_ok=True)
    return p


def nav(code: str, fetch: NavFetch = mf_nav) -> Optional[pd.Series]:
    """Daily NAVs, oldest first; memory then disk cache, 12 hours."""
    now = time.time()
    with _lock:
        hit = _mem.get(code)
    if hit and now - hit[0] < NAV_TTL:
        return hit[1]
    path = _cache_dir() / f"{code}.json"
    series: Optional[pd.Series] = None
    try:
        if path.exists() and now - path.stat().st_mtime < NAV_TTL:
            raw = json.loads(path.read_text(encoding="utf-8"))
            series = pd.Series(raw["nav"], index=pd.to_datetime(raw["date"]), dtype=float)
    except Exception:
        series = None
    if series is None:
        try:
            series = fetch(code)
        except Exception as exc:
            logger.info("NAV history for %s unavailable: %s", code, exc)
            series = None
        if series is not None and len(series):
            try:
                path.write_text(json.dumps({"date": [d.strftime("%Y-%m-%d") for d in series.index],
                                            "nav": [float(v) for v in series.values]}), encoding="utf-8")
            except OSError:
                pass
    with _lock:
        _mem[code] = (now, series)
    return series


# ---------------------------------------------------------------- metrics

def _ret(s: pd.Series, years: float) -> Optional[float]:
    if s is None or len(s) < 2:
        return None
    end = s.index[-1]
    start_at = end - pd.DateOffset(days=round(365.25 * years))
    if s.index[0] > start_at + pd.Timedelta(days=7):
        return None  # fund not that old
    base = s[s.index <= start_at]
    if base.empty or base.iloc[-1] <= 0:
        return None
    growth = s.iloc[-1] / base.iloc[-1]
    return (growth ** (1 / years) - 1) * 100 if years > 1 else (growth - 1) * 100


def metrics(s: Optional[pd.Series]) -> dict:
    out = {"r1": None, "r3": None, "r5": None, "volatility": None, "drawdown": None, "sharpe": None,
           "since": None, "nav": None}
    if s is None or len(s) < 30:
        return out
    out["nav"] = _f(s.iloc[-1])
    out["since"] = s.index[0].strftime("%Y-%m-%d")
    out["r1"], out["r3"], out["r5"] = _ret(s, 1), _ret(s, 3), _ret(s, 5)
    last3 = s[s.index >= s.index[-1] - pd.DateOffset(years=3)]
    daily = last3.pct_change().dropna()
    if len(daily) > 60:
        vol = float(daily.std() * math.sqrt(TRADING_DAYS) * 100)
        out["volatility"] = vol
        peak = last3.cummax()
        out["drawdown"] = float(((last3 / peak) - 1).min() * 100)
        basis = out["r3"] if out["r3"] is not None else out["r1"]
        if basis is not None and vol > 0:
            out["sharpe"] = (basis - RISK_FREE) / vol
    return out


def similarity(a: Optional[pd.Series], b: Optional[pd.Series]) -> Optional[float]:
    if a is None or b is None:
        return None
    cutoff = a.index[-1] - pd.DateOffset(years=1)
    ra = a[a.index >= cutoff].pct_change()
    rb = b[b.index >= cutoff].pct_change()
    joined = pd.concat([ra, rb], axis=1, join="inner").dropna()
    if len(joined) < 60:
        return None
    return _f(joined.iloc[:, 0].corr(joined.iloc[:, 1]))


# ---------------------------------------------------------------- peers

def _growth(row: dict) -> bool:
    text = f"{row.get('option') or ''} {row.get('name') or ''}"
    return "growth" in text.lower() and not _EXCLUDE.search(text)


def candidates(row: dict, rows: list[dict]) -> list[dict]:
    """Same SEBI category and plan, growth option, open-ended; one per fund house
    (the chosen fund always included)."""
    category, plan = row.get("sector"), row.get("plan")
    best: dict[str, dict] = {}
    for r in rows:
        if r.get("type") != "mf" or r.get("sector") != category or r.get("plan") != plan:
            continue
        if str(r["symbol"]) != str(row["symbol"]) and not _growth(r):
            continue
        if "close ended" in str(r.get("sector") or "").lower():
            continue
        amc = r.get("amc") or r["symbol"]
        if str(r["symbol"]) == str(row["symbol"]):
            best[amc] = r
        elif amc not in best or (len(r["name"]) < len(best[amc]["name"]) and str(best[amc]["symbol"]) != str(row["symbol"])):
            best[amc] = r  # the plainest name is usually the flagship scheme
    out = list(best.values())
    if not any(str(r["symbol"]) == str(row["symbol"]) for r in out):
        out.append(row)
    return out


def _overlap(a: Optional[dict], b: Optional[dict]) -> Optional[float]:
    """Share of the portfolio the two funds hold in common (sum of min weights)."""
    from .fund_holdings import pair_overlap

    out = pair_overlap(a, b)
    return out["overlap"] if out else None


def _rank(values: list[tuple[str, Optional[float]]], code: str, higher_better: bool = True) -> Optional[dict]:
    scored = [(c, v) for c, v in values if v is not None]
    mine = next((v for c, v in scored if c == code), None)
    if mine is None or len(scored) < 3:
        return None
    ordered = sorted(scored, key=lambda t: -t[1] if higher_better else t[1])
    position = next(i for i, (c, _) in enumerate(ordered) if c == code) + 1
    quartile = min(4, 1 + (position - 1) * 4 // len(ordered))
    return {"rank": position, "of": len(ordered), "quartile": quartile,
            "median": sorted(v for _, v in scored)[len(scored) // 2]}


def compare(code: str, rows: Optional[list[dict]] = None, fetch: NavFetch = mf_nav,
            holdings: Optional[Callable[[str], dict]] = None) -> dict:
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows("india")
    row = next((r for r in rows if r.get("type") == "mf" and str(r["symbol"]) == str(code)), None)
    if row is None:
        return {"status": "unknown", "note": "No such scheme."}
    peers = candidates(row, rows)
    if len(peers) > MAX_PEERS:
        peers = sorted(peers, key=lambda r: str(r["symbol"]) != str(code))[:MAX_PEERS]
    with ThreadPoolExecutor(max_workers=8) as pool:
        series = dict(zip((str(p["symbol"]) for p in peers), pool.map(lambda p: nav(str(p["symbol"]), fetch), peers)))
    mine = series.get(str(code))

    if holdings is None:
        from . import fund_holdings

        holdings = fund_holdings.for_fund
    my_holdings = None
    try:
        my_holdings = holdings(str(code))
    except Exception:
        pass

    out_rows = []
    for p in peers:
        c = str(p["symbol"])
        m = metrics(series.get(c))
        if m["nav"] is None:
            continue
        overlap = None
        if c != str(code) and my_holdings and my_holdings.get("status") == "ok":
            try:
                overlap = _overlap(my_holdings, holdings(c))
            except Exception:
                overlap = None
        out_rows.append({"code": c, "name": p["name"], "amc": p.get("amc"), "is_self": c == str(code),
                         **m, "similarity": 1.0 if c == str(code) else similarity(mine, series.get(c)),
                         "overlap": overlap})
    out_rows.sort(key=lambda r: (r["r3"] is None, -(r["r3"] or 0), -(r["r1"] or 0)))

    ranks = {}
    for key, higher in (("r1", True), ("r3", True), ("r5", True), ("volatility", False), ("drawdown", True),
                        ("sharpe", True)):
        ranks[key] = _rank([(r["code"], r[key]) for r in out_rows], str(code), higher)
    closest = sorted((r for r in out_rows if not r["is_self"] and r["similarity"] is not None),
                     key=lambda r: -r["similarity"])[:3]
    return {
        "status": "ok", "code": str(code), "name": row["name"],
        "category": row.get("sector"), "group": row.get("category"), "plan": row.get("plan"),
        "count": len(out_rows), "ranks": ranks, "rows": out_rows,
        "closest": [{"code": r["code"], "name": r["name"], "similarity": r["similarity"]} for r in closest],
        "risk_free": RISK_FREE,
        "note": "Same SEBI category and plan, growth option, one scheme per fund house. Past returns don't predict future ones.",
    }
