"""Tests for the compare and peers service (offline, synthetic data)."""

import numpy as np
import pandas as pd
import pytest

from marketmyna.services import compare as cmp

IDX = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=520)


def _walk(seed, drift=0.0005, vol=0.012):
    r = np.random.default_rng(seed).normal(drift, vol, len(IDX))
    return pd.Series(100 * np.cumprod(1 + r), index=IDX)


INFOS = {
    "AAA": {"shortName": "Alpha", "currency": "USD", "trailingPE": 30, "forwardPE": 25, "returnOnEquity": 0.25,
            "debtToEquity": 150.0, "currentPrice": 100, "targetMeanPrice": 120, "industry": "Software", "sector": "Tech",
            "dividendYield": 0.5},
    "BBB": {"shortName": "Beta", "currency": "USD", "trailingPE": 15, "forwardPE": -3, "returnOnEquity": 0.10,
            "debtToEquity": 40.0, "currentPrice": 50, "targetMeanPrice": 45, "industry": "Software", "sector": "Tech"},
}


def _prices(tickers, period):
    out = {"AAA": _walk(1, 0.001), "BBB": _walk(2, 0.0), "^GSPC": _walk(3)}
    return {t: out[t] for t in tickers if t in out}


def test_compare_payload():
    out = cmp.compare([("aaa", "us"), ("BBB", "US")], "1y", info_fetch=lambda t: INFOS.get(t, {}), price_fetch=_prices)
    assert [i["symbol"] for i in out["items"]] == ["AAA", "BBB"]
    assert out["chart"][0]["AAA"] == pytest.approx(100) and out["chart"][0]["BBB"] == pytest.approx(100)
    one_y = next(r for r in out["returns"] if r["window"] == "1Y")
    assert one_y["values"]["AAA"] is not None
    assert out["risk"]["AAA"]["beta"] is not None and out["risk"]["AAA"]["max_drawdown"] <= 0
    assert out["correlation"]["symbols"] == ["AAA", "BBB"]
    m = {x["label"]: x for x in out["metrics"]}
    assert m["P/E (trailing)"]["best"] == "BBB"           # lower is better
    assert m["P/E (forward)"]["best"] is None             # negative P/E not ranked, one left
    assert m["Return on equity"]["values"]["AAA"] == pytest.approx(25)
    assert m["Debt / equity"]["values"]["AAA"] == pytest.approx(1.5) and m["Debt / equity"]["best"] == "BBB"
    assert m["Analyst target upside"]["values"]["AAA"] == pytest.approx(20)
    assert m["Dividend yield"]["values"]["AAA"] == pytest.approx(0.5)


def test_compare_validates_count_and_missing_history():
    with pytest.raises(ValueError):
        cmp.compare([("AAA", "us")], info_fetch=lambda t: {}, price_fetch=_prices)
    out = cmp.compare([("AAA", "us"), ("ZZZ", "us")], info_fetch=lambda t: {}, price_fetch=_prices)
    assert any("ZZZ" in w for w in out["warnings"])
    assert "ZZZ" not in out["risk"]


def test_peers_prefers_same_industry_and_size():
    rows = [{"symbol": s, "name": s, "type": "stock", "market_cap": cap, "category": "Financials", "price": 1}
            for s, cap in [("ME", 1e12), ("B1", 9e11), ("B2", 1.1e12), ("B3", 5e11), ("INS", 1e12), ("TINY", 1e8), ("IT", 1e12)]]
    rows[-1]["category"] = "Technology"
    ind = {"ME.NS": "Banks", "B1.NS": "Banks", "B2.NS": "Banks", "B3.NS": "Banks", "INS.NS": "Insurance", "TINY.NS": "Banks"}
    info = lambda t: {"industry": ind.get(t), "sector": "Financial Services"}
    out = cmp.peers("ME", "india", limit=3, info_fetch=info, rows=rows)
    assert out["basis"] == "Same industry: Banks"
    assert [p["symbol"] for p in out["peers"]] == ["B2", "B1", "B3"]  # nearest in size first, no insurer, no IT
