"""Stress scenarios and benchmark-relative metrics (src/portfolio/analytics.py)."""

import numpy as np
import pandas as pd
import pytest

from src.portfolio import analytics as a


def test_stress_uses_peak_to_trough_and_beta():
    idx = pd.bdate_range("2019-12-02", "2020-06-30")
    prices = np.linspace(100, 110, len(idx))
    s = pd.Series(prices, index=idx)
    s[(idx >= "2020-02-20") & (idx <= "2020-03-23")] = np.linspace(108, 66, ((idx >= "2020-02-20") & (idx <= "2020-03-23")).sum())
    rows = a.stress({"A": 0.5, "B": 0.5}, {"A": 1.2, "B": None}, s)
    covid = next(r for r in rows if r["label"].startswith("2020"))
    peak = float(s[(s.index >= "2020-01-14") & (s.index <= "2020-03-31")].max())
    assert covid["index_move"] == pytest.approx(66 / peak - 1)
    assert covid["portfolio_move"] == pytest.approx(covid["index_move"] * 1.1)  # 0.5 x 1.2 + 0.5 x 1
    assert covid["to"] == "2020-03-23"
    flat = [r for r in rows if r["from"] is None]
    assert [r["index_move"] for r in flat] == [-0.10, -0.20, -0.30]
    assert not any(r["label"].startswith("2008") for r in rows)  # no data for that window


def test_versus_benchmark():
    idx = pd.bdate_range("2025-01-01", periods=200)
    rng = np.random.default_rng(1)
    bench = pd.Series(rng.normal(0.0005, 0.01, len(idx)), index=idx)
    port = bench * 1.0  # a perfect tracker
    m = a.versus_benchmark(port, bench)
    assert m["tracking_error"] == pytest.approx(0, abs=1e-12)
    assert m["up_capture"] == pytest.approx(1) and m["down_capture"] == pytest.approx(1)
    half = a.versus_benchmark(bench * 0.5, bench)
    assert half["up_capture"] == pytest.approx(0.5) and half["down_capture"] == pytest.approx(0.5)
    assert half["tracking_error"] > 0
