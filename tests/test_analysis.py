"""Tests for analysis module."""

import numpy as np
import pandas as pd
import pytest


class TestTechnicalAnalyzer:
    """Tests for TechnicalAnalyzer."""

    @pytest.fixture
    def sample_df(self):
        """Create sample OHLCV data."""
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        prices = 100 + np.cumsum(np.random.randn(100) * 2)

        return pd.DataFrame({
            "open": prices + np.random.randn(100),
            "high": prices + abs(np.random.randn(100)) * 2,
            "low": prices - abs(np.random.randn(100)) * 2,
            "close": prices,
            "volume": np.random.randint(1000000, 5000000, 100),
        }, index=dates)

    def test_sma_calculation(self, sample_df):
        """Test SMA calculation."""
        from marketmyna.analysis.technical import TechnicalAnalyzer

        analyzer = TechnicalAnalyzer(sample_df)
        sma = analyzer.sma(period=20)

        assert len(sma) == len(sample_df)
        assert sma.iloc[:19].isna().all()  # First 19 values should be NaN
        assert not sma.iloc[19:].isna().any()  # Rest should have values

    def test_rsi_range(self, sample_df):
        """Test RSI values are in valid range."""
        from marketmyna.analysis.technical import TechnicalAnalyzer

        analyzer = TechnicalAnalyzer(sample_df)
        rsi = analyzer.rsi()

        valid_rsi = rsi.dropna()
        assert (valid_rsi >= 0).all()
        assert (valid_rsi <= 100).all()

    def test_bollinger_bands(self, sample_df):
        """Test Bollinger Bands calculation."""
        from marketmyna.analysis.technical import TechnicalAnalyzer

        analyzer = TechnicalAnalyzer(sample_df)
        upper, middle, lower = analyzer.bollinger_bands()

        # Upper should always be above middle, middle above lower
        valid_idx = ~upper.isna()
        assert (upper[valid_idx] >= middle[valid_idx]).all()
        assert (middle[valid_idx] >= lower[valid_idx]).all()

    def test_macd_components(self, sample_df):
        """Test MACD returns three components."""
        from marketmyna.analysis.technical import TechnicalAnalyzer

        analyzer = TechnicalAnalyzer(sample_df)
        macd_line, signal_line, histogram = analyzer.macd()

        assert len(macd_line) == len(sample_df)
        assert len(signal_line) == len(sample_df)
        assert len(histogram) == len(sample_df)

    def test_get_signals(self, sample_df):
        """Test signal generation."""
        from marketmyna.analysis.technical import TechnicalAnalyzer

        analyzer = TechnicalAnalyzer(sample_df)
        signals = analyzer.get_signals()

        assert "rsi" in signals
        assert "macd" in signals
        assert "ma" in signals
        assert "bollinger" in signals


class TestFundamentalAnalyzer:
    """Tests for FundamentalAnalyzer."""

    @pytest.fixture
    def sample_info(self):
        """Create sample stock info."""
        return {
            "symbol": "AAPL",
            "sector": "Technology",
            "pe_ratio": 25,
            "forward_pe": 22,
            "peg_ratio": 1.5,
            "price_to_book": 35,
            "dividend_yield": 0.005,
            "payout_ratio": 0.15,
            "debt_to_equity": 1.5,
            "current_ratio": 1.0,
            "return_on_equity": 0.45,
            "return_on_assets": 0.20,
            "profit_margin": 0.25,
            "revenue_growth": 0.08,
            "earnings_growth": 0.10,
        }

    def test_pe_analysis(self, sample_info):
        """Test P/E analysis."""
        from marketmyna.analysis.fundamental import FundamentalAnalyzer

        analyzer = FundamentalAnalyzer(sample_info)
        result = analyzer.pe_analysis()

        assert "value" in result
        assert "status" in result
        assert "message" in result

    def test_dividend_analysis(self, sample_info):
        """Test dividend analysis."""
        from marketmyna.analysis.fundamental import FundamentalAnalyzer

        analyzer = FundamentalAnalyzer(sample_info)
        result = analyzer.dividend_analysis()

        assert "yield" in result
        assert "payout_ratio" in result
        assert "sustainable" in result

    def test_get_summary(self, sample_info):
        """Test summary generation."""
        from marketmyna.analysis.fundamental import FundamentalAnalyzer

        analyzer = FundamentalAnalyzer(sample_info)
        summary = analyzer.get_summary()

        assert "overall_score" in summary
        assert 0 <= summary["overall_score"] <= 100
        assert "valuation" in summary
        assert "profitability" in summary


def test_yfinance_fundamentals_units():
    from marketmyna.analysis.fundamental import FundamentalAnalyzer, yfinance_fundamentals

    info = {
        "trailingPE": 38.6, "debtToEquity": 78.4, "currentRatio": 1.0, "returnOnEquity": 1.49,
        "revenueGrowth": 0.164, "dividendYield": 0.32, "trailingAnnualDividendYield": 0,
        "dividendRate": 1.08, "currentPrice": 335.92,
    }
    norm = yfinance_fundamentals(info)
    assert norm["debt_to_equity"] == pytest.approx(0.784)
    assert norm["dividend_yield"] == pytest.approx(1.08 / 335.92)
    summary = FundamentalAnalyzer(norm).get_summary()
    assert summary["dividend"]["yield"] == pytest.approx(0.3215, abs=1e-3)
    assert summary["financial_health"]["rating"] == "good"
    # Banks don't report a current ratio - that alone must not mean "poor".
    bank = FundamentalAnalyzer(yfinance_fundamentals({"debtToEquity": 50})).get_summary()
    assert bank["financial_health"]["rating"] == "good"
