"""Chart payload for the Trade page: bars plus indicator series, pivots and
opening range, all computed here (src/trading/indicators.py)."""

from __future__ import annotations

import math

import pandas as pd

from ..core.constants import TimeFrame
from . import indicators as ind

INTERVALS = ("1m", "5m", "15m", "30m", "1h", "1d", "1wk")
INTRADAY = {"1m", "5m", "15m", "30m", "1h"}
# Longest history Yahoo serves per bar size (and a sensible default).
MAX_PERIOD = {"1m": "5d", "5m": "1mo", "15m": "1mo", "30m": "1mo", "1h": "6mo"}
DEFAULT_PERIOD = {"1m": "1d", "5m": "5d", "15m": "5d", "30m": "1mo", "1h": "3mo", "1d": "1y", "1wk": "5y"}
PERIOD_ORDER = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"]
INDICATORS = ("vwap", "ema9", "ema21", "ema50", "ema200", "supertrend", "vwma", "knn_st")


def clamp_period(interval: str, period: str | None) -> str:
    period = period if period in PERIOD_ORDER else DEFAULT_PERIOD[interval]
    limit = MAX_PERIOD.get(interval)
    if limit and PERIOD_ORDER.index(period) > PERIOD_ORDER.index(limit):
        return limit
    return period


def _times(index: pd.Index) -> list[int]:
    """Bar times as exchange wall-clock seconds, so the chart's axis shows
    9:15 for an NSE open whatever the viewer's timezone."""
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return [int(t.value // 1_000_000_000) for t in idx]


def _series(times: list[int], values: pd.Series) -> list[dict]:
    return [
        {"time": t, "value": round(float(v), 6)}
        for t, v in zip(times, values.to_numpy())
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)
    for col in ("open", "high", "low"):
        if col not in df:
            df[col] = df["close"]
    if "volume" not in df:
        df["volume"] = 0.0
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.dropna(subset=["close"])


def _vwma_knn(df: pd.DataFrame, times: list[int], series: dict) -> list[dict]:
    """VWMA 13 / 19 lines; each crossover marked with its kNN vote (experimental:
    tested on 19 stocks it had no out-of-sample edge over the plain crossover):
    solid when the filter would take it."""
    from . import knn

    fast, slow = knn.vwma(df, 13), knn.vwma(df, 19)
    series["vwma13"] = _series(times, fast)
    series["vwma19"] = _series(times, slow)
    v = knn.crossover_vote(df, 13, 19, 23)
    out = []
    for t, c, vote in zip(times, v["cross"].to_numpy(), v["vote"].to_numpy()):
        if c == 0 or (isinstance(vote, float) and math.isnan(vote)):
            continue
        up = c > 0
        take = vote >= 2 if up else vote <= -2
        out.append({"time": t, "kind": ("buy" if up else "sell") + ("" if take else "_skip"),
                    "text": f"kNN {vote:+.0f}"})
    return out


def _knn_supertrend(df: pd.DataFrame, times: list[int], series: dict) -> tuple[list[dict], dict]:
    """Adaptive Supertrend legs and the filtered strategy's entries / exits
    (experimental, same rules as the backtest strategy knn_supertrend)."""
    from . import knn

    a = knn.analog_score(df)
    line, d = knn.adaptive_supertrend(df, a["agree"], 10, 2.0)
    series["knn_st_up"] = _series(times, line.where(d == 1))
    series["knn_st_down"] = _series(times, line.where(d == -1))
    state = (d == 1) & (a["score"] >= 0.15)
    entry = (state & ~state.shift(1, fill_value=False)).to_numpy()
    exit_ = ((d == -1) & (d.shift(1) == 1)).to_numpy()
    out = [{"time": t, "kind": "buy", "text": "kNN buy"} for t, e in zip(times, entry) if e]
    out += [{"time": t, "kind": "sell", "text": "exit"} for t, x in zip(times, exit_) if x]
    last = a.dropna().iloc[-1] if a["score"].notna().any() else None
    now = None if last is None else {"score": round(float(last["score"]), 3), "agree": round(float(last["agree"]), 3),
                                     "trend": "up" if d.iloc[-1] == 1 else "down"}
    return out, now


def build_chart(df: pd.DataFrame, interval: str, wanted: list[str]) -> dict:
    df = normalize(df)
    if df.empty:
        return {"bars": [], "series": {}, "markers": [], "knn": None, "pivots": None, "opening_range": None, "last": None}
    times = _times(df.index)
    bars = [
        {"time": t, "open": o, "high": h, "low": low, "close": c, "volume": v}
        for t, o, h, low, c, v in zip(times, *(df[k].round(6).tolist() for k in ("open", "high", "low", "close", "volume")))
    ]
    series: dict[str, list[dict]] = {}
    markers: list[dict] = []
    knn_now = None
    intraday = interval in INTRADAY
    for name in wanted:
        if name == "vwap" and intraday and df["volume"].sum() > 0:
            series["vwap"] = _series(times, ind.vwap(df))
        elif name.startswith("ema") and name[3:].isdigit():
            series[name] = _series(times, ind.ema(df["close"], int(name[3:])).where(
                pd.Series(range(len(df)), index=df.index) >= int(name[3:]) - 1))
        elif name == "supertrend" and len(df) > 12:
            line, direction = ind.supertrend(df)
            series["supertrend_up"] = _series(times, line.where(direction == 1))
            series["supertrend_down"] = _series(times, line.where(direction == -1))
        elif name == "vwma" and df["volume"].sum() > 0 and len(df) > 40:
            markers += _vwma_knn(df, times, series)
        elif name == "knn_st" and len(df) > 120:
            extra, knn_now = _knn_supertrend(df, times, series)
            markers += extra

    # Pivots from the previous complete session.
    pivots = None
    if intraday:
        days = df.groupby(ind.session_key(df.index))
        sessions = list(days)
        if len(sessions) >= 2:
            prev = sessions[-2][1]
            pivots = ind.pivots(float(prev["high"].max()), float(prev["low"].min()), float(prev["close"].iloc[-1]))
    elif len(df) >= 2:
        prev = df.iloc[-2]
        pivots = ind.pivots(float(prev["high"]), float(prev["low"]), float(prev["close"]))

    last = df.iloc[-1]
    rsi = ind.rsi(df["close"]).iloc[-1] if len(df) > 15 else float("nan")
    return {
        "bars": bars,
        "series": series,
        "pivots": {k: round(v, 4) for k, v in pivots.items()} if pivots else None,
        "opening_range": ind.opening_range(df) if intraday else None,
        "markers": sorted(markers, key=lambda m: m["time"]),
        "knn": knn_now,
        "last": {
            "time": times[-1],
            "close": float(last["close"]),
            "rsi": None if math.isnan(rsi) else round(float(rsi), 1),
        },
    }


BINANCE_INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "1d": "1d", "1wk": "1w"}
INTERVAL_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "1d": 86400, "1wk": 604800}
PERIOD_DAYS = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 91, "6mo": 182, "1y": 365, "2y": 730, "5y": 1826}


def binance_pair(symbol: str) -> str:
    """BTC-USD -> BTCUSDT (the listing's crypto symbols are Binance USDT pairs)."""
    base = symbol.upper().split("-")[0]
    return base if base.endswith("USDT") else f"{base}USDT"


def binance_klines(symbol: str, interval: str, period: str) -> pd.DataFrame:
    """Crypto candles straight from Binance: real volume and no delay."""
    import requests

    limit = min(1000, max(2, PERIOD_DAYS.get(period, 30) * 86400 // INTERVAL_SECONDS[interval]))
    r = requests.get("https://api.binance.com/api/v3/klines", timeout=10,
                     params={"symbol": binance_pair(symbol), "interval": BINANCE_INTERVALS[interval], "limit": limit})
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "volume", *range(6)])
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def fetch_bars(symbol: str, market: str, interval: str, period: str) -> pd.DataFrame:
    from ..agent.agents import _resolve_fetcher

    if market == "crypto":
        try:
            df = binance_klines(symbol, interval, period)
            if not df.empty:
                return df
        except Exception as exc:  # fall back to the fetcher chain (Yahoo)
            import logging

            logging.getLogger(__name__).warning("Binance klines for %s failed: %s", symbol, exc)
    return _resolve_fetcher(market).get_history(symbol, period=period, interval=TimeFrame(interval))
