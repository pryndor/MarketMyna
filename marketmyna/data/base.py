"""Base data fetcher interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import pandas as pd

from ..core.constants import TimeFrame


class DataFetcher(ABC):
    """Abstract base class for data fetchers."""

    @abstractmethod
    def get_quote(self, symbol: str) -> dict:
        """Get current quote for a symbol."""

    @abstractmethod
    def get_history(
        self,
        symbol: str,
        period: str = "1y",
        interval: TimeFrame = TimeFrame.DAY_1,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """Get historical price data."""

    @abstractmethod
    def search(self, query: str) -> list[dict]:
        """Search for symbols matching query."""

    @abstractmethod
    def get_info(self, symbol: str) -> dict:
        """Get detailed information about a symbol."""
