"""Dealer gamma exposure and the IV fill for legs without one (src/trading/options.py)."""

import pytest

from src.trading import options as o


def _row(k, c_oi=0, p_oi=0, c_iv=20.0, p_iv=20.0):
    return {"strike": k, "call": {"oi": c_oi, "iv": c_iv}, "put": {"oi": p_oi, "iv": p_iv}}


def test_calls_positive_puts_negative_and_scale():
    rows = [_row(100, c_oi=10)]
    g = o.gamma_exposure(100.0, rows, 30, 0.05, 100)
    gamma = o.bs(100.0, 100, 30 / 365, 0.05, 0.2, "call")["gamma"]
    assert g["total"] == pytest.approx(gamma * 10 * 100 * 100 * 100 * 0.01, rel=1e-6)
    puts = o.gamma_exposure(100.0, [_row(100, p_oi=10)], 30, 0.05, 100)
    assert puts["total"] == pytest.approx(-g["total"], rel=1e-6)


def test_zero_gamma_between_put_and_call_walls():
    # heavy puts at 90, heavy calls at 110: total is negative near 90 and positive near 110
    rows = [_row(90, p_oi=1000), _row(100, c_oi=10, p_oi=10), _row(110, c_oi=1000)]
    g = o.gamma_exposure(100.0, rows, 30, 0.05, 1)
    assert 90 < g["zero_gamma"] < 110
    assert {d["strike"] for d in g["by_strike"]} == {90, 100, 110}
    assert g["by_strike"][0]["net"] < 0 < g["by_strike"][-1]["net"]


def test_missing_iv_filled_from_neighbours():
    rows = [_row(90, p_oi=5, p_iv=30.0), _row(100, c_oi=5, c_iv=None, p_iv=None), _row(110, c_oi=5, c_iv=20.0)]
    assert o._iv_at(o._smile_iv(rows), 100, 100.0) == pytest.approx(25.0)
    g = o.gamma_exposure(100.0, rows, 30, 0.05, 1)
    assert g["interpolated_iv"] and any(d["strike"] == 100 for d in g["by_strike"])


def test_no_iv_or_spot_returns_none():
    assert o.gamma_exposure(0, [_row(100, c_oi=1)], 30, 0.05, 1) is None
    assert o.gamma_exposure(100.0, [_row(100, c_oi=1, c_iv=None, p_iv=None)], 30, 0.05, 1) is None


def test_smile_recovers_flat_vol_through_the_forward():
    spot, r, days, sigma = 100.0, 0.065, 30, 0.2
    T = days / 365
    rows = []
    for k in range(90, 111, 2):
        c = o.bs(spot, k, T, r, sigma, "call")["price"]
        p = o.bs(spot, k, T, r, sigma, "put")["price"]
        rows.append({"strike": float(k), "call": {"ltp": round(c, 4)}, "put": {"ltp": round(p, 4)}})
    fwd = o.implied_forward(spot, rows, T, r)
    assert fwd == pytest.approx(spot * __import__("math").exp(r * T), rel=1e-4)
    sm = o.smile(spot, rows, days, r)
    assert {p["side"] for p in sm["points"]} == {"call", "put"}
    assert all(p["iv"] == pytest.approx(20.0, abs=0.05) for p in sm["points"])
