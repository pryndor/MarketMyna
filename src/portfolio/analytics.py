"""Portfolio risk analytics: return / risk ratios, drawdown, beta, VaR, per-holding
risk contribution, correlation and an optimizer suggestion; tracking error,
information ratio and up / down capture against the benchmark; stress
scenarios (past market falls and flat index shocks, via each holding's beta);
and default inputs for the Monte Carlo projection the page runs in the
browser (frontend/src/lib/montecarlo.ts).

The current allocation is replayed over the last year of daily closes (the
usual "what would today's mix have done" view). Ratio definitions follow the
OpenBB quantitative extension (Apache 2.0); the optimizers are the existing
src/ai/portfolio_optimizer.py.
"""

from __future__ import annotations

import logging
import math
from typing import Callable, Optional

import numpy as np
import pandas as pd

from ..core.numbers import finite as _f

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
# Annual risk-free rate by market (rough 1-year government yield).
RISK_FREE = {"india": 0.065, "us": 0.04, "china_a": 0.015, "hong_kong": 0.035, "crypto": 0.04}
MIN_BARS = 60

# Market falls replayed in the stress test: (label, start = the peak, end = the trough)
# on the market's benchmark, with each holding moving by its beta times the index.
EPISODES = [
    ("2008 financial crisis", "2007-10-01", "2009-03-31"),
    ("2020 Covid crash", "2020-01-14", "2020-03-31"),
    ("2022 rate-rise sell-off", "2021-10-01", "2022-10-31"),
]
SHOCKS = (-0.10, -0.20, -0.30)
# Long-run return assumption for the Monte Carlo projection (nominal, a year):
# trailing one-year returns are far too noisy to project from.
LONG_RUN_RETURN = {"india": 0.11, "us": 0.08, "hong_kong": 0.07, "china_a": 0.07, "crypto": 0.10}
_long_bench: dict[str, tuple[float, pd.Series]] = {}

Fetch = Callable[[list[str]], dict[str, pd.Series]]


MF_PREFIX = "MF:"  # mutual fund holdings: NAV history by AMFI scheme code


def _download_closes(tickers: list[str]) -> dict[str, pd.Series]:
    from ..trading.scanner import _cache

    funds = [t for t in tickers if t.startswith(MF_PREFIX)]
    stocks = [t for t in tickers if not t.startswith(MF_PREFIX)]
    out = {t: df["close"].astype(float) for t, df in (_cache.get(stocks, "1d", "1y") if stocks else {}).items()}
    if funds:
        from ..data.mutual_funds import MutualFundDataFetcher

        mf = MutualFundDataFetcher()
        for t in funds:
            df = mf.get_historical_nav(int(t[len(MF_PREFIX):]), days=TRADING_DAYS + 10)
            if not df.empty:
                out[t] = df["nav"].astype(float)
    return out


def _market(value: str) -> str:
    m = (value or "us").lower()
    return "india" if m == "mf" else m  # Indian mutual funds: INR, Nifty benchmark


def _benchmark(market: str) -> tuple[str, str]:
    from ..services.analysis_run import MARKET_INDICES

    return (MARKET_INDICES.get(market) or MARKET_INDICES["us"])[0]


def _drawdown(returns: pd.Series) -> float:
    curve = (1 + returns).cumprod()
    return float((curve / curve.cummax() - 1).min())


def _benchmark_long(ticker: str) -> Optional[pd.Series]:
    """Full daily history of the benchmark (for the stress windows), kept a day."""
    import time

    hit = _long_bench.get(ticker)
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    try:
        import yfinance as yf

        from ..utils.yf_lock import YF_DOWNLOAD_LOCK

        with YF_DOWNLOAD_LOCK:
            df = yf.download(ticker, start="2007-06-01", interval="1d", progress=False, auto_adjust=True)
        close = df["Close"]
        close = close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
        close.index = pd.DatetimeIndex(close.index).tz_localize(None)
        close = close.dropna()
    except Exception as exc:
        logger.info("Benchmark history %s unavailable: %s", ticker, exc)
        return None
    _long_bench[ticker] = (time.time(), close)
    return close


def stress(weights: dict[str, float], betas: dict[str, Optional[float]], bench: Optional[pd.Series]) -> list[dict]:
    """Estimated portfolio move in past market falls and flat index shocks:
    each holding moves by its beta times the index (beta 1 when unknown)."""
    port_beta = sum(w * (betas.get(s) if betas.get(s) is not None else 1.0) for s, w in weights.items())
    out = []
    if bench is not None and len(bench):
        for label, start, end in EPISODES:
            window = bench[(bench.index >= start) & (bench.index <= end)]
            if len(window) < 10:
                continue
            peak_at = window.idxmax()
            after = window[window.index >= peak_at]
            trough_at = after.idxmin()
            move = float(after.min() / window.max() - 1)
            out.append({"label": label, "index_move": move, "portfolio_move": move * port_beta,
                        "from": str(peak_at.date()), "to": str(trough_at.date())})
    for shock in SHOCKS:
        out.append({"label": f"Index falls {abs(shock):.0%}", "index_move": shock, "portfolio_move": shock * port_beta,
                    "from": None, "to": None})
    return out


def versus_benchmark(port: pd.Series, bench: pd.Series) -> dict:
    """Tracking error, information ratio and up / down capture on daily returns."""
    pair = pd.concat([port, bench], axis=1, keys=["p", "b"]).dropna()
    if len(pair) < MIN_BARS - 1:
        return {}
    active = pair["p"] - pair["b"]
    te = float(active.std()) * math.sqrt(TRADING_DAYS)
    ann = lambda r: float((1 + r).prod()) ** (TRADING_DAYS / len(r)) - 1  # noqa: E731
    up, down = pair[pair["b"] > 0], pair[pair["b"] < 0]
    return {
        "tracking_error": te,
        "information_ratio": _f((ann(pair["p"]) - ann(pair["b"])) / te) if te else None,
        "up_capture": _f(up["p"].mean() / up["b"].mean()) if len(up) else None,
        "down_capture": _f(down["p"].mean() / down["b"].mean()) if len(down) else None,
    }


def ratios(returns: pd.Series, rf: float) -> dict:
    """Annualised return / volatility, Sharpe, Sortino, max drawdown, 1-day 95% VaR / CVaR."""
    mean, std = float(returns.mean()), float(returns.std())
    ann_return = float((1 + returns).prod()) ** (TRADING_DAYS / len(returns)) - 1
    ann_vol = std * math.sqrt(TRADING_DAYS)
    downside = returns[returns < 0]
    down_dev = float(np.sqrt((downside ** 2).sum() / len(returns))) * math.sqrt(TRADING_DAYS)
    var = float(np.percentile(returns, 5))
    tail = returns[returns <= var]
    return {
        "annual_return": ann_return,
        "volatility": ann_vol,
        "sharpe": _f((mean * TRADING_DAYS - rf) / ann_vol) if ann_vol else None,
        "sortino": _f((mean * TRADING_DAYS - rf) / down_dev) if down_dev else None,
        "max_drawdown": _drawdown(returns),
        "var_95": -var,
        "cvar_95": -float(tail.mean()) if len(tail) else -var,
    }


def analyze(holdings: list[dict], fetch: Fetch = _download_closes) -> dict:
    """holdings: [{symbol, market, market_value}] -> analytics payload.

    Raises ValueError when there is nothing to analyse."""
    from ..services.analysis_run import yahoo_symbol

    rows = [h for h in holdings if (_f(h.get("market_value")) or 0) > 0]
    if not rows:
        raise ValueError("No holdings with a current value to analyse")
    warnings: list[str] = []

    value_by_market: dict[str, float] = {}
    for h in rows:
        value_by_market[_market(h.get("market"))] = value_by_market.get(_market(h.get("market")), 0) + float(h["market_value"])
    main_market = max(value_by_market, key=value_by_market.get)
    if len(value_by_market) > 1:
        warnings.append("Holdings span several markets; weights mix currencies without conversion.")
    bench_ticker, bench_name = _benchmark(main_market)
    rf = RISK_FREE.get(main_market, 0.04)

    ticker_of = {h["symbol"]: MF_PREFIX + h["symbol"] if (h.get("market") or "").lower() == "mf"
                 else yahoo_symbol(h["symbol"], _market(h.get("market"))) for h in rows}
    closes = fetch(list(dict.fromkeys([*ticker_of.values(), bench_ticker])))

    series = {}
    for sym, t in ticker_of.items():
        s = closes.get(t)
        if s is None or len(s.dropna()) < MIN_BARS:
            warnings.append(f"{sym}: not enough price history, left out.")
            continue
        series[sym] = s
    if not series:
        raise ValueError("No price history available for these holdings")

    prices = pd.DataFrame(series)
    prices.index = pd.DatetimeIndex(prices.index).tz_localize(None).normalize()
    prices = prices[~prices.index.duplicated(keep="last")].sort_index().ffill().dropna()
    returns = prices.pct_change().dropna()
    if len(returns) < MIN_BARS - 1:
        raise ValueError("Not enough overlapping price history across holdings")

    values = {h["symbol"]: float(h["market_value"]) for h in rows if h["symbol"] in prices}
    total = sum(values.values())
    weights = pd.Series({s: values[s] / total for s in prices.columns})
    port = returns.dot(weights)

    bench = closes.get(bench_ticker)
    bench_ret = None
    if bench is not None and len(bench.dropna()) >= MIN_BARS:
        b = bench.copy()
        b.index = pd.DatetimeIndex(b.index).tz_localize(None).normalize()
        b = b[~b.index.duplicated(keep="last")].sort_index()
        bench_ret = b.reindex(prices.index).ffill().pct_change().reindex(returns.index)
    else:
        warnings.append(f"Benchmark {bench_name} unavailable; beta not computed.")

    def beta(r: pd.Series) -> Optional[float]:
        if bench_ret is None:
            return None
        pair = pd.concat([r, bench_ret], axis=1).dropna()
        var = float(pair.iloc[:, 1].var())
        return _f(float(pair.iloc[:, 0].cov(pair.iloc[:, 1])) / var) if var else None

    metrics = ratios(port, rf)
    metrics["beta"] = beta(port)
    if bench_ret is not None:
        metrics.update(versus_benchmark(port, bench_ret))
    metrics["var_95_value"] = metrics["var_95"] * total
    metrics["cvar_95_value"] = metrics["cvar_95"] * total

    cov = returns.cov() * TRADING_DAYS
    port_var = float(weights @ cov @ weights)
    contrib = weights * (cov @ weights) / port_var if port_var else weights * 0
    per_holding = []
    for sym in prices.columns:
        r = ratios(returns[sym], rf)
        per_holding.append({
            "symbol": sym, "weight": float(weights[sym]), "annual_return": r["annual_return"],
            "volatility": r["volatility"], "max_drawdown": r["max_drawdown"], "beta": beta(returns[sym]),
            "risk_contribution": _f(contrib[sym]),
        })
    per_holding.sort(key=lambda x: -x["weight"])

    top = max(per_holding, key=lambda x: x["risk_contribution"] or 0)
    if len(per_holding) > 1 and (top["risk_contribution"] or 0) > max(0.4, top["weight"] * 1.5):
        warnings.append(f"{top['symbol']} carries {top['risk_contribution']:.0%} of portfolio risk "
                        f"on a {top['weight']:.0%} weight.")

    corr = returns.corr()
    pairs = [(a, b, float(corr.loc[a, b])) for i, a in enumerate(corr.columns) for b in corr.columns[i + 1:]]
    high = [p for p in pairs if p[2] >= 0.8]
    if high:
        a, b, c = max(high, key=lambda p: p[2])
        warnings.append(f"{a} and {b} move together (correlation {c:.2f}); they diversify little.")

    curve = pd.DataFrame({"portfolio": (1 + port).cumprod() * 100})
    if bench_ret is not None:
        curve["benchmark"] = (1 + bench_ret.fillna(0)).cumprod() * 100
    curve = curve.resample("W-FRI").last().dropna(how="all")
    if bench_ret is not None:
        metrics["benchmark_return"] = ratios(bench_ret.dropna(), rf)["annual_return"]

    betas = {h["symbol"]: h["beta"] for h in per_holding}
    stress_rows = stress(weights.to_dict(), betas, _benchmark_long(bench_ticker) if fetch is _download_closes else None)

    return {
        "as_of": str(returns.index[-1].date()),
        "stress": [{k: (_f(v) if isinstance(v, float) else v) for k, v in r.items()} for r in stress_rows],
        "projection": {"expected_return": LONG_RUN_RETURN.get(main_market, 0.08),
                       "volatility": _f(metrics["volatility"])},
        "days": len(returns),
        "market": main_market,
        "benchmark": {"symbol": bench_ticker, "name": bench_name},
        "risk_free": rf,
        "total_value": total,
        "metrics": {k: _f(v) for k, v in metrics.items()},
        "holdings": per_holding,
        "correlation": {"symbols": list(corr.columns),
                        "matrix": [[_f(v) for v in row] for row in corr.to_numpy()]},
        "optimizer": _optimize(prices, weights, total, rf) if len(prices.columns) >= 2 else None,
        "curve": [{"time": str(i.date()), **{k: _f(v) for k, v in row.items()}} for i, row in curve.iterrows()],
        "warnings": warnings,
    }


def _optimize(prices: pd.DataFrame, weights: pd.Series, total: float, rf: float) -> dict:
    """Max-Sharpe, risk-parity, hierarchical risk parity and minimum-CVaR target
    weights, plus the trades to reach the max-Sharpe mix."""
    from ..ai.portfolio_optimizer import PortfolioOptimizer

    opt = PortfolioOptimizer(risk_free_rate=rf)
    returns = opt.calculate_returns(prices)
    # Uncapped max-Sharpe piles everything into the best past performer; cap each holding
    cap = min(1.0, max(0.4, 1.5 / len(prices.columns)))
    out: dict = {"current": _mix(opt, weights.to_numpy(), returns), "max_weight": cap}
    try:
        result = opt.optimize(prices, current_weights=weights.to_dict(), portfolio_value=total,
                              method="mean_variance", max_weight=cap)
        out["max_sharpe"] = {**_mix(opt, np.array([result.optimal_weights[s] for s in prices.columns]), returns),
                             "weights": {s: round(w, 4) for s, w in result.optimal_weights.items()}}
        out["trades"] = result.rebalance_trades
        out["suggestions"] = result.suggestions
    except Exception as exc:
        logger.warning("Max-Sharpe optimisation failed: %s", exc)
    try:
        rp = opt.risk_parity_optimization(returns)
        rp = rp / rp.sum()
        out["risk_parity"] = {**_mix(opt, rp, returns),
                              "weights": {s: round(float(w), 4) for s, w in zip(prices.columns, rp)}}
    except Exception as exc:
        logger.warning("Risk-parity optimisation failed: %s", exc)
    from .optimizers import hrp, min_cvar

    for key, build in (("hrp", lambda: hrp(returns)), ("min_cvar", lambda: min_cvar(returns, max_weight=cap))):
        try:
            w = build().reindex(prices.columns).fillna(0)
            out[key] = {**_mix(opt, w.to_numpy(), returns),
                        "weights": {s: round(float(v), 4) for s, v in w.items()}}
        except Exception as exc:
            logger.warning("%s optimisation failed: %s", key, exc)
    return out


def _mix(opt, w: np.ndarray, returns: pd.DataFrame) -> dict:
    from .optimizers import cvar

    r, vol, sharpe = opt.calculate_portfolio_metrics(w, returns)
    return {"expected_return": _f(r), "volatility": _f(vol), "sharpe": _f(sharpe),
            "cvar_95": _f(cvar(returns.to_numpy() @ np.asarray(w, dtype=float)))}
