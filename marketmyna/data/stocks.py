"""Stock data fetcher using Yahoo Finance."""

from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf

from ..analysis.fundamental import yfinance_fundamentals
from ..core.constants import TimeFrame
from .base import DataFetcher
from .extra_sources import (
    alphavantage_history,
    alphavantage_key,
    alphavantage_quote,
    finnhub_key,
    finnhub_quote,
    nasdaq_history,
    nasdaq_quote,
    polygon_history,
    polygon_key,
    polygon_quote,
    tiingo_history,
    tiingo_key,
    tiingo_quote,
    twelvedata_history,
    twelvedata_key,
    twelvedata_quote,
)
from .resilience import FallbackChain


def _plain_us(symbol: str) -> bool:
    return symbol.replace(".", "").replace("-", "").isalpha()


class StockDataFetcher(DataFetcher):
    """Fetches stock data from Yahoo Finance (US & Global markets).

    Yahoo first; plain US tickers then fall back to the keyed sources
    configured (Finnhub, Twelve Data, Tiingo, Alpha Vantage, Polygon) and
    Nasdaq, which needs no key. Index and foreign symbols (^GSPC,
    RELIANCE.NS) have only Yahoo.
    """

    def __init__(self):
        self._cache = {}

    def _fetch_quote_yfinance(self, symbol: str) -> dict:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        try:
            price = info.last_price
        except KeyError:
            return {}  # unknown symbol: empty, not a source failure (see india.py)

        return {
            "symbol": symbol,
            "price": price,
            "previous_close": info.previous_close,
            "open": info.open,
            "day_high": info.day_high,
            "day_low": info.day_low,
            "volume": info.last_volume,
            "market_cap": info.market_cap,
            "change": info.last_price - info.previous_close,
            "change_percent": ((info.last_price - info.previous_close) / info.previous_close) * 100
            if info.previous_close
            else 0,
        }

    def get_quote(self, symbol: str) -> dict:
        """Get current quote for a stock."""
        chain = FallbackChain("stocks.get_quote").add("yfinance", self._fetch_quote_yfinance)
        # Keyed backups for US tickers (index/foreign symbols like ^GSPC or
        # RELIANCE.NS aren't covered by these APIs' free tiers).
        if _plain_us(symbol):
            if finnhub_key():
                chain.add("finnhub", finnhub_quote)
            if twelvedata_key():
                chain.add("twelvedata", twelvedata_quote)
            if tiingo_key():
                chain.add("tiingo", tiingo_quote)
            chain.add("nasdaq", nasdaq_quote)
            if alphavantage_key():
                chain.add("alphavantage", alphavantage_quote)
            if polygon_key():
                chain.add("polygon", polygon_quote)
        return chain.call(symbol, is_empty=lambda d: not d or d.get("price") is None)

    def _fetch_history_yfinance(
        self,
        symbol: str,
        period: str = "1y",
        interval: TimeFrame = TimeFrame.DAY_1,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        ticker = yf.Ticker(symbol)

        if start and end:
            df = ticker.history(start=start, end=end, interval=interval.value)
        else:
            df = ticker.history(period=period, interval=interval.value)

        if df.empty:
            return pd.DataFrame()

        # Standardize column names
        df.columns = [col.lower().replace(" ", "_") for col in df.columns]
        return df

    def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: TimeFrame = TimeFrame.DAY_1,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Get historical price data for a stock."""
        chain = FallbackChain("stocks.get_history").add("yfinance", self._fetch_history_yfinance)
        # Daily bars only: an intraday request skips these (they raise).
        if _plain_us(symbol):
            if twelvedata_key():
                chain.add("twelvedata", twelvedata_history)
            if tiingo_key():
                chain.add("tiingo", tiingo_history)
            if polygon_key():
                chain.add("polygon", polygon_history)
            chain.add("nasdaq", nasdaq_history)
            if alphavantage_key():
                chain.add("alphavantage", alphavantage_history)
        return chain.call(symbol, period=period, interval=interval, start=start, end=end, is_empty=lambda df: df.empty)

    def search(self, query: str) -> list[dict]:
        """Search for stocks matching query."""
        try:
            ticker = yf.Ticker(query)
            info = ticker.info
            if info and "symbol" in info:
                return [
                    {
                        "symbol": info.get("symbol", query),
                        "name": info.get("longName", info.get("shortName", "")),
                        "exchange": info.get("exchange", ""),
                        "type": info.get("quoteType", ""),
                    }
                ]
        except Exception:
            pass
        return []

    def get_info(self, symbol: str) -> dict:
        """Get detailed information about a stock."""
        ticker = yf.Ticker(symbol)
        info = ticker.info

        return {
            "symbol": info.get("symbol", symbol),
            "name": info.get("longName", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "description": info.get("longBusinessSummary", ""),
            "website": info.get("website", ""),
            "employees": info.get("fullTimeEmployees", 0),
            "country": info.get("country", ""),
            "currency": info.get("currency", "USD"),
            # Valuation metrics
            "market_cap": info.get("marketCap", 0),
            "pe_ratio": info.get("trailingPE", 0),
            "forward_pe": info.get("forwardPE", 0),
            "peg_ratio": info.get("pegRatio", 0),
            "price_to_book": info.get("priceToBook", 0),
            "price_to_sales": info.get("priceToSalesTrailing12Months", 0),
            # Financial metrics
            "revenue": info.get("totalRevenue", 0),
            "gross_profit": info.get("grossProfits", 0),
            "ebitda": info.get("ebitda", 0),
            "net_income": info.get("netIncomeToCommon", 0),
            "eps": info.get("trailingEps", 0),
            # Dividend info
            "dividend_yield": info.get("dividendYield", 0),
            "dividend_rate": info.get("dividendRate", 0),
            "payout_ratio": info.get("payoutRatio", 0),
            # Trading info
            "52_week_high": info.get("fiftyTwoWeekHigh", 0),
            "52_week_low": info.get("fiftyTwoWeekLow", 0),
            "50_day_avg": info.get("fiftyDayAverage", 0),
            "200_day_avg": info.get("twoHundredDayAverage", 0),
            "avg_volume": info.get("averageVolume", 0),
            "beta": info.get("beta", 0),
            # Normalized ratios for FundamentalAnalyzer (overrides the raw
            # yfinance-unit fields above, e.g. dividend_yield)
            **yfinance_fundamentals(info),
        }

