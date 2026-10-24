"""Nearest-neighbour (kNN) signal filters, written for MarketMyna from
general methods (k-nearest neighbours, Fisher's discriminant ratio, ATR
bands); not a port of any published script.

Everything is causal: at bar t the model only learns from rows whose
outcome was already known at t, so a backtest never sees the future.

  analog_score   for each bar, find the k most similar past market states
                 (trend, stretch, momentum, volatility, position in the bar's
                 range, short slope) and average what happened next
                 (+1 / -1, weighted by similarity). Features are weighted by
                 how well they separated up from down outcomes in the memory
                 (Fisher ratio), so useless features count less.
  crossover_vote for moving-average crossovers: each past crossover is stored
                 with its ADX and MFI and whether the trade that followed
                 made money; a new crossover gets the sum of the votes of its
                 k nearest past crossovers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind

FEATURES = ("trend", "stretch", "momentum", "volatility", "range_pos", "slope")


def features(df: pd.DataFrame) -> pd.DataFrame:
    """Six bounded features per bar (each roughly in -1..1)."""
    close, high, low = df["close"], df["high"], df["low"]
    atr = ind.atr(df, 14).replace(0, np.nan)
    trend = ((ind.ema(close, 10) - ind.ema(close, 34)) / atr).clip(-3, 3) / 3
    basis, dev = close.rolling(30).mean(), close.rolling(30).std().replace(0, np.nan)
    stretch = (-(close - basis) / dev).clip(-3, 3) / 3  # stretched up -> negative
    momentum = ((close / close.shift(14) - 1) / 0.05).clip(-3, 3) / 3
    vol = close.rolling(20).std()
    lo, hi = vol.rolling(100).min(), vol.rolling(100).max()
    volatility = (((vol - lo) / (hi - lo).replace(0, np.nan)).clip(0, 1) * 2 - 1)
    rng = (high - low).replace(0, np.nan)
    range_pos = (((close - low) / rng) * 2 - 1).clip(-1, 1)
    slope = ((close - close.shift(3)) / atr).clip(-3, 3) / 3
    return pd.DataFrame({"trend": trend, "stretch": stretch, "momentum": momentum, "volatility": volatility,
                         "range_pos": range_pos, "slope": slope}, index=df.index)


def outcomes(df: pd.DataFrame, horizon: int, atr_band: float) -> pd.Series:
    """+1 / -1 when the close `horizon` bars later moved more than atr_band x ATR
    up / down, 0 for a flat outcome (not learned from). Known only at t + horizon."""
    move = df["close"].shift(-horizon) - df["close"]
    band = atr_band * ind.atr(df, 14)
    return pd.Series(np.where(move > band, 1.0, np.where(move < -band, -1.0, 0.0)), index=df.index).where(move.notna())


def fisher_weights(x: np.ndarray, y: np.ndarray, floor: float = 0.4) -> np.ndarray:
    """Per-feature (mean_up - mean_down)^2 / (var_up + var_down), scaled so the
    best feature gets 1; `floor` keeps every feature in play."""
    up, dn = x[y > 0], x[y < 0]
    if len(up) < 5 or len(dn) < 5:
        return np.ones(x.shape[1])
    f = (up.mean(0) - dn.mean(0)) ** 2 / (up.var(0) + dn.var(0) + 1e-9)
    return np.maximum(floor, f / f.max()) if f.max() > 0 else np.ones(x.shape[1])


def analog_score(df: pd.DataFrame, horizon: int = 4, k: int = 9, memory: int = 400, atr_band: float = 0.45,
                 min_rows: int = 60, refit_every: int = 20) -> pd.DataFrame:
    """Columns: score (-1..1, similarity-weighted average outcome of the k
    nearest past states) and agree (share of that weight on the winning side)."""
    feats = features(df)
    out_lbl = outcomes(df, horizon, atr_band)
    x_all = feats.to_numpy(dtype=float)
    y_all = out_lbl.to_numpy(dtype=float)
    n = len(df)
    score = np.full(n, np.nan)
    agree = np.full(n, np.nan)
    weights = np.ones(len(FEATURES))
    for t in range(n):
        xt = x_all[t]
        if np.isnan(xt).any():
            continue
        last_known = t - horizon  # rows up to here have a known outcome at bar t
        lo = max(0, last_known - memory + 1)
        if last_known - lo + 1 < min_rows:
            continue
        xs, ys = x_all[lo:last_known + 1], y_all[lo:last_known + 1]
        ok = ~np.isnan(xs).any(axis=1) & ~np.isnan(ys) & (ys != 0)
        xs, ys = xs[ok], ys[ok]
        if len(ys) < max(k, 10):
            continue
        if t % refit_every == 0:
            weights = fisher_weights(xs, ys)
        dist = (np.log1p(np.abs(xs - xt)) * weights).sum(axis=1)
        idx = np.argpartition(dist, min(k, len(dist) - 1))[:k]
        w = 1.0 / (1.0 + dist[idx])
        s = float((ys[idx] * w).sum() / w.sum())
        score[t] = s
        side = ys[idx] > 0 if s >= 0 else ys[idx] < 0
        agree[t] = float(w[side].sum() / w.sum())
    return pd.DataFrame({"score": score, "agree": agree}, index=df.index)


def adaptive_supertrend(df: pd.DataFrame, confidence: pd.Series, period: int = 10, multiplier: float = 2.0,
                        adapt: float = 0.8) -> tuple[pd.Series, pd.Series]:
    """Supertrend whose band widens when the model is unsure (confidence near 0)
    and tightens toward `multiplier` when it is sure: mult x (1 + adapt x (1 - conf))."""
    close = df["close"].to_numpy(dtype=float)
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy(dtype=float)
    atr = ind.atr(df, period).to_numpy(dtype=float)
    conf = confidence.fillna(0).clip(0, 1).to_numpy(dtype=float)
    mult = multiplier * (1 + adapt * (1 - conf))
    n = len(df)
    line = np.full(n, np.nan)
    direction = np.zeros(n)
    up = dn = np.nan
    d = 1
    for i in range(n):
        if np.isnan(atr[i]):
            continue
        lower, upper = hl2[i] - mult[i] * atr[i], hl2[i] + mult[i] * atr[i]
        up = lower if np.isnan(up) or close[i - 1] <= up else max(lower, up)
        dn = upper if np.isnan(dn) or close[i - 1] >= dn else min(upper, dn)
        if d == -1 and close[i] > dn:
            d = 1
        elif d == 1 and close[i] < up:
            d = -1
        direction[i] = d
        line[i] = up if d == 1 else dn
    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


def vwma(df: pd.DataFrame, period: int) -> pd.Series:
    vol = df["volume"].astype(float)
    return (df["close"] * vol).rolling(period).sum() / vol.rolling(period).sum().replace(0, np.nan)


def crossover_vote(df: pd.DataFrame, fast: int = 13, slow: int = 19, k: int = 23, filter_len: int = 13) -> pd.DataFrame:
    """For every bar: cross (+1 up / -1 down / 0) and, on cross bars, the vote of
    the k nearest past crossovers in (ADX, MFI) space. A past crossover's label
    is +1 when price at the following crossover was higher (the move it started
    went up), known only once that following crossover has happened."""
    f, s = vwma(df, fast), vwma(df, slow)
    above = (f > s).astype(int)
    cross = above.diff().fillna(0)
    adx = ind.adx(df, filter_len)["adx"]
    mfi = ind.mfi(df, filter_len)
    close = df["close"].to_numpy(dtype=float)
    feats: list[tuple[float, float]] = []
    labels: list[float] = []
    prev = None  # (adx, mfi, price) of the last crossover, label pending
    vote = np.full(len(df), np.nan)
    for i, c in enumerate(cross.to_numpy()):
        if c == 0 or np.isnan(adx.iloc[i]) or np.isnan(mfi.iloc[i]):
            continue
        a, m = float(adx.iloc[i]) / 100, float(mfi.iloc[i]) / 100
        if feats:
            d = np.hypot(np.array([p[0] for p in feats]) - a, np.array([p[1] for p in feats]) - m)
            idx = np.argsort(d)[:k]
            vote[i] = float(np.array(labels)[idx].sum())
        if prev is not None:  # the previous crossover's outcome is known now
            feats.append((prev[0], prev[1]))
            labels.append(1.0 if close[i] >= prev[2] else -1.0)
        prev = (a, m, close[i])
    return pd.DataFrame({"cross": cross, "vote": vote}, index=df.index)
