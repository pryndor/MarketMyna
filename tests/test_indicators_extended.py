"""Tests for the oscillators, channels, candlestick patterns, divergences and
the scans built on them (offline, synthetic bars)."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.trading import indicators as ind
from src.trading.scanner import SCANS, evaluate


def _bars(close, spread=0.5, volume=1000.0):
    close = np.asarray(close, dtype=float)
    idx = pd.date_range(end=datetime(2026, 9, 25), periods=len(close), freq="B")
    return pd.DataFrame({"open": close - 0.1, "high": close + spread, "low": close - spread, "close": close,
                         "volume": np.full(len(close), volume)}, index=idx)


def _trend(n=120, start=100.0, step=0.5):
    return _bars(start + np.arange(n) * step)


def _set(df, i, **values):
    df = df.copy()
    for k, v in values.items():
        df.iloc[i, df.columns.get_loc(k)] = v
    return df


class TestOscillators:
    def test_uptrend_reads_strong(self):
        d = _trend()
        assert ind.macd(d["close"])["macd"].iloc[-1] > 0
        assert ind.stochastic(d)["k"].iloc[-1] > 80
        assert ind.williams_r(d).iloc[-1] > -20
        assert ind.mfi(d).iloc[-1] == pytest.approx(100.0)
        assert ind.cci(d).iloc[-1] > 0
        a = ind.adx(d).iloc[-1]
        assert a["adx"] > 25 and a["plus_di"] > a["minus_di"]
        assert ind.aroon(d)["up"].iloc[-1] == pytest.approx(100.0)

    def test_downtrend_reads_weak(self):
        d = _trend(start=200, step=-0.5)
        assert ind.stochastic(d)["k"].iloc[-1] < 20
        assert ind.mfi(d).iloc[-1] < 20
        a = ind.adx(d).iloc[-1]
        assert a["minus_di"] > a["plus_di"]

    def test_bounded(self):
        d = _bars(100 + np.sin(np.arange(200) / 3) * 5)
        for s in (ind.stochastic(d)["k"], ind.mfi(d)):
            s = s.dropna()
            assert ((s >= 0) & (s <= 100)).all()
        w = ind.williams_r(d).dropna()
        assert ((w >= -100) & (w <= 0)).all()


class TestChannels:
    def test_bollinger_contains_mid(self):
        d = _bars(100 + np.sin(np.arange(100)) * 3)
        bb = ind.bollinger(d["close"]).dropna()
        assert (bb["upper"] >= bb["mid"]).all() and (bb["lower"] <= bb["mid"]).all()
        assert ((bb["pct_b"] > -1) & (bb["pct_b"] < 2)).all()

    def test_donchian_excludes_current_bar(self):
        d = _trend(40)
        dc = ind.donchian(d, 20)
        assert dc["upper"].iloc[-1] == pytest.approx(d["high"].iloc[-21:-1].max())

    def test_squeeze_on_quiet_range(self):
        quiet = _bars(np.r_[100 + np.sin(np.arange(60)) * 5, np.full(30, 100.0) + np.sin(np.arange(30)) * 0.05],
                      spread=2.0)
        assert bool(ind.squeeze(quiet).iloc[-1])

    def test_ichimoku_cloud_below_uptrend(self):
        d = _trend(150)
        ich = ind.ichimoku(d)
        assert d["close"].iloc[-1] > max(ich["span_a"].iloc[-1], ich["span_b"].iloc[-1])


class TestCandles:
    def test_bullish_engulfing_after_decline(self):
        d = _trend(20, start=120, step=-1.0)
        d = _set(d, -2, open=102.0, close=100.5, high=102.2, low=100.3)
        d = _set(d, -1, open=100.2, close=103.0, high=103.2, low=100.0)
        assert "bullish_engulfing" in ind.candle_patterns(d)

    def test_engulfing_needs_prior_trend(self):
        d = _trend(20, start=80, step=1.0)
        d = _set(d, -2, open=100.0, close=98.5, high=100.2, low=98.3)
        d = _set(d, -1, open=98.2, close=101.0, high=101.2, low=98.0)
        assert "bullish_engulfing" not in ind.candle_patterns(d)

    def test_hammer_and_doji(self):
        d = _trend(20, start=120, step=-1.0)
        d = _set(d, -1, open=100.0, close=100.5, high=100.6, low=98.0)
        assert "hammer" in ind.candle_patterns(d)
        d = _set(d, -1, open=100.0, close=100.02, high=101.0, low=99.0)
        assert "doji" in ind.candle_patterns(d)

    def test_morning_star(self):
        d = _trend(20, start=120, step=-1.0)
        d = _set(d, -3, open=104.0, close=100.0, high=104.2, low=99.8)
        d = _set(d, -2, open=99.5, close=99.6, high=99.9, low=99.2)
        d = _set(d, -1, open=99.8, close=103.0, high=103.2, low=99.7)
        assert "morning_star" in ind.candle_patterns(d)

    def test_short_frame(self):
        assert ind.candle_patterns(_trend(5)) == []


class TestDivergence:
    def _v(self, second_low):
        # two dips; the second dip is deeper in price
        price = np.r_[np.linspace(110, 100, 10), np.linspace(100, 108, 8), np.linspace(108, second_low, 8),
                      np.linspace(second_low, second_low + 3, 5)]
        return _bars(price, spread=0.2)

    def test_bullish(self):
        d = self._v(98)
        osc = pd.Series(np.nan, index=d.index)
        lows = d["low"].to_numpy()
        # oscillator mirrors price but with a higher second low
        osc[:] = np.r_[np.linspace(50, 20, 10), np.linspace(20, 45, 8), np.linspace(45, 30, 8), np.linspace(30, 40, 5)]
        assert lows[25] < lows[9]
        assert ind.divergence(d, osc) == "bullish"

    def test_none_when_confirmed(self):
        d = self._v(98)
        osc = pd.Series(np.r_[np.linspace(50, 20, 10), np.linspace(20, 45, 8), np.linspace(45, 10, 8),
                              np.linspace(10, 20, 5)], index=d.index)
        assert ind.divergence(d, osc) is None


class TestExtendedScans:
    def test_all_scans_run(self):
        d = _bars(100 + np.sin(np.arange(260) / 7) * 8 + np.arange(260) * 0.05)
        metrics, hits = evaluate(d, None, list(SCANS), {})
        assert metrics and set(hits) <= set(SCANS)

    def test_upper_band_break_and_strong_trend(self):
        d = _trend(120)
        d = _set(d, -1, close=d["close"].iloc[-2] + 6, high=d["close"].iloc[-2] + 6.5)
        _, hits = evaluate(d, None, ["bb_upper_break", "adx_strong_up", "ichimoku_above_cloud", "stoch_overbought"], {})
        assert set(hits) == {"bb_upper_break", "adx_strong_up", "ichimoku_above_cloud", "stoch_overbought"}

    def test_macd_cross_up(self):
        d = _bars(np.r_[np.linspace(150, 100, 60), np.linspace(100, 101, 3), [104.0]])
        _, hits = evaluate(d, None, ["macd_cross_up", "macd_cross_down"], {})
        macd = ind.macd(d["close"])
        crossed = macd["macd"].iloc[-1] > macd["signal"].iloc[-1] and macd["macd"].iloc[-2] <= macd["signal"].iloc[-2]
        assert ("macd_cross_up" in hits) == crossed and "macd_cross_down" not in hits

    def test_candle_scan(self):
        d = _trend(60, start=160, step=-1.0)
        d = _set(d, -2, open=102.0, close=100.5, high=102.2, low=100.3)
        d = _set(d, -1, open=100.2, close=103.0, high=103.2, low=100.0)
        _, hits = evaluate(d, None, ["bullish_engulfing", "bearish_engulfing"], {})
        assert set(hits) == {"bullish_engulfing"}
