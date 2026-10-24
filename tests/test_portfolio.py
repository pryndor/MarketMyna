"""Tests for portfolio module."""

from datetime import datetime

import pytest


class TestHolding:
    """Tests for Holding model."""

    def test_market_value(self):
        """Test market value calculation."""
        from marketmyna.portfolio.models import Holding

        holding = Holding(
            symbol="AAPL",
            quantity=10,
            avg_cost=150.0,
            current_price=160.0,
        )

        assert holding.market_value == 1600.0
        assert holding.cost_basis == 1500.0
        assert holding.unrealized_gain == 100.0
        assert abs(holding.unrealized_gain_percent - 6.67) < 0.1


class TestPortfolio:
    """Tests for Portfolio model."""

    def test_total_calculations(self):
        """Test portfolio total calculations."""
        from marketmyna.portfolio.models import Holding, Portfolio

        portfolio = Portfolio(name="Test")
        portfolio.holdings = {
            "AAPL": Holding("AAPL", 10, 150, 160),
            "GOOGL": Holding("GOOGL", 5, 100, 110),
        }

        assert portfolio.total_market_value == 2150.0
        assert portfolio.total_cost_basis == 2000.0
        assert portfolio.total_unrealized_gain == 150.0


class TestTransaction:
    """Tests for Transaction model."""

    def test_total_cost_buy(self):
        """Test total cost for buy transaction."""
        from marketmyna.portfolio.models import Transaction, TransactionType

        tx = Transaction(
            symbol="AAPL",
            transaction_type=TransactionType.BUY,
            quantity=10,
            price=150.0,
            date=datetime.now(),
            fees=10.0,
        )

        assert tx.total_cost == 1510.0

    def test_total_cost_sell(self):
        """Test total cost for sell transaction."""
        from marketmyna.portfolio.models import Transaction, TransactionType

        tx = Transaction(
            symbol="AAPL",
            transaction_type=TransactionType.SELL,
            quantity=10,
            price=160.0,
            date=datetime.now(),
            fees=10.0,
        )

        assert tx.total_cost == 1590.0


def _pm(tmp_path):
    from marketmyna.portfolio.manager import PortfolioManager

    pm = PortfolioManager(tmp_path)
    pm.create_portfolio("P", currency="INR")
    return pm


def test_split_and_bonus_change_quantity_and_cost(tmp_path):
    from marketmyna.portfolio.models import TransactionType as T

    pm = _pm(tmp_path)
    pm.add_transaction("P", "ACME", T.BUY, 10, 500.0, date=datetime(2024, 1, 1), market="india")
    pm.add_transaction("P", "ACME", T.SPLIT, 5, 0.0, date=datetime(2024, 6, 1), market="india")  # 1:5 split
    h = pm.portfolios["P"].holdings["ACME"]
    assert h.quantity == 50 and h.avg_cost == 100
    pm.add_transaction("P", "ACME", T.BUY, 50, 120.0, date=datetime(2024, 7, 1), market="india")
    pm.add_transaction("P", "ACME", T.SPLIT, 2, 0.0, date=datetime(2024, 8, 1), market="india")  # 1:1 bonus
    assert pm.portfolios["P"].holdings["ACME"].quantity == 200
    # Deleting a transaction replays history: the splits must survive it
    pm.delete_transaction("P", 2)
    h = pm.portfolios["P"].holdings["ACME"]
    assert h.quantity == 100 and h.avg_cost == 50


def test_rejected_sell_or_split_is_not_recorded(tmp_path):
    from marketmyna.portfolio.models import TransactionType as T

    pm = _pm(tmp_path)
    pm.add_transaction("P", "ACME", T.BUY, 5, 100.0, market="india")
    with pytest.raises(ValueError):
        pm.add_transaction("P", "ACME", T.SELL, 10, 100.0, market="india")
    with pytest.raises(ValueError):
        pm.add_transaction("P", "NOPE", T.SPLIT, 2, 0.0, market="india")
    assert len(pm.portfolios["P"].transactions) == 1
