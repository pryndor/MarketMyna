"""Live prices for the Market insights views (Market pulse, Hot stocks,
Market mood, Sector / ETF rotation, World markets, Commodities).

The listings store is a snapshot (India: the last session's exchange file;
US: hourly; China / HK: every 4 hours), and the rotation / mood maths run on
daily closes. While a market is open this module keeps fresh quotes for its
largest names, so the views recompute gainers, losers, breadth, sector moves,
mood readings and the leading / weakening / lagging / improving quadrants on
live prices:

- `market(name)`: quotes for the market's largest names (whole market where
  one call covers it), refreshed in the background while someone is looking
  and the market is open, at most every REFRESH seconds. Requests never wait
  on the upstream source once something is cached.
- `latest(tickers)`: last price of index / futures / FX / ETF tickers from
  one batched 1-minute download, cached LATEST_SECONDS.
- `merge(rows, quotes)` and `extend(series, price, day)` fold those into
  listing rows and daily close series.

Sources: the broker feed for India when it is set up (else the regular feed),
the US screener (whole market, one call), the crypto exchange's tickers (whole
market, one call), batched exchange quotes for China A / Hong Kong.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)

# Seconds between upstream refreshes per market while it is open.
REFRESH = {
    "india": float(os.environ.get("LIVE_MARKET_REFRESH_INDIA", 60)),
    "us": float(os.environ.get("LIVE_MARKET_REFRESH_US", 60)),
    "china_a": float(os.environ.get("LIVE_MARKET_REFRESH_CHINA_A", 60)),
    "hong_kong": float(os.environ.get("LIVE_MARKET_REFRESH_HONG_KONG", 60)),
    "crypto": float(os.environ.get("LIVE_MARKET_REFRESH_CRYPTO", 15)),
}
# The regular feed is slow for hundreds of Indian names and lags anyway.
INDIA_FEED_REFRESH = float(os.environ.get("LIVE_MARKET_REFRESH_INDIA_FEED", 120))
# How many of the largest names get live prices (US and crypto: the whole
# market comes in one call, so everything).
TOP = {
    "india": int(os.environ.get("LIVE_MARKET_TOP_INDIA", 500)),
    "china_a": int(os.environ.get("LIVE_MARKET_TOP_CHINA_A", 1000)),
    "hong_kong": int(os.environ.get("LIVE_MARKET_TOP_HONG_KONG", 600)),
}
WATCH_SECONDS = 120  # nobody asked for two minutes: stop refreshing
MAX_AGE = 18 * 3600  # older quotes are from an earlier session: not used
LATEST_SECONDS = 60
YAHOO_CHUNK = 150
TIMEZONES = {"india": "Asia/Kolkata", "us": "America/New_York", "china_a": "Asia/Shanghai",
             "hong_kong": "Asia/Hong_Kong", "crypto": "UTC"}


def _now() -> float:
    return time.time()


def market_day(market: str, epoch: Optional[float] = None) -> date:
    """The calendar date in the market's own time zone."""
    tz = ZoneInfo(TIMEZONES.get(market, "UTC"))
    return datetime.fromtimestamp(epoch if epoch is not None else _now(), tz).date()


# ------------------------------------------------------------- market quotes


class _State:
    def __init__(self):
        self.quotes: dict[str, dict] = {}  # symbol -> {price, change, change_percent, volume, time, day}
        self.updated = 0.0  # wall clock of the last successful refresh
        self.asked = 0.0  # wall clock of the last request
        self.error: Optional[str] = None
        self.source = ""
        self.busy = False
        self.version = 0
        self.lock = threading.Lock()


_states: dict[str, _State] = {}
_states_lock = threading.Lock()


def _state(name: str) -> _State:
    with _states_lock:
        return _states.setdefault(name, _State())


def _broker_on() -> bool:
    from . import live_quotes

    return live_quotes._broker_live()


def refresh_seconds(name: str) -> float:
    if name == "india" and not _broker_on():
        return INDIA_FEED_REFRESH
    return REFRESH.get(name, 60)


def _source(name: str) -> str:
    from . import live_quotes

    return live_quotes.source(name)


def market(name: str) -> dict:
    """{"quotes": {symbol: quote}, "status": {...}} for one market. Starts a
    background refresh when due; returns at once with what is cached."""
    from ..trading.market_hours import is_open

    s = _state(name)
    now = _now()
    open_now = is_open(name)
    with s.lock:
        s.asked = now
        age = now - s.updated if s.updated else None
        due = age is None or age >= MAX_AGE or (open_now and age >= refresh_seconds(name))
        start = due and not s.busy and name in REFRESH
        if start:
            s.busy = True
        fresh = age is not None and age < MAX_AGE
        quotes = dict(s.quotes) if fresh else {}
    # The tables' per-second cache (live_quotes) is fresher for the names on
    # someone's screen: take those prices too.
    if quotes:
        quotes.update(_table_quotes(name, quotes))
    with s.lock:
        status = {
            "open": open_now,
            "live": bool(quotes),
            "updated": s.updated or None,
            "age_seconds": round(age, 1) if age is not None else None,
            "refresh_seconds": refresh_seconds(name),
            "covered": len(quotes),
            "source": s.source or _source(name),
            "error": s.error,
            "version": s.version,
        }
    if start:
        threading.Thread(target=_refresh, args=(name,), name=f"live-market-{name}", daemon=True).start()
    return {"quotes": quotes, "status": status}


def _table_quotes(name: str, quotes: dict[str, dict]) -> dict[str, dict]:
    """Quotes from the tables' cache that are newer than ours, with the
    trading day added."""
    from . import live_quotes

    m = live_quotes._markets.get(name)
    if m is None:
        return {}
    with m.lock:
        table = dict(m.quotes)
    out = {}
    for sym, q in table.items():
        mine = quotes.get(sym)
        if mine is not None and q.get("price") and (q.get("time") or 0) > (mine.get("time") or 0):
            out[sym] = {**q, "day": market_day(name, q.get("time"))}
    return out


def _universe(name: str) -> list[str]:
    """Symbols of the market's largest names, biggest first."""
    from ..data.listings import get_store

    if name not in TOP:
        return []
    rows = [r for r in get_store().rows(name) if r.get("type") == "stock" and r.get("market_cap")]
    rows.sort(key=lambda r: -r["market_cap"])
    return [r["symbol"] for r in rows[:TOP[name]]]


def _refresh(name: str) -> None:
    s = _state(name)
    try:
        fresh = FETCHERS[name](_universe(name))
        if not fresh:
            raise RuntimeError("no quotes returned")
        error = None
    except Exception as exc:  # keep serving the last quotes
        logger.warning("Live market prices for %s failed: %s", name, exc)
        fresh, error = {}, "Live prices are temporarily unavailable; showing the last ones."
    with s.lock:
        if fresh:
            s.quotes = fresh
            s.updated = _now()
            s.version += 1
        s.error = error
        s.source = _source(name)
        s.busy = False


def _fetch_us(_symbols: list[str]) -> dict[str, dict]:
    """The whole US market from the screener, one call."""
    from ..data.listings import _float, _nasdaq_screener
    from ..trading.market_hours import is_open

    now = _now()
    day = market_day("us", now) if is_open("us") else None
    out = {}
    for r in _nasdaq_screener("stocks"):
        sym = (r.get("symbol") or "").strip().replace("/", "-").replace("^", "-P")
        price = _float(r.get("lastsale"))
        if not sym or not price:
            continue
        out[sym] = {"price": price, "change": _float(r.get("netchange")), "change_percent": _float(r.get("pctchange")),
                    "volume": _float(r.get("volume")), "time": now, "day": day}
    return out


def _fetch_crypto(_symbols: list[str]) -> dict[str, dict]:
    """Every USDT pair's 24-hour ticker, one call."""
    import requests

    r = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=15)
    r.raise_for_status()
    now = _now()
    day = market_day("crypto", now)
    out = {}
    for t in r.json():
        pair = t.get("symbol", "")
        if not pair.endswith("USDT"):
            continue
        price = _num(t.get("lastPrice"))
        if price:
            out[f"{pair[:-4]}-USD"] = {"price": price, "change": _num(t.get("priceChange")),
                                       "change_percent": _num(t.get("priceChangePercent")),
                                       "volume": _num(t.get("quoteVolume")), "time": now, "day": day}
    return out


def _tencent(symbols: list[str], name: str) -> dict[str, dict]:
    from ..data.extra_sources import tencent_symbol
    from ..data.listings import _tencent_quote_lines

    tz = ZoneInfo(TIMEZONES[name])
    out = {}
    for f in _tencent_quote_lines([tencent_symbol(c, name) for c in symbols]):
        if len(f) < 33 or not f[2]:
            continue
        price = _num(f[3])
        if not price:
            continue
        try:
            stamp = datetime.strptime(f[30][:14], "%Y%m%d%H%M%S").replace(tzinfo=tz)
        except (ValueError, IndexError):
            stamp = datetime.now(tz)
        vol = _num(f[6])
        if vol is not None and name == "china_a":
            vol *= 100  # lots of 100 shares
        out[f[2]] = {"price": price, "change": _num(f[31]), "change_percent": _num(f[32]), "volume": vol,
                     "time": stamp.timestamp(), "day": stamp.date()}
    return out


def _fetch_india(symbols: list[str]) -> dict[str, dict]:
    """Broker feed when it is set up (live); the regular feed otherwise, or
    for names the broker can't price."""
    out: dict[str, dict] = {}
    if _broker_on():
        from . import live_quotes
        from .brokers import angel

        try:
            for sym, q in angel.client(live_quotes._broker_config()).quotes(symbols).items():
                out[sym] = {**q, "day": market_day("india", q.get("time"))}
        except Exception as exc:
            logger.warning("Broker quotes for the live market failed, using the regular feed: %s", exc)
    rest = [s for s in symbols if s not in out]
    if rest:
        out.update(_yahoo_daily(rest, "india"))
    return out


def _yahoo_daily(symbols: list[str], name: str) -> dict[str, dict]:
    """Today's bar so far (price, change vs the previous close, volume) for
    many names: daily bars are far lighter than minute bars."""
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK
    from .analysis_run import yahoo_symbol

    out: dict[str, dict] = {}
    now = _now()
    for i in range(0, len(symbols), YAHOO_CHUNK):
        tickers = {yahoo_symbol(s, name): s for s in symbols[i:i + YAHOO_CHUNK]}
        with YF_DOWNLOAD_LOCK:
            df = yf.download(list(tickers), period="5d", interval="1d", group_by="ticker", progress=False,
                             threads=True, auto_adjust=False, timeout=20)
        if df is None or df.empty:
            continue
        for yt, sym in tickers.items():
            try:
                frame = (df[yt] if isinstance(df.columns, pd.MultiIndex) else df).dropna(subset=["Close"])
            except KeyError:
                continue
            if len(frame) < 2:
                continue
            price, prev = float(frame["Close"].iloc[-1]), float(frame["Close"].iloc[-2])
            out[sym] = {"price": round(price, 4), "change": round(price - prev, 4),
                        "change_percent": round((price / prev - 1) * 100, 2) if prev else None,
                        "volume": _num(frame["Volume"].iloc[-1]) if "Volume" in frame else None,
                        "time": now, "day": pd.Timestamp(frame.index[-1]).date()}
    return out


FETCHERS = {
    "india": _fetch_india,
    "us": _fetch_us,
    "crypto": _fetch_crypto,
    "china_a": lambda symbols: _tencent(symbols, "china_a"),
    "hong_kong": lambda symbols: _tencent(symbols, "hong_kong"),
}


def merge(rows: list[dict], quotes: dict[str, dict], only_live: bool = False) -> list[dict]:
    """Listing rows with live price, change and volume folded in; the 52-week
    range widens when a live price breaks it and market cap moves with price.
    `only_live` drops rows of the quoted kind that have no live quote, so
    today's moves are never mixed with an earlier session's."""
    if not quotes:
        return rows
    out = []
    for r in rows:
        q = quotes.get(r.get("symbol"))
        if q is None:
            if not (only_live and r.get("type") in ("stock", "crypto")):
                out.append(r)
            continue
        new = dict(r)
        price, old = q["price"], r.get("price")
        new["price"] = price
        for key in ("change", "change_percent", "volume"):
            if q.get(key) is not None:
                new[key] = q[key]
        if r.get("market_cap") and old:
            new["market_cap"] = r["market_cap"] * price / old
        if r.get("high_52w"):
            new["high_52w"] = max(r["high_52w"], price)
        if r.get("low_52w"):
            new["low_52w"] = min(r["low_52w"], price)
        new["live"] = True
        out.append(new)
    return out


# ------------------------------------------------------------ latest tickers

_latest: dict[str, tuple[float, dict]] = {}
_latest_lock = threading.Lock()
_latest_busy: set[str] = set()


def latest(tickers: list[str], wait: bool = True) -> dict[str, dict]:
    """ticker -> {price, day, time} from one batched 1-minute download.
    Cached LATEST_SECONDS; stale tickers refresh in the background, and only
    tickers never seen before are fetched inline (when `wait`)."""
    now = _now()
    tickers = list(dict.fromkeys(tickers))
    with _latest_lock:
        have = {t: v for t, (at, v) in _latest.items() if t in tickers}
        stale = [t for t in tickers if t not in _latest or now - _latest[t][0] >= LATEST_SECONDS]
        stale = [t for t in stale if t not in _latest_busy]
        _latest_busy.update(stale)
    missing = [t for t in stale if t not in have]
    background = [t for t in stale if t in have]
    if missing:
        if wait:
            _fill_latest(missing)
        else:
            background += missing
    if background:
        threading.Thread(target=_fill_latest, args=(background,), name="live-latest", daemon=True).start()
    with _latest_lock:
        return {t: _latest[t][1] for t in tickers if t in _latest}


def _fill_latest(tickers: list[str]) -> None:
    try:
        got = _yahoo_latest(tickers)
    except Exception as exc:
        logger.info("Latest prices failed: %s", exc)
        got = {}
    now = _now()
    with _latest_lock:
        for t in tickers:
            _latest_busy.discard(t)
            if t in got:
                _latest[t] = (now, got[t])


def _yahoo_latest(tickers: list[str]) -> dict[str, dict]:
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    with YF_DOWNLOAD_LOCK:
        df = yf.download(tickers, period="5d", interval="1m", group_by="ticker", progress=False,
                         threads=True, auto_adjust=False, prepost=False, timeout=15)
    out = {}
    if df is None or df.empty:
        return out
    for t in tickers:
        try:
            frame = (df[t] if isinstance(df.columns, pd.MultiIndex) else df).dropna(subset=["Close"])
        except KeyError:
            continue
        if frame.empty:
            continue
        stamp = pd.Timestamp(frame.index[-1])
        out[t] = {"price": float(frame["Close"].iloc[-1]), "day": stamp.date(), "time": stamp.timestamp()}
    return out


def extend(series: pd.Series, price: Optional[float], day: Optional[date]) -> pd.Series:
    """A daily close series with `price` as the close of `day`: replaces the
    last bar when it is that day, appends one when the day is newer, and
    leaves the series alone for an older day (or no price)."""
    if price is None or day is None or series is None or not len(series):
        return series
    last = pd.Timestamp(series.index[-1])
    if last.date() > day:
        return series
    s = series.copy()
    if last.date() == day:
        s.iloc[-1] = price
        return s
    stamp = pd.Timestamp(day)
    if last.tzinfo is not None:
        stamp = stamp.tz_localize(last.tzinfo)
    s.loc[stamp] = price
    return s


def extend_all(closes: dict[str, pd.Series], prices: dict[str, dict]) -> dict[str, pd.Series]:
    """`extend` for every series that has a live {price, day}."""
    out = dict(closes)
    for t, q in prices.items():
        if t in out and q:
            out[t] = extend(out[t], q.get("price"), q.get("day"))
    return out


def for_tickers(name: str, quotes: dict[str, dict]) -> dict[str, dict]:
    """Market quotes keyed by the app's symbols -> keyed by Yahoo tickers,
    for `extend_all` on daily close series."""
    from .analysis_run import yahoo_symbol

    return {yahoo_symbol(sym, name): q for sym, q in quotes.items()}


def status_for(prices: dict[str, dict], source: str = "Market data feed, can lag up to 15 min") -> dict:
    """The `live` block for views priced by `latest` (no market cache):
    live while something in it traded in the last 15 minutes."""
    times = [q["time"] for q in prices.values() if q.get("time")]
    newest = max(times) if times else None
    age = _now() - newest if newest else None
    return {"open": age is not None and age < 900, "live": bool(prices), "updated": newest,
            "age_seconds": round(age, 1) if age is not None else None, "refresh_seconds": LATEST_SECONDS,
            "covered": len(prices), "source": source, "error": None, "version": None}


_memo: dict[tuple, tuple[float, object]] = {}
_memo_lock = threading.Lock()
MEMO_SECONDS = 15


def memo(key: tuple, fn, seconds: float = MEMO_SECONDS):
    """fn() shared by every request for `seconds`: many people polling a
    view cost one recomputation per interval."""
    now = _now()
    with _memo_lock:
        hit = _memo.get(key)
    if hit and now - hit[0] < seconds:
        return hit[1]
    value = fn()
    with _memo_lock:
        _memo[key] = (now, value)
    return value


def _num(value) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # NaN -> None
