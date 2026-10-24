"""Best SIP day: the vectorised 28-day XIRR matches the per-day simulator."""

import json

import numpy as np
import pandas as pd
import pytest

from marketmyna.services import sip, sip_days


def _series(years: int = 11, seed: int = 7) -> pd.Series:
    days = pd.bdate_range(end="2026-10-01", periods=years * 252)
    rng = np.random.default_rng(seed)
    prices = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, len(days))))
    return pd.Series(prices, index=days)


@pytest.mark.parametrize("years", [3, 5, 10])
def test_matches_per_day_simulation(years):
    nav = _series()
    start = nav.index[-1] - pd.DateOffset(years=years)
    fast = sip_days.day_xirrs(nav, start)
    for day in (1, 7, 15, 22, 28):
        slow = sip.simulate(nav, 1000, start, day)["xirr_pct"]
        assert fast[day - 1] * 100 == pytest.approx(slow, abs=1e-6)


def test_analyze_labels_and_windows():
    result = sip_days.analyze(_series())
    assert set(result["windows"]) == {"3y", "5y", "10y"}
    assert 1 <= result["best_day"] <= 28
    assert result["best_day"] == result["windows"]["10y"]["best"]
    assert result["edge"] in ("consistent", "no_edge", "negligible")
    assert result["spread"] >= 0


def test_short_history_is_labelled_short():
    result = sip_days.analyze(_series(years=4))
    assert list(result["windows"]) == ["3y"]
    assert result["edge"] in ("short", "negligible")


def test_tiny_gap_is_negligible_even_when_days_agree():
    w = {"3y": {"best": 28, "spread": 0.04}, "5y": {"best": 28, "spread": 0.03}, "10y": {"best": 28, "spread": 0.03}}
    assert sip_days.label(w) == "negligible"
    w = {k: {**v, "spread": 0.3} for k, v in w.items()}
    assert sip_days.label(w) == "consistent"


def test_too_little_history_returns_none():
    assert sip_days.analyze(_series(years=2)) is None


def test_near_wraps_month_end():
    assert sip_days._near(28, 1)
    assert sip_days._near(10, 13)
    assert not sip_days._near(5, 20)


def test_consistent_when_every_window_agrees(monkeypatch):
    # Force the same best day in every window.
    def fake(nav, start):
        x = np.full(28, 0.10)
        x[9] = 0.11
        return x

    monkeypatch.setattr(sip_days, "day_xirrs", fake)
    result = sip_days.analyze(_series())
    assert result["edge"] == "consistent" and result["best_day"] == 10


def test_inactive_scheme_is_skipped():
    old = _series().loc[:"2025-01-01"]
    entry = sip_days._record(old, pd.Timestamp("2026-10-01").date())
    assert entry["status"] == "inactive" and "best_day" not in entry


def test_annotate_adds_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(sip_days, "_root", lambda: tmp_path)
    sip_days._memory.clear()
    (tmp_path / "india.json").write_text(json.dumps({
        "120503": {"best_day": 3, "edge": "no_edge", "spread": 0.2},
        "NIFTYBEES": {"best_day": 12, "edge": "consistent", "spread": 0.4},
    }), encoding="utf-8")
    rows = [
        {"market": "india", "type": "mf", "symbol": "120503"},
        {"market": "india", "type": "etf", "symbol": "NIFTYBEES"},
        {"market": "india", "type": "stock", "symbol": "NIFTYBEES"},
    ]
    sip_days.annotate(rows, "india")
    assert rows[0]["sip_day"] == 3 and rows[0]["sip_edge"] == "no_edge"
    assert rows[1]["sip_edge"] == "consistent"
    assert "sip_day" not in rows[2]
    sip_days._memory.clear()


def test_clean_drops_split_glitch_but_keeps_crash():
    nav = _series(years=2)
    bad = nav.copy()
    bad.iloc[100:102] = bad.iloc[100:102] / 10  # Yahoo split glitch
    bad.iloc[300] = bad.iloc[299] * 0.88  # a genuine 12% fall
    cleaned = sip_days.clean(bad)
    assert len(cleaned) == len(bad) - 2
    assert bad.index[300] in cleaned.index
