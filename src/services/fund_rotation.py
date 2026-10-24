"""Relative rotation for Indian equity mutual funds: is a category, a fund
house, or a single fund Leading, Weakening, Lagging or Improving against the
Nifty 500? Same RS-Ratio / RS-Momentum maths as the stock sector view
(services/rotation.py), on weekly NAVs.

- Categories (Large Cap, Mid Cap, Small Cap, Flexi Cap, ELSS, ...) and fund
  houses are equal-weighted baskets of their Direct-Growth equity funds;
  the longest-running schemes (lowest AMFI codes) are picked first.
- Drill into one category or fund house to see each of its funds.
NAVs come from mfapi.in (AMFI data); each fund's history is cached for the
day, results for a few hours (NAVs change once a day).
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

import pandas as pd

from .rotation import TAIL, WINDOW, _weekly, quadrant, rrg

logger = logging.getLogger(__name__)

BENCHMARK = ("^CRSLDX", "Nifty 500")
BASKET = 8  # funds per category / fund house basket
DRILL = 15  # funds shown when drilling into one group
MIN_WEEKS = 30
CACHE_SECONDS = 6 * 3600
EQUITY_CATEGORIES = ("Equity", "ELSS (Tax Saving)")
# Fund-house baskets lean on the core diversified categories first.
CORE = ("Large Cap Fund", "Flexi Cap Fund", "Large & Mid Cap Fund", "Mid Cap Fund", "Small Cap Fund",
        "Multi Cap Fund", "ELSS", "Focused Fund", "Value Fund")

NavFetch = Callable[[int], Optional[pd.Series]]
_cache: dict[tuple, tuple[float, dict]] = {}
_navs: dict[int, tuple[float, Optional[pd.Series]]] = {}
_lock = threading.Lock()


def _nav(code: int) -> Optional[pd.Series]:
    from ..data.mutual_funds import MutualFundDataFetcher

    with _lock:
        hit = _navs.get(code)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        df = MutualFundDataFetcher().get_historical_nav(code, days=400)
        s = df["nav"].astype(float) if not df.empty else None
    except Exception as exc:
        logger.debug("NAV %s failed: %s", code, exc)
        s = None
    with _lock:
        _navs[code] = (time.time(), s)
    return s


def _bench() -> pd.Series:
    import yfinance as yf

    h = yf.Ticker(BENCHMARK[0]).history(period="1y")
    if h.empty:
        raise ValueError(f"{BENCHMARK[1]} is unavailable right now")
    return _weekly(h["Close"])


def equity_funds(rows: list[dict]) -> list[dict]:
    """Direct-plan, growth-option equity funds (not index funds / ETFs)."""
    out = []
    for r in rows:
        if r.get("type") != "mf" or r.get("category") not in EQUITY_CATEGORIES:
            continue
        option = (r.get("option") or "").lower()
        if r.get("plan") != "Direct" or "growth" not in option or "idcw" in option:
            continue
        if not str(r.get("symbol", "")).isdigit():
            continue
        out.append(r)
    # Oldest schemes first; one entry per fund name (a merged scheme can keep
    # two AMFI codes under the same name).
    seen, unique = set(), []
    for r in sorted(out, key=lambda r: int(r["symbol"])):
        k = (r.get("amc"), _short(r.get("name", "")).lower())
        if k not in seen:
            seen.add(k)
            unique.append(r)
    return unique


def _group_key(r: dict, by: str) -> Optional[str]:
    if by == "amc":
        return r.get("amc")
    sector = r.get("sector") or ""
    if "ELSS" in sector or r.get("category") == "ELSS (Tax Saving)":
        return "ELSS"
    if sector in ("Sectoral/ Thematic", "Thematic Fund", "Sectoral Fund"):
        return "Sectoral / Thematic"
    return sector or None


def _short(name: str) -> str:
    for cut in (" - Direct Plan", " Direct Plan", " - Direct", "-Direct", " Direct"):
        if cut in name:
            return name.split(cut)[0].strip()
    return name


def _point(weekly: pd.Series, bench: pd.Series) -> Optional[dict]:
    path = rrg(weekly, bench)
    if path.empty:
        return None
    tail = path.tail(TAIL)
    last = tail.iloc[-1]
    return {
        "ratio": float(last["ratio"]), "momentum": float(last["momentum"]),
        "quadrant": quadrant(float(last["ratio"]), float(last["momentum"])),
        "return_4w": float(weekly.iloc[-1] / weekly.iloc[-5] - 1) * 100 if len(weekly) > 5 else None,
        "tail": [{"week": str(i.date()), "ratio": float(v["ratio"]), "momentum": float(v["momentum"])}
                 for i, v in tail.iterrows()],
    }


def build(by: str = "category", name: Optional[str] = None, rows: Optional[list[dict]] = None,
          nav: NavFetch = _nav, bench: Optional[Callable[[], pd.Series]] = None) -> dict:
    """by: "category" or "amc". With `name`, each fund inside that group."""
    if by not in ("category", "amc"):
        raise ValueError("Group by category or amc")
    key = (by, name)
    use_cache = rows is None
    if use_cache:
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        from ..data.listings import get_store

        rows = get_store().rows("india")

    funds = equity_funds(rows)
    groups: dict[str, list[dict]] = {}
    for r in funds:
        g = _group_key(r, by)
        if g:
            groups.setdefault(g, []).append(r)

    if name is not None:
        if name not in groups:
            raise ValueError(f"No equity funds found for '{name}'")
        picked = {name: groups[name][:DRILL]}
    elif by == "amc":
        # A fund house: its core diversified funds first, then the rest.
        picked = {g: sorted(m, key=lambda r: (_group_key(r, "category") not in CORE, int(r["symbol"])))[:BASKET]
                  for g, m in groups.items() if len(m) >= 3}
    else:
        picked = {g: m[:BASKET] for g, m in groups.items() if len(m) >= 3}

    codes = sorted({int(r["symbol"]) for m in picked.values() for r in m})
    with ThreadPoolExecutor(max_workers=8) as pool:
        series = dict(zip(codes, pool.map(nav, codes)))
    weekly = {c: _weekly(s) for c, s in series.items() if s is not None and len(s.dropna()) > MIN_WEEKS * 5}
    b = (bench or _bench)()

    items = []
    for g, members in picked.items():
        if name is not None:  # one point per fund
            for r in members:
                w = weekly.get(int(r["symbol"]))
                if w is None or len(w) < MIN_WEEKS:
                    continue
                p = _point(w, b)
                if p:
                    items.append({"name": _short(r["name"]), "code": r["symbol"], "amc": r.get("amc"),
                                  "category": _group_key(r, "category"), **p})
            continue
        parts = [weekly[int(r["symbol"])] for r in members if int(r["symbol"]) in weekly
                 and len(weekly[int(r["symbol"])]) >= MIN_WEEKS]
        if len(parts) < 2:
            continue
        frame = pd.concat([p / p.iloc[0] for p in parts], axis=1).ffill().dropna()
        basket = frame.mean(axis=1)  # equal weight
        p = _point(basket, b)
        if p:
            items.append({"name": g, "funds": len(parts), "total_funds": len(groups[g]), **p})

    order = {"leading": 0, "improving": 1, "weakening": 2, "lagging": 3}
    items.sort(key=lambda s: (order[s["quadrant"]], -s["ratio"]))
    out = {"by": by, "group": name, "benchmark": {"symbol": BENCHMARK[0], "name": BENCHMARK[1]},
           "as_of": str(b.index[-1].date()), "window_weeks": WINDOW, "items": items,
           "groups": sorted(groups) if name is None else None}
    if use_cache:
        with _lock:
            _cache[key] = (time.time(), out)
    return out


def warm() -> None:
    """Pre-build both views after start-up so the first visitor doesn't wait."""
    for by in ("category", "amc"):
        try:
            build(by)
        except Exception as exc:
            logger.info("Fund rotation warm-up (%s) skipped: %s", by, exc)
