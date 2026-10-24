"""Realized-volatility estimators and volatility cones on OHLC frames
(lower-case columns). Annualised, as fractions (0.25 = 25%).

Estimator formulas follow the OpenBB technical extension (Apache 2.0):
close-to-close, Parkinson, Garman-Klass, Rogers-Satchell and Yang-Zhang.
Range-based estimators use the high / low / open, so they read more from
the same number of bars than close-to-close does.

garch() fits a GARCH(1,1) by maximum likelihood (scipy, Gaussian) to forecast
volatility forward, the econometrics piece of OpenBB's quantitative extension.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252
ESTIMATORS = {
    "close_to_close": "Close-to-close",
    "parkinson": "Parkinson (high-low)",
    "garman_klass": "Garman-Klass",
    "rogers_satchell": "Rogers-Satchell",
    "yang_zhang": "Yang-Zhang",
}


def _ann(var: pd.Series) -> pd.Series:
    return np.sqrt(var.clip(lower=0) * TRADING_DAYS)


def realized(df: pd.DataFrame, window: int = 20, kind: str = "yang_zhang") -> pd.Series:
    o, h, l, c = (df[k].astype(float) for k in ("open", "high", "low", "close"))
    roll = lambda s: s.rolling(window, min_periods=window).mean()  # noqa: E731
    if kind == "close_to_close":
        return np.log(c / c.shift(1)).rolling(window, min_periods=window).std() * math.sqrt(TRADING_DAYS)
    hl = np.log(h / l)
    if kind == "parkinson":
        return _ann(roll(hl ** 2) / (4 * math.log(2)))
    co = np.log(c / o)
    if kind == "garman_klass":
        return _ann(roll(0.5 * hl ** 2 - (2 * math.log(2) - 1) * co ** 2))
    rs = np.log(h / c) * np.log(h / o) + np.log(l / c) * np.log(l / o)
    if kind == "rogers_satchell":
        return _ann(roll(rs))
    if kind == "yang_zhang":
        overnight = np.log(o / c.shift(1))
        k = 0.34 / (1.34 + (window + 1) / (window - 1))
        var = overnight.rolling(window).var() + k * co.rolling(window).var() + (1 - k) * roll(rs)
        return _ann(var)
    raise ValueError(f"unknown estimator {kind}")


def cones(df: pd.DataFrame, windows=(10, 20, 60, 120), kind: str = "yang_zhang") -> list[dict]:
    """Per window: today's realized vol and its historical min / quartiles / max."""
    out = []
    for w in windows:
        s = realized(df, w, kind).dropna()
        if len(s) < max(20, w // 2):
            continue
        q = s.quantile([0.25, 0.5, 0.75])
        out.append({"window": w, "current": float(s.iloc[-1]), "min": float(s.min()), "p25": float(q[0.25]),
                    "median": float(q[0.5]), "p75": float(q[0.75]), "max": float(s.max()),
                    "percentile": float((s <= s.iloc[-1]).mean() * 100)})
    return out


def _garch_filter(r: np.ndarray, omega: float, alpha: float, beta: float) -> np.ndarray:
    var = np.empty(len(r))
    var[0] = r.var()
    for t in range(1, len(r)):
        var[t] = omega + alpha * r[t - 1] ** 2 + beta * var[t - 1]
    return var


def garch(close: pd.Series, horizons=(5, 21)) -> dict | None:
    """GARCH(1,1) on daily log returns: current and forecast annualised volatility.

    sigma2[t] = omega + alpha * r[t-1]^2 + beta * sigma2[t-1]. Forecasts revert to
    the long-run level omega / (1 - alpha - beta) at rate alpha + beta per day.
    Needs about a year of closes; returns None when the fit is not usable.
    """
    from scipy.optimize import minimize

    c = close.dropna()
    c = c[c > 0]
    r = np.diff(np.log(c.to_numpy(dtype=float))) * 100  # percent, better conditioned
    if len(r) < 200:
        return None
    r = r - r.mean()
    v0 = float(r.var())

    def nll(p):
        omega, alpha, beta = p
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
            return 1e10
        var = _garch_filter(r, omega, alpha, beta)
        return 0.5 * float(np.sum(np.log(var) + r ** 2 / var))

    best = None
    for a, b in ((0.05, 0.9), (0.1, 0.8), (0.03, 0.95)):
        res = minimize(nll, [v0 * (1 - a - b), a, b], method="Nelder-Mead",
                       options={"maxiter": 3000, "xatol": 1e-8, "fatol": 1e-8})
        if res.fun < 1e9 and (best is None or res.fun < best.fun):
            best = res
    if best is None:
        return None
    omega, alpha, beta = (float(x) for x in best.x)
    persistence = alpha + beta
    long_run = omega / (1 - persistence)
    var = _garch_filter(r, omega, alpha, beta)
    nxt = omega + alpha * r[-1] ** 2 + beta * var[-1]  # tomorrow's variance

    def ann(daily_pct_var: float) -> float:
        return math.sqrt(daily_pct_var * TRADING_DAYS) / 100

    forecasts = []
    for h in horizons:
        # mean variance over the next h days
        k = np.arange(h)
        path = long_run + (persistence ** k) * (nxt - long_run)
        forecasts.append({"days": int(h), "volatility": ann(float(path.mean()))})
    return {
        "current": ann(float(var[-1])),
        "next_day": ann(float(nxt)),
        "long_run": ann(long_run),
        "forecasts": forecasts,
        "alpha": alpha,
        "beta": beta,
        "persistence": persistence,
        "half_life_days": math.log(0.5) / math.log(persistence) if 0 < persistence < 1 else None,
    }


def summary(df: pd.DataFrame, window: int = 20) -> dict:
    """Current value of every estimator, cones, and a calm / normal / stormy regime."""
    d = df.dropna(subset=["open", "high", "low", "close"])
    d = d[(d[["open", "high", "low", "close"]] > 0).all(axis=1)]
    if len(d) < window + 5:
        raise ValueError("not enough OHLC history for volatility")
    now = {k: realized(d, window, k).iloc[-1] for k in ESTIMATORS}
    cone = cones(d)
    ref = next((c for c in cone if c["window"] == window), None)
    regime = None
    if ref:
        regime = "stormy" if ref["percentile"] >= 80 else "calm" if ref["percentile"] <= 20 else "normal"
    return {
        "window": window,
        "estimators": [{"key": k, "name": ESTIMATORS[k], "value": float(v) if v == v else None} for k, v in now.items()],
        "cones": cone,
        "regime": regime,
        "percentile": ref["percentile"] if ref else None,
        "garch": _safe_garch(d["close"]),
    }


def _safe_garch(close: pd.Series) -> dict | None:
    try:
        return garch(close)
    except Exception:
        return None
