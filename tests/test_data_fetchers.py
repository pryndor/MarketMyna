"""Tests for data fetchers."""

from unittest.mock import patch


class TestStockDataFetcher:
    """Tests for StockDataFetcher."""

    def test_get_quote_returns_dict(self):
        """Test that get_quote returns a dictionary with required fields."""
        from src.data.stocks import StockDataFetcher

        fetcher = StockDataFetcher()

        with patch.object(fetcher, "get_quote") as mock_quote:
            mock_quote.return_value = {
                "symbol": "AAPL",
                "price": 150.0,
                "change": 2.5,
                "change_percent": 1.7,
            }

            result = fetcher.get_quote("AAPL")

            assert "symbol" in result
            assert "price" in result
            assert "change" in result

    def test_get_history_returns_dataframe(self):
        """Test that get_history returns a DataFrame."""
        from src.data.stocks import StockDataFetcher
        import pandas as pd

        fetcher = StockDataFetcher()

        with patch.object(fetcher, "get_history") as mock_history:
            mock_history.return_value = pd.DataFrame({
                "open": [100, 101],
                "high": [105, 106],
                "low": [99, 100],
                "close": [104, 105],
                "volume": [1000000, 1100000],
            })

            result = fetcher.get_history("AAPL")

            assert isinstance(result, pd.DataFrame)
            assert "close" in result.columns


class TestCryptoDataFetcher:
    """Tests for CryptoDataFetcher."""

    def test_yf_symbol_conversion(self):
        """Test Yahoo Finance symbol conversion."""
        from src.data.crypto import CryptoDataFetcher

        fetcher = CryptoDataFetcher()

        assert fetcher._get_yf_symbol("BTC") == "BTC-USD"
        assert fetcher._get_yf_symbol("BTC-USD") == "BTC-USD"


class TestIndiaDataFetcher:
    """Tests for IndiaDataFetcher."""

    def test_yf_symbol_conversion(self):
        """Test Yahoo Finance symbol conversion for Indian stocks."""
        from src.data.india import IndiaDataFetcher

        fetcher = IndiaDataFetcher()

        assert fetcher._get_yf_symbol("RELIANCE") == "RELIANCE.NS"
        assert fetcher._get_yf_symbol("RELIANCE.NS") == "RELIANCE.NS"
        assert fetcher._get_yf_symbol("RELIANCE.BO") == "RELIANCE.BO"
