"""ETF screens (src/services/etf_screens.py), offline."""

import numpy as np
import pandas as pd

from src.services import etf_screens as es

IDX = pd.bdate_range("2025-10-01", periods=260)


def _bars(start, end, volume=1000.0):
    return pd.DataFrame({"close": np.linspace(start, end, len(IDX)), "volume": volume}, index=IDX)


def test_universe_skips_leveraged_and_ranks_by_turnover():
    rows = [
        {"symbol": "AAA", "name": "Plain ETF", "type": "etf", "volume": 10, "price": 10},
        {"symbol": "BBB", "name": "Big ETF", "type": "etf", "volume": 1000, "price": 10},
        {"symbol": "LEV", "name": "Something 3x Bull", "type": "etf", "volume": 10**9, "price": 10},
        {"symbol": "INV", "name": "Short fund", "type": "etf", "volume": 10**9, "price": 10, "category": "Leveraged & Inverse"},
        {"symbol": "STK", "name": "A stock", "type": "stock", "volume": 10**9, "price": 10},
    ]
    syms = [f["symbol"] for f in es.universe("india", rows)]
    assert syms == ["BBB", "AAA"]
    assert es.universe("india", rows)[0]["ticker"] == "BBB.NS"


def test_screens_rank_on_price_history():
    rows = [{"symbol": s, "name": s, "type": "etf", "volume": 100, "price": 10, "currency": "INR"} for s in ("UP", "DOWN", "FLAT")]
    data = {"UP.NS": _bars(100, 160, 5000), "DOWN.NS": _bars(160, 100, 10), "FLAT.NS": _bars(100, 100.5, 50),
            "^NSEI": _bars(100, 110)}
    fetch = lambda tickers: {t: data[t] for t in tickers if t in data}
    best = es.run("best_1y", "india", fetch=fetch, rows=rows, use_cache=False)
    assert [r["symbol"] for r in best["results"]] == ["UP", "FLAT"]
    beat = es.run("beating_index", "india", fetch=fetch, rows=rows, use_cache=False)
    assert [r["symbol"] for r in beat["results"]] == ["UP"]
    traded = es.run("most_traded", "india", fetch=fetch, rows=rows, use_cache=False)
    assert [r["symbol"] for r in traded["results"]] == ["UP", "FLAT", "DOWN"]
    assert traded["results"][0]["volume"] > traded["results"][1]["volume"]
    calm = es.run("low_volatility", "india", fetch=fetch, rows=rows, use_cache=False)
    assert "FLAT" in [r["symbol"] for r in calm["results"]]
    assert es.run("drawdown", "india", fetch=fetch, rows=rows, use_cache=False)["results"][0]["symbol"] == "DOWN"


def test_hong_kong_leveraged_codes_are_skipped():
    rows = [{"symbol": "07522", "name": "Fi2Camndq100", "type": "etf", "volume": 10**9, "price": 1},
            {"symbol": "03175", "name": "F Samsung Oil", "type": "etf", "volume": 10, "price": 1}]
    assert [f["symbol"] for f in es.universe("hong_kong", rows) if f["symbol"] in ("07522", "03175")] == ["03175"]
