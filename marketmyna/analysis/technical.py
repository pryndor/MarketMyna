"""Technical analysis indicators and signals."""

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd


class Signal(Enum):
    """Trading signal types."""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    NEUTRAL = "neutral"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class IndicatorResult:
    """Result of a technical indicator calculation."""
    name: str
    value: float
    signal: Signal
    description: str = ""


class TechnicalAnalyzer:
    """Technical analysis calculator."""

    def __init__(self, df: pd.DataFrame):
        """
        Initialize with OHLCV dataframe.

        Args:
            df: DataFrame with columns: open, high, low, close, volume
        """
        self.df = df.copy()
        self._ensure_columns()

    def _ensure_columns(self):
        """Ensure required columns exist with proper names."""
        col_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
        for old, new in col_map.items():
            if old in self.df.columns and new not in self.df.columns:
                self.df[new] = self.df[old]

    # Moving Averages
    def sma(self, period: int = 20, column: str = "close") -> pd.Series:
        """Simple Moving Average."""
        return self.df[column].rolling(window=period).mean()

    def ema(self, period: int = 20, column: str = "close") -> pd.Series:
        """Exponential Moving Average."""
        return self.df[column].ewm(span=period, adjust=False).mean()


    # Momentum Indicators
    def rsi(self, period: int = 14) -> pd.Series:
        """Relative Strength Index, Wilder smoothing - the same formula as
        broker charts and the rest of the app (marketmyna/trading/indicators.py)."""
        from ..trading.indicators import rsi

        return rsi(self.df["close"].astype(float), period)

    def macd(
        self, fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        MACD - Moving Average Convergence Divergence.

        Returns: (macd_line, signal_line, histogram)
        """
        ema_fast = self.ema(fast)
        ema_slow = self.ema(slow)
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    def stochastic(
        self, k_period: int = 14, d_period: int = 3
    ) -> tuple[pd.Series, pd.Series]:
        """
        Stochastic Oscillator.

        Returns: (k_line, d_line)
        """
        low_min = self.df["low"].rolling(window=k_period).min()
        high_max = self.df["high"].rolling(window=k_period).max()

        k = 100 * (self.df["close"] - low_min) / (high_max - low_min)
        d = k.rolling(window=d_period).mean()

        return k, d

    def williams_r(self, period: int = 14) -> pd.Series:
        """Williams %R."""
        high_max = self.df["high"].rolling(window=period).max()
        low_min = self.df["low"].rolling(window=period).min()

        return -100 * (high_max - self.df["close"]) / (high_max - low_min)

    def cci(self, period: int = 20) -> pd.Series:
        """Commodity Channel Index."""
        typical_price = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
        sma_tp = typical_price.rolling(window=period).mean()
        mean_dev = typical_price.rolling(window=period).apply(
            lambda x: np.abs(x - x.mean()).mean()
        )

        return (typical_price - sma_tp) / (0.015 * mean_dev)


    # Volatility Indicators
    def bollinger_bands(
        self, period: int = 20, std_dev: float = 2.0
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        Bollinger Bands.

        Returns: (upper_band, middle_band, lower_band)
        """
        middle = self.sma(period)
        std = self.df["close"].rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)

        return upper, middle, lower

    def atr(self, period: int = 14) -> pd.Series:
        """Average True Range."""
        high = self.df["high"]
        low = self.df["low"]
        close = self.df["close"]

        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()


    # Volume Indicators
    def obv(self) -> pd.Series:
        """On-Balance Volume."""
        obv = [0]
        for i in range(1, len(self.df)):
            if self.df["close"].iloc[i] > self.df["close"].iloc[i - 1]:
                obv.append(obv[-1] + self.df["volume"].iloc[i])
            elif self.df["close"].iloc[i] < self.df["close"].iloc[i - 1]:
                obv.append(obv[-1] - self.df["volume"].iloc[i])
            else:
                obv.append(obv[-1])
        return pd.Series(obv, index=self.df.index)

    def vwap(self) -> pd.Series:
        """Volume Weighted Average Price."""
        typical_price = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
        return (typical_price * self.df["volume"]).cumsum() / self.df["volume"].cumsum()

    def mfi(self, period: int = 14) -> pd.Series:
        """Money Flow Index."""
        typical_price = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
        money_flow = typical_price * self.df["volume"]

        positive_flow = money_flow.where(typical_price > typical_price.shift(), 0)
        negative_flow = money_flow.where(typical_price < typical_price.shift(), 0)

        positive_mf = positive_flow.rolling(window=period).sum()
        negative_mf = negative_flow.rolling(window=period).sum()

        mfi = 100 - (100 / (1 + positive_mf / negative_mf))
        return mfi

    # Trend Indicators
    def adx(self, period: int = 14) -> pd.Series:
        """Average Directional Index."""
        high = self.df["high"]
        low = self.df["low"]

        plus_dm = high.diff()
        minus_dm = low.diff().abs()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

        atr_val = self.atr(period)

        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr_val)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr_val)

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()

        return adx

    def supertrend(
        self, period: int = 10, multiplier: float = 3.0
    ) -> tuple[pd.Series, pd.Series]:
        """
        Supertrend indicator.

        Returns: (supertrend, direction)  direction: 1=uptrend, -1=downtrend
        """
        atr_val = self.atr(period)
        hl2 = (self.df["high"] + self.df["low"]) / 2

        upper_band = hl2 + (multiplier * atr_val)
        lower_band = hl2 - (multiplier * atr_val)

        supertrend = pd.Series(index=self.df.index, dtype=float)
        direction = pd.Series(index=self.df.index, dtype=float)

        for i in range(period, len(self.df)):
            if self.df["close"].iloc[i] > upper_band.iloc[i - 1]:
                direction.iloc[i] = 1
            elif self.df["close"].iloc[i] < lower_band.iloc[i - 1]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = direction.iloc[i - 1]

            if direction.iloc[i] == 1:
                supertrend.iloc[i] = lower_band.iloc[i]
            else:
                supertrend.iloc[i] = upper_band.iloc[i]

        return supertrend, direction

    # Analysis Summary
    def get_signals(self) -> dict[str, IndicatorResult]:
        """Get trading signals from multiple indicators."""
        signals = {}
        close = self.df["close"].iloc[-1]

        # RSI Signal
        rsi_val = self.rsi().iloc[-1]
        if rsi_val < 30:
            rsi_signal = Signal.BUY
        elif rsi_val > 70:
            rsi_signal = Signal.SELL
        else:
            rsi_signal = Signal.NEUTRAL
        signals["rsi"] = IndicatorResult("RSI", rsi_val, rsi_signal)

        # MACD Signal
        macd_line, signal_line, _ = self.macd()
        macd_val = macd_line.iloc[-1]
        if macd_line.iloc[-1] > signal_line.iloc[-1] and macd_line.iloc[-2] <= signal_line.iloc[-2]:
            macd_signal = Signal.BUY
        elif macd_line.iloc[-1] < signal_line.iloc[-1] and macd_line.iloc[-2] >= signal_line.iloc[-2]:
            macd_signal = Signal.SELL
        else:
            macd_signal = Signal.NEUTRAL
        signals["macd"] = IndicatorResult("MACD", macd_val, macd_signal)

        # Moving Average Signal
        sma20 = self.sma(20).iloc[-1]
        sma50 = self.sma(50).iloc[-1]
        if close > sma20 > sma50:
            ma_signal = Signal.BUY
        elif close < sma20 < sma50:
            ma_signal = Signal.SELL
        else:
            ma_signal = Signal.NEUTRAL
        signals["ma"] = IndicatorResult("Moving Averages", sma20, ma_signal)

        # Bollinger Bands Signal
        upper, middle, lower = self.bollinger_bands()
        bb_position = (close - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1])
        if bb_position < 0.2:
            bb_signal = Signal.BUY
        elif bb_position > 0.8:
            bb_signal = Signal.SELL
        else:
            bb_signal = Signal.NEUTRAL
        signals["bollinger"] = IndicatorResult("Bollinger Bands", bb_position * 100, bb_signal)

        # Stochastic Signal
        k, d = self.stochastic()
        stoch_val = k.iloc[-1]
        if stoch_val < 20:
            stoch_signal = Signal.BUY
        elif stoch_val > 80:
            stoch_signal = Signal.SELL
        else:
            stoch_signal = Signal.NEUTRAL
        signals["stochastic"] = IndicatorResult("Stochastic", stoch_val, stoch_signal)

        return signals

    def get_summary(self) -> dict:
        """Get overall analysis summary."""
        signals = self.get_signals()

        buy_count = sum(1 for s in signals.values() if s.signal in [Signal.BUY, Signal.STRONG_BUY])
        sell_count = sum(1 for s in signals.values() if s.signal in [Signal.SELL, Signal.STRONG_SELL])
        neutral_count = sum(1 for s in signals.values() if s.signal == Signal.NEUTRAL)

        if buy_count > sell_count + neutral_count:
            overall = Signal.BUY
        elif sell_count > buy_count + neutral_count:
            overall = Signal.SELL
        else:
            overall = Signal.NEUTRAL

        return {
            "overall_signal": overall,
            "buy_signals": buy_count,
            "sell_signals": sell_count,
            "neutral_signals": neutral_count,
            "indicators": {name: {"value": r.value, "signal": r.signal.value} for name, r in signals.items()},
        }
