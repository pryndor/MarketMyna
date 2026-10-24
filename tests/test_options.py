"""Tests for option pricing, analytics and strategy payoff (offline)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.trading.options import analyse, bs, implied_vol, max_pain, payoff


def test_black_scholes_reference_and_parity():
    # Hull's textbook example: S=42, K=40, r=10%, sigma=20%, T=0.5 -> call 4.76, put 0.81
    c = bs(42, 40, 0.5, 0.1, 0.2, "call")
    p = bs(42, 40, 0.5, 0.1, 0.2, "put")
    assert c["price"] == pytest.approx(4.76, abs=0.01) and p["price"] == pytest.approx(0.81, abs=0.01)
    assert c["delta"] - p["delta"] == pytest.approx(1.0)
    assert c["gamma"] == pytest.approx(p["gamma"]) and c["vega"] == pytest.approx(p["vega"])


def test_implied_vol_roundtrip():
    price = bs(100, 105, 30 / 365, 0.065, 0.27, "call")["price"]
    assert implied_vol(price, 100, 105, 30 / 365, 0.065, "call") == pytest.approx(0.27, abs=1e-4)
    assert implied_vol(0.01, 100, 50, 30 / 365, 0.065, "call") is None  # below intrinsic


def _rows():
    return [
        {"strike": 90.0, "call": {"oi": 100, "ltp": 12}, "put": {"oi": 900, "ltp": 0.5}},
        {"strike": 100.0, "call": {"oi": 500, "ltp": 3, "iv": 20}, "put": {"oi": 600, "ltp": 3, "iv": 22}},
        {"strike": 110.0, "call": {"oi": 1200, "ltp": 0.6}, "put": {"oi": 100, "ltp": 10.5}},
    ]


def test_max_pain_and_summary():
    rows = _rows()
    assert max_pain(rows) == 100.0
    s = analyse(101.0, rows, "2026-10-09", "india", today=date(2026, 9, 25))
    assert s["atm_strike"] == 100.0 and s["atm_iv"] == 21.0 and s["days_to_expiry"] == 14
    assert s["support"] == 90.0 and s["resistance"] == 110.0
    # Levels come from the right side of spot even when OI is larger elsewhere.
    rows[2]["put"]["oi"] = 5000
    assert analyse(101.0, rows, "2026-10-09", "india", today=date(2026, 9, 25))["support"] == 90.0
    assert s["pcr_oi"] == pytest.approx(1600 / 1800, abs=0.01)
    assert rows[0]["call"]["iv"] and rows[0]["call"]["iv_estimated"]  # IV backed out of the price
    assert "delta" in rows[1]["put"]


def test_zero_oi_gives_no_levels():
    rows = [{"strike": 100.0, "call": {"oi": 0, "ltp": 1}, "put": {"oi": 0, "ltp": 1}}]
    s = analyse(100.0, rows, "2026-10-09", "us", today=date(2026, 9, 25))
    assert s["max_pain"] is None and s["support"] is None


def test_payoff_bull_call_spread():
    legs = [{"type": "call", "side": "buy", "strike": 100, "premium": 4, "quantity": 10, "iv": 20},
            {"type": "call", "side": "sell", "strike": 110, "premium": 1, "quantity": 10, "iv": 20}]
    p = payoff(legs, 100, 10, 0.05)
    assert p["breakevens"] == [pytest.approx(103, abs=0.01)]
    assert p["max_profit"] == pytest.approx(70) and p["max_loss"] == pytest.approx(-30)
    assert p["net_premium"] == -30  # debit


def test_payoff_unlimited_sides():
    naked = payoff([{"type": "call", "side": "sell", "strike": 100, "premium": 2, "quantity": 1, "iv": 20}], 100, 5, 0.05)
    assert naked["max_loss"] is None and naked["max_profit"] == pytest.approx(2)
    straddle = payoff([{"type": "call", "side": "buy", "strike": 100, "premium": 3, "quantity": 1},
                       {"type": "put", "side": "buy", "strike": 100, "premium": 3, "quantity": 1}], 100, 5, 0.05)
    assert straddle["max_profit"] is None and straddle["max_loss"] == pytest.approx(-6)
    assert [round(b) for b in straddle["breakevens"]] == [94, 106]
    short_put = payoff([{"type": "put", "side": "sell", "strike": 100, "premium": 2, "quantity": 1}], 100, 5, 0.05)
    assert short_put["max_profit"] == pytest.approx(2) and short_put["max_loss"] == pytest.approx(-98)  # bounded at price 0
    long_put = payoff([{"type": "put", "side": "buy", "strike": 100, "premium": 2, "quantity": 1}], 100, 5, 0.05)
    assert long_put["max_profit"] == pytest.approx(98)


class TestVolCompare:
    def _bars(self, sigma, n=250, seed=4):
        rng = np.random.default_rng(seed)
        steps = 30
        path = 100 * np.exp(np.cumsum(rng.normal(0, sigma / np.sqrt(252 * steps), n * steps))).reshape(n, steps)
        idx = pd.date_range(end="2026-09-25", periods=n, freq="B")
        return pd.DataFrame({"Open": path[:, 0], "High": path.max(1), "Low": path.min(1), "Close": path[:, -1]}, index=idx)

    def test_verdicts(self):
        from src.trading.options import compare_vol

        bars = self._bars(0.2)
        base = compare_vol(None, bars)
        assert base["verdict"] is None and 10 < base["rv_20"] < 30
        assert compare_vol(base["rv_20"] * 1.5, bars)["verdict"] == "expensive"
        assert compare_vol(base["rv_20"] * 0.7, bars)["verdict"] == "cheap"
        fair = compare_vol(base["rv_20"], bars)
        assert fair["verdict"] == "fair" and fair["ratio"] == 1.0
        assert compare_vol(20, bars.head(30)) is None
