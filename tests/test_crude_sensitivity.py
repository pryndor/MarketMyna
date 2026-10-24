"""Tests for the crude sensitivity regression (offline, synthetic prices)."""

import numpy as np
import pandas as pd
import pytest

from src.services import crude_sensitivity as cs

IDX = pd.bdate_range(end="2026-09-30", periods=520)


def _series(r):
    return pd.Series(100 * np.cumprod(1 + r), index=IDX)


def _factors(seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(0.0004, 0.01, len(IDX)), rng.normal(0, 0.02, len(IDX))


def test_regress_recovers_crude_beta_net_of_market():
    m, c = _factors()
    noise = np.random.default_rng(9).normal(0, 0.004, len(IDX))
    stock = _series(1.0 * m - 0.4 * c + noise)
    r = cs.regress(stock, _series(m), _series(c))
    assert r["beta_crude"] == pytest.approx(-0.4, abs=0.08)
    assert r["beta_market"] == pytest.approx(1.0, abs=0.15)
    assert r["significant"] and r["t_crude"] < -2 and r["r2_added"] > 0.1


def test_unrelated_stock_not_significant():
    m, c = _factors(1)
    stock = _series(0.8 * m + np.random.default_rng(3).normal(0, 0.015, len(IDX)))
    r = cs.regress(stock, _series(m), _series(c))
    assert abs(r["beta_crude"]) < 0.15


def test_build_groups_and_implied_move():
    m, c = _factors(2)
    fx = pd.Series(np.full(len(IDX), 85.0), index=IDX)

    def fetch(tickers):
        out = {t: _series(0.9 * m - 0.3 * c + np.random.default_rng(len(t)).normal(0, 0.004, len(IDX))) for t in tickers}
        out.update({cs.BRENT: _series(c), cs.FX: fx, cs.NIFTY: _series(m)})
        out.pop("MRF.NS")  # a missing stock is skipped
        return out

    out = cs.build(fetch, use_cache=False)
    names = [g["name"] for g in out["groups"]]
    assert names[0] == "Oil marketing (OMCs)" and len(names) == len(cs.GROUPS)
    tyres = next(g for g in out["groups"] if g["name"] == "Tyres")
    assert "MRF" not in [s["symbol"] for s in tyres["stocks"]]
    s0 = out["groups"][0]["stocks"][0]
    assert s0["crude_implied_1m"] == pytest.approx(s0["beta_crude"] * out["brent_inr_change_1m"])


def test_build_without_crude():
    assert cs.build(lambda t: {}, use_cache=False)["groups"] == []
