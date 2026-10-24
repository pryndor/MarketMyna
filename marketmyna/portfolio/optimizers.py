"""Two portfolio construction methods from the literature, on daily returns.

- Hierarchical risk parity (López de Prado, "Building Diversified Portfolios
  that Outperform Out of Sample", 2016): cluster holdings by correlation,
  order them so similar ones sit together, then split weight top-down
  between clusters in inverse proportion to each cluster's variance. Needs
  no covariance inversion, so it is stable with few observations.
- Minimum CVaR (Rockafellar & Uryasev, "Optimization of Conditional
  Value-at-Risk", 2000): the long-only mix whose average loss on its worst
  5% of days, in the history given, is smallest; solved as a linear programme.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.optimize import linprog
from scipy.spatial.distance import squareform


def _ivp(cov: np.ndarray) -> np.ndarray:
    w = 1 / np.diag(cov)
    return w / w.sum()


def _cluster_var(cov: pd.DataFrame, items: list) -> float:
    sub = cov.loc[items, items].to_numpy()
    w = _ivp(sub)
    return float(w @ sub @ w)


def hrp(returns: pd.DataFrame) -> pd.Series:
    """Weights summing to 1, indexed like returns.columns."""
    cols = list(returns.columns)
    if len(cols) == 1:
        return pd.Series([1.0], index=cols)
    cov, corr = returns.cov(), returns.corr().clip(-1, 1)
    # a writable copy: with pandas copy-on-write, DataFrame.values is read-only
    dist = np.sqrt(((1 - corr) / 2).clip(lower=0)).to_numpy(copy=True)
    np.fill_diagonal(dist, 0)
    order = [cols[i] for i in leaves_list(linkage(squareform(dist, checks=False), method="single"))]
    w = pd.Series(1.0, index=order)
    clusters = [order]
    while clusters:
        nxt = []
        for c in clusters:
            if len(c) < 2:
                continue
            half = len(c) // 2
            left, right = c[:half], c[half:]
            v_l, v_r = _cluster_var(cov, left), _cluster_var(cov, right)
            alpha = 1 - v_l / (v_l + v_r)
            w[left] *= alpha
            w[right] *= 1 - alpha
            nxt += [left, right]
        clusters = nxt
    return w.reindex(cols) / w.sum()


def min_cvar(returns: pd.DataFrame, beta: float = 0.95, max_weight: float = 1.0) -> pd.Series:
    """Long-only weights minimising the historical CVaR at `beta` (Rockafellar-Uryasev LP).

    Variables: n weights, VaR level a, T excess losses u_t >= 0.
    minimise a + sum(u) / ((1 - beta) T)
    subject to u_t >= -r_t . w - a,  sum(w) = 1,  0 <= w <= max_weight.
    """
    r = returns.to_numpy()
    t, n = r.shape
    cap = max(max_weight, 1.0 / n)
    c = np.concatenate([np.zeros(n), [1.0], np.full(t, 1.0 / ((1 - beta) * t))])
    # -r_t.w - a - u_t <= 0
    a_ub = np.hstack([-r, -np.ones((t, 1)), -np.eye(t)])
    b_ub = np.zeros(t)
    a_eq = np.concatenate([np.ones(n), [0.0], np.zeros(t)])[None, :]
    bounds = [(0, cap)] * n + [(None, None)] + [(0, None)] * t
    res = linprog(c, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=[1.0], bounds=bounds, method="highs")
    if not res.success:
        raise ValueError(f"Minimum-CVaR solve failed: {res.message}")
    w = np.clip(res.x[:n], 0, None)
    return pd.Series(w / w.sum(), index=returns.columns)


def cvar(port_returns: pd.Series | np.ndarray, beta: float = 0.95) -> float:
    """Average daily loss on the worst (1 - beta) of days, as a positive fraction."""
    x = np.sort(np.asarray(port_returns, dtype=float))
    k = max(1, int(np.ceil(round((1 - beta) * len(x), 9))))  # round: 0.05 * 40 is 2.0000000000000018
    return float(-x[:k].mean())
