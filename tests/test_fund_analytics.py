"""Tests for mutual fund rolling returns, risk and drawdowns (offline)."""

import numpy as np
import pandas as pd
import pytest

from marketmyna.services import fund_analytics as fa


def _series(values, start="2015-01-01", freq="D"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq=freq), dtype=float)


def _grow(yearly, years, start="2015-01-01", noise=0.0, seed=1):
    days = int(365.25 * years) + 1
    rng = np.random.default_rng(seed)
    t = np.arange(days) / 365.25
    return _series(100 * (1 + yearly) ** t * np.exp(rng.normal(0, noise, days).cumsum() if noise else 0), start)


def test_benchmark_for_categories():
    assert fa.benchmark_for("Large Cap Fund")[1] == "Nifty 100"
    assert fa.benchmark_for("Mid Cap Fund")[1] == "Nifty Midcap 150"
    assert fa.benchmark_for("Small Cap Fund")[1] == "Nifty Smallcap 250"
    assert fa.benchmark_for("Large & Mid Cap Fund")[1] == "Nifty 500"
    assert fa.benchmark_for("Flexi Cap Fund")[1] == "Nifty 500"
    assert fa.benchmark_for("Index Funds", "UTI Nifty Next 50 Index Fund")[1] == "Nifty Next 50"
    assert fa.benchmark_for("Index Funds", "HDFC Nifty 50 Index Fund")[1] == "Nifty 50"
    assert fa.benchmark_for("Index Funds", "Nifty Bank Index Fund") is None
    assert fa.benchmark_for("Liquid Fund") is None and fa.benchmark_for("Aggressive Hybrid Fund") is None


def test_clean_nav_fixes_face_value_change_and_spikes():
    s = _series([28.50, 28.55, 28.56, 2857.24, 2857.83, 2858.43])  # 100x face-value change
    out = fa.clean_nav(s)
    assert out.iloc[-1] == pytest.approx(2858.43)
    assert out.iloc[0] == pytest.approx(28.50 * 2857.24 / 28.56)
    assert np.abs(np.log(out / out.shift(1)).dropna()).max() < 0.01
    spike = _series([10.0, 10.1, 55.0, 10.2, 10.3])  # one bad print
    assert list(fa.clean_nav(spike)) == [10.0, 10.1, 10.2, 10.3]


def test_rolling_returns_against_benchmark():
    fund, bench = _grow(0.15, 8), _grow(0.10, 8)
    out = fa.rolling(fund, bench)
    by = {w["years"]: w for w in out["windows"]}
    assert set(by) == {1, 3, 5}
    assert by[3]["median"] == pytest.approx(15, abs=0.05) and by[3]["bench_median"] == pytest.approx(10, abs=0.05)
    assert by[3]["beat_pct"] == 100 and by[3]["negative_pct"] == 0 and by[3]["above_12_pct"] == 100
    assert out["chart_years"] == 3 and out["chart"][0]["bench"] is not None


def test_risk_beta_alpha_capture():
    rng = np.random.default_rng(7)
    b_ret = rng.normal(0.0004, 0.01, 900)
    idx = pd.bdate_range("2022-01-03", periods=900)
    bench = pd.Series(100 * np.cumprod(1 + b_ret), index=idx)
    fund = pd.Series(100 * np.cumprod(1 + 0.5 * b_ret), index=idx)  # half the market's moves
    out = fa.risk(fund, bench)
    assert out["beta"] == pytest.approx(0.5, abs=0.01)
    assert out["up_capture"] == pytest.approx(0.5, abs=0.01) and out["down_capture"] == pytest.approx(0.5, abs=0.01)
    assert out["correlation"] == pytest.approx(1, abs=1e-6)
    assert fa.risk(fund.iloc[:50], bench) is None  # too short


def test_drawdowns_episodes_and_recovery():
    values = [100] * 10 + list(np.linspace(100, 70, 31)) + list(np.linspace(70, 100, 61)) + [101, 102] * 20
    out = fa.drawdowns(_series(values, start="2020-01-01"))
    ep = out["episodes"][0]
    assert ep["depth"] == pytest.approx(-30, abs=0.01) and ep["recovered"] is not None
    assert ep["days_down"] == 30 and ep["days_to_recover"] == 61  # peak: day 10; low 70 on day 40, 100 again on day 101
    assert out["max"] == pytest.approx(-30, abs=0.01)
    assert [c["label"] for c in out["crashes"]] == ["2020 Covid crash"]


def test_dividend_yield_from_etf_and_total_return():
    index = _grow(0.10, 8, noise=0.004)
    etf = fa.total_return(index, 0.012)
    fetch = {"^NSEI": index, "NIFTYBEES.NS": etf}.get
    assert fa.dividend_yield("^NSEI", fetch) == pytest.approx(0.012, abs=0.0005)
    assert fa.dividend_yield("^CRSLDX", fetch) == pytest.approx(0.012, abs=0.0005)  # borrows Nifty 50's
    assert fa.dividend_yield("^NSEI", {"^NSEI": index}.get) is None
    tr = fa.total_return(_series([100.0] * 366), 0.02)
    assert tr.iloc[-1] == pytest.approx(102, abs=0.01)


def test_build_end_to_end_and_payout_flag():
    fund, index = _grow(0.14, 7, noise=0.005), _grow(0.10, 9, start="2013-01-01", noise=0.004, seed=2)
    etf = fa.total_return(index, 0.012)  # the ETF earns the index plus 1.2% of dividends a year
    row = {"symbol": "1", "name": "Test Flexi Cap Fund - Direct - IDCW", "sector": "Flexi Cap Fund", "option": "IDCW"}
    out = fa.build("1", fetch=lambda code: fund, bench_fetch={"^CRSLDX": index, "^NSEI": index, "NIFTYBEES.NS": etf}.get,
                   row=row, use_cache=False)
    assert out["status"] == "ok" and out["benchmark"]["name"] == "Nifty 500" and out["benchmark"]["available"]
    assert out["benchmark"]["dividend_yield"] == pytest.approx(1.2, abs=0.1)
    assert out["payout_option"] is True
    assert out["risk"]["beta"] is not None and out["drawdowns"]["episodes"]
    assert fa.build("2", fetch=lambda code: None, row=row, use_cache=False)["status"] == "no_history"
