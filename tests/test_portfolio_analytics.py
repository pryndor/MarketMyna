"""Tests for portfolio risk analytics (offline, synthetic closes)."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from marketmyna.portfolio.analytics import analyze, ratios

IDX = pd.date_range(end=datetime(2026, 9, 25), periods=250, freq="B")


def _walk(seed, drift=0.0005, vol=0.01, base=None):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, len(IDX)) if base is None else base + rng.normal(0, vol / 4, len(IDX))
    return pd.Series(100 * np.cumprod(1 + r), index=IDX), r


def _fetch_for(closes):
    return lambda tickers: {t: closes[t] for t in tickers if t in closes}


class TestRatios:
    def test_known_values(self):
        r = pd.Series([0.01, -0.02, 0.02, -0.005, 0.0] * 50)  # mean +0.1%/day
        m = ratios(r, rf=0.0)
        assert m["volatility"] == pytest.approx(r.std() * np.sqrt(252))
        assert m["max_drawdown"] < 0
        assert m["var_95"] == pytest.approx(0.02)
        assert m["sortino"] > m["sharpe"]


class TestAnalyze:
    def test_full_payload(self):
        bench, bench_r = _walk(1)
        a, _ = _walk(2, base=bench_r * 1.5)  # high beta, tracks the index
        b, _ = _walk(3, drift=0.0002, vol=0.005)
        fetch = _fetch_for({"AAA.NS": a, "BBB.NS": b, "^NSEI": bench})
        out = analyze([{"symbol": "AAA", "market": "india", "market_value": 6000},
                       {"symbol": "BBB", "market": "india", "market_value": 4000}], fetch)
        assert out["benchmark"]["symbol"] == "^NSEI" and out["market"] == "india"
        assert out["total_value"] == 10000
        h = {x["symbol"]: x for x in out["holdings"]}
        assert h["AAA"]["weight"] == pytest.approx(0.6)
        assert h["AAA"]["beta"] == pytest.approx(1.5, abs=0.15)
        assert sum(x["risk_contribution"] for x in out["holdings"]) == pytest.approx(1.0)
        assert out["correlation"]["symbols"] == ["AAA", "BBB"]
        assert out["correlation"]["matrix"][0][0] == pytest.approx(1.0)
        m = out["metrics"]
        assert m["var_95_value"] == pytest.approx(m["var_95"] * 10000)
        assert m["beta"] is not None and m["benchmark_return"] is not None
        opt = out["optimizer"]
        assert sum(opt["max_sharpe"]["weights"].values()) == pytest.approx(1.0, abs=1e-3)
        assert sum(opt["risk_parity"]["weights"].values()) == pytest.approx(1.0, abs=1e-3)
        assert out["curve"][0]["portfolio"] is not None and "benchmark" in out["curve"][0]

    def test_max_sharpe_caps_each_holding(self):
        star, _ = _walk(4, drift=0.004, vol=0.008)  # far better than the rest
        rest = {f"S{i}.NS": _walk(10 + i)[0] for i in range(3)}
        bench, _ = _walk(1)
        fetch = _fetch_for({"STAR.NS": star, "^NSEI": bench, **rest})
        holdings = [{"symbol": "STAR", "market": "india", "market_value": 2500}] + [
            {"symbol": s.split(".")[0], "market": "india", "market_value": 2500} for s in rest]
        opt = analyze(holdings, fetch)["optimizer"]
        assert opt["max_weight"] == pytest.approx(0.4)
        w = opt["max_sharpe"]["weights"]
        assert max(w.values()) <= 0.4 + 1e-3
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-3)

    def test_mutual_funds_use_nav_and_india_benchmark(self):
        bench, bench_r = _walk(1)
        fund, _ = _walk(5, base=bench_r)
        stock, _ = _walk(6)
        fetch = _fetch_for({"MF:118989": fund, "RELIANCE.NS": stock, "^NSEI": bench})
        out = analyze([{"symbol": "118989", "market": "mf", "market_value": 5000},
                       {"symbol": "RELIANCE", "market": "india", "market_value": 5000}], fetch)
        assert out["market"] == "india" and out["benchmark"]["symbol"] == "^NSEI"
        assert not any("several markets" in w for w in out["warnings"])
        assert {h["symbol"] for h in out["holdings"]} == {"118989", "RELIANCE"}

    def test_single_holding_skips_optimizer_and_missing_history_warns(self):
        a, _ = _walk(2)
        out = analyze([{"symbol": "AAPL", "market": "US", "market_value": 1000},
                       {"symbol": "NOPE", "market": "US", "market_value": 500}], _fetch_for({"AAPL": a}))
        assert out["optimizer"] is None
        assert any("NOPE" in w for w in out["warnings"])
        assert any("Benchmark" in w for w in out["warnings"]) and out["metrics"]["beta"] is None

    def test_mixed_markets_warn(self):
        a, _ = _walk(2)
        b, _ = _walk(3)
        out = analyze([{"symbol": "AAPL", "market": "US", "market_value": 1000},
                       {"symbol": "TCS", "market": "india", "market_value": 500}],
                      _fetch_for({"AAPL": a, "TCS.NS": b}))
        assert out["market"] == "us" and any("currencies" in w for w in out["warnings"])

    def test_nothing_to_analyse(self):
        with pytest.raises(ValueError):
            analyze([{"symbol": "X", "market": "US", "market_value": 0}], _fetch_for({}))
        with pytest.raises(ValueError):
            analyze([{"symbol": "X", "market": "US", "market_value": 10}], _fetch_for({}))
