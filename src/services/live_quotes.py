"""Live prices for the rows on screen (Markets, Watchlist), shared by all users.

The Markets listing is a whole-market snapshot refreshed every few hours.
This module keeps a small cache of fresh quotes for just the symbols people
are looking at:

- Browsers ask every second (cheap: the answer comes from this cache).
- The cache refreshes each market in the background, one batched upstream
  call for every symbol anyone is watching, at most every REFRESH[market]
  seconds. 1,000 users on the same page cost the data source the same as one.
- Free sources: Yahoo for stocks / ETFs (can lag up to ~15 min for NSE),
  Binance for crypto (real time). A licensed broker feed (Kite Connect,
  Upstox, SmartAPI websockets) can replace `_fetch_*` for true tick data.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Seconds between upstream refreshes per market (env LIVE_REFRESH_<MARKET>).
REFRESH = {
    "india": float(os.environ.get("LIVE_REFRESH_INDIA", 15)),
    "us": float(os.environ.get("LIVE_REFRESH_US", 15)),
    "china_a": float(os.environ.get("LIVE_REFRESH_CHINA_A", 30)),
    "hong_kong": float(os.environ.get("LIVE_REFRESH_HONG_KONG", 30)),
    "crypto": float(os.environ.get("LIVE_REFRESH_CRYPTO", 2)),
}
# With a broker feed (Angel One) Indian prices refresh every second.
BROKER_REFRESH = float(os.environ.get("LIVE_REFRESH_BROKER", 1))
WATCH_SECONDS = 60  # a symbol nobody asked about for a minute stops being fetched
MAX_SYMBOLS = 100  # per request (one page of the table)
SOURCE = {"crypto": "Crypto exchange, real time"}
DEFAULT_SOURCE = "Market data feed, can lag up to 15 min"


class _Market:
    def __init__(self):
        self.quotes: dict[str, dict] = {}  # symbol -> {price, change, change_percent, volume, time}
        self.watched: dict[str, float] = {}  # symbol -> last asked (monotonic)
        self.fetched_at = 0.0
        self.error: Optional[str] = None
        self.busy = False
        self.lock = threading.Lock()


_markets: dict[str, _Market] = {}
_lock = threading.Lock()


def _market(name: str) -> _Market:
    with _lock:
        return _markets.setdefault(name, _Market())


def get(market: str, symbols: list[str], depth: bool = False) -> dict:
    """Latest cached quotes for `symbols`; starts a background refresh when
    the market's cache is older than its refresh interval. Never blocks on
    the upstream source. The order book (broker feed only) is left out
    unless `depth`, so the tables' per-second poll stays small."""
    from ..trading.market_hours import is_open

    m = _market(market)
    now = time.monotonic()
    symbols = [s.strip().upper() for s in symbols if s.strip()][:MAX_SYMBOLS]
    open_now = is_open(market)
    with m.lock:
        for s in symbols:
            m.watched[s] = now
        stale = now - m.fetched_at >= refresh_seconds(market)
        missing = any(s not in m.quotes for s in symbols)
        start = (stale and (open_now or missing)) and not m.busy and market in REFRESH
        if start:
            m.busy = True
        out = {s: m.quotes[s] if depth else {k: v for k, v in m.quotes[s].items() if k != "depth"}
               for s in symbols if s in m.quotes}
        age = None if not m.fetched_at else round(now - m.fetched_at, 1)
        error = m.error
    if start:
        threading.Thread(target=_refresh, args=(market,), name=f"live-quotes-{market}", daemon=True).start()
    return {
        "market": market,
        "open": open_now,
        "quotes": out,
        "age_seconds": age,
        "refresh_seconds": refresh_seconds(market),
        "source": source(market),
        "error": error,
        # Newest trade time among these quotes (epoch seconds). During "market
        # hours" on a holiday this stays at the last session's close.
        "last_trade": max((q.get("time") or 0 for q in out.values()), default=None) or None,
    }


def _refresh(market: str) -> None:
    m = _market(market)
    now = time.monotonic()
    with m.lock:
        m.watched = {s: t for s, t in m.watched.items() if now - t < WATCH_SECONDS}
        symbols = list(m.watched)
    try:
        fresh = (_fetch_crypto(symbols) if market == "crypto" else _fetch_india(symbols) if market == "india"
                 else _fetch_us(symbols) if market == "us" else _fetch_yahoo(symbols, market))
        error = None
    except Exception as exc:  # keep serving the last quotes
        logger.warning("Live quotes for %s failed: %s", market, exc)
        fresh, error = {}, "Live prices are temporarily unavailable; showing the last ones."
    with m.lock:
        m.quotes.update(fresh)
        m.fetched_at = time.monotonic()
        m.error = error
        m.busy = False


def _broker_config():
    """App config when Angel One is set up (admin panel or env), else None."""
    try:
        from api.deps import get_config_dep

        from .brokers import angel

        config = get_config_dep()
        return config if angel.configured(config) else None
    except Exception:
        return None


_broker_failed_at = 0.0


def _broker_live() -> bool:
    # After a broker failure, a minute at the normal pace (Yahoo can't take 1 s polling).
    return _broker_config() is not None and time.monotonic() - _broker_failed_at > 60


def _finnhub_config():
    try:
        from api.deps import get_config_dep

        from .brokers import finnhub

        config = get_config_dep()
        return config if finnhub.configured(config) else None
    except Exception:
        return None


_yahoo_us_at = 0.0


def _fetch_us(symbols: list[str]) -> dict[str, dict]:
    """Finnhub's trade stream when a key is set (real time); Yahoo otherwise.
    Symbols Finnhub has no price for yet are filled from Yahoo, at Yahoo's
    normal 15 s pace."""
    global _yahoo_us_at
    config = _finnhub_config()
    if config is None:
        return _fetch_yahoo(symbols, "us")
    from .brokers import finnhub

    s = finnhub.stream(config)
    s.want(symbols)
    out = s.quotes(symbols)
    rest = [x for x in symbols if x not in out]
    if rest and time.monotonic() - _yahoo_us_at >= REFRESH["us"]:
        _yahoo_us_at = time.monotonic()
        try:
            out.update(_fetch_yahoo(rest, "us"))
        except Exception:
            pass
    return out


def refresh_seconds(market: str) -> float:
    if market == "us" and _finnhub_config() is not None:
        return 1.0
    if market == "india" and _broker_live():
        # Every second for one batch of 50; slower when more symbols are watched,
        # so the shared Angel account stays under its hourly call limit.
        from .brokers.angel import BATCH, CALLS_PER_SECOND

        batches = max(1, -(-len(_market("india").watched) // BATCH))
        return max(BROKER_REFRESH, batches / CALLS_PER_SECOND)
    return REFRESH.get(market, 30)


def source(market: str) -> str:
    if market == "us" and _finnhub_config() is not None:
        return "Real-time feed"
    if market == "india" and _broker_live():
        return "Broker feed, live"
    return SOURCE.get(market, DEFAULT_SOURCE)


def _fetch_india(symbols: list[str]) -> dict[str, dict]:
    """Angel One when configured (live); Yahoo otherwise or if it fails.
    Symbols Angel can't price (e.g. BSE-only) are filled from Yahoo."""
    global _broker_failed_at
    config = _broker_config()
    # During the minute after a failure (e.g. Angel's rate limit) stay on Yahoo.
    if config is None or time.monotonic() - _broker_failed_at <= 60:
        return _fetch_yahoo(symbols, "india")
    from .brokers import angel

    try:
        out = angel.client(config).quotes(symbols)
    except Exception as exc:
        logger.warning("Angel One quotes failed, using Yahoo: %s", exc)
        _broker_failed_at = time.monotonic()
        return _fetch_yahoo(symbols, "india")
    rest = [s for s in symbols if s not in out]
    if rest:
        try:
            out.update(_fetch_yahoo(rest, "india"))
        except Exception:
            pass
    return out


def _fetch_crypto(symbols: list[str]) -> dict[str, dict]:
    """Binance 24h tickers for BASE-USD symbols (USDT pairs), one request."""
    import json

    import requests

    pairs = {f"{s.split('-')[0]}USDT": s for s in symbols if s}
    if not pairs:
        return {}
    r = requests.get("https://api.binance.com/api/v3/ticker/24hr",
                     params={"symbols": json.dumps(list(pairs), separators=(",", ":"))}, timeout=10)
    r.raise_for_status()
    stamp = time.time()
    out = {}
    for t in r.json():
        sym = pairs.get(t.get("symbol"))
        price = _num(t.get("lastPrice"))
        if sym and price:
            out[sym] = {"price": price, "change": _num(t.get("priceChange")),
                        "change_percent": _num(t.get("priceChangePercent")),
                        "volume": _num(t.get("quoteVolume")), "time": stamp}
    return out


def _fetch_yahoo(symbols: list[str], market: str) -> dict[str, dict]:
    """One batched 1-minute download for every watched symbol: last trade,
    change against the previous session's close, and today's volume."""
    import pandas as pd
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK
    from .analysis_run import yahoo_symbol

    if not symbols:
        return {}
    tickers = {yahoo_symbol(s, market): s for s in symbols}
    with YF_DOWNLOAD_LOCK:
        df = yf.download(list(tickers), period="5d", interval="1m", group_by="ticker", progress=False,
                         threads=True, auto_adjust=False, prepost=False)
    out = {}
    for yt, sym in tickers.items():
        try:
            # group_by="ticker" nests columns under the ticker even for one
            # symbol in current yfinance; older releases returned them flat.
            frame = df[yt] if len(tickers) > 1 or isinstance(df.columns, pd.MultiIndex) else df
            frame = frame.dropna(subset=["Close"])
        except (KeyError, TypeError):
            continue
        if frame.empty:
            continue
        last_day = frame.index[-1].date()
        today = frame[frame.index.date == last_day]
        before = frame[frame.index.date < last_day]
        price = float(today["Close"].iloc[-1])
        prev = float(before["Close"].iloc[-1]) if not before.empty else None
        change = price - prev if prev else None
        out[sym] = {
            "price": round(price, 4),
            "change": round(change, 4) if change is not None else None,
            "change_percent": round(change / prev * 100, 2) if prev else None,
            "volume": float(today["Volume"].sum()) if "Volume" in today else None,
            "time": frame.index[-1].timestamp(),
        }
    return out


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
