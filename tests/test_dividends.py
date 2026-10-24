"""Tests for dividend history (offline)."""

import pandas as pd
import pytest

from src.services import dividends as dv


def _series():
    dates, amts = [], []
    for y, amt in zip(range(2017, 2027), [1.0, 1.1, 1.2, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 0.9]):
        for q in (3, 6, 9, 12):
            if y == 2026 and q > 6:
                continue
            dates.append(pd.Timestamp(y, q, 15, tz="America/New_York"))
            amts.append(amt / 4 if y < 2026 else amt / 2)
    return pd.Series(amts, index=pd.DatetimeIndex(dates))


def test_build_history():
    fake = lambda s: {"dividends": _series(), "info": {"currentPrice": 50, "currency": "USD", "dividendRate": 1.8,
                                                         "payoutRatio": 0.45}}
    out = dv.build("X", fetch=fake, today=pd.Timestamp("2026-07-01"))
    assert out["pays"] and out["frequency"] == "Quarterly"
    # TTM: Sep+Dec 2025 (0.425 each) + Mar+Jun 2026 (0.45 each)
    assert out["ttm"] == pytest.approx(0.425 * 2 + 0.45 * 2)
    assert out["ttm_yield"] == pytest.approx(out["ttm"] / 50 * 100)
    assert out["growth_5y"] == pytest.approx(((1.7 / 1.2) ** 0.2 - 1) * 100)
    assert out["years_without_cut"] == 8  # 2018..2025, 2020 flat counts as no cut
    assert out["years"][-1] == {"year": 2026, "total": pytest.approx(0.9), "partial": True}
    assert out["payout_ratio"] == pytest.approx(45)
    assert out["payments"][0]["date"] == "2026-06-15"


def test_no_dividends():
    assert dv.build("X", fetch=lambda s: {"dividends": pd.Series(dtype=float), "info": {}})["pays"] is False


def test_gap_years_break_the_streak():
    idx = pd.DatetimeIndex([pd.Timestamp(y, 6, 1) for y in (2015, 2016, 2019, 2020, 2021)])
    s = pd.Series([1.0, 1.0, 1.0, 1.1, 1.2], index=idx)
    out = dv.build("X", fetch=lambda _: {"dividends": s, "info": {}}, today=pd.Timestamp("2022-03-01"))
    assert out["years_without_cut"] == 2  # 2020, 2021; 2017-2018 paid nothing
