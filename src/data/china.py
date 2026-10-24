"""China A-share and Hong Kong market data fetchers, backed by akshare
(with yfinance as the fallback source, so quotes/history still work when
akshare isn't installed).

akshare is free and token-less (unlike tushare/baostock/pytdx, which need
paid tiers or registered tokens), making it the pragmatic first source for
a self-hosted personal tool. Two real gotchas carried forward from how
daily_stock_analysis's own akshare adapter uses these same endpoints:

- The realtime-quote endpoints (`stock_zh_a_spot_em` / `stock_hk_spot_em`)
  return a FULL MARKET snapshot (thousands of rows), not a single symbol -
  fetching it per quote request would be both slow and a good way to get
  rate-limited/banned. Snapshots are cached in-memory with a TTL and a
  single symbol is filtered out of the cached DataFrame.
- akshare's free endpoints are known to be flaky/occasionally rate-limit
  or ban aggressive callers. A small randomized delay is added before each
  raw network call, and both fetchers go through Phase 2a's
  `FallbackChain`/`CircuitBreaker` so a source having a bad day gets
  skipped for a cooldown instead of hammered on every call.

Known limitation (not implemented in this pass): the index codes listed in
`MARKET_INDICES` (e.g. "000001" for 上证指数) are NOT resolvable through
these fetchers - `stock_zh_a_hist`/`stock_zh_a_spot_em` are stock-only
endpoints, and a 6-digit index code can collide with an A-share stock code
in the same numeric range. Index history needs akshare's separate
`index_zh_a_hist`-family functions, out of scope for this phase (which
targets individual stock quotes/history).
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timedelta
from threading import RLock
from typing import Optional

import pandas as pd

from .base import DataFetcher
from .extra_sources import tencent_history, tencent_quote
from .resilience import FallbackChain
from ..core.constants import TimeFrame

# Akshare's Chinese column names -> the same lowercase-English convention
# StockDataFetcher.get_history already returns, so downstream analysis
# code (src/analysis/technical.py etc.) needs no market-specific handling.
_CN_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "pct_chg",
    "涨跌额": "change",
    "换手率": "turnover_rate",
}

# period string -> approximate days, same convention as IndiaDataFetcher's
# _PERIOD_DAYS, used to compute a start date when the caller doesn't pass
# explicit start/end datetimes.
_PERIOD_DAYS = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825, "10y": 3650}

# akshare's stock_zh_a_hist/stock_hk_hist only offer daily/weekly/monthly
# bars - there is no intraday endpoint behind these functions.
_TIMEFRAME_TO_AKSHARE_PERIOD = {
    TimeFrame.DAY_1: "daily",
    TimeFrame.WEEK_1: "weekly",
    TimeFrame.MONTH_1: "monthly",
}


def _yf_quote(yf_symbol: str, code: str) -> dict:
    """yfinance fallback for when akshare is missing or failing."""
    from .stocks import StockDataFetcher

    quote = StockDataFetcher()._fetch_quote_yfinance(yf_symbol)
    quote["symbol"] = code
    return quote


def _yf_history(yf_symbol: str, **kwargs) -> pd.DataFrame:
    from .stocks import StockDataFetcher

    return StockDataFetcher()._fetch_history_yfinance(yf_symbol, **kwargs)


def _rate_limit_delay() -> None:
    """Small randomized delay before a raw akshare call, mirroring
    daily_stock_analysis's own anti-ban strategy for these free endpoints."""
    time.sleep(random.uniform(0.5, 1.5))


class _SnapshotCache:
    """Caches one akshare full-market-snapshot DataFrame with a TTL, so a
    quote for a single symbol doesn't trigger a fresh full-market pull on
    every call. Thread-safe; a failed fetch is not cached (so the next call
    retries rather than serving a permanently-empty snapshot)."""

    def __init__(self, ttl_seconds: float = 1200.0):
        self.ttl_seconds = ttl_seconds
        self._lock = RLock()
        self._df: Optional[pd.DataFrame] = None
        self._fetched_at: float = 0.0

    def get(self, fetch_fn) -> pd.DataFrame:
        with self._lock:
            age = time.time() - self._fetched_at
            if self._df is not None and age < self.ttl_seconds:
                return self._df
            _rate_limit_delay()
            df = fetch_fn()
            if df is not None and not df.empty:
                self._df = df
                self._fetched_at = time.time()
                return df
            # Failed/empty fetch: serve a stale snapshot if we have one
            # rather than nothing, but don't reset the TTL clock on it.
            if self._df is not None:
                return self._df
            return pd.DataFrame()


def _resolve_date_range(
    period: str, start: Optional[datetime], end: Optional[datetime]
) -> tuple[str, str]:
    """-> (start_date, end_date) as 'YYYYMMDD' strings, akshare's expected format."""
    range_end = end or datetime.now()
    range_start = start or (range_end - timedelta(days=_PERIOD_DAYS.get(period, 365)))
    return range_start.strftime("%Y%m%d"), range_end.strftime("%Y%m%d")


def _resolve_akshare_period(interval: TimeFrame) -> str:
    ak_period = _TIMEFRAME_TO_AKSHARE_PERIOD.get(interval)
    if ak_period is None:
        raise ValueError(
            f"Intraday interval {interval.value!r} is not supported by akshare's "
            "A-share/Hong Kong history endpoints (daily/weekly/monthly only)."
        )
    return ak_period


def _normalize_history_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns=_CN_COLUMN_MAP)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
    return df


class _AkshareFetcher(DataFetcher):
    """Shared by the A-share and Hong Kong fetchers: eastmoney (akshare) first,
    then Tencent, then yfinance. Subclasses set the market specifics below."""

    MARKET = ""  # FallbackChain / tencent market name
    EXCHANGE = ""
    CURRENCY = ""
    SNAPSHOT_FN = ""  # akshare spot table
    HISTORY_FN = ""  # akshare daily / weekly / monthly history
    PE_COLUMN = ""

    def __init__(self):
        self._snapshot = _SnapshotCache()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        raise NotImplementedError

    def _yf_symbol(self, symbol: str) -> str:
        raise NotImplementedError

    def _fetch_quote_tencent(self, symbol: str) -> dict:
        return tencent_quote(self._normalize_symbol(symbol), self.MARKET)

    def _fetch_history_tencent(self, symbol: str, **kwargs) -> pd.DataFrame:
        return tencent_history(self._normalize_symbol(symbol), self.MARKET, **kwargs)

    def _fetch_quote_yfinance(self, symbol: str) -> dict:
        return _yf_quote(self._yf_symbol(symbol), self._normalize_symbol(symbol))

    def _fetch_history_yfinance(self, symbol: str, **kwargs) -> pd.DataFrame:
        return _yf_history(self._yf_symbol(symbol), **kwargs)

    def _fetch_snapshot(self) -> pd.DataFrame:
        import akshare as ak

        return self._snapshot.get(getattr(ak, self.SNAPSHOT_FN))

    def _fetch_quote_akshare(self, symbol: str) -> dict:
        code = self._normalize_symbol(symbol)
        df = self._fetch_snapshot()
        if df.empty:
            return {}

        row = df[df["代码"] == code]
        if row.empty:
            return {}
        row = row.iloc[0]

        price = row.get("最新价")
        change = row.get("涨跌额")
        previous_close = (price - change) if price is not None and change is not None else None

        return {
            "symbol": code,
            "name": str(row.get("名称", "")),
            "price": price,
            "previous_close": previous_close,
            "open": row.get("今开"),
            "day_high": row.get("最高"),
            "day_low": row.get("最低"),
            "volume": row.get("成交量"),
            "market_cap": row.get("总市值"),
            "change": change,
            "change_percent": row.get("涨跌幅"),
        }

    def get_quote(self, symbol: str) -> dict:
        chain = FallbackChain(f"{self.MARKET}.get_quote")
        chain.add("akshare_em", self._fetch_quote_akshare)
        chain.add("tencent", self._fetch_quote_tencent)
        chain.add("yfinance", self._fetch_quote_yfinance)
        return chain.call(symbol, is_empty=lambda d: not d or d.get("price") is None)

    def _fetch_history_akshare(
        self,
        symbol: str,
        period: str = "1y",
        interval: TimeFrame = TimeFrame.DAY_1,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        import akshare as ak

        code = self._normalize_symbol(symbol)
        ak_period = _resolve_akshare_period(interval)
        start_date, end_date = _resolve_date_range(period, start, end)

        _rate_limit_delay()
        df = getattr(ak, self.HISTORY_FN)(
            symbol=code, period=ak_period, start_date=start_date, end_date=end_date, adjust="qfq"
        )
        return _normalize_history_columns(df)

    def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: TimeFrame = TimeFrame.DAY_1,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        chain = FallbackChain(f"{self.MARKET}.get_history")
        chain.add("akshare_em", self._fetch_history_akshare)
        chain.add("tencent", self._fetch_history_tencent)
        chain.add("yfinance", self._fetch_history_yfinance)
        return chain.call(
            symbol, period=period, interval=interval, start=start, end=end, is_empty=lambda df: df.empty
        )

    def search(self, query: str) -> list[dict]:
        """Stocks by code prefix or name substring."""
        df = self._fetch_snapshot()
        if df.empty:
            return []
        query_lower = query.strip().lower()
        matches = df[
            df["代码"].astype(str).str.lower().str.startswith(query_lower)
            | df["名称"].astype(str).str.contains(query, case=False, na=False)
        ]
        return [
            {"symbol": row["代码"], "name": row["名称"], "exchange": self.EXCHANGE, "type": "EQUITY"}
            for _, row in matches.head(20).iterrows()
        ]

    def get_info(self, symbol: str) -> dict:
        code = self._normalize_symbol(symbol)
        df = self._fetch_snapshot()
        row = df[df["代码"] == code] if not df.empty else df
        if row.empty:
            return {"symbol": code, "name": "", "currency": self.CURRENCY}
        row = row.iloc[0]
        return {
            "symbol": code,
            "name": str(row.get("名称", "")),
            "sector": "",
            "industry": "",
            "currency": self.CURRENCY,
            "market_cap": row.get("总市值", 0),
            "pe_ratio": row.get(self.PE_COLUMN, 0),
            "pb_ratio": row.get("市净率", 0),
            "52_week_high": row.get("52周最高", 0),
            "52_week_low": row.get("52周最低", 0),
        }


class ChinaAFetcher(_AkshareFetcher):
    """Fetches mainland China A-share data (Shanghai/Shenzhen) via akshare."""

    MARKET = "china_a"
    EXCHANGE = "SH/SZ"
    CURRENCY = "CNY"
    SNAPSHOT_FN = "stock_zh_a_spot_em"
    HISTORY_FN = "stock_zh_a_hist"
    PE_COLUMN = "市盈率-动态"

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Accept 'sh600519', 'SZ000001', '600519.SH', or bare '600519' ->
        the bare 6-digit code akshare's A-share functions expect."""
        code = symbol.strip().lower()
        for prefix in ("sh", "sz", "bj"):
            if code.startswith(prefix):
                code = code[len(prefix):]
        for suffix in (".sh", ".sz", ".bj"):
            if code.endswith(suffix):
                code = code[: -len(suffix)]
        code = code.strip()
        if not code.isdigit() or len(code) != 6:
            raise ValueError(f"'{symbol}' does not look like a 6-digit A-share code")
        return code

    def _yf_symbol(self, symbol: str) -> str:
        code = self._normalize_symbol(symbol)
        suffix = ".SS" if code[0] in "569" else ".BJ" if code[0] in "48" else ".SZ"
        return code + suffix


class HongKongFetcher(_AkshareFetcher):
    """Fetches Hong Kong exchange data via akshare."""

    MARKET = "hong_kong"
    EXCHANGE = "HKEX"
    CURRENCY = "HKD"
    SNAPSHOT_FN = "stock_hk_spot_em"
    HISTORY_FN = "stock_hk_hist"
    PE_COLUMN = "市盈率"

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """Accept 'hk00700', '00700.HK', '700', or bare '00700' -> the
        zero-padded 5-digit code akshare's HK functions expect."""
        code = symbol.strip().lower()
        if code.startswith("hk"):
            code = code[2:]
        if code.endswith(".hk"):
            code = code[:-3]
        code = code.strip()
        if not code.isdigit() or not (1 <= len(code) <= 5):
            raise ValueError(f"'{symbol}' does not look like a Hong Kong stock code")
        return code.zfill(5)

    def _yf_symbol(self, symbol: str) -> str:
        # yfinance uses 4-digit HK codes: 00700 -> 0700.HK, 09988 -> 9988.HK
        return f"{int(self._normalize_symbol(symbol)):04d}.HK"
