"""Live prices for the Market insights views: merged into listing rows and
daily closes, refreshed in the background, and recomputing the boards,
breadth and rotation quadrants."""

from __future__ import annotations

import time
from datetime import date

import numpy as np
import pandas as pd

from marketmyna.services import discovery, hot_stocks, rotation
from marketmyna.services import live_market as L


def _row(sym, price, chg, cap, cat="Banks", **kw):
    return {"symbol": sym, "name": sym, "type": "stock", "price": price, "change_percent": chg, "volume": 1000,
            "market_cap": cap, "category": cat, "currency": "INR", **kw}


def test_merge_takes_live_prices_and_widens_range():
    rows = [_row("A", 100, 1.0, 1e9, high_52w=105, low_52w=80), _row("B", 50, -1.0, 5e8)]
    quotes = {"A": {"price": 110.0, "change_percent": 5.0, "volume": 9.0}}
    a, b = L.merge(rows, quotes)
    assert a["price"] == 110 and a["change_percent"] == 5.0 and a["volume"] == 9.0 and a["live"]
    assert a["high_52w"] == 110 and a["low_52w"] == 80 and a["market_cap"] == 1.1e9
    assert b == rows[1]
    # only_live drops the names that still carry an earlier session's move
    assert [r["symbol"] for r in L.merge(rows, quotes, only_live=True)] == ["A"]
    assert L.merge(rows, {}) is rows


def test_extend_replaces_or_appends_todays_close():
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2026-10-15", "2026-10-16"]))
    assert L.extend(s, 3.0, date(2026, 10, 16)).tolist() == [1.0, 3.0]
    grown = L.extend(s, 4.0, date(2026, 10, 19))
    assert grown.tolist() == [1.0, 2.0, 4.0] and grown.index[-1] == pd.Timestamp("2026-10-19")
    assert L.extend(s, 9.0, date(2026, 10, 1)).tolist() == [1.0, 2.0]  # older day: untouched
    assert L.extend(s, None, date(2026, 10, 19)) is s
    tz = s.tz_localize("Asia/Kolkata")
    assert L.extend(tz, 5.0, date(2026, 10, 19)).index[-1].tzinfo is not None


def test_market_refreshes_in_background_and_keeps_last_on_failure(monkeypatch):
    monkeypatch.setattr(L, "_states", {})
    monkeypatch.setattr("marketmyna.trading.market_hours.is_open", lambda m, now=None: True)
    monkeypatch.setattr(L, "_source", lambda name: "feed")
    monkeypatch.setattr(L, "_universe", lambda name: ["A"])
    calls = []

    def fetch(symbols):
        calls.append(symbols)
        return {"A": {"price": 10.0, "change_percent": 1.0, "time": time.time(), "day": date.today()}}

    monkeypatch.setitem(L.FETCHERS, "us", fetch)
    first = L.market("us")
    assert first["quotes"] == {} and not first["status"]["live"]  # never waits on the source
    for _ in range(100):
        if L.market("us")["quotes"]:
            break
        time.sleep(0.02)
    out = L.market("us")
    assert out["quotes"]["A"]["price"] == 10.0 and out["status"]["live"] and out["status"]["covered"] == 1
    for _ in range(5):  # within the refresh interval: no new upstream call
        L.market("us")
    assert len(calls) == 1

    def boom(symbols):
        raise RuntimeError("down")

    monkeypatch.setitem(L.FETCHERS, "us", boom)
    L._refresh("us")
    out = L.market("us")
    assert out["quotes"]["A"]["price"] == 10.0 and out["status"]["error"]


def _live(quotes):
    return {"quotes": quotes, "status": {"open": True, "live": True, "updated": time.time(), "covered": len(quotes)}}


def test_discovery_ranks_on_live_prices_only():
    rows = [_row("A", 100, 3.0, 3e9), _row("B", 100, -2.0, 2e9), _row("C", 100, 9.0, 1e9)]
    live = _live({"A": {"price": 95.0, "change_percent": -5.0}, "B": {"price": 104.0, "change_percent": 4.0}})
    out = discovery.build("india", size=20, rows=rows, with_indices=False, live=live)
    assert [r["symbol"] for r in out["gainers"]] == ["B"] and [r["symbol"] for r in out["losers"]] == ["A"]
    assert out["breadth"] == {"advancers": 1, "decliners": 1, "unchanged": 0, "total": 2}  # C is yesterday's
    assert out["live"]["live"] and out["as_of"]
    sector = out["sectors"][0]
    assert sector["leader"]["symbol"] == "B" and sector["laggard"]["symbol"] == "A"


def test_hot_trader_and_investor_rows_follow_live_prices():
    rows = [_row(f"S{i}", 100, 0.5, 1e9 + i) for i in range(60)]
    live = _live({r["symbol"]: {"price": 105.0, "change_percent": 5.0 if i == 59 else 0.1, "volume": 5000 if i == 59 else 1000}
                  for i, r in enumerate(rows)})
    out = hot_stocks.trader("india", rows=rows, live=live)
    momentum = next(b for b in out["boards"] if b["key"] == "momentum")
    assert [r["symbol"] for r in momentum["rows"]] == ["S59"] and out["live"]["live"]
    cached = {"boards": [{"key": "x", "rows": [{"symbol": "S1", "price": 1.0, "change_percent": 0.0}]}]}
    fresh = hot_stocks.with_live_prices(cached, live)
    assert fresh["boards"][0]["rows"][0]["price"] == 105.0 and cached["boards"][0]["rows"][0]["price"] == 1.0


def test_rotation_quadrant_moves_with_todays_live_price():
    days = pd.bdate_range("2025-10-01", "2026-10-16")
    rng = np.random.default_rng(1)
    bench = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.005, len(days))), index=days)
    closes = {"^NSEI": bench}
    rows = []
    for i in range(3):
        sym = f"X{i}"
        closes[f"{sym}.NS"] = bench * (1 + rng.normal(0, 0.002, len(days)))
        rows.append(_row(sym, 1, 0, 1e9 - i, cat="Tech"))
    fetch = lambda t: {k: closes[k] for k in t if k in closes}  # noqa: E731
    before = rotation.build("india", rows=rows, fetch=fetch)["sectors"][0]
    today = date(2026, 10, 19)
    surge = {f"X{i}.NS": {"price": float(closes[f"X{i}.NS"].iloc[-1]) * 1.15, "day": today} for i in range(3)}
    surge["^NSEI"] = {"price": float(bench.iloc[-1]), "day": today}
    after = rotation.build("india", rows=rows, fetch=fetch, live=surge)["sectors"][0]
    assert after["ratio"] > before["ratio"] and after["quadrant"] in ("leading", "weakening")
    assert after["tail"][-1]["week"] >= "2026-10-23"  # the current week's point


def test_memo_shares_one_computation():
    L._memo.clear()
    calls = []
    for _ in range(3):
        L.memo(("t",), lambda: calls.append(1) or len(calls))
    assert calls == [1]
