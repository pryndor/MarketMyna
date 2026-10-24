"""Strategy backtester.

Rules that keep results honest:
- signals are computed on a bar's close and filled at the NEXT bar's open
  (no look-ahead);
- stops / targets are checked inside each bar with its high/low; if both
  could have been hit in the same bar the stop is assumed first;
- a gap through the stop fills at the open, not at the stop;
- every fill pays slippage and costs (commission + taxes) per side.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from . import indicators as ind

# id -> label, description, default params, optimisation grid
STRATEGIES: dict[str, dict] = {
    "ema_cross": {
        "label": "EMA crossover",
        "description": "Buy when the fast EMA crosses above the slow EMA; exit on the cross back.",
        "params": {"fast": 9, "slow": 21},
        "grid": {"fast": [5, 9, 12, 20], "slow": [21, 30, 50, 100]},
    },
    "breakout": {
        "label": "Donchian breakout",
        "description": "Buy a close above the N-day high; exit on a close below the M-day low.",
        "params": {"entry_days": 20, "exit_days": 10},
        "grid": {"entry_days": [10, 20, 55], "exit_days": [5, 10, 20]},
    },
    "rsi_reversion": {
        "label": "RSI mean reversion",
        "description": "Buy when RSI(14) closes below the lower level; exit above the upper level.",
        "params": {"buy_below": 30, "sell_above": 55},
        "grid": {"buy_below": [20, 25, 30, 35], "sell_above": [50, 55, 60, 70]},
    },
    "supertrend": {
        "label": "Supertrend",
        "description": "Long while Supertrend is up; exit when it turns down.",
        "params": {"period": 10, "multiplier": 3.0},
        "grid": {"period": [7, 10, 14], "multiplier": [2.0, 2.5, 3.0, 4.0]},
    },
    "sma_trend": {
        "label": "Moving-average trend",
        "description": "Long while the close is above its N-bar simple moving average.",
        "params": {"period": 200},
        "grid": {"period": [20, 50, 100, 150, 200]},
    },
    "vwma_cross": {
        "label": "VWMA crossover",
        "description": "Buy when the fast volume-weighted moving average crosses above the slow one; exit on the "
                       "cross back. Volume-weighting gives heavy-volume days more say.",
        "params": {"fast": 13, "slow": 19},
        "grid": {"fast": [9, 13, 20], "slow": [19, 30, 50]},
    },
    "vwma_knn": {
        "label": "VWMA crossover + kNN filter (experimental)",
        "description": "The VWMA crossover, taken only when its nearest past crossovers (by ADX trend strength and "
                       "MFI money flow) mostly went the right way. Experimental: on 19 large Indian and US stocks "
                       "(10 years, judged on the unseen last 3) the filter cut returns from 13.9% to 1.6% on average "
                       "and beat the plain crossover on only 4. Test it on your stock before trusting it.",
        "params": {"fast": 13, "slow": 19, "k": 23, "min_vote": 2, "use_filter": 1},
        "grid": {"fast": [9, 13, 20], "slow": [19, 30, 50], "min_vote": [0, 2, 5]},
    },
    "knn_supertrend": {
        "label": "kNN-filtered Supertrend (experimental)",
        "description": "An adaptive Supertrend (band tightens when a nearest-neighbour model of similar past market "
                       "states is confident) taken only when that model leans up. Experimental: on 19 large stocks "
                       "(unseen last 3 of 10 years) it averaged -2.3% against +9.4% for a plain Supertrend and beat "
                       "it on 6. Test it on your stock before trusting it.",
        "params": {"period": 10, "multiplier": 2.0, "min_score": 0.15, "k": 9, "horizon": 4},
        "grid": {"multiplier": [1.5, 2.0, 3.0], "min_score": [0.0, 0.15, 0.3], "horizon": [4, 8]},
    },
}

BARS_PER_YEAR = {"1d": 252, "1wk": 52, "1h": 252 * 7}


@dataclass
class Settings:
    strategy: str = "ema_cross"
    params: dict = field(default_factory=dict)
    capital: float = 100000.0
    sizing: str = "percent"  # percent (of equity) | risk (% of equity lost at the stop)
    position_pct: float = 100.0
    risk_pct: float = 1.0
    stop_type: str = "none"  # none | percent | atr
    stop_value: float = 2.0  # % or ATR multiple
    target_r: Optional[float] = None  # take profit at N x the stop distance
    cost_pct: float = 0.1  # per side: commission + taxes
    slippage_pct: float = 0.05  # per side
    allow_short: bool = False


def signals(df: pd.DataFrame, strategy: str, p: dict) -> tuple[pd.Series, pd.Series]:
    """(long_entry, long_exit) booleans evaluated on each bar's close.
    Short trades use the mirror image: entry = long_exit, exit = long_entry."""
    close = df["close"]
    if strategy == "ema_cross":
        fast, slow = ind.ema(close, int(p["fast"])), ind.ema(close, int(p["slow"]))
        above = fast > slow
        warm = pd.Series(np.arange(len(df)) >= int(p["slow"]), index=df.index)
        return above & ~above.shift(1, fill_value=False) & warm, ~above & above.shift(1, fill_value=False) & warm
    if strategy == "breakout":
        hi = ind.donchian(df, int(p["entry_days"]))["upper"]
        lo = ind.donchian(df, int(p["exit_days"]))["lower"]
        return close > hi, close < lo
    if strategy == "rsi_reversion":
        r = ind.rsi(close)
        return r < float(p["buy_below"]), r > float(p["sell_above"])
    if strategy == "supertrend":
        _, d = ind.supertrend(df, int(p["period"]), float(p["multiplier"]))
        warm = pd.Series(np.arange(len(df)) > int(p["period"]), index=df.index)
        return (d == 1) & (d.shift(1) == -1) & warm, (d == -1) & (d.shift(1) == 1) & warm
    if strategy == "vwma_cross":
        if "volume" not in df or df["volume"].fillna(0).sum() == 0:
            raise ValueError("This strategy needs volume data")
        from . import knn

        f, sl = knn.vwma(df, int(p["fast"])), knn.vwma(df, int(p["slow"]))
        above = f > sl
        warm = sl.notna()
        return above & ~above.shift(1, fill_value=False) & warm, ~above & above.shift(1, fill_value=False) & warm
    if strategy == "vwma_knn":
        if "volume" not in df or df["volume"].fillna(0).sum() == 0:
            raise ValueError("This strategy needs volume data")
        from . import knn

        v = knn.crossover_vote(df, int(p["fast"]), int(p["slow"]), int(p["k"]))
        ok = v["vote"] >= float(p["min_vote"]) if int(p.get("use_filter", 1)) else True
        return (v["cross"] == 1) & ok, v["cross"] == -1
    if strategy == "knn_supertrend":
        from . import knn

        a = knn.analog_score(df, horizon=int(p["horizon"]), k=int(p["k"]))
        _, d = knn.adaptive_supertrend(df, a["agree"], int(p["period"]), float(p["multiplier"]))
        state = (d == 1) & (a["score"] >= float(p["min_score"]))
        return state & ~state.shift(1, fill_value=False), (d == -1) & (d.shift(1) == 1)
    if strategy == "sma_trend":
        sma = close.rolling(int(p["period"])).mean()
        above = close > sma
        return above & ~above.shift(1, fill_value=False) & sma.notna(), ~above & sma.notna()
    raise ValueError(f"Unknown strategy '{strategy}'")


def run(df: pd.DataFrame, s: Settings, interval: str = "1d") -> dict:
    cols = ["open", "high", "low", "close"] + (["volume"] if "volume" in df else [])
    df = df[cols].astype(float).dropna(subset=["open", "high", "low", "close"])
    n = len(df)
    params = {**STRATEGIES[s.strategy]["params"], **(s.params or {})}
    long_in, long_out = (x.to_numpy() for x in signals(df, s.strategy, params))
    atr = ind.atr(df, 14).to_numpy()
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    times = df.index
    slip, cost = s.slippage_pct / 100, s.cost_pct / 100

    # Cash holds realised equity; open trades are marked to market, so long
    # and short are symmetric: equity = cash + (price - entry) * qty * side.
    cash, qty, side = s.capital, 0.0, 0  # side 1 long, -1 short
    entry_px = stop = target = risk_per_unit = None
    entry_i = 0
    entry_fee = 0.0
    pending: Optional[int] = None  # +1 open long, -1 open short, 0 close
    trades: list[dict] = []
    equity = np.empty(n)
    bars_in = 0

    def close_position(i: int, px: float, reason: str) -> None:
        nonlocal cash, qty, side, entry_px, stop, target, risk_per_unit
        fill = px * (1 - slip * side)
        exit_fee = qty * fill * cost
        gross = (fill - entry_px) * qty * side
        cash += gross - exit_fee
        pnl = gross - exit_fee - entry_fee
        trades.append({
            "side": "long" if side == 1 else "short",
            "entry_time": times[entry_i].isoformat(), "exit_time": times[i].isoformat(),
            "entry": round(entry_px, 4), "exit": round(fill, 4), "quantity": round(qty, 6),
            "pnl": round(pnl, 2), "return_pct": round((fill / entry_px - 1) * 100 * side, 2),
            "r": round(pnl / (risk_per_unit * qty), 2) if risk_per_unit and qty else None,
            "bars": i - entry_i, "reason": reason,
        })
        qty, side, entry_px, stop, target, risk_per_unit = 0.0, 0, None, None, None, None

    for i in range(n):
        # 1) fill the previous bar's signal at this bar's open
        if pending is not None:
            if side != 0 and pending != side:
                close_position(i, o[i], "signal")
            if pending in (1, -1) and side == 0:
                price_in = o[i] * (1 + slip * pending)
                dist = None
                if s.stop_type == "percent":
                    dist = price_in * s.stop_value / 100
                elif s.stop_type == "atr" and i > 0 and not math.isnan(atr[i - 1]):
                    dist = atr[i - 1] * s.stop_value
                if s.sizing == "risk" and dist:
                    units = cash * s.risk_pct / 100 / dist
                else:
                    units = cash * s.position_pct / 100 / price_in
                units = min(units, cash / (price_in * (1 + cost)))  # no leverage
                if units > 0:
                    side, qty, entry_px, entry_i, risk_per_unit = pending, units, price_in, i, dist
                    stop = entry_px - dist * side if dist else None
                    target = entry_px + dist * s.target_r * side if dist and s.target_r else None
                    entry_fee = qty * entry_px * cost
                    cash -= entry_fee
            pending = None

        # 2) stop / target inside the bar (stop first when both are possible)
        if side != 0:
            if stop is not None and ((side == 1 and l[i] <= stop) or (side == -1 and h[i] >= stop)):
                close_position(i, min(o[i], stop) if side == 1 else max(o[i], stop), "stop")
            elif target is not None and ((side == 1 and h[i] >= target) or (side == -1 and l[i] <= target)):
                close_position(i, max(o[i], target) if side == 1 else min(o[i], target), "target")

        # 3) signals on this close, filled at the next open
        if i < n - 1:
            if side == 1 and long_out[i]:
                pending = -1 if s.allow_short else 0
            elif side == -1 and long_in[i]:
                pending = 1
            elif side == 0:
                if long_in[i]:
                    pending = 1
                elif s.allow_short and long_out[i]:
                    pending = -1

        if side != 0:
            bars_in += 1
        equity[i] = cash + ((c[i] - entry_px) * qty * side if side != 0 else 0.0)

    if side != 0:
        close_position(n - 1, c[-1], "end of test")
        equity[-1] = cash

    return _report(df, equity, trades, s, interval, bars_in)


def _report(df: pd.DataFrame, equity: np.ndarray, trades: list[dict], s: Settings, interval: str, bars_in: int) -> dict:
    n = len(df)
    eq = pd.Series(equity, index=df.index)
    peak = eq.cummax()
    dd = (eq / peak - 1) * 100
    rets = eq.pct_change().dropna()
    per_year = BARS_PER_YEAR.get(interval, 252)
    years = n / per_year if per_year else 0
    total = (eq.iloc[-1] / s.capital - 1) * 100
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    rs = [t["r"] for t in trades if t["r"] is not None]
    step = max(1, n // 500)
    close = df["close"]
    return {
        "metrics": {
            "total_return": round(total, 2),
            "cagr": round(((eq.iloc[-1] / s.capital) ** (1 / years) - 1) * 100, 2) if years > 0 and eq.iloc[-1] > 0 else None,
            "max_drawdown": round(float(dd.min()), 2),
            "sharpe": round(float(rets.mean() / rets.std() * math.sqrt(per_year)), 2) if len(rets) > 2 and rets.std() > 0 else None,
            "trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
            "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "avg_trade_pct": round(float(np.mean([t["return_pct"] for t in trades])), 2) if trades else None,
            "avg_r": round(float(np.mean(rs)), 2) if rs else None,
            "best_trade": max(pnls) if pnls else None,
            "worst_trade": min(pnls) if pnls else None,
            "avg_bars": round(float(np.mean([t["bars"] for t in trades])), 1) if trades else None,
            "exposure": round(bars_in / n * 100, 1) if n else None,
            "buy_hold_return": round((close.iloc[-1] / close.iloc[0] - 1) * 100, 2),
            "final_equity": round(float(eq.iloc[-1]), 2),
            "start": df.index[0].isoformat(), "end": df.index[-1].isoformat(), "bars": n,
        },
        "equity": [
            {"time": t.isoformat(), "equity": round(float(v), 2), "buy_hold": round(float(s.capital * close.loc[t] / close.iloc[0]), 2),
             "drawdown": round(float(d), 2)}
            for t, v, d in list(zip(eq.index, eq.to_numpy(), dd.to_numpy()))[::step]
        ],
        "trades": trades,
    }


def split_test(df: pd.DataFrame, s: Settings, interval: str, train_frac: float = 0.7) -> dict:
    """Same settings on the first 70% (in-sample) and the last 30% (out-of-sample)."""
    cut = int(len(df) * train_frac)
    return {"train": run(df.iloc[:cut], s, interval)["metrics"], "test": run(df.iloc[cut:], s, interval)["metrics"]}


def optimize(df: pd.DataFrame, s: Settings, interval: str, objective: str = "sharpe", train_frac: float = 0.7,
             min_trades: int = 3) -> dict:
    """Grid-search the strategy's parameters on the training part only,
    then report the winner on the unseen test part (walk-forward check)."""
    grid = STRATEGIES[s.strategy]["grid"]
    keys = list(grid)
    cut = int(len(df) * train_frac)
    train, test = df.iloc[:cut], df.iloc[cut:]
    results = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        p = dict(zip(keys, combo))
        if s.strategy == "ema_cross" and p["fast"] >= p["slow"]:
            continue
        m = run(train, Settings(**{**s.__dict__, "params": p}), interval)["metrics"]
        score = m.get(objective)
        results.append({"params": p, "score": score if m["trades"] >= min_trades else None, **{k: m[k] for k in
                        ("total_return", "sharpe", "max_drawdown", "trades", "win_rate", "profit_factor")}})
    ranked = sorted((r for r in results if r["score"] is not None), key=lambda r: -r["score"])
    best = ranked[0]["params"] if ranked else STRATEGIES[s.strategy]["params"]
    test_metrics = run(test, Settings(**{**s.__dict__, "params": best}), interval)["metrics"]
    return {"objective": objective, "best": best, "train": ranked[0] if ranked else None, "test": test_metrics,
            "grid": results, "keys": keys}
