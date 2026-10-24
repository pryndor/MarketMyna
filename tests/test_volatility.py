"""Tests for realized-volatility estimators and cones (offline, simulated GBM bars)."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from marketmyna.trading import volatility as vol


def _gbm(sigma=0.3, n=400, seed=1, steps=40):
    """Daily OHLC from an intraday random walk with annual vol `sigma`."""
    rng = np.random.default_rng(seed)
    step = sigma / np.sqrt(252 * steps)
    path = 100 * np.exp(np.cumsum(rng.normal(0, step, n * steps)))
    bars = path.reshape(n, steps)
    idx = pd.date_range(end=datetime(2026, 9, 25), periods=n, freq="B")
    return pd.DataFrame({"open": bars[:, 0], "high": bars.max(axis=1), "low": bars.min(axis=1), "close": bars[:, -1]}, index=idx)


@pytest.mark.parametrize("kind", list(vol.ESTIMATORS))
def test_estimators_recover_true_vol(kind):
    est = vol.realized(_gbm(0.3), 60, kind).dropna()
    # range estimators are biased slightly low on discrete bars; all land near 30%
    assert 0.2 < est.median() < 0.38


def test_higher_vol_reads_higher():
    calm, wild = vol.realized(_gbm(0.15), 20).dropna(), vol.realized(_gbm(0.6), 20).dropna()
    assert wild.median() > 3 * calm.median()


def test_cones_ordered_and_summary():
    df = _gbm(0.3)
    for c in vol.cones(df):
        assert c["min"] <= c["p25"] <= c["median"] <= c["p75"] <= c["max"]
        assert 0 < c["percentile"] <= 100
    s = vol.summary(df)
    assert s["regime"] in ("calm", "normal", "stormy") and len(s["estimators"]) == 5
    assert [c["window"] for c in s["cones"]] == [10, 20, 60, 120]


def test_summary_rejects_short_or_bad_rows():
    with pytest.raises(ValueError):
        vol.summary(_gbm(n=10))
    df = _gbm()
    df.iloc[5, 1] = 0  # a zero high must be dropped, not produce inf
    assert all(e["value"] is None or np.isfinite(e["value"]) for e in vol.summary(df)["estimators"])


def _simulate_garch(n, omega, alpha, beta, seed=0, last_shock=None):
    rng = np.random.default_rng(seed)
    var = omega / (1 - alpha - beta)
    r = np.empty(n)
    for t in range(n):
        r[t] = rng.normal(0, np.sqrt(var))
        if last_shock is not None and t == n - 1:
            r[t] = last_shock
        var = omega + alpha * r[t] ** 2 + beta * var
    return pd.Series(100 * np.exp(np.cumsum(r / 100)))


def test_garch_recovers_parameters_and_long_run():
    close = _simulate_garch(2500, omega=0.05, alpha=0.08, beta=0.9, seed=1)
    g = vol.garch(close)
    assert g["persistence"] == pytest.approx(0.98, abs=0.02)
    # long-run daily var 0.05/0.02 = 2.5 %^2 -> annualised ~25%
    assert g["long_run"] == pytest.approx(np.sqrt(2.5 * 252) / 100, rel=0.25)
    assert [f["days"] for f in g["forecasts"]] == [5, 21]


def test_garch_forecast_reverts_after_shock():
    close = _simulate_garch(1500, omega=0.05, alpha=0.1, beta=0.85, seed=2, last_shock=8.0)
    g = vol.garch(close)
    five, month = (f["volatility"] for f in g["forecasts"])
    assert g["next_day"] > five > month > g["long_run"]
    assert g["half_life_days"] and g["half_life_days"] > 0


def test_garch_needs_history():
    assert vol.garch(pd.Series(np.linspace(100, 110, 50))) is None
