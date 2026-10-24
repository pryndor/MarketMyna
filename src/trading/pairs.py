"""Pairs test: are two prices cointegrated, and how stretched is the spread now?

Engle-Granger two-step, the method behind OpenBB's econometrics cointegration
command: regress log(A) on log(B) for the hedge ratio, then run an augmented
Dickey-Fuller test on the residual spread. A stationary spread means the pair
tends to drift back together, the premise of pairs trading. Plain numpy, so no
statsmodels dependency; critical values are MacKinnon's (2010) for two series
with a constant.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

# MacKinnon (2010) asymptotic critical values, Engle-Granger, N=2, constant, no trend
EG_CRITICAL = {"1%": -3.90, "5%": -3.34, "10%": -3.04}
MIN_BARS = 120


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return beta, y - x @ beta


def adf(series: np.ndarray, max_lag: int | None = None) -> dict:
    """ADF t-statistic (constant, lag order by BIC) for a residual series.

    BIC rather than AIC: daily closes of two listings carry bid-ask and timing
    noise that AIC answers with many lags, which drains the test of power."""
    y = np.asarray(series, dtype=float)
    n = len(y)
    if max_lag is None:
        max_lag = int(12 * (n / 100) ** 0.25)
    dy = np.diff(y)
    best = None
    for lag in range(max_lag + 1):
        rows = len(dy) - max_lag  # same sample for every lag so BIC is comparable
        target = dy[max_lag:]
        cols = [np.ones(rows), y[max_lag:-1]]
        cols += [dy[max_lag - k:len(dy) - k] for k in range(1, lag + 1)]
        x = np.column_stack(cols)
        beta, resid = _ols(target, x)
        sigma2 = float(resid @ resid) / rows
        bic = rows * math.log(sigma2) + x.shape[1] * math.log(rows)
        if best is None or bic < best[0]:
            dof = rows - x.shape[1]
            s2 = float(resid @ resid) / dof
            se = math.sqrt(s2 * np.linalg.inv(x.T @ x)[1, 1])
            best = (bic, float(beta[1] / se), lag)
    return {"stat": best[1], "lag": best[2]}


def analyze(a: pd.Series, b: pd.Series) -> dict:
    """a, b: close prices indexed by date. Raises ValueError on too little overlap."""
    df = pd.concat([a, b], axis=1, keys=["a", "b"]).dropna()
    df = df[(df > 0).all(axis=1)]
    if len(df) < MIN_BARS:
        raise ValueError(f"Need at least {MIN_BARS} shared trading days, got {len(df)}")
    la, lb = np.log(df["a"].to_numpy()), np.log(df["b"].to_numpy())
    (alpha, hedge), spread = _ols(la, np.column_stack([np.ones(len(lb)), lb]))
    test = adf(spread)

    # mean-reversion speed: d(spread) = k * spread(t-1) + e  ->  half-life = -ln2 / k
    k = float(np.polyfit(spread[:-1], np.diff(spread), 1)[0])
    half_life = -math.log(2) / k if k < 0 else None
    z = (spread - spread.mean()) / spread.std()
    ret = df.pct_change().dropna()

    level = next((lvl for lvl, cv in EG_CRITICAL.items() if test["stat"] < cv), None)
    z_now = float(z[-1])
    if level is None:
        verdict = "not_cointegrated"
    elif abs(z_now) >= 2:
        verdict = "stretched"
    else:
        verdict = "cointegrated"
    return {
        "days": len(df),
        "start": str(df.index[0].date()),
        "end": str(df.index[-1].date()),
        "hedge_ratio": float(hedge),
        "correlation": float(ret["a"].corr(ret["b"])),
        "adf_stat": test["stat"],
        "adf_lag": test["lag"],
        "critical": EG_CRITICAL,
        "significance": level,
        "half_life_days": half_life,
        "z_now": z_now,
        "verdict": verdict,
        "spread": [{"time": str(d.date()), "z": round(float(v), 3)} for d, v in zip(df.index, z)],
    }
