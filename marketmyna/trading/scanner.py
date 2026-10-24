"""Market scanner: run trader scans over a universe of stocks.

Daily bars (with today's forming bar last) come from one batched Yahoo
download per universe, so 100-500 stocks take seconds. Intraday scans
(opening-range breakout, VWAP cross) add a batched 5-minute download.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import pandas as pd

from ..core.numbers import finite as _num
from . import indicators as ind

logger = logging.getLogger(__name__)

# id -> (label, group, needs intraday, default parameter, parameter label)
SCANS: dict[str, tuple[str, str, bool, Optional[float], Optional[str]]] = {
    "gap_up": ("Gap up", "Gaps & moves", False, 2.0, "min gap %"),
    "gap_down": ("Gap down", "Gaps & moves", False, 2.0, "min gap %"),
    "big_mover": ("Big mover", "Gaps & moves", False, 3.0, "min move %"),
    "volume_surge": ("Volume surge", "Gaps & moves", False, 2.0, "x 20-day avg"),
    "high_52w": ("New 52-week high", "Breakouts", False, None, None),
    "near_high_52w": ("Near 52-week high", "Breakouts", False, 2.0, "within %"),
    "low_52w": ("New 52-week low", "Breakouts", False, None, None),
    "breakout_20d": ("20-day breakout", "Breakouts", False, 20.0, "days"),
    "breakdown_20d": ("20-day breakdown", "Breakouts", False, 20.0, "days"),
    "rsi_overbought": ("RSI overbought", "Momentum", False, 70.0, "RSI ≥"),
    "rsi_oversold": ("RSI oversold", "Momentum", False, 30.0, "RSI ≤"),
    "ema_cross_up": ("EMA 9/21 bullish cross", "Momentum", False, None, None),
    "ema_cross_down": ("EMA 9/21 bearish cross", "Momentum", False, None, None),
    "supertrend_buy": ("Supertrend turned up", "Momentum", False, None, None),
    "supertrend_sell": ("Supertrend turned down", "Momentum", False, None, None),
    "uptrend": ("Uptrend (price > SMA50 > SMA200)", "Momentum", False, None, None),
    "macd_cross_up": ("MACD bullish cross", "Momentum", False, None, None),
    "macd_cross_down": ("MACD bearish cross", "Momentum", False, None, None),
    "stoch_oversold": ("Stochastic oversold", "Momentum", False, 20.0, "%K ≤"),
    "stoch_overbought": ("Stochastic overbought", "Momentum", False, 80.0, "%K ≥"),
    "mfi_oversold": ("Money flow oversold", "Momentum", False, 20.0, "MFI ≤"),
    "mfi_overbought": ("Money flow overbought", "Momentum", False, 80.0, "MFI ≥"),
    "cci_oversold": ("CCI oversold", "Momentum", False, -100.0, "CCI ≤"),
    "cci_overbought": ("CCI overbought", "Momentum", False, 100.0, "CCI ≥"),
    "adx_strong_up": ("Strong uptrend (ADX)", "Momentum", False, 25.0, "ADX ≥"),
    "adx_strong_down": ("Strong downtrend (ADX)", "Momentum", False, 25.0, "ADX ≥"),
    "ichimoku_above_cloud": ("Above Ichimoku cloud", "Momentum", False, None, None),
    "ichimoku_tk_cross_up": ("Ichimoku Tenkan/Kijun bullish cross", "Momentum", False, None, None),
    "bb_squeeze": ("Bollinger squeeze (inside Keltner)", "Volatility", False, None, None),
    "bb_squeeze_fire_up": ("Squeeze released upward", "Volatility", False, None, None),
    "bb_squeeze_fire_down": ("Squeeze released downward", "Volatility", False, None, None),
    "bb_upper_break": ("Close above upper Bollinger band", "Volatility", False, None, None),
    "bb_lower_break": ("Close below lower Bollinger band", "Volatility", False, None, None),
    "rsi_bull_div": ("RSI bullish divergence", "Divergences", False, None, None),
    "rsi_bear_div": ("RSI bearish divergence", "Divergences", False, None, None),
    "macd_bull_div": ("MACD bullish divergence", "Divergences", False, None, None),
    "macd_bear_div": ("MACD bearish divergence", "Divergences", False, None, None),
    "near_support": ("Near 20-day support", "Patterns", False, 2.0, "within %"),
    "open_low": ("Open = low (bullish)", "Patterns", False, 0.1, "tolerance %"),
    "open_high": ("Open = high (bearish)", "Patterns", False, 0.1, "tolerance %"),
    "inside_day": ("Inside day", "Patterns", False, None, None),
    "nr7": ("NR7 (narrowest range in 7)", "Patterns", False, None, None),
    **{key: (label, "Candlesticks", False, None, None) for key, (label, _) in ind.CANDLE_PATTERNS.items()},
    "orb_up": ("Opening-range breakout up", "Intraday", True, 15.0, "range minutes"),
    "orb_down": ("Opening-range breakdown", "Intraday", True, 15.0, "range minutes"),
    "vwap_cross_up": ("Crossed above VWAP", "Intraday", True, None, None),
    "vwap_cross_down": ("Crossed below VWAP", "Intraday", True, None, None),
}

CACHE_SECONDS = 180
CHUNK = 150


@dataclass(frozen=True)
class Target:
    symbol: str
    market: str


# ------------------------------------------------------------------ data


def _yahoo(symbol: str, market: str) -> str:
    from ..services.analysis_run import yahoo_symbol

    return yahoo_symbol(symbol, market)


def _yf_download(tickers: list[str], interval: str, period: str) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), CHUNK):
        chunk = tickers[i:i + CHUNK]
        with YF_DOWNLOAD_LOCK:
            df = yf.download(chunk, period=period, interval=interval, group_by="ticker", threads=True,
                             progress=False, auto_adjust=False, timeout=20)
        if df is None or df.empty:
            continue
        for t in chunk:
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
            except KeyError:
                continue
            sub = sub.rename(columns=str.lower).dropna(subset=["close"])
            if not sub.empty:
                out[t] = sub
    return out


class BarCache:
    """Short-lived cache so repeated scans and saved scans share downloads."""

    def __init__(self, fetch: Callable[[list[str], str, str], dict[str, pd.DataFrame]] = _yf_download):
        self._fetch = fetch
        self._data: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}
        self._lock = threading.Lock()

    def get(self, tickers: Iterable[str], interval: str, period: str) -> dict[str, pd.DataFrame]:
        now = time.time()
        tickers = list(dict.fromkeys(tickers))
        with self._lock:
            fresh = {t: self._data[(t, interval)][1] for t in tickers
                     if (t, interval) in self._data and now - self._data[(t, interval)][0] < CACHE_SECONDS}
        missing = [t for t in tickers if t not in fresh]
        if missing:
            got = self._fetch(missing, interval, period)
            with self._lock:
                for t, df in got.items():
                    self._data[(t, interval)] = (now, df)
            fresh.update(got)
        return fresh


_cache = BarCache()


# ------------------------------------------------------------------ scans


def evaluate(daily: pd.DataFrame, intraday: Optional[pd.DataFrame], scans: list[str],
             params: dict[str, float]) -> tuple[dict, dict[str, str]]:
    """(metrics, {scan id: why it matched}) for one stock."""
    d = daily.dropna(subset=["close"])
    if len(d) < 3:
        return {}, {}
    today, prev = d.iloc[-1], d.iloc[-2]
    past = d.iloc[:-1]
    close, open_, high, low = float(today["close"]), float(today["open"]), float(today["high"]), float(today["low"])
    prev_close = float(prev["close"])
    change = (close / prev_close - 1) * 100 if prev_close else 0.0
    gap = (open_ / prev_close - 1) * 100 if prev_close else 0.0
    vol = _num(today.get("volume")) or 0.0
    avg_vol = float(past["volume"].tail(20).mean()) if "volume" in past else 0.0
    vol_ratio = vol / avg_vol if avg_vol else None
    rsi_series = ind.rsi(d["close"].astype(float))
    rsi = _num(rsi_series.iloc[-1])
    p = lambda k: params.get(k, SCANS[k][3])  # noqa: E731

    metrics = {"price": close, "change_percent": change, "gap_percent": gap, "volume_ratio": vol_ratio, "rsi": rsi}
    hits: dict[str, str] = {}
    wanted = set(scans)

    def hit(key: str, text: str) -> None:
        if key in wanted:
            hits[key] = text

    if gap >= p("gap_up"):
        hit("gap_up", f"gapped up {gap:+.1f}%")
    if gap <= -p("gap_down"):
        hit("gap_down", f"gapped down {gap:+.1f}%")
    if abs(change) >= p("big_mover"):
        hit("big_mover", f"moved {change:+.1f}%")
    if vol_ratio is not None and vol_ratio >= p("volume_surge"):
        hit("volume_surge", f"volume {vol_ratio:.1f}x average")

    year = past.tail(252)
    if len(year) >= 60:
        hi52, lo52 = float(year["high"].max()), float(year["low"].min())
        metrics["high_52w"], metrics["low_52w"] = hi52, lo52
        if high > hi52:
            hit("high_52w", f"new 52-week high {high:,.2f}")
        if close >= hi52 * (1 - p("near_high_52w") / 100):
            hit("near_high_52w", f"{(close / hi52 - 1) * 100:+.1f}% from 52-week high")
        if low < lo52:
            hit("low_52w", f"new 52-week low {low:,.2f}")

    for key, is_up in (("breakout_20d", True), ("breakdown_20d", False)):
        if key not in wanted:
            continue
        n = int(p(key))
        win = past.tail(n)
        if len(win) == n:
            level = float(win["high"].max()) if is_up else float(win["low"].min())
            if (close > level) if is_up else (close < level):
                hit(key, f"{'above' if is_up else 'below'} {n}-day {'high' if is_up else 'low'} {level:,.2f}")

    if rsi is not None:
        if rsi >= p("rsi_overbought"):
            hit("rsi_overbought", f"RSI {rsi:.0f}")
        if rsi <= p("rsi_oversold"):
            hit("rsi_oversold", f"RSI {rsi:.0f}")

    if len(d) >= 25 and wanted & {"ema_cross_up", "ema_cross_down"}:
        fast, slow = ind.ema(d["close"], 9), ind.ema(d["close"], 21)
        now_diff, before = fast.iloc[-1] - slow.iloc[-1], fast.iloc[-2] - slow.iloc[-2]
        if now_diff > 0 >= before:
            hit("ema_cross_up", "EMA 9 crossed above EMA 21")
        if now_diff < 0 <= before:
            hit("ema_cross_down", "EMA 9 crossed below EMA 21")

    if len(d) >= 15 and wanted & {"supertrend_buy", "supertrend_sell"}:
        _, direction = ind.supertrend(d)
        if direction.iloc[-1] == 1 and direction.iloc[-2] == -1:
            hit("supertrend_buy", "Supertrend flipped up")
        if direction.iloc[-1] == -1 and direction.iloc[-2] == 1:
            hit("supertrend_sell", "Supertrend flipped down")

    if len(d) >= 200:
        sma50, sma200 = float(d["close"].tail(50).mean()), float(d["close"].tail(200).mean())
        if close > sma50 > sma200:
            hit("uptrend", "price > SMA50 > SMA200")

    low20 = float(past["low"].tail(20).min()) if len(past) >= 20 else None
    if low20 and low20 <= close <= low20 * (1 + p("near_support") / 100):
        hit("near_support", f"{(close / low20 - 1) * 100:.1f}% above 20-day low {low20:,.2f}")

    _extended_scans(d, wanted, p, hit)

    tol = lambda k: open_ * p(k) / 100  # noqa: E731
    if abs(open_ - low) <= tol("open_low") and close > open_:
        hit("open_low", "opened at the day's low")
    if abs(open_ - high) <= tol("open_high") and close < open_:
        hit("open_high", "opened at the day's high")
    if high < float(prev["high"]) and low > float(prev["low"]):
        hit("inside_day", "inside yesterday's range")
    if len(d) >= 7:
        ranges = (d["high"] - d["low"]).tail(7)
        if float(ranges.iloc[-1]) <= float(ranges.min()):
            hit("nr7", "narrowest range of 7 days")

    if intraday is not None and len(intraday) >= 3:
        bars = intraday.dropna(subset=["close"])
        days = pd.DatetimeIndex(bars.index).date
        session = bars[days == days[-1]]
        if len(session) >= 2:
            last_close, prev_bar_close = float(session["close"].iloc[-1]), float(session["close"].iloc[-2])
            rng = ind.opening_range(session, int(p("orb_up") if "orb_up" in wanted else p("orb_down")))
            if rng:
                metrics["or_high"], metrics["or_low"] = rng["high"], rng["low"]
                if last_close > rng["high"]:
                    hit("orb_up", f"above opening range {rng['high']:,.2f}")
                if last_close < rng["low"]:
                    hit("orb_down", f"below opening range {rng['low']:,.2f}")
            if session["volume"].sum() > 0:
                vw = ind.vwap(session)
                v_now, v_before = float(vw.iloc[-1]), float(vw.iloc[-2])
                metrics["vwap"] = v_now
                if last_close > v_now and prev_bar_close <= v_before:
                    hit("vwap_cross_up", f"crossed above VWAP {v_now:,.2f}")
                if last_close < v_now and prev_bar_close >= v_before:
                    hit("vwap_cross_down", f"crossed below VWAP {v_now:,.2f}")
    return metrics, hits


def _crossed(a: pd.Series, b: pd.Series) -> int:
    """1 if `a` crossed above `b` on the last bar, -1 if below, else 0."""
    now, before = a.iloc[-1] - b.iloc[-1], a.iloc[-2] - b.iloc[-2]
    if pd.isna(now) or pd.isna(before):
        return 0
    return 1 if now > 0 >= before else -1 if now < 0 <= before else 0


def _extended_scans(d: pd.DataFrame, wanted: set, p: Callable[[str], float], hit: Callable[[str, str], None]) -> None:
    """Oscillator, channel, Ichimoku, candlestick and divergence scans.
    Each block only runs when one of its scans is requested."""
    close = d["close"].astype(float)

    macd_df = None
    if wanted & {"macd_cross_up", "macd_cross_down", "macd_bull_div", "macd_bear_div"} and len(d) >= 35:
        macd_df = ind.macd(close)
        cross = _crossed(macd_df["macd"], macd_df["signal"])
        if cross == 1:
            hit("macd_cross_up", "MACD crossed above signal")
        if cross == -1:
            hit("macd_cross_down", "MACD crossed below signal")

    if wanted & {"stoch_oversold", "stoch_overbought"} and len(d) >= 17:
        k = _num(ind.stochastic(d)["k"].iloc[-1])
        if k is not None and k <= p("stoch_oversold"):
            hit("stoch_oversold", f"%K {k:.0f}")
        if k is not None and k >= p("stoch_overbought"):
            hit("stoch_overbought", f"%K {k:.0f}")

    if wanted & {"mfi_oversold", "mfi_overbought"} and len(d) >= 15:
        m = _num(ind.mfi(d).iloc[-1])
        if m is not None and m <= p("mfi_oversold"):
            hit("mfi_oversold", f"MFI {m:.0f}")
        if m is not None and m >= p("mfi_overbought"):
            hit("mfi_overbought", f"MFI {m:.0f}")

    if wanted & {"cci_oversold", "cci_overbought"} and len(d) >= 20:
        c = _num(ind.cci(d).iloc[-1])
        if c is not None and c <= p("cci_oversold"):
            hit("cci_oversold", f"CCI {c:.0f}")
        if c is not None and c >= p("cci_overbought"):
            hit("cci_overbought", f"CCI {c:.0f}")

    if wanted & {"adx_strong_up", "adx_strong_down"} and len(d) >= 30:
        row = ind.adx(d).iloc[-1]
        a = _num(row["adx"])
        if a is not None and row["plus_di"] > row["minus_di"] and a >= p("adx_strong_up"):
            hit("adx_strong_up", f"ADX {a:.0f}, +DI above -DI")
        if a is not None and row["minus_di"] > row["plus_di"] and a >= p("adx_strong_down"):
            hit("adx_strong_down", f"ADX {a:.0f}, -DI above +DI")

    if wanted & {"ichimoku_above_cloud", "ichimoku_tk_cross_up"} and len(d) >= 80:
        ich = ind.ichimoku(d)
        top = max(float(ich["span_a"].iloc[-1]), float(ich["span_b"].iloc[-1]))
        if float(close.iloc[-1]) > top:
            hit("ichimoku_above_cloud", f"above cloud top {top:,.2f}")
        if _crossed(ich["tenkan"], ich["kijun"]) == 1:
            hit("ichimoku_tk_cross_up", "Tenkan crossed above Kijun")

    if wanted & {"bb_squeeze", "bb_squeeze_fire_up", "bb_squeeze_fire_down", "bb_upper_break", "bb_lower_break"} and len(d) >= 25:
        bb = ind.bollinger(close)
        sq = ind.squeeze(d)
        last = float(close.iloc[-1])
        if bool(sq.iloc[-1]):
            hit("bb_squeeze", f"band width {float(bb['width'].iloc[-1]):.1f}%")
        if bool(sq.iloc[-2]) and not bool(sq.iloc[-1]):
            if last > float(bb["mid"].iloc[-1]):
                hit("bb_squeeze_fire_up", "squeeze ended, close above mid band")
            else:
                hit("bb_squeeze_fire_down", "squeeze ended, close below mid band")
        if last > float(bb["upper"].iloc[-1]):
            hit("bb_upper_break", f"above upper band {float(bb['upper'].iloc[-1]):,.2f}")
        if last < float(bb["lower"].iloc[-1]):
            hit("bb_lower_break", f"below lower band {float(bb['lower'].iloc[-1]):,.2f}")

    if wanted & set(ind.CANDLE_PATTERNS):
        for key in ind.candle_patterns(d):
            hit(key, ind.CANDLE_PATTERNS[key][0].lower())

    if wanted & {"rsi_bull_div", "rsi_bear_div"} and len(d) >= 40:
        kind = ind.divergence(d, ind.rsi(close))
        if kind == "bullish":
            hit("rsi_bull_div", "lower low in price, higher low in RSI")
        if kind == "bearish":
            hit("rsi_bear_div", "higher high in price, lower high in RSI")
    if wanted & {"macd_bull_div", "macd_bear_div"} and macd_df is not None:
        kind = ind.divergence(d, macd_df["macd"])
        if kind == "bullish":
            hit("macd_bull_div", "lower low in price, higher low in MACD")
        if kind == "bearish":
            hit("macd_bear_div", "higher high in price, lower high in MACD")


def run_scan(targets: list[Target], scans: list[str], params: Optional[dict] = None, match: str = "any",
             cache: Optional[BarCache] = None, names: Optional[dict] = None) -> dict:
    """Scan every target. `match` = "any" (at least one scan) or "all"."""
    started = time.time()
    scans = [s for s in scans if s in SCANS]
    params = {k: float(v) for k, v in (params or {}).items() if k in SCANS and v is not None}
    cache = cache or _cache
    by_ticker = {_yahoo(t.symbol, t.market): t for t in targets}
    daily = cache.get(by_ticker.keys(), "1d", "1y")
    intraday: dict[str, pd.DataFrame] = {}
    if any(SCANS[s][2] for s in scans):
        intraday = cache.get(by_ticker.keys(), "5m", "1d")

    rows, failed = [], []
    for ticker, t in by_ticker.items():
        df = daily.get(ticker)
        if df is None or df.empty:
            failed.append(t.symbol)
            continue
        try:
            metrics, hits = evaluate(df, intraday.get(ticker), scans, params)
        except Exception as exc:
            logger.warning("Scan of %s failed: %s", t.symbol, exc)
            failed.append(t.symbol)
            continue
        ok = bool(hits) if match == "any" else len(hits) == len(scans) and bool(scans)
        if ok:
            rows.append({"symbol": t.symbol, "market": t.market, "name": (names or {}).get((t.symbol, t.market)),
                         **metrics, "matched": list(hits), "reasons": list(hits.values())})
    rows.sort(key=lambda r: (-len(r["matched"]), -abs(r.get("change_percent") or 0)))
    return {"rows": rows, "scanned": len(by_ticker) - len(failed), "failed": failed,
            "seconds": round(time.time() - started, 1)}


# ------------------------------------------------------------------ universe


def resolve_universe(spec: dict, config=None) -> tuple[list[Target], dict]:
    """spec: {sources: [top|watchlist|portfolio|custom], market, top_n,
    watchlist_ids, portfolio_names, symbols} -> (targets, names)."""
    from ..data.listings import get_store
    from ..services.schedule_config import source_catalog

    sources = spec.get("sources") or ["top"]
    market = spec.get("market") or "india"
    pairs: list[tuple[str, str]] = []
    names: dict[tuple[str, str], str] = {}
    if "top" in sources:
        n = max(1, min(500, int(spec.get("top_n") or 100)))
        rows = [r for r in get_store().rows(market) if r.get("type") in ("stock", "crypto")]
        key = "volume" if market == "crypto" else "market_cap"
        rows = sorted((r for r in rows if r.get(key)), key=lambda r: -r[key])[:n]
        for r in rows:
            pairs.append((r["symbol"], market))
            names[(r["symbol"], market)] = r.get("name")
    if {"watchlist", "portfolio"} & set(sources):
        cat = source_catalog(config)
        if "portfolio" in sources:
            for p in cat["portfolios"]:
                if not spec.get("portfolio_names") or p["name"] in spec["portfolio_names"]:
                    pairs += [(s["symbol"], s["market"]) for s in p["symbols"]]
        if "watchlist" in sources:
            for w in cat["watchlists"]:
                if not spec.get("watchlist_ids") or w["id"] in spec["watchlist_ids"]:
                    pairs += [(s["symbol"], s["market"]) for s in w["symbols"]]
    if "custom" in sources:
        pairs += [(s.strip().upper(), market) for s in spec.get("symbols") or [] if s.strip()]
    return [Target(s, m) for s, m in dict.fromkeys(pairs)], names


# ------------------------------------------------------------------ saved scans


def scan_markets(universe: dict, targets: list[Target]) -> set[str]:
    return {t.market for t in targets} or {universe.get("market") or "india"}


def run_saved_scans(config, now=None, dispatcher=None, cache: Optional[BarCache] = None, force_id: Optional[int] = None) -> list[dict]:
    """Run saved scans that are due (or just `force_id`), notify new matches.
    Called from AlertMonitor's loop."""
    from datetime import datetime, timedelta

    from ..storage import DatabaseManager, SavedScanRecord, get_db_url
    from .market_hours import is_open

    now = now or datetime.now()
    aware = now.astimezone() if now.tzinfo is None else now
    naive = now.replace(tzinfo=None)
    db = DatabaseManager.instance(get_db_url(config=config))
    with db.get_session() as s:
        q = s.query(SavedScanRecord)
        q = q.filter(SavedScanRecord.id == force_id) if force_id else q.filter(SavedScanRecord.notify.is_(True))
        saved = [{c.name: getattr(r, c.name) for c in SavedScanRecord.__table__.columns} for r in q]

    results = []
    for sc in saved:
        if not force_id:
            due = sc["last_run_at"] is None or naive - sc["last_run_at"] >= timedelta(minutes=sc["interval_minutes"] or 15)
            if not due:
                continue
        targets, names = resolve_universe(sc["universe"] or {}, config)
        if not force_id and not any(is_open(m, aware) for m in scan_markets(sc["universe"] or {}, targets)):
            continue
        out = run_scan(targets, sc["scans"] or [], sc["params"] or {}, sc["match"] or "any", cache=cache, names=names)
        day = naive.strftime("%Y-%m-%d")
        already = set(sc["notified_symbols"] or []) if sc["notified_day"] == day else set()
        fresh = [r for r in out["rows"] if r["symbol"] not in already]
        delivery = {}
        if sc["notify"] and fresh and not force_id:
            delivery = _notify_scan(config, sc["name"], fresh, dispatcher)
            already |= {r["symbol"] for r in fresh}
        with db.get_session() as s:
            rec = s.get(SavedScanRecord, sc["id"])
            if rec is not None:
                rec.last_run_at = naive
                rec.last_count = len(out["rows"])
                rec.notified_day = day
                rec.notified_symbols = sorted(already)
        results.append({"id": sc["id"], "name": sc["name"], **out, "new": [r["symbol"] for r in fresh], "delivery": delivery})
    return results


def _notify_scan(config, name: str, rows: list[dict], dispatcher=None) -> dict:
    from ..notifiers.dispatcher import NotificationDispatcher

    lines = [f"🔎 {name}: {len(rows)} new match{'es' if len(rows) != 1 else ''}"]
    for r in rows[:15]:
        lines.append(f"• {r['symbol']} {r['price']:,.2f} ({r['change_percent']:+.1f}%): {', '.join(r['reasons'][:2])}")
    if len(rows) > 15:
        lines.append(f"…and {len(rows) - 15} more (open Trade → Scanner)")
    try:
        dispatcher = dispatcher or NotificationDispatcher(config)
        return dispatcher.send_all("\n".join(lines), title=f"Scan: {name}", purpose="alert")
    except Exception as exc:
        logger.error("Scan notification failed: %s", exc)
        return {}
