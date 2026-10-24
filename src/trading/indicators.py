"""Trader indicators on OHLCV frames (lower-case columns). Pure pandas, one
implementation shared by the chart, the alert engine, the scanner and tests.

Formulas for the oscillators, channels, Ichimoku, candlestick patterns and
divergences follow the OpenBB technical extension (Apache 2.0,
https://github.com/OpenBB-finance/OpenBB), reimplemented here without pandas-ta."""

from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def session_key(index: pd.Index) -> pd.Index:
    """Trading day of each bar, in the bars' own (exchange) timezone."""
    return pd.Index(pd.DatetimeIndex(index).date)


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume-weighted average price, restarting every session."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    volume = df["volume"].fillna(0)
    day = session_key(df.index)
    pv = (typical * volume).groupby(day).cumsum()
    vol = volume.groupby(day).cumsum()
    return (pv / vol.where(vol > 0)).set_axis(df.index)


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """(line, direction): direction 1 = uptrend (line below price), -1 = down."""
    mid = (df["high"] + df["low"]) / 2
    band = multiplier * atr(df, period)
    upper, lower = (mid + band).to_numpy(), (mid - band).to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    line = [float("nan")] * n
    direction = [0] * n
    final_upper, final_lower = upper.copy(), lower.copy()
    for i in range(n):
        if i == 0 or pd.isna(upper[i]) or pd.isna(final_upper[i - 1]):
            direction[i] = 1
            continue
        final_upper[i] = upper[i] if upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1] else final_upper[i - 1]
        final_lower[i] = lower[i] if lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1] else final_lower[i - 1]
        if direction[i - 1] == -1 and close[i] > final_upper[i - 1]:
            direction[i] = 1
        elif direction[i - 1] == 1 and close[i] < final_lower[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1] or 1
        line[i] = final_lower[i] if direction[i] == 1 else final_upper[i]
    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


def pivots(high: float, low: float, close: float) -> dict[str, float]:
    """Classic floor pivots from the previous session's high / low / close."""
    p = (high + low + close) / 3
    return {
        "R3": high + 2 * (p - low),
        "R2": p + (high - low),
        "R1": 2 * p - low,
        "P": p,
        "S1": 2 * p - high,
        "S2": p - (high - low),
        "S3": low - 2 * (high - p),
    }


def opening_range(df: pd.DataFrame, minutes: int = 15) -> dict[str, float] | None:
    """High / low of the first `minutes` of the latest session (intraday bars)."""
    if df.empty:
        return None
    index = pd.DatetimeIndex(df.index)
    last_day = index[-1].date()
    today = df[index.date == last_day]
    start = pd.DatetimeIndex(today.index)[0]
    first = today[pd.DatetimeIndex(today.index) < start + pd.Timedelta(minutes=minutes)]
    if first.empty:
        return None
    return {"high": float(first["high"].max()), "low": float(first["low"].min())}


# ------------------------------------------------------------------ trend / channels


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """Columns: macd, signal, hist."""
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return pd.DataFrame({"macd": line, "signal": sig, "hist": line - sig})


def bollinger(close: pd.Series, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    """Columns: mid, upper, lower, width (band width as % of mid), pct_b (0 = lower, 1 = upper)."""
    mid = sma(close, period)
    dev = close.rolling(period, min_periods=period).std(ddof=0)
    upper, lower = mid + std * dev, mid - std * dev
    span = (upper - lower).where(upper != lower)
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower,
                         "width": (upper - lower) / mid * 100, "pct_b": (close - lower) / span})


def keltner(df: pd.DataFrame, period: int = 20, atr_period: int = 10, multiplier: float = 2.0) -> pd.DataFrame:
    """Columns: mid (EMA), upper, lower."""
    mid = ema(df["close"], period)
    band = multiplier * atr(df, atr_period)
    return pd.DataFrame({"mid": mid, "upper": mid + band, "lower": mid - band})


def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Highest high / lowest low of the previous `period` bars (excludes the current bar)."""
    upper = df["high"].shift(1).rolling(period, min_periods=period).max()
    lower = df["low"].shift(1).rolling(period, min_periods=period).min()
    return pd.DataFrame({"upper": upper, "lower": lower, "mid": (upper + lower) / 2})


def squeeze(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """True while the Bollinger band sits inside the Keltner channel (TTM squeeze)."""
    bb, kc = bollinger(df["close"], period), keltner(df, period, period, 1.5)
    return (bb["upper"] < kc["upper"]) & (bb["lower"] > kc["lower"])


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Wilder's ADX. Columns: adx, plus_di, minus_di."""
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    rng = atr(df, period)
    smooth = lambda s: s.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()  # noqa: E731
    plus_di = 100 * smooth(plus_dm) / rng
    minus_di = 100 * smooth(minus_dm) / rng
    total = (plus_di + minus_di).where(lambda x: x != 0)
    dx = 100 * (plus_di - minus_di).abs() / total
    return pd.DataFrame({"adx": smooth(dx), "plus_di": plus_di, "minus_di": minus_di})


def aroon(df: pd.DataFrame, period: int = 25) -> pd.DataFrame:
    """Columns: up, down, osc (up - down). 100 = extreme set this bar."""
    window = period + 1
    since_high = df["high"].rolling(window, min_periods=window).apply(lambda x: period - x.argmax(), raw=True)
    since_low = df["low"].rolling(window, min_periods=window).apply(lambda x: period - x.argmin(), raw=True)
    up = 100 * (period - since_high) / period
    down = 100 * (period - since_low) / period
    return pd.DataFrame({"up": up, "down": down, "osc": up - down})


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou: int = 52) -> pd.DataFrame:
    """Columns: tenkan, kijun, span_a, span_b. Spans are already shifted
    forward, so row i holds the cloud drawn under bar i."""
    mid = lambda n: (df["high"].rolling(n, min_periods=n).max() + df["low"].rolling(n, min_periods=n).min()) / 2  # noqa: E731
    t, k = mid(tenkan), mid(kijun)
    return pd.DataFrame({"tenkan": t, "kijun": k, "span_a": ((t + k) / 2).shift(kijun),
                         "span_b": mid(senkou).shift(kijun)})


# ------------------------------------------------------------------ oscillators


def stochastic(df: pd.DataFrame, period: int = 14, smooth_d: int = 3) -> pd.DataFrame:
    """Columns: k, d (0-100)."""
    hi = df["high"].rolling(period, min_periods=period).max()
    lo = df["low"].rolling(period, min_periods=period).min()
    k = 100 * (df["close"] - lo) / (hi - lo).where(hi != lo)
    return pd.DataFrame({"k": k, "d": k.rolling(smooth_d, min_periods=smooth_d).mean()})


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """-100 (at the low) .. 0 (at the high)."""
    hi = df["high"].rolling(period, min_periods=period).max()
    lo = df["low"].rolling(period, min_periods=period).min()
    return -100 * (hi - df["close"]) / (hi - lo).where(hi != lo)


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    mean = typical.rolling(period, min_periods=period).mean()
    mad = typical.rolling(period, min_periods=period).apply(lambda x: abs(x - x.mean()).mean(), raw=True)
    return (typical - mean) / (0.015 * mad.where(mad != 0))


def mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Money flow index (volume-weighted RSI), 0-100."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    flow = typical * df["volume"].fillna(0)
    move = typical.diff()
    pos = flow.where(move > 0, 0.0).rolling(period, min_periods=period).sum()
    neg = flow.where(move < 0, 0.0).rolling(period, min_periods=period).sum()
    out = 100 - 100 / (1 + pos / neg.where(neg != 0))
    return out.where(neg != 0, 100.0).where(pos.notna())


# ------------------------------------------------------------------ patterns


CANDLE_PATTERNS: dict[str, tuple[str, str]] = {
    "bullish_engulfing": ("Bullish engulfing", "bullish"),
    "bearish_engulfing": ("Bearish engulfing", "bearish"),
    "hammer": ("Hammer", "bullish"),
    "shooting_star": ("Shooting star", "bearish"),
    "morning_star": ("Morning star", "bullish"),
    "evening_star": ("Evening star", "bearish"),
    "doji": ("Doji", "neutral"),
}


def candle_patterns(df: pd.DataFrame, trend_bars: int = 5) -> list[str]:
    """Pattern ids (keys of CANDLE_PATTERNS) completed on the last bar.
    Reversal patterns need the preceding `trend_bars` move to point the other way."""
    d = df.dropna(subset=["open", "high", "low", "close"])
    if len(d) < trend_bars + 4:
        return []
    o, h, l, c = (d[k].astype(float).to_numpy() for k in ("open", "high", "low", "close"))
    body = abs(c - o)
    rng = h - l
    avg_body = float(pd.Series(body[-11:-1]).mean()) or 1e-9
    i = len(d) - 1
    prior = c[i - 1] - c[i - 1 - trend_bars]  # trend into the pattern
    down_before, up_before = prior < 0, prior > 0
    upper = h[i] - max(o[i], c[i])
    lower = min(o[i], c[i]) - l[i]
    found: list[str] = []

    if rng[i] > 0 and body[i] <= 0.1 * rng[i]:
        found.append("doji")
    if body[i] > 0 and lower >= 2 * body[i] and upper <= body[i] and down_before:
        found.append("hammer")
    if body[i] > 0 and upper >= 2 * body[i] and lower <= body[i] and up_before:
        found.append("shooting_star")
    if c[i - 1] < o[i - 1] and c[i] > o[i] and o[i] <= c[i - 1] and c[i] >= o[i - 1] and body[i] > body[i - 1] and down_before:
        found.append("bullish_engulfing")
    if c[i - 1] > o[i - 1] and c[i] < o[i] and o[i] >= c[i - 1] and c[i] <= o[i - 1] and body[i] > body[i - 1] and up_before:
        found.append("bearish_engulfing")
    first, star = i - 2, i - 1
    if body[first] >= avg_body and body[star] <= 0.5 * body[first]:
        if c[first] < o[first] and c[i] > o[i] and c[i] > (o[first] + c[first]) / 2 and c[first - 1] - c[first - 1 - trend_bars] < 0:
            found.append("morning_star")
        if c[first] > o[first] and c[i] < o[i] and c[i] < (o[first] + c[first]) / 2 and c[first - 1] - c[first - 1 - trend_bars] > 0:
            found.append("evening_star")
    return found


def _swings(values, k: int, lows: bool) -> list[int]:
    """Indexes of confirmed swing lows (or highs) with k bars each side. Strict
    against the left side, so a flat bottom counts once (at its first bar)."""
    out = []
    for i in range(k, len(values) - k):
        v, left, right = values[i], values[i - k:i], values[i + 1:i + k + 1]
        if v != v:  # NaN
            continue
        if lows and all(v < x for x in left) and all(v <= x for x in right):
            out.append(i)
        if not lows and all(v > x for x in left) and all(v >= x for x in right):
            out.append(i)
    return out


def divergence(df: pd.DataFrame, oscillator: pd.Series, lookback: int = 60, k: int = 3,
               recent: int = 8) -> str | None:
    """'bullish' when price makes a lower swing low while the oscillator makes a
    higher low, 'bearish' for the mirror on swing highs. The latest swing must be
    within `recent` bars of the end so the signal is actionable."""
    d = df.tail(lookback)
    osc = oscillator.reindex(d.index).to_numpy(dtype=float)
    last = len(d) - 1
    for lows, kind in ((True, "bullish"), (False, "bearish")):
        price = d["low" if lows else "high"].to_numpy(dtype=float)
        swings = [i for i in _swings(price, k, lows) if osc[i] == osc[i]]
        if len(swings) < 2:
            continue
        a, b = swings[-2], swings[-1]
        if last - b > recent or b - a < k:
            continue
        if lows and price[b] < price[a] and osc[b] > osc[a]:
            return kind
        if not lows and price[b] > price[a] and osc[b] < osc[a]:
            return kind
    return None
