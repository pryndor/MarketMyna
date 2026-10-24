"""Ready-made crypto screens. Coins have no earnings or book value, so these
work on price and volume: momentum, strength against Bitcoin, oversold RSI,
breakouts, drawdowns, and liquidity.

Universe: the 100 most-traded USD pairs in our crypto listing (stablecoins
dropped), six months of daily closes from Binance's public klines (Yahoo for the
few coins Binance lacks; Yahoo alone misses many, e.g. SUI, UNI, PEPE).
Cached CACHE_SECONDS. Same result shape as marketmyna/services/screens.py so the Screens
card renders both.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

UNIVERSE = 100
CACHE_SECONDS = 3600
STABLES = {"USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "BUSD", "USDD", "USDP", "GUSD", "EURC", "USD1", "RLUSD",
           "PAXG", "XAUT", "EUR", "EURI", "AEUR"}  # stablecoins and gold tokens: no crypto price action to screen

LABELS = {
    "volume": "24h volume $", "ret_7d": "7d %", "ret_30d": "30d %", "ret_90d": "90d %", "vs_btc_30d": "vs BTC 30d pts",
    "rsi14": "RSI 14", "from_high_90d": "From 90d high %", "volatility": "Volatility %/yr", "above_ma50": "Above 50d avg %",
}

# key: title, description, [(field, op, value)], (sort field, descending), columns
PRESETS = {
    "volume_leaders": ("Most traded", "The most liquid coins by 24-hour dollar volume",
                       [], ("volume", True), ["volume", "ret_7d", "ret_30d", "volatility"]),
    "momentum": ("Strong momentum", "Up over 10% in 30 days and trading above the 50-day average",
                 [("ret_30d", ">", 10), ("above_ma50", ">", 0)], ("ret_30d", True),
                 ["ret_30d", "ret_7d", "above_ma50", "rsi14", "volume"]),
    "beating_btc": ("Beating Bitcoin", "30-day return ahead of Bitcoin's",
                    [("vs_btc_30d", ">", 0)], ("vs_btc_30d", True), ["vs_btc_30d", "ret_30d", "ret_90d", "volume"]),
    "oversold": ("Oversold (RSI < 35)", "Sold hard recently: 14-day RSI under 35",
                 [("rsi14", "<", 35)], ("rsi14", False), ["rsi14", "ret_7d", "ret_30d", "from_high_90d", "volume"]),
    "near_high": ("Near 90-day high", "Within 5% of the 90-day closing high",
                  [("from_high_90d", ">", -5)], ("from_high_90d", True), ["from_high_90d", "ret_30d", "rsi14", "volume"]),
    "drawdown": ("Deep drawdown", "More than 40% below the 90-day high",
                 [("from_high_90d", "<", -40)], ("from_high_90d", False), ["from_high_90d", "ret_90d", "rsi14", "volume"]),
}

Fetch = Callable[[list[str]], dict[str, pd.Series]]

_cache: dict[str, tuple[float, tuple[list[dict], dict]]] = {}
_lock = threading.Lock()


def _binance_one(symbol: str, days: int = 180) -> Optional[pd.Series]:
    import requests

    pair = symbol.split("-")[0] + "USDT"
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": pair, "interval": "1d", "limit": days}, timeout=15)
    if r.status_code != 200:
        return None
    rows = r.json()
    if not rows:
        return None
    return pd.Series([float(k[4]) for k in rows], index=pd.to_datetime([k[0] for k in rows], unit="ms"))


def _fetch(tickers: list[str], days: int = 180) -> dict[str, pd.Series]:
    """Binance first (parallel), Yahoo for the rest."""
    from concurrent.futures import ThreadPoolExecutor

    def one(t):
        try:
            return t, _binance_one(t, days)
        except Exception:
            return t, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        got = {t: s for t, s in pool.map(one, tickers) if s is not None and len(s) > 20}
    missing = [t for t in tickers if t not in got]
    if missing:
        try:
            got.update(_yahoo(missing))
        except Exception as exc:
            logger.warning("Yahoo crypto history failed: %s", exc)
    return got


def _yahoo(tickers: list[str]) -> dict[str, pd.Series]:
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    with YF_DOWNLOAD_LOCK:
        df = yf.download(tickers, period="6mo", interval="1d", progress=False, auto_adjust=True, threads=True)
    closes = df["Close"]
    return {t: closes[t].dropna() for t in tickers if t in closes and closes[t].notna().sum()}


def universe(rows: list[dict]) -> list[dict]:
    coins = [
        r for r in rows
        if r.get("symbol", "").endswith("-USD") and r["symbol"].split("-")[0] not in STABLES and (r.get("volume") or 0) > 0
    ]
    if not any(r["symbol"] == "BTC-USD" for r in coins):
        coins.append({"symbol": "BTC-USD", "name": "BTC", "volume": 0})
    return sorted(coins, key=lambda r: -(r.get("volume") or 0))[:UNIVERSE]


def _ret(s: pd.Series, days: int) -> Optional[float]:
    if len(s) <= days:
        return None
    return float(s.iloc[-1] / s.iloc[-1 - days] - 1) * 100


def rsi(s: pd.Series, n: int = 14) -> Optional[float]:
    if len(s) <= n:
        return None
    d = s.diff().dropna()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if loss == 0:
        return 100.0
    return float(100 - 100 / (1 + gain / loss))


def metrics(s: pd.Series, btc_30d: Optional[float]) -> dict:
    s = s.dropna()
    out = {"ret_7d": _ret(s, 7), "ret_30d": _ret(s, 30), "ret_90d": _ret(s, 90), "rsi14": rsi(s)}
    last90 = s.tail(90)
    out["from_high_90d"] = float(s.iloc[-1] / last90.max() - 1) * 100 if len(last90) else None
    ma50 = s.tail(50).mean() if len(s) >= 50 else None
    out["above_ma50"] = float(s.iloc[-1] / ma50 - 1) * 100 if ma50 else None
    daily = s.pct_change().dropna().tail(30)
    out["volatility"] = float(daily.std() * math.sqrt(365) * 100) if len(daily) > 5 else None
    out["vs_btc_30d"] = out["ret_30d"] - btc_30d if out["ret_30d"] is not None and btc_30d is not None else None
    return out


def _passes(m: dict, rules: list) -> bool:
    for field, op, value in rules:
        v = m.get(field)
        if v is None or (op == ">" and not v > value) or (op == "<" and not v < value):
            return False
    return True


def _rule_text(rule) -> str:
    field, op, value = rule
    return f"{LABELS.get(field, field)} {op} {value:g}"


def list_presets() -> list[dict]:
    return [{"key": k, "title": p[0], "description": p[1], "large_only": False, "rules": [_rule_text(r) for r in p[2]]}
            for k, p in PRESETS.items()]


_history: dict[str, tuple[float, dict[str, pd.Series], set[str]]] = {}


def history(coins: list[dict], fetch: Fetch = _fetch, use_cache: bool = True) -> dict[str, pd.Series]:
    """Six months of daily closes for `coins`, cached CACHE_SECONDS (shared by
    the screens and the crypto market mood)."""
    wanted = [c["symbol"] for c in coins]
    if use_cache:
        with _lock:
            hit = _history.get("all")
        if hit and time.time() - hit[0] < CACHE_SECONDS and set(wanted) <= hit[2]:
            return hit[1]
    closes = fetch(wanted)
    if use_cache and closes:
        with _lock:
            _history["all"] = (time.time(), closes, set(wanted))
    return closes


def _measured(rows: Optional[list[dict]], fetch: Fetch, use_cache: bool = False) -> tuple[list[dict], dict]:
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows("crypto")
    coins = universe(rows)
    closes = history(coins, fetch, use_cache)
    btc_30d = _ret(closes["BTC-USD"], 30) if "BTC-USD" in closes else None
    return coins, {sym: metrics(s, btc_30d) for sym, s in closes.items() if len(s) > 20}


def run(key: str, fetch: Fetch = _fetch, rows: Optional[list[dict]] = None, use_cache: bool = True) -> dict:
    if key not in PRESETS:
        raise ValueError(f"Unknown screen '{key}'")
    title, desc, rules, (sort_field, desc_sort), columns = PRESETS[key]
    hit = None
    if use_cache:
        with _lock:
            hit = _cache.get("all")
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        coins, ms = hit[1]
    else:
        coins, ms = _measured(rows, fetch, use_cache)
        if use_cache and ms:
            with _lock:
                _cache["all"] = (time.time(), (coins, ms))

    hits = []
    for c in coins:
        m = ms.get(c["symbol"])
        if m is None:
            continue
        m = {**m, "volume": c.get("volume")}
        if _passes(m, rules):
            hits.append({"symbol": c["symbol"], "name": c.get("name"), "market": "crypto", "market_cap": None,
                         "volume": c.get("volume"), "price": c.get("price"), "currency": "USD",
                         "change_percent": c.get("change_percent"), "sector": None,
                         **{col: m.get(col) for col in columns}})
    hits.sort(key=lambda h: (h.get(sort_field) is None, -(h.get(sort_field) or 0) if desc_sort else (h.get(sort_field) or 0)))
    return {
        "key": key, "title": title, "description": desc, "market": "crypto",
        "rules": [_rule_text(r) for r in rules] or ["Ranked by 24h volume"],
        "columns": [{"key": c, "label": LABELS.get(c, c)} for c in columns],
        "universe": f"{UNIVERSE} most-traded coins (stablecoins excluded)",
        "scanned": len(ms),
        "results": hits[:50],
    }
