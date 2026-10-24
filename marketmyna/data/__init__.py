"""Data fetching module for market data."""

from .base import DataFetcher
from .crypto import CryptoDataFetcher
from .india import IndiaDataFetcher
from .stocks import StockDataFetcher

__all__ = ["DataFetcher", "StockDataFetcher", "CryptoDataFetcher", "IndiaDataFetcher"]
