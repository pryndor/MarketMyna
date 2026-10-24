"""Tests for the Engle-Granger pairs test (offline, synthetic prices)."""

import numpy as np
import pandas as pd
import pytest

from src.trading import pairs

IDX = pd.bdate_range(end="2026-09-30", periods=500)


def _walk(seed, n=len(IDX)):
    return np.cumsum(np.random.default_rng(seed).normal(0, 0.01, n))


def test_adf_separates_noise_from_random_walk():
    rng = np.random.default_rng(0)
    assert pairs.adf(rng.normal(size=500))["stat"] < -10
    assert pairs.adf(np.cumsum(rng.normal(size=500)))["stat"] > -3


def test_cointegrated_pair_found_with_hedge_ratio():
    lb = 4 + _walk(1)
    noise = np.zeros(len(IDX))
    e = np.random.default_rng(2).normal(0, 0.01, len(IDX))
    for t in range(1, len(IDX)):
        noise[t] = 0.9 * noise[t - 1] + e[t]
    la = 0.5 + 1.2 * lb + noise
    out = pairs.analyze(pd.Series(np.exp(la), IDX), pd.Series(np.exp(lb), IDX))
    assert out["hedge_ratio"] == pytest.approx(1.2, abs=0.1)
    assert out["significance"] == "1%" and out["verdict"] in ("cointegrated", "stretched")
    assert 3 < out["half_life_days"] < 15  # AR(0.9) -> ln2/0.1 ~ 6.6
    assert len(out["spread"]) == len(IDX)


def test_independent_walks_not_cointegrated():
    out = pairs.analyze(pd.Series(np.exp(4 + _walk(5)), IDX), pd.Series(np.exp(4 + _walk(6)), IDX))
    assert out["verdict"] == "not_cointegrated" and out["significance"] is None


def test_needs_overlap():
    s = pd.Series(np.linspace(1, 2, 50), index=IDX[:50])
    with pytest.raises(ValueError):
        pairs.analyze(s, s * 2)
