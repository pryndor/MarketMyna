"""Backup market-data sources, plugged into the fetchers' FallbackChains.

- Tencent (qt.gtimg.cn / web.ifzq.gtimg.cn): free, no key. Quotes and
  daily history for China A-shares and Hong Kong - used when akshare is
  missing or Eastmoney is throttling, before Yahoo.
- Finnhub (FINNHUB_API_KEY, free tier 60 calls/min): US quotes.
- Alpha Vantage (ALPHAVANTAGE_API_KEY, free tier 25 calls/day): US quotes
  and ~100 days of daily history.
- Nasdaq (api.nasdaq.com, no key): US quotes and daily history.
- Twelve Data (twelvedata_api_key, free tier 800 calls/day): US and NSE / BSE
  quotes and daily history.
- Tiingo (tiingo_api_key, free tier): US quotes (IEX) and daily history.
- Polygon (polygon_key, free tier 5 calls/min): US daily history; its quote is
  the latest daily bar.

Keys come from the environment or from the admin Integrations page
(config.json), see key().

Environment variable names match daily_stock_analysis. Every function
returns the same shapes the fetchers already use: a quote dict
(price, previous_close, open, day_high, day_low, volume, change,
change_percent) or a DataFrame indexed by date with lower-case OHLCV.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

from ..core.constants import TimeFrame

_TIMEOUT = 12
_TENCENT_HEADERS = {"Referer": "https://finance.qq.com", "User-Agent": "Mozilla/5.0"}
_TENCENT_MAX_BARS = 640

_PERIOD_DAYS = {"1d": 1, "5d": 7, "1mo": 31, "3mo": 93, "6mo": 186, "1y": 366, "2y": 731, "5y": 1827, "10y": 3653}


_KEY_TTL = 60.0
_key_cache: dict[str, tuple[float, Optional[str]]] = {}


def key(field: str, *env_names: str) -> Optional[str]:
    """API key from an environment variable, else the saved config field.

    Config.load() reads and decrypts config.json, so the answer is cached
    for a minute: a key saved on the admin page is picked up shortly after.
    """
    for name in (field.upper(), *env_names):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    now = time.monotonic()
    hit = _key_cache.get(field)
    if hit and now - hit[0] < _KEY_TTL:
        return hit[1]
    value = _config_key(field)
    _key_cache[field] = (now, value)
    return value


def _config_key(field: str) -> Optional[str]:
    try:
        from ..core.config import Config

        return (getattr(Config.load(), field, None) or "").strip() or None
    except Exception:  # noqa: BLE001 - a broken config must not break price fetching
        return None


def _trim(df: pd.DataFrame, period: str, start: Optional[datetime], end: Optional[datetime]) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.sort_index()[["open", "high", "low", "close", "volume"]]
    cutoff = start or (datetime.now() - timedelta(days=period_days(period)))
    df = df[df.index >= pd.Timestamp(cutoff)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def quote_from_frame(symbol: str, df: pd.DataFrame) -> dict:
    """A quote from the last two daily bars (lower-case OHLCV columns)."""
    if df.empty:
        raise ValueError(f"no bars for {symbol}")
    bar = df.iloc[-1]
    price = float(bar["close"])
    prev = float(df["close"].iloc[-2]) if len(df) > 1 else None
    return {
        "symbol": symbol, "price": price, "previous_close": prev, "open": float(bar["open"]),
        "day_high": float(bar["high"]), "day_low": float(bar["low"]),
        "volume": float(bar["volume"]) if pd.notna(bar["volume"]) else None,
        "change": price - prev if prev else 0, "change_percent": (price - prev) / prev * 100 if prev else 0,
        "as_of": df.index[-1].strftime("%Y-%m-%d"),
    }


def period_days(period: str, start: Optional[datetime] = None) -> int:
    if start is not None:
        return max(1, (datetime.now() - start).days + 1)
    if period == "ytd":
        return datetime.now().timetuple().tm_yday
    return _PERIOD_DAYS.get(period, 366)


def _ensure_daily(interval: TimeFrame) -> None:
    if interval != TimeFrame.DAY_1:
        raise ValueError(f"backup source only serves daily bars, not {interval.value}")


# --------------------------------------------------------------- Tencent


def tencent_symbol(code: str, market: str) -> str:
    code = code.strip().upper()
    if market == "hong_kong":
        return f"hk{int(code):05d}"
    if code[:1] in "69" or code[:1] == "5":
        return f"sh{code}"
    if code[:1] in "48":
        return f"bj{code}"
    return f"sz{code}"


def tencent_quote(code: str, market: str) -> dict:
    symbol = tencent_symbol(code, market)
    resp = requests.get(f"https://qt.gtimg.cn/q={symbol}", headers=_TENCENT_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    text = resp.content.decode("gbk", errors="replace")
    start, end = text.find('"'), text.rfind('"')
    fields = text[start + 1:end].split("~") if 0 <= start < end else []
    if len(fields) < 35 or not fields[3]:
        raise ValueError(f"Tencent has no quote for {symbol}")

    def num(i: int) -> Optional[float]:
        try:
            return float(fields[i])
        except (ValueError, IndexError):
            return None

    volume = num(6)
    if volume is not None and market == "china_a":
        volume *= 100  # A-share volume is quoted in lots of 100
    return {
        "symbol": code,
        "name": fields[1],
        "price": num(3),
        "previous_close": num(4),
        "open": num(5),
        "day_high": num(33),
        "day_low": num(34),
        "volume": volume,
        "change": num(31),
        "change_percent": num(32),
    }


def tencent_history(code: str, market: str, period: str = "1y", interval: TimeFrame = TimeFrame.DAY_1,
                    start: Optional[datetime] = None, end: Optional[datetime] = None, **_ignored) -> pd.DataFrame:
    _ensure_daily(interval)
    symbol = tencent_symbol(code, market)
    bars = min(_TENCENT_MAX_BARS, int(period_days(period, start) * 0.72) + 10)
    resp = requests.get(
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
        params={"param": f"{symbol},day,,,{bars},qfq"},
        headers=_TENCENT_HEADERS,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    node = ((resp.json().get("data") or {}).get(symbol) or {})
    rows = node.get("qfqday") or node.get("day") or []
    if not rows:
        return pd.DataFrame()
    # Tencent order: date, open, close, high, low, volume, [extras]
    df = pd.DataFrame([r[:6] for r in rows], columns=["date", "open", "close", "high", "low", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "close", "high", "low", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if market == "china_a":
        df["volume"] = df["volume"] * 100  # lots of 100 -> shares, matching the quote
    df = df.set_index("date").sort_index()[["open", "high", "low", "close", "volume"]]
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end)]
    return df


# --------------------------------------------------------------- Finnhub


def finnhub_key() -> Optional[str]:
    return key("finnhub_api_key")


def finnhub_quote(symbol: str) -> dict:
    key = finnhub_key()
    if not key:
        raise ValueError("FINNHUB_API_KEY not set")
    resp = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": symbol.upper(), "token": key},
                        timeout=_TIMEOUT)
    resp.raise_for_status()
    q = resp.json()
    if not q or not q.get("c"):
        raise ValueError(f"Finnhub has no quote for {symbol}")
    return {
        "symbol": symbol, "price": q.get("c"), "previous_close": q.get("pc"), "open": q.get("o"),
        "day_high": q.get("h"), "day_low": q.get("l"), "volume": None,
        "change": q.get("d"), "change_percent": q.get("dp"),
    }


# ----------------------------------------------------------- Alpha Vantage


def alphavantage_key() -> Optional[str]:
    return key("alpha_vantage_key", "ALPHAVANTAGE_API_KEY")


def _alphavantage(params: dict) -> dict:
    key = alphavantage_key()
    if not key:
        raise ValueError("ALPHAVANTAGE_API_KEY not set")
    resp = requests.get("https://www.alphavantage.co/query", params={**params, "apikey": key}, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    # Rate limits come back as HTTP 200 with a "Note"/"Information" message.
    if "Note" in data or "Information" in data or "Error Message" in data:
        raise ValueError(data.get("Note") or data.get("Information") or data.get("Error Message"))
    return data


def alphavantage_quote(symbol: str) -> dict:
    q = _alphavantage({"function": "GLOBAL_QUOTE", "symbol": symbol.upper()}).get("Global Quote") or {}
    if not q.get("05. price"):
        raise ValueError(f"Alpha Vantage has no quote for {symbol}")

    def num(key: str) -> Optional[float]:
        try:
            return float(str(q.get(key, "")).rstrip("%"))
        except ValueError:
            return None

    return {
        "symbol": symbol, "price": num("05. price"), "previous_close": num("08. previous close"),
        "open": num("02. open"), "day_high": num("03. high"), "day_low": num("04. low"),
        "volume": num("06. volume"), "change": num("09. change"), "change_percent": num("10. change percent"),
    }


def alphavantage_history(symbol: str, period: str = "1y", interval: TimeFrame = TimeFrame.DAY_1,
                         start: Optional[datetime] = None, end: Optional[datetime] = None, **_ignored) -> pd.DataFrame:
    _ensure_daily(interval)
    data = _alphavantage({"function": "TIME_SERIES_DAILY", "symbol": symbol.upper(), "outputsize": "compact"})
    series = data.get("Time Series (Daily)") or {}
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame.from_dict(series, orient="index").rename(columns={
        "1. open": "open", "2. high": "high", "3. low": "low", "4. close": "close", "5. volume": "volume",
    })
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    df = df.astype(float).sort_index()[["open", "high", "low", "close", "volume"]]
    cutoff = start or (datetime.now() - timedelta(days=period_days(period)))
    return df[df.index >= pd.Timestamp(cutoff)]


# ------------------------------------------------------------------ Nasdaq

_NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept": "application/json",
}


def _money(text) -> Optional[float]:
    """'$1,234.50' / '+1.16' / '+0.34%' / '25,900,600' -> float."""
    if text in (None, "", "N/A"):
        return None
    try:
        return float(str(text).replace("$", "").replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def _nasdaq(path: str, params: dict) -> dict:
    resp = requests.get(f"https://api.nasdaq.com/api/quote/{path}", params=params,
                        headers=_NASDAQ_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    body = resp.json() or {}
    data = body.get("data")
    if not data:
        raise ValueError(((body.get("status") or {}).get("bCodeMessage") or [{}])[0].get("errorMessage")
                         or "Nasdaq returned no data")
    return data


def nasdaq_quote(symbol: str) -> dict:
    data = _nasdaq(f"{symbol.upper()}/info", {"assetclass": "stocks"})
    primary = data.get("primaryData") or {}
    price = _money(primary.get("lastSalePrice"))
    if not price:
        raise ValueError(f"Nasdaq has no quote for {symbol}")
    change = _money(primary.get("netChange"))
    return {
        "symbol": symbol, "price": price, "previous_close": price - change if change is not None else None,
        "open": None, "day_high": None, "day_low": None, "volume": _money(primary.get("volume")),
        "change": change, "change_percent": _money(primary.get("percentageChange")),
    }


def nasdaq_history(symbol: str, period: str = "1y", interval: TimeFrame = TimeFrame.DAY_1,
                   start: Optional[datetime] = None, end: Optional[datetime] = None, **_ignored) -> pd.DataFrame:
    _ensure_daily(interval)
    since = start or (datetime.now() - timedelta(days=period_days(period)))
    until = end or datetime.now()
    data = _nasdaq(f"{symbol.upper()}/historical", {
        "assetclass": "stocks", "fromdate": since.strftime("%Y-%m-%d"), "todate": until.strftime("%Y-%m-%d"),
        "limit": 9999,
    })
    rows = ((data.get("tradesTable") or {}).get("rows")) or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame([{
        "date": pd.to_datetime(r.get("date"), format="%m/%d/%Y"), "open": _money(r.get("open")),
        "high": _money(r.get("high")), "low": _money(r.get("low")), "close": _money(r.get("close")),
        "volume": _money(r.get("volume")),
    } for r in rows]).set_index("date")
    return _trim(df.dropna(subset=["close"]), period, start, end)


# ------------------------------------------------------------- Twelve Data


def twelvedata_key() -> Optional[str]:
    return key("twelvedata_api_key", "TWELVE_DATA_API_KEY")


def _twelvedata_symbol(symbol: str, market: str) -> dict:
    if market == "india":
        code = symbol.upper()
        exchange = "BSE" if code.endswith(".BO") else "NSE"
        return {"symbol": code.removesuffix(".NS").removesuffix(".BO"), "exchange": exchange}
    return {"symbol": symbol.upper()}


def _twelvedata(path: str, params: dict) -> dict:
    k = twelvedata_key()
    if not k:
        raise ValueError("Twelve Data key not set")
    resp = requests.get(f"https://api.twelvedata.com/{path}", params={**params, "apikey": k}, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json() or {}
    # Errors (bad key, rate limit, symbol not on the plan) come back as HTTP 200.
    if data.get("status") == "error":
        raise ValueError(f"Twelve Data: {data.get('message')}")
    return data


def twelvedata_quote(symbol: str, market: str = "us") -> dict:
    q = _twelvedata("quote", _twelvedata_symbol(symbol, market))
    num = lambda k: _money(q.get(k))  # noqa: E731
    price = num("close")
    if not price:
        raise ValueError(f"Twelve Data has no quote for {symbol}")
    return {
        "symbol": symbol, "price": price, "previous_close": num("previous_close"), "open": num("open"),
        "day_high": num("high"), "day_low": num("low"), "volume": num("volume"),
        "change": num("change"), "change_percent": num("percent_change"),
    }


def twelvedata_history(symbol: str, market: str = "us", period: str = "1y", interval: TimeFrame = TimeFrame.DAY_1,
                       start: Optional[datetime] = None, end: Optional[datetime] = None, **_ignored) -> pd.DataFrame:
    _ensure_daily(interval)
    bars = min(5000, int(period_days(period, start) * 0.72) + 10)
    data = _twelvedata("time_series", {**_twelvedata_symbol(symbol, market), "interval": "1day", "outputsize": bars})
    values = data.get("values") or []
    if not values:
        return pd.DataFrame()
    df = pd.DataFrame(values)
    df["date"] = pd.to_datetime(df["datetime"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    return _trim(df.set_index("date"), period, start, end)


# ------------------------------------------------------------------ Tiingo


def tiingo_key() -> Optional[str]:
    return key("tiingo_api_key")


def _tiingo(path: str, params: Optional[dict] = None):
    k = tiingo_key()
    if not k:
        raise ValueError("Tiingo key not set")
    resp = requests.get(f"https://api.tiingo.com/{path}", params={**(params or {}), "token": k}, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def tiingo_quote(symbol: str) -> dict:
    rows = _tiingo(f"iex/{symbol.lower()}") or []
    q = rows[0] if isinstance(rows, list) and rows else {}
    price = q.get("tngoLast") or q.get("last")
    if not price:
        raise ValueError(f"Tiingo has no quote for {symbol}")
    prev = q.get("prevClose")
    return {
        "symbol": symbol, "price": float(price), "previous_close": prev, "open": q.get("open"),
        "day_high": q.get("high"), "day_low": q.get("low"), "volume": q.get("volume"),
        "change": float(price) - prev if prev else None,
        "change_percent": (float(price) - prev) / prev * 100 if prev else None,
    }


def tiingo_history(symbol: str, period: str = "1y", interval: TimeFrame = TimeFrame.DAY_1,
                   start: Optional[datetime] = None, end: Optional[datetime] = None, **_ignored) -> pd.DataFrame:
    _ensure_daily(interval)
    since = start or (datetime.now() - timedelta(days=period_days(period)))
    params = {"startDate": since.strftime("%Y-%m-%d")}
    if end is not None:
        params["endDate"] = end.strftime("%Y-%m-%d")
    rows = _tiingo(f"tiingo/daily/{symbol.lower()}/prices", params) or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Split- and dividend-adjusted bars, like Yahoo's default history.
    if "adjClose" in df:
        df = df.assign(open=df["adjOpen"], high=df["adjHigh"], low=df["adjLow"], close=df["adjClose"],
                       volume=df["adjVolume"])
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    return _trim(df.set_index("date"), period, start, end)


# ----------------------------------------------------------------- Polygon


def polygon_key() -> Optional[str]:
    return key("polygon_key", "POLYGON_API_KEY")


def polygon_history(symbol: str, period: str = "1y", interval: TimeFrame = TimeFrame.DAY_1,
                    start: Optional[datetime] = None, end: Optional[datetime] = None, **_ignored) -> pd.DataFrame:
    _ensure_daily(interval)
    k = polygon_key()
    if not k:
        raise ValueError("Polygon key not set")
    since = start or (datetime.now() - timedelta(days=period_days(period)))
    until = end or datetime.now()
    resp = requests.get(
        f"https://api.polygon.io/v2/aggs/ticker/{symbol.upper()}/range/1/day/"
        f"{since:%Y-%m-%d}/{until:%Y-%m-%d}",
        params={"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": k}, timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    if data.get("status") == "ERROR":
        raise ValueError(f"Polygon: {data.get('error') or data.get('message')}")
    rows = data.get("results") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    # A point at 00:00 UTC is the previous day's close; the last point is "now".
    df["date"] = pd.to_datetime(df["t"] - 1, unit="ms").dt.normalize()
    return _trim(df.set_index("date"), period, start, end)


def polygon_quote(symbol: str) -> dict:
    return quote_from_frame(symbol, polygon_history(symbol, period="1mo"))


# --------------------------------------------------------------- CoinGecko

_COINGECKO = "https://api.coingecko.com/api/v3"
_coin_ids: dict[str, Optional[str]] = {}


def _coingecko(path: str, params: dict):
    headers = {"Accept": "application/json"}
    k = key("coingecko_api_key")  # optional free "demo" key: higher rate limit
    if k:
        headers["x-cg-demo-api-key"] = k
    resp = requests.get(f"{_COINGECKO}/{path}", params=params, headers=headers, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def coin_base(symbol: str) -> str:
    """BTC-USD / BTCUSDT / BTC/USDT / btc -> BTC."""
    s = symbol.upper().replace("/", "").replace("-", "")
    for quote in ("USDT", "USDC", "USD"):
        if s.endswith(quote) and len(s) > len(quote):
            return s[: -len(quote)]
    return s


def coingecko_id(symbol: str) -> str:
    """CoinGecko's id for a ticker: the best-ranked coin with exactly that symbol."""
    base = coin_base(symbol)
    if base not in _coin_ids:
        coins = (_coingecko("search", {"query": base}) or {}).get("coins") or []
        same = [c for c in coins if (c.get("symbol") or "").upper() == base]
        same.sort(key=lambda c: c.get("market_cap_rank") or 10**9)
        _coin_ids[base] = same[0]["id"] if same else None
    coin = _coin_ids[base]
    if not coin:
        raise ValueError(f"CoinGecko has no coin {base}")
    return coin


def coingecko_quote(symbol: str) -> dict:
    rows = _coingecko("coins/markets", {"vs_currency": "usd", "ids": coingecko_id(symbol)}) or []
    if not rows or rows[0].get("current_price") is None:
        raise ValueError(f"CoinGecko has no price for {symbol}")
    q = rows[0]
    price, change = q["current_price"], q.get("price_change_24h")
    return {
        "symbol": symbol, "price": price, "previous_close": price - change if change is not None else None,
        "open": None, "day_high": q.get("high_24h"), "day_low": q.get("low_24h"),
        "volume": q.get("total_volume"), "change": change, "change_percent": q.get("price_change_percentage_24h"),
        "market_cap": q.get("market_cap"),
    }


def coingecko_history(symbol: str, period: str = "1y", interval: TimeFrame = TimeFrame.DAY_1,
                      start: Optional[datetime] = None, end: Optional[datetime] = None, **_ignored) -> pd.DataFrame:
    """Daily closes and USD volume only (daily candles are a paid feature):
    open is the previous close and high / low equal the close."""
    _ensure_daily(interval)
    days = min(365, period_days(period, start))  # the free API serves the last 365 days
    data = _coingecko(f"coins/{coingecko_id(symbol)}/market_chart",
                      {"vs_currency": "usd", "days": days, "interval": "daily"}) or {}
    prices = data.get("prices") or []
    if not prices:
        return pd.DataFrame()
    df = pd.DataFrame(prices, columns=["t", "close"])
    vol = dict((t, v) for t, v in (data.get("total_volumes") or []))
    df["volume"] = df["t"].map(vol)
    # A point at 00:00 UTC is the previous day's close; the last point is "now".
    df["date"] = pd.to_datetime(df["t"] - 1, unit="ms").dt.normalize()
    df = df.drop_duplicates("date", keep="last").set_index("date")
    df["open"] = df["close"].shift(1).fillna(df["close"])
    df["high"] = df[["open", "close"]].max(axis=1)
    df["low"] = df[["open", "close"]].min(axis=1)
    df = _trim(df, period, start, end)
    df.attrs["close_only"] = True
    return df


# ------------------------------------------------------- Crypto fear & greed


def crypto_fear_greed(days: int = 30) -> list[dict]:
    """alternative.me's daily crypto fear & greed index (0-100), newest first."""
    resp = requests.get("https://api.alternative.me/fng/", params={"limit": days}, timeout=_TIMEOUT)
    resp.raise_for_status()
    rows = (resp.json() or {}).get("data") or []
    return [{
        "date": datetime.fromtimestamp(int(r["timestamp"]), timezone.utc).strftime("%Y-%m-%d"),
        "value": int(r["value"]), "label": r.get("value_classification"),
    } for r in rows if r.get("value") is not None]
