"""Portfolio data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum


class TransactionType(Enum):
    """Transaction types."""
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    SPLIT = "split"


@dataclass
class Transaction:
    """Represents a single transaction."""

    symbol: str
    transaction_type: TransactionType
    quantity: float
    price: float
    date: datetime
    fees: float = 0.0
    notes: str = ""
    id: Optional[int] = None
    market: str = ""

    @property
    def total_cost(self) -> float:
        """Total cost including fees."""
        if self.transaction_type == TransactionType.BUY:
            return (self.quantity * self.price) + self.fees
        elif self.transaction_type == TransactionType.SELL:
            return (self.quantity * self.price) - self.fees
        return 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "transaction_type": self.transaction_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "date": self.date.isoformat() if self.date else None,
            "fees": self.fees,
            "notes": self.notes,
            "market": self.market,
            "total": self.total_cost,
        }


@dataclass
class Holding:
    """Represents a current holding in the portfolio."""

    symbol: str
    quantity: float
    avg_cost: float
    current_price: float = 0.0
    market: str = "US"

    @property
    def market_value(self) -> float:
        """Current market value of the holding."""
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        """Total cost basis of the holding."""
        return self.quantity * self.avg_cost

    @property
    def unrealized_gain(self) -> float:
        """Unrealized gain/loss."""
        return self.market_value - self.cost_basis

    @property
    def unrealized_gain_percent(self) -> float:
        """Unrealized gain/loss as percentage."""
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_gain / self.cost_basis) * 100

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "cost_basis": self.cost_basis,
            "unrealized_gain": self.unrealized_gain,
            "unrealized_gain_percent": self.unrealized_gain_percent,
            "market": self.market,
        }


@dataclass
class Portfolio:
    """Represents a user's portfolio."""

    name: str
    holdings: dict[str, Holding] = field(default_factory=dict)
    transactions: list[Transaction] = field(default_factory=list)
    cash_balance: float = 0.0
    currency: str = "USD"
    id: Optional[int] = None
    created_at: datetime = field(default_factory=datetime.now)
    kind: Optional[str] = None  # "stocks" | "funds"; None = inferred from the holdings

    @property
    def total_market_value(self) -> float:
        """Total market value of all holdings."""
        return sum(h.market_value for h in self.holdings.values())

    @property
    def total_cost_basis(self) -> float:
        """Total cost basis of all holdings."""
        return sum(h.cost_basis for h in self.holdings.values())

    @property
    def total_unrealized_gain(self) -> float:
        """Total unrealized gain/loss."""
        return self.total_market_value - self.total_cost_basis

    @property
    def total_unrealized_gain_percent(self) -> float:
        """Total unrealized gain/loss as percentage."""
        if self.total_cost_basis == 0:
            return 0.0
        return (self.total_unrealized_gain / self.total_cost_basis) * 100

    @property
    def total_value(self) -> float:
        """Total portfolio value including cash."""
        return self.total_market_value + self.cash_balance

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "holdings": {s: h.to_dict() for s, h in self.holdings.items()},
            "cash_balance": self.cash_balance,
            "currency": self.currency,
            "total_market_value": self.total_market_value,
            "total_cost_basis": self.total_cost_basis,
            "total_unrealized_gain": self.total_unrealized_gain,
            "total_unrealized_gain_percent": self.total_unrealized_gain_percent,
            "total_value": self.total_value,
            # index = position in the list, which is what delete_transaction takes.
            "transactions": [{"index": i, **t.to_dict()} for i, t in enumerate(self.transactions)],
        }
