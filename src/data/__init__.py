"""Data fetching module for market data."""

from .base import DataFetcher
from .stocks import StockDataFetcher
from .crypto import CryptoDataFetcher
from .india import IndiaDataFetcher

__all__ = ["DataFetcher", "StockDataFetcher", "CryptoDataFetcher", "IndiaDataFetcher"]
