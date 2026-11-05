"""Stocks to watch (today, this week, this month) and new stock ideas.

Built for the Markets page next to "Trending". The AI notes on a list need
an AI model (Settings -> AI keys, or LLM_MODEL) - see notes().

Universe: the largest UNIVERSE stocks by market cap in the market. History:
one year of daily closes and volume, cached HISTORY_TTL and refreshed in the
background; today's bar comes from the listing row (live prices merged in by
live_market while the market is open), so the day boards move with prices.

Boards (every row says why it is there, with numbers - facts, not calls):

  day    up on heavy volume / down on heavy volume / breaking out (above the
         prior 20-day high) / bouncing after a weak week / near the 52-week high
  week   strongest / weakest week / volume building, price steady / weekly
         breakout (above the prior 4-week high) / pullback in an uptrend
  month  strongest / weakest month / new 3-month high / trend turning up
         (crossed above the 50-day average this month) / oversold, steadying
  ideas  fundamentals (the same cached company info as Trending) plus a fresh
         trend turn: quality turning up / fresh 52-week high, profitable /
         growth at a fair price / beaten-down quality steadying. A row is
         "new" when it was not on the ideas list a week ago (a daily snapshot
         is kept on disk).

Each row also carries watch levels: the 20-day high and low before today.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from ..core.numbers import finite as _f

logger = logging.getLogger(__name__)

MARKETS = ("india", "us", "china_a", "hong_kong")
PERIODS = ("day", "week", "month", "ideas")
UNIVERSE = 300
TOP = 20
HISTORY_TTL = 6 * 3600   # daily history; today's bar comes from the listings
HISTORY_STALE = 36 * 3600  # older than this: fetch inline instead of serving it
NOTES_TTL = 3600

History = Callable[[list[str]], dict[str, pd.DataFrame]]

_history: dict[str, tuple[float, dict]] = {}
_notes: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


# ------------------------------------------------------------------ measures


def _rsi(closes: pd.Series, n: int = 14) -> float | None:
    if len(closes) <= n:
        return None
    d = closes.diff().dropna()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    g, lo = float(gain.iloc[-1]), float(loss.iloc[-1])
    return 100.0 if lo == 0 else round(100 - 100 / (1 + g / lo), 1)


def _ret(c: pd.Series, n: int) -> float | None:
    return (float(c.iloc[-1]) / float(c.iloc[-1 - n]) - 1) * 100 if len(c) > n and c.iloc[-1 - n] else None


def _ratio(a: float, b: float) -> float | None:
    return a / b if b and not math.isnan(b) and not math.isnan(a) else None


def measure(closes: pd.Series, volumes: pd.Series) -> dict | None:
    """Readings on a daily series whose LAST bar is today."""
    c = closes.astype(float).dropna()
    v = volumes.astype(float).reindex(c.index).fillna(0)
    if len(c) < 30:
        return None
    price = float(c.iloc[-1])
    prev = c.iloc[:-1]
    pv = v.iloc[:-1]
    avg = lambda s, n: float(s.iloc[-n:].mean()) if len(s) >= n else math.nan  # noqa: E731
    sma50 = avg(c, 50)
    sma200 = avg(c, 200)
    sma50_month_ago = float(c.iloc[-71:-21].mean()) if len(c) >= 71 else math.nan
    high_252 = float(prev.iloc[-251:].max())
    # Days since the stock last closed at its (then) one-year high, before today.
    last_high_ago = None
    roll = prev.rolling(252, min_periods=60).max()
    at_high = prev[prev >= roll * 0.9999]
    if len(at_high):
        last_high_ago = int(len(prev) - prev.index.get_loc(at_high.index[-1]) - 1)
    return {
        "price": price,
        "r1d": _ret(c, 1), "r5d": _ret(c, 5),
        "r21d": _ret(c, 21), "r63d": _ret(c, 63),
        "r_before": _ret(prev, 4),  # the 4 sessions before today
        "vol_day": _ratio(float(v.iloc[-1]), avg(pv, 20)),
        "vol_week": _ratio(avg(v, 5), avg(v.iloc[:-5], 50)),
        "vol_month": _ratio(avg(v, 21), avg(v.iloc[:-21], 63)),
        "high_20": float(prev.iloc[-20:].max()), "low_20": float(prev.iloc[-20:].min()),
        "high_prior_20_before_week": float(c.iloc[-25:-5].max()) if len(c) >= 25 else math.nan,
        "high_63_prior": float(prev.iloc[-63:].max()),
        "high_252": high_252, "low_252": float(prev.iloc[-251:].min()),
        "last_high_ago": last_high_ago,
        "sma50": sma50, "sma200": sma200,
        "above_50": price > sma50 if not math.isnan(sma50) else None,
        "was_below_50": float(c.iloc[-22]) < sma50_month_ago if not math.isnan(sma50_month_ago) else None,
        "above_200": price > sma200 if not math.isnan(sma200) else None,
        "rsi": _rsi(c),
        "rsi_week_ago": _rsi(c.iloc[:-5]),
        "from_high": (price / max(high_252, price) - 1) * 100,
    }


# ------------------------------------------------------------------ data


def _yahoo_history(tickers: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), 150):
        chunk = tickers[i:i + 150]
        with YF_DOWNLOAD_LOCK:
            df = yf.download(chunk, period="1y", interval="1d", group_by="ticker", progress=False,
                             threads=True, auto_adjust=False, timeout=20)
        if df is None or df.empty:
            continue
        for t in chunk:
            try:
                f = (df[t] if isinstance(df.columns, pd.MultiIndex) else df)[["Close", "Volume"]].dropna(subset=["Close"])
            except KeyError:
                continue
            if len(f) >= 30:
                f.index = pd.to_datetime(f.index).tz_localize(None).normalize()
                out[t] = f
    return out


def _universe(market: str, rows: list[dict]) -> list[dict]:
    stocks = [r for r in rows if r.get("type") == "stock" and _f(r.get("market_cap")) and _f(r.get("price"))]
    stocks.sort(key=lambda r: -r["market_cap"])
    picked, seen = [], set()
    for r in stocks:
        name = (r.get("name") or r["symbol"]).lower()[:24]
        if name in seen:  # second share class of the same company
            continue
        seen.add(name)
        picked.append(r)
        if len(picked) >= UNIVERSE:
            break
    return picked


def _history_for(market: str, tickers: list[str], fetch: History) -> dict[str, pd.DataFrame]:
    from ..utils.swr import refresh_later

    def load() -> dict:
        data = fetch(tickers)
        if data:
            with _lock:
                _history[market] = (time.time(), data)
        return data

    with _lock:
        hit = _history.get(market)
    if hit:
        age = time.time() - hit[0]
        if age < HISTORY_TTL:
            return hit[1]
        if age < HISTORY_STALE:
            refresh_later(("stocks_to_watch", market), load)
            return hit[1]
    return load()


def _with_today(frame: pd.DataFrame, row: dict, today: date) -> tuple[pd.Series, pd.Series]:
    """History before today plus today's bar from the listing row."""
    day = row.get("close_date")
    try:
        day = pd.Timestamp(day).normalize() if day else pd.Timestamp(today)
    except (ValueError, TypeError):
        day = pd.Timestamp(today)
    before = frame[frame.index < day]
    closes = pd.concat([before["Close"], pd.Series([float(row["price"])], index=[day])])
    volumes = pd.concat([before["Volume"], pd.Series([float(row.get("volume") or 0)], index=[day])])
    return closes, volumes


# ------------------------------------------------------------------ boards


def _pct(v: float | None, d: int = 1) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:+.{d}f}%"


def _x(v: float | None) -> str:
    return f"{v:.1f}×" if v else "—"


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _board(key: str, title: str, description: str, hits: list[tuple[dict, dict, str]]) -> dict:
    rows = []
    for r, m, why in hits[:TOP]:
        rows.append({
            "symbol": r["symbol"], "name": r.get("name"), "market": r.get("market"),
            "price": r.get("price"), "change_percent": r.get("change_percent"), "currency": r.get("currency"),
            "sector": r.get("category") or r.get("sector"), "market_cap": r.get("market_cap"),
            "why": why, "watch_high": m.get("high_20"), "watch_low": m.get("low_20"),
            "r5d": m.get("r5d"), "r21d": m.get("r21d"), "rsi": m.get("rsi"), "new": m.get("new", False),
            "since": m.get("since"),
        })
    return {"key": key, "title": title, "description": description, "rows": rows}


def day_boards(items: list[tuple[dict, dict]]) -> list[dict]:
    g = lambda m, k: m.get(k) if _ok(m.get(k)) else math.nan  # noqa: E731
    up_vol = sorted([(r, m) for r, m in items if g(m, "r1d") >= 2 and g(m, "vol_day") >= 1.8],
                    key=lambda t: -t[1]["r1d"] * min(t[1]["vol_day"], 5))
    down_vol = sorted([(r, m) for r, m in items if g(m, "r1d") <= -2 and g(m, "vol_day") >= 1.8],
                      key=lambda t: t[1]["r1d"] * min(t[1]["vol_day"], 5))
    breakout = sorted([(r, m) for r, m in items if m["price"] > g(m, "high_20") and g(m, "r1d") > 0],
                      key=lambda t: -(t[1]["vol_day"] or 0))
    bounce = sorted([(r, m) for r, m in items if g(m, "r1d") >= 2 and g(m, "r_before") <= -5],
                    key=lambda t: -t[1]["r1d"])
    near_high = sorted([(r, m) for r, m in items if g(m, "from_high") >= -1.5 and g(m, "r1d") >= 0],
                       key=lambda t: -t[1]["from_high"])
    return [
        _board("up_volume", "Up on heavy volume", "Up 2% or more today on at least 1.8× the usual 20-day volume",
               [(r, m, f"{_pct(m['r1d'])} today on {_x(m['vol_day'])} usual volume") for r, m in up_vol]),
        _board("down_volume", "Down on heavy volume", "Down 2% or more today on at least 1.8× the usual 20-day volume",
               [(r, m, f"{_pct(m['r1d'])} today on {_x(m['vol_day'])} usual volume") for r, m in down_vol]),
        _board("breakout", "Breaking out", "Trading above its highest close of the last 20 days, up today",
               [(r, m, f"above the 20-day high {m['high_20']:,.2f}, {_pct(m['r1d'])} today, {_x(m['vol_day'])} volume")
                for r, m in breakout]),
        _board("bounce", "Bouncing after a weak week", "Up 2% or more today after falling 5% or more over the 4 sessions before",
               [(r, m, f"{_pct(m['r1d'])} today after {_pct(m['r_before'])} over the 4 sessions before") for r, m in bounce]),
        _board("near_high", "Near the 52-week high", "Within 1.5% of the one-year high and not down today",
               [(r, m, f"{abs(m['from_high']):.1f}% under the 52-week high, {_pct(m['r1d'])} today") for r, m in near_high]),
    ]


def week_boards(items: list[tuple[dict, dict]]) -> list[dict]:
    g = lambda m, k: m.get(k) if _ok(m.get(k)) else math.nan  # noqa: E731
    strong = sorted([(r, m) for r, m in items if g(m, "r5d") >= 3], key=lambda t: -t[1]["r5d"])
    weak = sorted([(r, m) for r, m in items if g(m, "r5d") <= -3], key=lambda t: t[1]["r5d"])
    building = sorted([(r, m) for r, m in items if g(m, "vol_week") >= 1.6 and abs(g(m, "r5d")) <= 3],
                      key=lambda t: -t[1]["vol_week"])
    breakout = sorted([(r, m) for r, m in items if m["price"] > g(m, "high_prior_20_before_week") and g(m, "r5d") > 0],
                      key=lambda t: -t[1]["r5d"])
    pullback = sorted([(r, m) for r, m in items if m.get("above_200") and g(m, "r21d") > 0 and g(m, "r5d") <= -4
                       and m["price"] > g(m, "sma200")],
                      key=lambda t: t[1]["r5d"])
    return [
        _board("strong_week", "Strongest this week", "Up 3% or more over the last 5 sessions",
               [(r, m, f"{_pct(m['r5d'])} this week, volume {_x(m['vol_week'])} usual") for r, m in strong]),
        _board("weak_week", "Weakest this week", "Down 3% or more over the last 5 sessions",
               [(r, m, f"{_pct(m['r5d'])} this week, volume {_x(m['vol_week'])} usual") for r, m in weak]),
        _board("volume_building", "Volume building, price steady",
               "This week's volume at least 1.6× the usual, while price moved under 3% either way",
               [(r, m, f"volume {_x(m['vol_week'])} usual, price {_pct(m['r5d'])} this week") for r, m in building]),
        _board("weekly_breakout", "Weekly breakout", "Now above its highest close of the 4 weeks before this one",
               [(r, m, f"above the prior 4-week high {m['high_prior_20_before_week']:,.2f}, {_pct(m['r5d'])} this week")
                for r, m in breakout]),
        _board("pullback", "Pullback in an uptrend",
               "Above its 200-day average and up over the month, but down 4% or more this week",
               [(r, m, f"{_pct(m['r5d'])} this week, {_pct(m['r21d'])} over the month, above the 200-day average")
                for r, m in pullback]),
    ]


def month_boards(items: list[tuple[dict, dict]]) -> list[dict]:
    g = lambda m, k: m.get(k) if _ok(m.get(k)) else math.nan  # noqa: E731
    strong = sorted([(r, m) for r, m in items if g(m, "r21d") >= 8 and m.get("above_50")], key=lambda t: -t[1]["r21d"])
    weak = sorted([(r, m) for r, m in items if g(m, "r21d") <= -8], key=lambda t: t[1]["r21d"])
    new_high = sorted([(r, m) for r, m in items if m["price"] >= g(m, "high_63_prior")], key=lambda t: -(t[1]["r21d"] or 0))
    turning = sorted([(r, m) for r, m in items if m.get("above_50") and m.get("was_below_50") and g(m, "r21d") > 0],
                     key=lambda t: -t[1]["r21d"])
    oversold = sorted([(r, m) for r, m in items if g(m, "rsi_week_ago") <= 35 and g(m, "rsi") > g(m, "rsi_week_ago")
                       and g(m, "r5d") >= 0],
                      key=lambda t: t[1]["rsi_week_ago"])
    return [
        _board("strong_month", "Strongest this month", "Up 8% or more over the last 21 sessions and above the 50-day average",
               [(r, m, f"{_pct(m['r21d'])} this month, {_pct(m['r63d'])} over 3 months") for r, m in strong]),
        _board("weak_month", "Weakest this month", "Down 8% or more over the last 21 sessions",
               [(r, m, f"{_pct(m['r21d'])} this month, {_pct(m['r63d'])} over 3 months") for r, m in weak]),
        _board("new_3m_high", "New 3-month high", "At or above its highest close of the last 3 months",
               [(r, m, f"at a 3-month high, {_pct(m['r21d'])} this month") for r, m in new_high]),
        _board("turning_up", "Trend turning up", "Below its 50-day average a month ago, above it now",
               [(r, m, f"back above the 50-day average {m['sma50']:,.2f}, {_pct(m['r21d'])} this month") for r, m in turning]),
        _board("oversold_steadying", "Oversold, steadying",
               "RSI(14) was 35 or lower a week ago, has risen since, and price is flat or up this week",
               [(r, m, f"RSI {m['rsi_week_ago']:.0f} a week ago, {m['rsi']:.0f} now, {_pct(m['r5d'])} this week")
                for r, m in oversold]),
    ]


def idea_boards(items: list[tuple[dict, dict]], funda: dict[str, dict]) -> list[dict]:
    """`funda`: symbol -> screens.metrics() (roe, debt_equity, earnings_growth, pe, ...)."""
    g = lambda d, k: d.get(k) if _ok(d.get(k)) else math.nan  # noqa: E731
    both = [(r, m, funda[r["symbol"]]) for r, m in items if r["symbol"] in funda]

    def rows(hits, why):
        return [(r, m, why(m, f)) for r, m, f in hits]

    quality_turn = sorted([t for t in both if g(t[2], "roe") > 15 and g(t[2], "debt_equity") < 1
                           and g(t[2], "earnings_growth") > 0 and t[1].get("above_50") and t[1].get("was_below_50")],
                          key=lambda t: -t[2]["roe"])
    fresh_high = sorted([t for t in both if g(t[2], "roe") > 12 and t[1]["price"] >= g(t[1], "high_252")
                         and (t[1].get("last_high_ago") or 0) >= 60],
                        key=lambda t: -t[2]["roe"])
    # EPS growth over 100% is usually a one-off (a weak year before), not a growth rate.
    garp = sorted([t for t in both if 15 < g(t[2], "earnings_growth") < 100 and g(t[2], "pe") > 0
                   and g(t[2], "pe") / max(g(t[2], "earnings_growth"), 1) < 1.2 and t[1].get("above_200")],
                  key=lambda t: t[2]["pe"] / t[2]["earnings_growth"])
    steadying = sorted([t for t in both if g(t[2], "roe") > 15 and g(t[2], "debt_equity") < 1
                        and g(t[1], "from_high") <= -25 and g(t[1], "r5d") > 0
                        and g(t[1], "rsi") > g(t[1], "rsi_week_ago")],
                       key=lambda t: t[1]["from_high"])
    pct0 = lambda v: f"{v:.0f}%" if _ok(v) else "—"  # noqa: E731
    return [
        _board("quality_turning", "Quality turning up",
               "ROE over 15%, debt under equity, earnings growing - and back above the 50-day average this month",
               rows(quality_turn, lambda m, f: f"ROE {pct0(f['roe'])}, EPS growth {pct0(f['earnings_growth'])}, "
                                               f"back above the 50-day average, {_pct(m['r21d'])} this month")),
        _board("fresh_high", "Fresh 52-week high, profitable",
               "First one-year high in 3 months or more, ROE over 12%",
               rows(fresh_high, lambda m, f: f"new 52-week high (last one {m['last_high_ago']} sessions ago), "
                                             f"ROE {pct0(f['roe'])}")),
        _board("growth_fair_price", "Growth at a fair price",
               "EPS growth 15-100% with P/E under 1.2× that growth, above the 200-day average",
               rows(garp, lambda m, f: f"P/E {f['pe']:.0f} vs EPS growth {pct0(f['earnings_growth'])}, "
                                       f"above the 200-day average")),
        _board("quality_steadying", "Beaten-down quality steadying",
               "ROE over 15%, low debt, 25% or more under the 52-week high, RSI rising and up this week",
               rows(steadying, lambda m, f: f"{abs(m['from_high']):.0f}% under the high, ROE {pct0(f['roe'])}, "
                                            f"{_pct(m['r5d'])} this week")),
    ]


# ------------------------------------------------------------------ "new" ideas


def _ideas_dir() -> Path:
    from ..core.home import app_home

    path = app_home() / "watch"
    path.mkdir(parents=True, exist_ok=True)
    return path


def mark_new(market: str, boards: list[dict], today: date | None = None, store: Path | None = None) -> None:
    """Flags rows that were on no ideas list 7+ days ago and records today's
    lists. `since` = the first day a symbol was seen on the lists (kept 60 days)."""
    today = today or date.today()
    path = (store or _ideas_dir()) / f"ideas-{market}.json"
    try:
        history: dict[str, list[str]] = json.loads(path.read_text())
    except (OSError, ValueError):
        history = {}
    week_ago = (today - timedelta(days=7)).isoformat()
    older = [d for d in history if d <= week_ago]
    before = set(history[max(older)]) if older else None
    first_seen: dict[str, str] = {}
    for d in sorted(history):
        for s in history[d]:
            first_seen.setdefault(s, d)
    now = sorted({r["symbol"] for b in boards for r in b["rows"]})
    for b in boards:
        for r in b["rows"]:
            r["new"] = before is not None and r["symbol"] not in before
            r["since"] = first_seen.get(r["symbol"], today.isoformat())
    history[today.isoformat()] = now
    cutoff = (today - timedelta(days=60)).isoformat()
    history = {d: s for d, s in history.items() if d >= cutoff}
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(history))
        tmp.replace(path)
    except OSError as exc:
        logger.warning("Could not save ideas snapshot: %s", exc)


# ------------------------------------------------------------------ build


def build(market: str, period: str, rows: list[dict] | None = None, fetch: History = _yahoo_history,
          info_fetch=None, live: dict | None = None, today: date | None = None) -> dict:
    from .analysis_run import yahoo_symbol
    from .live_market import market_day, merge

    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows(market)
    quotes = (live or {}).get("quotes") or {}
    if quotes:
        rows = merge(rows, quotes)
    universe = _universe(market, rows)
    ysym = {r["symbol"]: yahoo_symbol(r["symbol"], market) for r in universe}
    history = _history_for(market, list(ysym.values()), fetch)
    today = today or market_day(market)

    items: list[tuple[dict, dict]] = []
    for r in universe:
        frame = history.get(ysym[r["symbol"]])
        if frame is None:
            continue
        try:
            m = measure(*_with_today(frame, r, today))
        except Exception as exc:  # noqa: BLE001 - one bad series must not sink the lists
            logger.debug("watch: %s skipped: %s", r["symbol"], exc)
            m = None
        if m:
            items.append(({**r, "market": market}, m))

    if period == "day":
        boards = day_boards(items)
    elif period == "week":
        boards = week_boards(items)
    elif period == "month":
        boards = month_boards(items)
    else:
        from . import screens

        if info_fetch is None:
            from .compare import _yahoo_info as info_fetch
        top = [r for r, _ in items][:screens.UNIVERSE]
        with ThreadPoolExecutor(max_workers=8) as pool:
            infos = list(pool.map(lambda r: info_fetch(ysym[r["symbol"]]), top))
        funda = {r["symbol"]: screens.metrics(i) for r, i in zip(top, infos) if i}
        boards = idea_boards(items, funda)
        if fetch is _yahoo_history:  # real run: keep the daily snapshot
            mark_new(market, boards, today)
    return {
        "market": market, "period": period, "boards": boards,
        "universe": f"Largest {len(universe)} stocks by market cap ({len(items)} with a year of prices)",
        "as_of": time.strftime("%Y-%m-%dT%H:%M:%S"), "live": (live or {}).get("status"),
    }


# ------------------------------------------------------------------ AI notes


def notes(market: str, period: str, board: dict, config) -> dict:
    """AI notes on one board: a short read of the list and, per stock, what
    to watch (levels from the numbers given, no buy / sell). Shared per board
    for NOTES_TTL. The endpoint checks that an AI model is set up first."""
    from ..core.compliance import guard_prompt
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig, GenerationError, GenerationErrorCode

    rows = board.get("rows") or []
    key = (market, period, board.get("key"), tuple(r["symbol"] for r in rows), time.strftime("%Y-%m-%d %H"))
    with _lock:
        hit = _notes.get(key)
    if hit and time.time() - hit[0] < NOTES_TTL:
        return hit[1]

    lines = [f"Market: {market}. List: {board.get('title')} - {board.get('description')}.",
             "Stocks (symbol | name | sector | price | why on the list | 20-day high | 20-day low | RSI14):"]
    for r in rows[:TOP]:
        lines.append(" | ".join(str(x) for x in (
            r["symbol"], r.get("name") or "", r.get("sector") or "", r.get("price"), r.get("why"),
            round(r["watch_high"], 2) if _ok(r.get("watch_high")) else "-",
            round(r["watch_low"], 2) if _ok(r.get("watch_low")) else "-",
            r.get("rsi") if r.get("rsi") is not None else "-")))
    system = guard_prompt(
        "You write short watch notes for a stock list for retail investors. Use ONLY the numbers given. "
        "Reply with ONLY a JSON object, no prose around it:\n"
        '{"summary": "2-3 sentences on what this list shows today (sectors, common thread)", '
        '"stocks": [{"symbol": "...", "note": "1-2 sentences: what to watch next, naming the 20-day high / low '
        'as the levels and one risk"}]}\n'
        "Neutral, factual wording. Never say buy, sell, hold, target, or recommend; no disclaimers."
    )
    result = create_generation_backend(config, tier="fast").generate(
        "\n".join(lines), GenerationConfig(max_tokens=1600, timeout=120), system_prompt=system)
    text = (result.text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    try:
        parsed = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        raise GenerationError(GenerationErrorCode.INVALID_RESPONSE,
                              "The AI model did not return usable notes. Try again.", stage="parse",
                              retryable=True, fallbackable=False, backend="marketmyna")
    allowed = {r["symbol"] for r in rows}
    out = {"summary": str(parsed.get("summary") or "").strip(),
           "stocks": {str(s.get("symbol")): str(s.get("note") or "").strip()
                      for s in parsed.get("stocks") or [] if isinstance(s, dict) and s.get("symbol") in allowed},
           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with _lock:
        _notes[key] = (time.time(), out)
    return out
