"""Index board: live index values for one market (or all), shown above the
Markets table as a scrolling ticker and, opened up, as tiles with a day
sparkline and a few readings.

Each index carries: last value, change vs the previous official close (points
and %), day high / low, today's (or the last session's) 5-minute line, and
readings from its daily closes: RSI(14), distance from the 50- and 200-day
averages, and where it sits in its 52-week range. Readings are numbers, not
advice.

Prices: the market data feed (daily bars, which track the live price during
the session, plus 5-minute bars), refreshed at most every REFRESH seconds per
index while someone is looking; requests never wait once something is cached.
GIFT Nifty comes from the exchange's market-status feed (it is not on the
regular feed); its day line is built from the values seen here.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)

REFRESH = 60
OPEN_SECONDS = 30 * 60  # traded in the last 30 min: in session (some feeds lag ~15-20 min)
GIFT = "GIFTNIFTY"

# (ticker, label, note)
_IN_MAIN = [
    ("^NSEI", "Nifty 50", "50 largest NSE companies"),
    ("^BSESN", "Sensex", "30 largest BSE companies"),
    (GIFT, "GIFT Nifty", "Nifty futures at NSE IX, GIFT City; trades before and after India hours"),
    ("^NSEBANK", "Nifty Bank", "Large banks"),
    ("^NSMIDCP", "Nifty Next 50", "The 50 after the Nifty 50"),
    ("NIFTY_MIDCAP_100.NS", "Nifty Midcap 100", "Mid caps"),
    ("^CNXSC", "Nifty Smallcap 100", "Small caps"),
    ("^CRSLDX", "Nifty 500", "Broad market"),
    ("^INDIAVIX", "India VIX", "Expected Nifty volatility, next 30 days"),
]
_IN_SECTORS = [
    ("^CNXIT", "Nifty IT", "Software and IT services"),
    ("^CNXPHARMA", "Nifty Pharma", "Drug makers"),
    ("NIFTY_HEALTHCARE.NS", "Nifty Healthcare", "Pharma, hospitals, diagnostics"),
    ("NIFTY_FIN_SERVICE.NS", "Nifty Financial Services", "Banks, NBFCs, insurers"),
    ("NIFTY_PVT_BANK.NS", "Nifty Private Bank", "Private sector banks"),
    ("^CNXPSUBANK", "Nifty PSU Bank", "Public sector banks"),
    ("^CNXAUTO", "Nifty Auto", "Carmakers and parts"),
    ("^CNXFMCG", "Nifty FMCG", "Consumer staples"),
    ("^CNXMETAL", "Nifty Metal", "Steel, aluminium, mining"),
    ("^CNXENERGY", "Nifty Energy", "Power, oil and gas"),
    ("NIFTY_OIL_AND_GAS.NS", "Nifty Oil & Gas", "Oil and gas"),
    ("^CNXREALTY", "Nifty Realty", "Real estate"),
    ("^CNXINFRA", "Nifty Infrastructure", "Infrastructure"),
    ("^CNXPSE", "Nifty PSE", "Public sector companies"),
    ("^CNXCONSUM", "Nifty Consumption", "Consumer spending"),
    ("^CNXMEDIA", "Nifty Media", "Media and entertainment"),
]
_US_MAIN = [
    ("^GSPC", "S&P 500", "US large caps"),
    ("^IXIC", "Nasdaq Composite", "All Nasdaq stocks, tech-heavy"),
    ("^NDX", "Nasdaq 100", "100 largest Nasdaq non-financials"),
    ("^DJI", "Dow Jones", "30 US blue chips"),
    ("^RUT", "Russell 2000", "US small caps"),
    ("^SOX", "PHLX Semiconductor", "Chip makers"),
    ("^VIX", "VIX", "Expected S&P 500 volatility, next 30 days"),
]
_US_FUTURES = [
    ("ES=F", "S&P 500 futures", "Trades nearly round the clock"),
    ("NQ=F", "Nasdaq 100 futures", "Trades nearly round the clock"),
    ("YM=F", "Dow futures", "Trades nearly round the clock"),
]
_US_SECTORS = [
    ("XLK", "Technology", "Sector fund XLK"),
    ("XLV", "Health care", "Sector fund XLV"),
    ("XLF", "Financials", "Sector fund XLF"),
    ("XLE", "Energy", "Sector fund XLE"),
    ("XLY", "Consumer discretionary", "Sector fund XLY"),
    ("XLP", "Consumer staples", "Sector fund XLP"),
    ("XLI", "Industrials", "Sector fund XLI"),
    ("XLB", "Materials", "Sector fund XLB"),
    ("XLU", "Utilities", "Sector fund XLU"),
    ("XLRE", "Real estate", "Sector fund XLRE"),
    ("XLC", "Communication", "Sector fund XLC"),
]
_CN = [
    ("000001.SS", "Shanghai Composite", "All Shanghai A and B shares"),
    ("399001.SZ", "Shenzhen Component", "500 Shenzhen stocks"),
    ("000300.SS", "CSI 300", "300 largest A-shares"),
    ("000016.SS", "SSE 50", "50 largest Shanghai stocks"),
    ("399006.SZ", "ChiNext", "Shenzhen growth board"),
    ("000688.SS", "STAR 50", "Shanghai tech board"),
]
_HK = [
    ("^HSI", "Hang Seng", "Largest Hong Kong stocks"),
    ("^HSCE", "Hang Seng China Enterprises", "Mainland companies listed in HK"),
    ("HSTECH.HK", "Hang Seng Tech", "30 largest HK tech stocks"),
]
_CRYPTO = [
    ("BTC-USD", "Bitcoin", "In US dollars"),
    ("ETH-USD", "Ether", "In US dollars"),
    ("SOL-USD", "Solana", "In US dollars"),
    ("XRP-USD", "XRP", "In US dollars"),
    ("BNB-USD", "BNB", "In US dollars"),
]
_GLOBAL = [
    ("^990100-USD-STRD", "MSCI World", "Developed markets, in US dollars"),
    ("^N225", "Nikkei 225", "Japan"),
    ("^KS11", "KOSPI", "South Korea"),
    ("^TWII", "Taiwan Weighted", "Taiwan"),
    ("^AXJO", "ASX 200", "Australia"),
    ("^STI", "Straits Times", "Singapore"),
    ("^STOXX50E", "Euro Stoxx 50", "Eurozone blue chips"),
    ("^FTSE", "FTSE 100", "UK"),
    ("^GDAXI", "DAX", "Germany"),
    ("^FCHI", "CAC 40", "France"),
    ("^GSPTSE", "S&P/TSX", "Canada"),
    ("^BVSP", "Bovespa", "Brazil"),
]

_WORLD = {
    "canada": [("^GSPTSE", "S&P/TSX Composite", "Canada's main index")],
    "uk": [("^FTSE", "FTSE 100", "100 largest London-listed companies"),
           ("^FTMC", "FTSE 250", "The next 250, more UK-focused"),
           ("^FTAS", "FTSE All-Share", "Broad UK market")],
    "australia": [("^AXJO", "S&P/ASX 200", "200 largest ASX companies"),
                  ("^AORD", "All Ordinaries", "Broad Australian market")],
    "singapore": [("^STI", "Straits Times", "30 largest SGX companies")],
    "israel": [("TA35.TA", "TA-35", "35 largest Tel Aviv companies"),
               ("^TA125.TA", "TA-125", "Broad Israeli market")],
}
_GLOBAL.append(("TA35.TA", "TA-35", "Israel"))

def _pick(rows: list[tuple], *tickers: str) -> list[tuple]:
    by = {r[0]: r for r in rows}
    return [by[t] for t in tickers]


# market -> [(group key, group label, items)]; the first group is the ticker strip.
BOARDS: dict[str, list[tuple[str, str, list[tuple]]]] = {
    "india": [("main", "Benchmarks", _IN_MAIN), ("sectors", "Sectors", _IN_SECTORS), ("global", "Global", _GLOBAL)],
    "us": [("main", "Benchmarks", _US_MAIN + _US_FUTURES), ("sectors", "Sectors", _US_SECTORS),
           ("global", "Global", _GLOBAL)],
    "china_a": [("main", "China A-shares", _CN), ("hk", "Hong Kong", _HK), ("global", "Global", _GLOBAL)],
    "hong_kong": [("main", "Hong Kong", _HK), ("cn", "China A-shares", _CN), ("global", "Global", _GLOBAL)],
    "crypto": [("main", "Crypto", _CRYPTO), ("us", "US", _pick(_US_MAIN + _US_FUTURES, "^GSPC", "^IXIC", "NQ=F")),
               ("global", "Global", _GLOBAL)],
    **{m: [("main", label, items), ("global", "Global", _GLOBAL)]
       for m, (label, items) in {"canada": ("Canada", _WORLD["canada"]), "uk": ("UK", _WORLD["uk"]),
                                 "australia": ("Australia", _WORLD["australia"]),
                                 "singapore": ("Singapore", _WORLD["singapore"]),
                                 "israel": ("Israel", _WORLD["israel"])}.items()},
    "all": [("main", "Key indices", _pick(_IN_MAIN, "^NSEI", "^BSESN", GIFT, "^NSEBANK")
             + _pick(_US_MAIN + _US_FUTURES, "^GSPC", "^IXIC", "^DJI", "ES=F")
             + _pick(_CN, "000001.SS", "000300.SS") + _HK + _pick(_CRYPTO, "BTC-USD")),
            ("india_sectors", "India sectors", _IN_SECTORS), ("us_sectors", "US sectors", _US_SECTORS),
            ("global", "Global", _GLOBAL)],
}

# Ticker -> name in the exchange's all-indices feed (breadth, P/E, 52-week range).
NSE_NAMES = {
    "^NSEI": "NIFTY 50", "^NSEBANK": "NIFTY BANK", "^NSMIDCP": "NIFTY NEXT 50",
    "NIFTY_MIDCAP_100.NS": "NIFTY MIDCAP 100", "^CNXSC": "NIFTY SMALLCAP 100", "^CRSLDX": "NIFTY 500",
    "^CNXIT": "NIFTY IT", "^CNXPHARMA": "NIFTY PHARMA", "NIFTY_HEALTHCARE.NS": "NIFTY HEALTHCARE INDEX",
    "NIFTY_FIN_SERVICE.NS": "NIFTY FINANCIAL SERVICES", "NIFTY_PVT_BANK.NS": "NIFTY PRIVATE BANK",
    "^CNXPSUBANK": "NIFTY PSU BANK", "^CNXAUTO": "NIFTY AUTO", "^CNXFMCG": "NIFTY FMCG",
    "^CNXMETAL": "NIFTY METAL", "^CNXENERGY": "NIFTY ENERGY", "NIFTY_OIL_AND_GAS.NS": "NIFTY OIL & GAS",
    "^CNXREALTY": "NIFTY REALTY", "^CNXINFRA": "NIFTY INFRASTRUCTURE", "^CNXPSE": "NIFTY PSE",
    "^CNXCONSUM": "NIFTY INDIA CONSUMPTION", "^CNXMEDIA": "NIFTY MEDIA",
}

# Points, not percent, for volatility gauges.
POINT_CHANGE = {"^INDIAVIX", "^VIX"}

_quotes: dict[str, tuple[float, dict]] = {}
_busy: set[str] = set()
_lock = threading.Lock()
_gift_line: list[tuple[float, float]] = []  # (epoch, value) seen today


# ------------------------------------------------------------------ readings


def rsi(closes: pd.Series, n: int = 14) -> float | None:
    """Wilder's RSI on daily closes."""
    if len(closes) <= n:
        return None
    d = closes.diff().dropna()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if loss == 0:
        return 100.0
    return round(float(100 - 100 / (1 + gain / loss)), 1)


def _vs_avg(closes: pd.Series, n: int) -> float | None:
    if len(closes) < n:
        return None
    avg = float(closes.iloc[-n:].mean())
    return round((float(closes.iloc[-1]) / avg - 1) * 100, 2) if avg else None


def _sessions(intraday: pd.DataFrame) -> list[pd.DataFrame]:
    """5-minute bars split where trading paused 3h+ (lunch breaks and the
    futures' daily hour stay inside one session)."""
    if intraday.empty:
        return []
    idx = intraday.index.to_series()
    breaks = idx.diff() > pd.Timedelta(hours=3)
    group = breaks.cumsum()
    return [g for _, g in intraday.groupby(group.to_numpy())]


def quote_from(daily: pd.DataFrame, intraday: pd.DataFrame, now: float | None = None) -> dict | None:
    """One index's quote from its daily bars (last bar is live in session) and
    5-minute bars."""
    now = now or time.time()
    daily = daily.dropna(subset=["Close"]) if daily is not None and "Close" in daily else pd.DataFrame()
    intraday = intraday.dropna(subset=["Close"]) if intraday is not None and "Close" in intraday else pd.DataFrame()
    sessions = _sessions(intraday)
    last = sessions[-1] if sessions else None
    if last is not None:  # at most a day of bars (futures and crypto barely pause)
        last = last[last.index >= last.index[-1] - pd.Timedelta(hours=24)]

    if len(daily) >= 2:
        closes = daily["Close"].astype(float)
        price, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
        high, low = float(daily["High"].iloc[-1]), float(daily["Low"].iloc[-1])
    elif last is not None and len(sessions) >= 2:  # daily history missing: use the sessions
        closes = pd.Series(dtype=float)
        price, prev = float(last["Close"].iloc[-1]), float(sessions[-2]["Close"].iloc[-1])
        high, low = float(last["High"].max()), float(last["Low"].min())
    else:
        return None
    if last is not None and len(last):  # the 5-minute bar can be newer than the daily one
        tail = float(last["Close"].iloc[-1])
        if pd.Timestamp(last.index[-1]).timestamp() >= now - OPEN_SECONDS:
            price = tail
            high, low = max(high, price), min(low, price)

    updated = pd.Timestamp(last.index[-1]).timestamp() if last is not None and len(last) else None
    year = closes.iloc[-252:] if len(closes) else closes
    return {
        "price": price,
        "prev_close": prev,
        "change": price - prev,
        "change_pct": (price / prev - 1) * 100 if prev else None,
        "day_high": high,
        "day_low": low,
        "spark": [round(float(v), 4) for v in last["Close"].to_numpy()][-120:] if last is not None else [],
        "updated": updated,
        "open": updated is not None and now - updated < OPEN_SECONDS,
        "rsi14": rsi(closes) if len(closes) else None,
        "vs_50d": _vs_avg(closes, 50) if len(closes) else None,
        "vs_200d": _vs_avg(closes, 200) if len(closes) else None,
        "high_52w": float(year.max()) if len(year) else None,
        "low_52w": float(year.min()) if len(year) else None,
    }


# ------------------------------------------------------------------ fetching


def _download(tickers: list[str]) -> dict[str, dict]:
    import yfinance as yf

    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    with YF_DOWNLOAD_LOCK:
        daily = yf.download(tickers, period="1y", interval="1d", group_by="ticker", progress=False,
                            threads=True, auto_adjust=False, timeout=15)
        intra = yf.download(tickers, period="5d", interval="5m", group_by="ticker", progress=False,
                            threads=True, auto_adjust=False, prepost=False, timeout=15)

    # A big batch sometimes comes back with only today's bar for a few
    # tickers; ask for those once more on their own.
    def short(df, t):
        try:
            return len(df[t].dropna(subset=["Close"])) < 2
        except (KeyError, TypeError, AttributeError):
            return True

    again = [t for t in tickers if short(daily, t)]
    if again and len(again) < len(tickers):
        with YF_DOWNLOAD_LOCK:
            retry = yf.download(again, period="1y", interval="1d", group_by="ticker", progress=False,
                                threads=False, auto_adjust=False, timeout=15)
        for t in again:
            if not short(retry, t):
                daily = daily.drop(columns=t, level=0, errors="ignore")
                daily = pd.concat([daily, retry[[t]] if isinstance(retry.columns, pd.MultiIndex) else
                                   pd.concat({t: retry}, axis=1)], axis=1)

    def frame(df, t):
        if df is None or df.empty:
            return pd.DataFrame()
        try:
            return df[t] if isinstance(df.columns, pd.MultiIndex) else df
        except KeyError:
            return pd.DataFrame()

    out = {}
    for t in tickers:
        try:
            q = quote_from(frame(daily, t), frame(intra, t))
        except Exception as exc:  # noqa: BLE001 - one bad series must not sink the board
            logger.info("Index %s skipped: %s", t, exc)
            q = None
        if q:
            out[t] = q
    return out


def _gift_nifty() -> dict[str, dict]:
    import requests

    from .market_calendar import NSE_HEADERS

    r = requests.get("https://www.nseindia.com/api/marketStatus", headers=NSE_HEADERS, timeout=10)
    r.raise_for_status()
    g = (r.json() or {}).get("giftnifty") or {}
    price, change = g.get("LASTPRICE"), g.get("DAYCHANGE")
    if price in (None, "") or change in (None, ""):
        return {}
    price, change = float(price), float(change)
    try:
        when = datetime.strptime(g["TIMESTMP"], "%d-%b-%Y %H:%M").replace(tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    except (KeyError, ValueError):
        when = None
    now = time.time()
    with _lock:
        if when and (not _gift_line or _gift_line[-1][0] < when):
            _gift_line.append((when, price))
        _gift_line[:] = [p for p in _gift_line if p[0] > now - 24 * 3600][-300:]
        spark = [v for _, v in _gift_line]
    prev = price - change
    return {GIFT: {
        "price": price, "prev_close": prev, "change": change,
        "change_pct": (price / prev - 1) * 100 if prev else None,
        "day_high": None, "day_low": None, "spark": spark if len(spark) > 1 else [],
        "updated": when, "open": when is not None and now - when < OPEN_SECONDS,
        "rsi14": None, "vs_50d": None, "vs_200d": None, "high_52w": None, "low_52w": None,
        "expiry": g.get("EXPIRYDATE"),
    }}


def _nse_extras() -> dict[str, dict]:
    """ticker -> advances / declines, P/E and 52-week range from the
    exchange's all-indices feed."""
    from .market_valuation import _nse_indices

    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rows = {r.get("index"): r for r in _nse_indices()}
    out = {}
    for t, name in NSE_NAMES.items():
        r = rows.get(name)
        if not r:
            continue
        adv, dec = f(r.get("advances")), f(r.get("declines"))
        out[t] = {"advances": int(adv) if adv is not None else None, "declines": int(dec) if dec is not None else None,
                  "pe": f(r.get("pe")) or None, "high_52w": f(r.get("yearHigh")) or None,
                  "low_52w": f(r.get("yearLow")) or None}
    return out


def _fill(tickers: list[str]) -> None:
    got: dict[str, dict] = {}
    feed = [t for t in tickers if t != GIFT]
    try:
        if feed:
            got.update(_download(feed))
    except Exception as exc:  # noqa: BLE001
        logger.info("Index board fetch failed: %s", exc)
    if GIFT in tickers:
        try:
            got.update(_gift_nifty())
        except Exception as exc:  # noqa: BLE001
            logger.info("GIFT Nifty unavailable: %s", exc)
    if any(t in NSE_NAMES for t in got):
        try:
            extras = _nse_extras()
        except Exception as exc:  # noqa: BLE001 - extras only
            logger.info("NSE index breadth unavailable: %s", exc)
            extras = {}
        for t, x in extras.items():
            q = got.get(t)
            if not q:
                continue
            q["advances"], q["declines"], q["pe"] = x["advances"], x["declines"], x["pe"]
            if q.get("high_52w") is None or q.get("low_52w") is None:  # feed had no daily history
                q["high_52w"], q["low_52w"] = x["high_52w"], x["low_52w"]
    now = time.time()
    with _lock:
        for t in tickers:
            _busy.discard(t)
            if t in got:
                _quotes[t] = (now, got[t])


def quotes(tickers: list[str], wait: bool = True) -> dict[str, dict]:
    """ticker -> quote, cached REFRESH seconds; stale ones refresh in the
    background, never-seen ones inline (when `wait`)."""
    now = time.time()
    with _lock:
        stale = [t for t in tickers if (t not in _quotes or now - _quotes[t][0] >= REFRESH) and t not in _busy]
        _busy.update(stale)
        have = {t for t in tickers if t in _quotes}
    missing = [t for t in stale if t not in have]
    background = [t for t in stale if t in have]
    if missing and wait:
        _fill(missing)
    elif missing:
        background += missing
    if background:
        threading.Thread(target=_fill, args=(background,), name="index-board", daemon=True).start()
    with _lock:
        return {t: _quotes[t][1] for t in tickers if t in _quotes}


def build(market: str = "india") -> dict:
    board = BOARDS.get(market) or BOARDS["india"]
    tickers = list(dict.fromkeys(t for _, _, items in board for t, *_ in items))
    got = quotes(tickers)
    groups, failed = [], []
    for key, label, items in board:
        rows = []
        for t, name, note in items:
            q = got.get(t)
            if not q:
                failed.append(name)
                continue
            rows.append({"key": t, "label": name, "note": note,
                         "change_unit": "points" if t in POINT_CHANGE else "%", **q})
        if rows:
            groups.append({"key": key, "label": label, "items": rows})
    times = [q["updated"] for q in got.values() if q.get("updated")]
    newest = max(times) if times else None
    age = time.time() - newest if newest else None
    live = {"open": any(q.get("open") for q in got.values()), "live": bool(got), "updated": newest,
            "age_seconds": round(age, 1) if age is not None else None, "refresh_seconds": REFRESH,
            "covered": len(got), "source": "Market data feed, can lag up to 15 min", "error": None,
            "version": None}
    return {"market": market, "groups": groups, "failed": list(dict.fromkeys(failed)), "live": live,
            "source": "Market data feed, can lag up to 15 min; GIFT Nifty from the exchange's market status. "
                      "Change is against the previous official close."}
