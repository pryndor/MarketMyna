"""Hierarchical risk parity and minimum CVaR (marketmyna/portfolio/optimizers.py)."""

import numpy as np
import pandas as pd
import pytest

from marketmyna.portfolio import optimizers as o


def _returns(seed=0, n=500):
    rng = np.random.default_rng(seed)
    common = rng.normal(0, 0.01, n)
    return pd.DataFrame({
        "A": common + rng.normal(0, 0.004, n),   # A and B: one cluster
        "B": common + rng.normal(0, 0.004, n),
        "C": rng.normal(0, 0.02, n),             # high-vol loner
        "D": rng.normal(0, 0.005, n),            # low-vol loner
    })


def test_hrp_weights_sum_and_favour_low_variance():
    w = o.hrp(_returns())
    assert w.sum() == pytest.approx(1) and (w > 0).all()
    assert list(w.index) == ["A", "B", "C", "D"]
    assert w["D"] > w["C"]  # lower variance gets more weight
    # independent equal-variance assets: HRP = equal weights
    rng = np.random.default_rng(3)
    eq = o.hrp(pd.DataFrame(rng.normal(0, 0.01, (2000, 4)), columns=list("wxyz")))
    assert np.allclose(eq.to_numpy(), 0.25, atol=0.03)


def test_min_cvar_beats_equal_weight_and_respects_cap():
    r = _returns(1)
    w = o.min_cvar(r, max_weight=0.6)
    assert w.sum() == pytest.approx(1) and (w >= -1e-9).all() and (w <= 0.6 + 1e-9).all()
    eq = np.full(4, 0.25)
    assert o.cvar(r.to_numpy() @ w.to_numpy()) <= o.cvar(r.to_numpy() @ eq) + 1e-9
    assert w["C"] < w["D"]  # the volatile loner gets less than the calm one


def test_cvar_definition():
    x = np.array([-0.05, -0.03, 0.01] + [0.0] * 37)  # 40 days: worst 5% = 2 days
    assert o.cvar(x) == pytest.approx(0.04)
