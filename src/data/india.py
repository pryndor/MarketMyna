"""Indian market data fetcher using jugaad-data and Yahoo Finance."""

from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

from .base import DataFetcher
from .extra_sources import twelvedata_history, twelvedata_key, twelvedata_quote
from .resilience import FallbackChain
from ..analysis.fundamental import yfinance_fundamentals
from ..core.constants import TimeFrame


STALE_QUOTE_GAP = 0.10


def quote_from_bars(symbol: str, bars: pd.DataFrame) -> dict:
    """A quote from the latest daily bars (Yahoo history: Open/High/Low/Close/Volume)."""
    bar = bars.iloc[-1]
    price = float(bar["Close"])
    prev = float(bars["Close"].iloc[-2]) if len(bars) > 1 else None
    return {
        "symbol": symbol,
        "price": price,
        "previous_close": prev,
        "open": float(bar["Open"]),
        "day_high": float(bar["High"]),
        "day_low": float(bar["Low"]),
        "volume": int(bar["Volume"]),
        "change": price - prev if prev else 0,
        "change_percent": (price - prev) / prev * 100 if prev else 0,
    }


# A BSE history shorter than this is treated as missing (see get_history).
BSE_MIN_BARS = 30


def is_bse(symbol: str) -> bool:
    """RELIANCE.BO = the BSE listing; RELIANCE or RELIANCE.NS = NSE."""
    return symbol.upper().endswith(".BO")


class IndiaDataFetcher(DataFetcher):
    """Fetches Indian stock market data (NSE/BSE)."""

    def __init__(self):
        self._cache = {}
        # Try to import jugaad_data, fall back to yfinance if not available
        try:
            from jugaad_data.nse import stock_df, NSELive
            self._nse_live = NSELive()
            self._stock_df = stock_df
            self._use_jugaad = True
        except ImportError:
            self._use_jugaad = False

    def _get_yf_symbol(self, symbol: str) -> str:
        """Convert to Yahoo Finance format for Indian stocks."""
        # Don't modify index symbols (they start with ^)
        if symbol.startswith("^"):
            return symbol
        if not symbol.endswith(".NS") and not symbol.endswith(".BO"):
            return f"{symbol}.NS"  # Default to NSE
        return symbol

    def _fetch_quote_jugaad(self, symbol: str) -> dict:
        quote = self._nse_live.stock_quote(symbol.replace(".NS", "").replace(".BO", ""))
        price_info = quote.get("priceInfo", {})
        return {
            "symbol": symbol,
            "price": price_info.get("lastPrice", 0),
            "previous_close": price_info.get("previousClose", 0),
            "open": price_info.get("open", 0),
            "day_high": price_info.get("intraDayHighLow", {}).get("max", 0),
            "day_low": price_info.get("intraDayHighLow", {}).get("min", 0),
            "volume": quote.get("securityWiseDP", {}).get("quantityTraded", 0),
            "change": price_info.get("change", 0),
            "change_percent": price_info.get("pChange", 0),
        }

    def _fetch_quote_yfinance(self, symbol: str) -> dict:
        import yfinance as yf
        ticker = yf.Ticker(self._get_yf_symbol(symbol))
        info = ticker.fast_info
        try:
            last, prev = info.last_price, info.previous_close
        except KeyError:
            # Yahoo has no such symbol (a typo, a fund name): an empty answer,
            # not a source failure, so it can't trip the breaker for every stock.
            return {}

        # Yahoo's live quote for some listings (REITs, InvITs) is frozen at
        # an old date while its daily bars stay current. A move of more than
        # 10% is checked against the bars; if they disagree, the bars win.
        if last and prev and abs(last / prev - 1) > STALE_QUOTE_GAP:
            bars = ticker.history(period="5d", interval="1d")
            if not bars.empty and abs(last / float(bars["Close"].iloc[-1]) - 1) > STALE_QUOTE_GAP:
                return quote_from_bars(symbol, bars)

        return {
            "symbol": symbol,
            "price": last,
            "previous_close": prev,
            "open": info.open,
            "day_high": info.day_high,
            "day_low": info.day_low,
            "volume": info.last_volume,
            "change": last - prev if prev else 0,
            "change_percent": ((last - prev) / prev) * 100 if prev else 0,
        }

    def get_quote(self, symbol: str) -> dict:
        """Get current quote for an Indian stock."""
        chain = FallbackChain("india.get_quote")
        # jugaad-data reads NSE only: a BSE symbol (.BO) goes straight to Yahoo.
        if self._use_jugaad and not is_bse(symbol):
            chain.add("jugaad", self._fetch_quote_jugaad)
        chain.add("yfinance", self._fetch_quote_yfinance)
        if not symbol.startswith("^") and twelvedata_key():
            chain.add("twelvedata", lambda s: twelvedata_quote(s, "india"))
        return chain.call(symbol, is_empty=lambda d: not d or not d.get("price"))

    _PERIOD_DAYS = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365, "2y": 730, "5y": 1825}

    def _fetch_history_jugaad(
        self,
        symbol: str,
        period: str = "1y",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        **_ignored,
    ) -> pd.DataFrame:
        clean_symbol = symbol.replace(".NS", "").replace(".BO", "")
        range_start = start or (datetime.now() - timedelta(days=self._PERIOD_DAYS.get(period, 365)))
        range_end = end or datetime.now()

        df = self._stock_df(symbol=clean_symbol, from_date=range_start.date(), to_date=range_end.date())
        if df.empty:
            return df

        df = df.rename(
            columns={
                "DATE": "date",
                "OPEN": "open",
                "HIGH": "high",
                "LOW": "low",
                "CLOSE": "close",
                "LTP": "ltp",
                "VOLUME": "volume",
            }
        )
        df.set_index("date", inplace=True)
        return df

    def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: TimeFrame = TimeFrame.DAY_1,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Get historical price data for an Indian stock."""
        chain = FallbackChain("india.get_history")
        if self._use_jugaad and interval == TimeFrame.DAY_1 and not is_bse(symbol):
            chain.add("jugaad", self._fetch_history_jugaad)
        chain.add("yfinance", self._fetch_history_yfinance)
        if not symbol.startswith("^") and twelvedata_key():
            chain.add("twelvedata", lambda s, **kw: twelvedata_history(s, "india", **kw))
        df = chain.call(
            symbol, period=period, interval=interval, start=start, end=end, is_empty=lambda df: df.empty
        )
        if is_bse(symbol) and len(df) < BSE_MIN_BARS:
            # Yahoo often has only the last day or two for a BSE listing
            # (RELIANCE.BO). The same company's NSE history trades within
            # paise of it, so charts, indicators and levels use that instead.
            try:
                nse = self.get_history(symbol[:-3], period=period, interval=interval, start=start, end=end)
            except Exception:
                nse = None
            if nse is not None and len(nse) > len(df):
                nse.attrs["history_from"] = "NSE"
                return nse
        return df

    def _fetch_history_yfinance(self, symbol: str, **kwargs) -> pd.DataFrame:
        from .stocks import StockDataFetcher

        return StockDataFetcher()._fetch_history_yfinance(self._get_yf_symbol(symbol), **kwargs)

    def search(self, query: str) -> list[dict]:
        """Search for Indian stocks matching query."""
        # Use yfinance for search
        import yfinance as yf

        results = []
        for suffix in [".NS", ".BO"]:
            try:
                ticker = yf.Ticker(f"{query}{suffix}")
                info = ticker.info
                if info and info.get("symbol"):
                    results.append(
                        {
                            "symbol": info.get("symbol"),
                            "name": info.get("longName", info.get("shortName", "")),
                            "exchange": "NSE" if suffix == ".NS" else "BSE",
                            "type": info.get("quoteType", "EQUITY"),
                        }
                    )
            except Exception:
                pass

        return results

    def get_info(self, symbol: str) -> dict:
        """Get detailed information about an Indian stock."""
        import yfinance as yf

        ticker = yf.Ticker(self._get_yf_symbol(symbol))
        info = ticker.info

        return {
            "symbol": info.get("symbol", symbol),
            "name": info.get("longName", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "description": info.get("longBusinessSummary", ""),
            "currency": "INR",
            "market_cap": info.get("marketCap", 0),
            "pe_ratio": info.get("trailingPE", 0),
            "pb_ratio": info.get("priceToBook", 0),
            "dividend_yield": info.get("dividendYield", 0),
            "52_week_high": info.get("fiftyTwoWeekHigh", 0),
            "52_week_low": info.get("fiftyTwoWeekLow", 0),
            "book_value": info.get("bookValue", 0),
            "face_value": info.get("faceValue", 0),
            # Normalized ratios for FundamentalAnalyzer (overrides the raw
            # yfinance-unit fields above, e.g. dividend_yield)
            **yfinance_fundamentals(info),
        }
