"""Cryptocurrency data fetcher: Binance (ccxt), then Yahoo, then CoinGecko."""

from datetime import datetime
from typing import Optional

import pandas as pd

from ..core.constants import TimeFrame
from .base import DataFetcher
from .extra_sources import coingecko_history, coingecko_quote
from .resilience import FallbackChain


class CryptoDataFetcher(DataFetcher):
    """Fetches cryptocurrency data from multiple exchanges."""

    def __init__(self, exchange: str = "binance"):
        self._exchange_name = exchange
        self._exchange = None
        self._init_exchange()

    def _init_exchange(self):
        """Initialize the exchange connection."""
        try:
            import ccxt
            exchange_class = getattr(ccxt, self._exchange_name, None)
            if exchange_class:
                self._exchange = exchange_class()
        except ImportError:
            self._exchange = None

    def _get_yf_symbol(self, symbol: str) -> str:
        """Convert to Yahoo Finance format for crypto."""
        if "-USD" not in symbol and "USDT" not in symbol:
            return f"{symbol}-USD"
        return symbol

    def _fetch_quote_ccxt(self, symbol: str) -> dict:
        # Convert symbol format (BTC -> BTC/USDT)
        ccxt_symbol = symbol.replace("-USD", "/USDT").replace("USD", "/USDT")
        if "/" not in ccxt_symbol:
            ccxt_symbol = f"{ccxt_symbol}/USDT"

        ticker = self._exchange.fetch_ticker(ccxt_symbol)
        return {
            "symbol": symbol,
            "price": ticker["last"],
            "previous_close": ticker["previousClose"] or ticker["open"],
            "open": ticker["open"],
            "day_high": ticker["high"],
            "day_low": ticker["low"],
            "volume": ticker["baseVolume"],
            "quote_volume": ticker["quoteVolume"],
            "change": ticker["change"] or 0,
            "change_percent": ticker["percentage"] or 0,
            "bid": ticker["bid"],
            "ask": ticker["ask"],
        }

    def _fetch_quote_yfinance(self, symbol: str) -> dict:
        import yfinance as yf
        ticker = yf.Ticker(self._get_yf_symbol(symbol))
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
            "change": info.last_price - info.previous_close if info.previous_close else 0,
            "change_percent": ((info.last_price - info.previous_close) / info.previous_close) * 100
            if info.previous_close
            else 0,
        }

    def get_quote(self, symbol: str) -> dict:
        """Get current quote for a cryptocurrency."""
        chain = FallbackChain("crypto.get_quote")
        if self._exchange:
            chain.add(self._exchange_name, self._fetch_quote_ccxt)
        chain.add("yfinance", self._fetch_quote_yfinance)
        chain.add("coingecko", coingecko_quote)
        return chain.call(symbol, is_empty=lambda d: not d or d.get("price") is None)

    _CCXT_TIMEFRAME_MAP = {
        TimeFrame.MINUTE_1: "1m",
        TimeFrame.MINUTE_5: "5m",
        TimeFrame.MINUTE_15: "15m",
        TimeFrame.MINUTE_30: "30m",
        TimeFrame.HOUR_1: "1h",
        TimeFrame.HOUR_4: "4h",
        TimeFrame.DAY_1: "1d",
        TimeFrame.WEEK_1: "1w",
    }

    def _fetch_history_ccxt(
        self, symbol: str, interval: TimeFrame, start: Optional[datetime] = None, **_ignored
    ) -> pd.DataFrame:
        ccxt_symbol = symbol.replace("-USD", "/USDT").replace("USD", "/USDT")
        if "/" not in ccxt_symbol:
            ccxt_symbol = f"{ccxt_symbol}/USDT"

        since = int(start.timestamp() * 1000) if start else None

        ohlcv = self._exchange.fetch_ohlcv(
            ccxt_symbol, self._CCXT_TIMEFRAME_MAP[interval], since=since, limit=1000
        )

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    def _fetch_history_yfinance(self, symbol: str, **kwargs) -> pd.DataFrame:
        from .stocks import StockDataFetcher

        return StockDataFetcher()._fetch_history_yfinance(self._get_yf_symbol(symbol), **kwargs)

    def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: TimeFrame = TimeFrame.DAY_1,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Get historical price data for a cryptocurrency."""
        chain = FallbackChain("crypto.get_history")
        if self._exchange and interval in self._CCXT_TIMEFRAME_MAP:
            chain.add(self._exchange_name, self._fetch_history_ccxt)
        chain.add("yfinance", self._fetch_history_yfinance)
        if interval == TimeFrame.DAY_1:
            chain.add("coingecko", coingecko_history)
        return chain.call(
            symbol, period=period, interval=interval, start=start, end=end, is_empty=lambda df: df.empty
        )

    def search(self, query: str) -> list[dict]:
        """Search for cryptocurrencies matching query."""
        query_upper = query.upper()

        # Common crypto symbols
        popular_cryptos = {
            "BTC": "Bitcoin",
            "ETH": "Ethereum",
            "BNB": "Binance Coin",
            "XRP": "Ripple",
            "SOL": "Solana",
            "ADA": "Cardano",
            "DOGE": "Dogecoin",
            "DOT": "Polkadot",
            "MATIC": "Polygon",
            "SHIB": "Shiba Inu",
            "LTC": "Litecoin",
            "AVAX": "Avalanche",
            "LINK": "Chainlink",
            "UNI": "Uniswap",
            "ATOM": "Cosmos",
        }

        results = []
        for symbol, name in popular_cryptos.items():
            if query_upper in symbol or query_upper in name.upper():
                results.append(
                    {
                        "symbol": f"{symbol}-USD",
                        "name": name,
                        "exchange": "Crypto",
                        "type": "CRYPTOCURRENCY",
                    }
                )

        return results

    def get_info(self, symbol: str) -> dict:
        """Get detailed information about a cryptocurrency."""
        import yfinance as yf

        ticker = yf.Ticker(self._get_yf_symbol(symbol))
        info = ticker.info

        return {
            "symbol": symbol,
            "name": info.get("name", info.get("shortName", "")),
            "description": info.get("description", ""),
            "market_cap": info.get("marketCap", 0),
            "circulating_supply": info.get("circulatingSupply", 0),
            "total_supply": info.get("totalSupply", 0),
            "max_supply": info.get("maxSupply", 0),
            "volume_24h": info.get("volume24Hr", 0),
            "52_week_high": info.get("fiftyTwoWeekHigh", 0),
            "52_week_low": info.get("fiftyTwoWeekLow", 0),
        }
