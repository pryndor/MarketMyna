"""Tests for the kNN signal filters: above all, no look-ahead (offline)."""

import numpy as np
import pandas as pd
import pytest

from src.trading import backtest as bt
from src.trading import knn


def _bars(n=600, seed=3):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    vol = rng.integers(1_000, 10_000, n).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol},
                        index=pd.bdate_range("2020-01-01", periods=n))


def test_analog_score_has_no_look_ahead():
    df = _bars()
    cut = 450
    full = knn.analog_score(df)
    future_changed = df.copy()
    future_changed.iloc[cut:, :4] *= 1.5  # wildly different future
    other = knn.analog_score(future_changed)
    # every bar before the change point - horizon must be identical
    a, b = full["score"].iloc[: cut - 4], other["score"].iloc[: cut - 4]
    assert a.notna().sum() > 200
    pd.testing.assert_series_equal(a, b)


def test_crossover_vote_has_no_look_ahead():
    df = _bars()
    cut = 450
    a = knn.crossover_vote(df)
    changed = df.copy()
    changed.iloc[cut:, :4] *= 0.5
    b = knn.crossover_vote(changed)
    pd.testing.assert_frame_equal(a.iloc[:cut], b.iloc[:cut])
    assert a["vote"].notna().sum() > 5


def test_fisher_weights_favour_the_separating_feature():
    rng = np.random.default_rng(1)
    y = np.where(rng.random(400) > 0.5, 1.0, -1.0)
    x = np.column_stack([y * 0.8 + rng.normal(0, 0.3, 400), rng.normal(0, 1, 400)])
    w = knn.fisher_weights(x, y)
    assert w[0] == 1.0 and w[1] == pytest.approx(0.4)  # noise feature sits at the floor


def test_adaptive_band_widens_when_unsure():
    df = _bars()
    sure, _ = knn.adaptive_supertrend(df, pd.Series(1.0, index=df.index), multiplier=2.0)
    unsure, _ = knn.adaptive_supertrend(df, pd.Series(0.0, index=df.index), multiplier=2.0)
    gap_sure = (df["close"] - sure).abs().iloc[100:].mean()
    gap_unsure = (df["close"] - unsure).abs().iloc[100:].mean()
    assert gap_unsure > gap_sure


@pytest.mark.parametrize("strategy", ["vwma_cross", "vwma_knn", "knn_supertrend"])
def test_strategies_run_and_need_volume(strategy):
    df = _bars()
    out = bt.run(df, bt.Settings(strategy=strategy), "1d")
    assert "metrics" in out
    if strategy.startswith("vwma"):
        with pytest.raises(ValueError, match="volume"):
            bt.run(df.drop(columns="volume"), bt.Settings(strategy=strategy), "1d")


def test_chart_draws_knn_indicators():
    from src.trading import chart

    df = _bars(400)
    out = chart.build_chart(df, "1d", ["vwma", "knn_st"])
    assert {"vwma13", "vwma19", "knn_st_up", "knn_st_down"} <= set(out["series"])
    assert out["markers"] and {m["kind"] for m in out["markers"]} <= {"buy", "sell", "buy_skip", "sell_skip"}
    assert out["markers"] == sorted(out["markers"], key=lambda m: m["time"])
    assert out["knn"] and -1 <= out["knn"]["score"] <= 1 and out["knn"]["trend"] in ("up", "down")
    plain = chart.build_chart(df, "1d", ["ema9"])
    assert plain["markers"] == [] and plain["knn"] is None
