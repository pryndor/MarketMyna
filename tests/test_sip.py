"""Tests for the SIP backtest service (offline, synthetic NAV)."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from marketmyna.services import sip


def _nav(daily=0.0004, years=6, seed=0, noise=0.0):
    idx = pd.bdate_range(end="2026-09-30", periods=int(252 * years))
    r = np.full(len(idx), daily) + np.random.default_rng(seed).normal(0, noise, len(idx))
    return pd.Series(10 * np.cumprod(1 + r), index=idx)


def test_xirr_matches_simple_compounding():
    flows = [(date(2020, 1, 1), -100.0), (date(2021, 1, 1), 110.0)]
    assert sip.xirr(flows) == pytest.approx(0.10, abs=1e-3)
    assert sip.xirr([(date(2020, 1, 1), -100.0)]) is None


def test_flat_nav_gives_zero_return():
    out = sip.backtest(_nav(daily=0.0), 1000, 3, 5)
    assert out["sip"]["installments"] in (36, 37)
    assert out["sip"]["value"] == pytest.approx(out["sip"]["invested"])
    assert out["sip"]["xirr_pct"] == pytest.approx(0, abs=1e-6)
    assert out["lumpsum"]["gain_pct"] == pytest.approx(0, abs=1e-9)


def test_rising_market_lumpsum_wins_and_days_listed():
    out = sip.backtest(_nav(), 5000, 5, 10)
    assert out["winner"] == "lumpsum"
    assert out["lumpsum"]["invested"] == out["sip"]["invested"]
    assert [r["day"] for r in out["by_day"]] == list(sip.SIP_DAYS)
    # steady 10%/yr-ish growth: SIP XIRR close to the lumpsum CAGR
    assert out["sip"]["xirr_pct"] == pytest.approx(out["lumpsum"]["cagr_pct"], abs=1.0)
    assert out["day_spread"]["diff_pts"] >= 0
    assert out["note"] is None


def test_short_history_notes_and_one_buy_per_month():
    nav = _nav(years=2, noise=0.01)
    out = sip.backtest(nav, 1000, 5, 25)
    assert out["note"] and "shorter" in out["note"]
    dates = sip._buy_dates(nav, nav.index[0], 25)
    months = [(d.year, d.month) for d in dates]
    assert len(months) == len(set(months)) and all(d.day >= 25 for d in dates)


def test_step_up_beats_flat():
    out = sip.step_up(10000, 10, 10, 12)
    assert out["corpus"] > out["flat_corpus"] > out["flat_invested"]
    assert out["flat_invested"] == 10000 * 120
    assert len(out["yearly"]) == 10
    assert out["yearly"][1]["monthly_sip"] == pytest.approx(11000)
