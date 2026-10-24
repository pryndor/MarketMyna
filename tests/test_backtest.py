"""Tests for the backtest engine: fills, stops, costs, no look-ahead (offline)."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from marketmyna.trading.backtest import STRATEGIES, Settings, optimize, run, signals


def _bars(closes, gap_open=None):
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range(datetime(2024, 1, 1), periods=len(closes), freq="B")
    opens = np.r_[closes[0], closes[:-1]] if gap_open is None else gap_open
    return pd.DataFrame({"open": opens, "high": np.maximum(opens, closes) + 0.5,
                         "low": np.minimum(opens, closes) - 0.5, "close": closes}, index=idx)


def _updown(n=120):
    return _bars(np.r_[np.linspace(100, 160, n // 2), np.linspace(160, 100, n // 2)])


def test_fills_at_next_open_no_costs():
    df = _updown()
    r = run(df, Settings(strategy="sma_trend", params={"period": 10}, cost_pct=0, slippage_pct=0))
    t = r["trades"][0]
    sig_in, _ = signals(df, "sma_trend", {"period": 10})
    first = int(np.argmax(sig_in.to_numpy()))
    assert t["entry"] == pytest.approx(df["open"].iloc[first + 1])  # next bar's open, not the signal close
    assert r["metrics"]["total_return"] > 0


def _wavy(n=200):
    x = np.arange(n)
    return _bars(100 + 15 * np.sin(x / 8) + x * 0.1)


def test_no_lookahead():
    df = _wavy()
    s = Settings(strategy="ema_cross", params={"fast": 5, "slow": 12})
    base = run(df, s)["trades"]
    changed = df.copy()
    changed.iloc[150:, :] *= 3  # rewrite the future
    after = run(changed, s)["trades"]
    early = [t for t in base if pd.Timestamp(t["exit_time"]) < df.index[149]]
    assert early and early == [t for t in after if pd.Timestamp(t["exit_time"]) < df.index[149]]


def test_costs_reduce_returns():
    df = _wavy()
    cheap = run(df, Settings(strategy="ema_cross", cost_pct=0, slippage_pct=0))["metrics"]["total_return"]
    dear = run(df, Settings(strategy="ema_cross", cost_pct=0.5, slippage_pct=0.2))["metrics"]["total_return"]
    assert dear < cheap


def test_percent_stop_and_gap_fill():
    closes = np.r_[np.linspace(100, 130, 40), [80.0], np.full(10, 80.0)]
    opens = np.r_[closes[0], closes[:-1]]
    opens[40] = 80.0  # gap down through the stop
    df = _bars(closes, gap_open=opens)
    r = run(df, Settings(strategy="sma_trend", params={"period": 5}, stop_type="percent", stop_value=5,
                         cost_pct=0, slippage_pct=0))
    stopped = [t for t in r["trades"] if t["reason"] == "stop"]
    assert stopped and stopped[0]["exit"] == pytest.approx(80.0)  # filled at the gap open, not the stop


def test_target_r_and_risk_sizing():
    df = _bars(np.linspace(100, 200, 80))
    r = run(df, Settings(strategy="sma_trend", params={"period": 5}, stop_type="percent", stop_value=2,
                         target_r=2, sizing="risk", risk_pct=1, cost_pct=0, slippage_pct=0))
    t = r["trades"][0]
    assert t["reason"] == "target" and t["r"] == pytest.approx(2, rel=0.05)
    # 1% of 100k at risk over a 2% stop -> about half the account.
    assert t["quantity"] * t["entry"] == pytest.approx(50000, rel=0.02)


def test_shorts_profit_in_downtrend():
    df = _bars(np.r_[np.linspace(100, 120, 30), np.linspace(120, 60, 90)])
    r = run(df, Settings(strategy="ema_cross", params={"fast": 5, "slow": 12}, allow_short=True, cost_pct=0, slippage_pct=0))
    shorts = [t for t in r["trades"] if t["side"] == "short"]
    assert shorts and sum(t["pnl"] for t in shorts) > 0


def test_every_strategy_runs_and_optimize():
    df = _updown(300).assign(volume=1000.0)  # the VWMA strategies need volume
    for sid in STRATEGIES:
        m = run(df, Settings(strategy=sid))["metrics"]
        assert m["bars"] == 300 and m["max_drawdown"] <= 0
    opt = optimize(df, Settings(strategy="breakout"), "1d")
    assert opt["best"].keys() == STRATEGIES["breakout"]["params"].keys()
    assert len(opt["grid"]) == 9 and opt["test"]["bars"] == 90
