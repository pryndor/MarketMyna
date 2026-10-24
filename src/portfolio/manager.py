"""Portfolio management functionality."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.core.home import app_home

from ..core.constants import Markets
from ..data.crypto import CryptoDataFetcher
from ..data.india import IndiaDataFetcher
from ..data.stocks import StockDataFetcher
from ..storage import DatabaseManager, HoldingRecord, PortfolioRecord, TransactionRecord, get_db_url
from .models import Holding, Portfolio, Transaction, TransactionType


class PortfolioManager:
    """Manages portfolio operations."""

    def __init__(self, data_dir: Optional[Path] = None, config=None):
        # data_dir is kept for backwards compatibility with existing call sites
        # and as a per-instance db override (e.g. test isolation); persistence
        # itself now lives in SQLite via storage.DatabaseManager, not JSON files.
        self.data_dir = data_dir or app_home() / "portfolios"
        self.config = config
        self.data_dir.mkdir(parents=True, exist_ok=True)

        db_url = get_db_url(config=config, override_dir=self.data_dir, filename="portfolios.db")
        self._db = DatabaseManager.instance(db_url)

        self.portfolios: dict[str, Portfolio] = {}
        self._fetchers = {
            Markets.US: StockDataFetcher(),
            Markets.GLOBAL: StockDataFetcher(),
            Markets.INDIA: IndiaDataFetcher(),
            Markets.CRYPTO: CryptoDataFetcher(),
        }

        self._load_portfolios()

    def _record_to_portfolio(self, record: PortfolioRecord) -> Portfolio:
        """Convert a PortfolioRecord (+ its holdings/transactions) to a Portfolio."""
        holdings = {
            h.symbol: Holding(
                symbol=h.symbol,
                quantity=h.quantity,
                avg_cost=h.avg_cost,
                current_price=h.current_price,
                market=h.market or "US",
            )
            for h in record.holdings
        }

        transactions = [
            Transaction(
                symbol=t.symbol,
                transaction_type=TransactionType(t.transaction_type),
                quantity=t.quantity,
                price=t.price,
                date=t.date,
                fees=t.fees or 0.0,
                notes=t.notes or "",
                id=t.id,
                market=t.market or "",
            )
            for t in record.transactions
        ]

        return Portfolio(
            name=record.name,
            holdings=holdings,
            transactions=transactions,
            cash_balance=record.cash_balance or 0.0,
            currency=record.currency or "USD",
            id=record.id,
            created_at=record.created_at or datetime.now(),
            kind=record.kind,
        )

    def _load_portfolios(self) -> None:
        """Load portfolios from the database."""
        try:
            with self._db.get_session() as session:
                for record in session.query(PortfolioRecord).all():
                    portfolio = self._record_to_portfolio(record)
                    self.portfolios[portfolio.name] = portfolio
        except Exception as e:
            print(f"Error loading portfolios: {e}")

    def save_portfolio(self, portfolio: Portfolio) -> None:
        """Persist a portfolio: full replace of its holdings/transactions,
        mirroring the previous "overwrite the whole JSON file" semantics."""
        with self._db.get_session() as session:
            record = session.query(PortfolioRecord).filter_by(name=portfolio.name).one_or_none()
            if record is None:
                record = PortfolioRecord(name=portfolio.name, created_at=portfolio.created_at)
                session.add(record)
                session.flush()

            record.cash_balance = portfolio.cash_balance
            record.currency = portfolio.currency
            if portfolio.kind:
                record.kind = portfolio.kind

            record.holdings.clear()
            # Flush the deletes now: SQLAlchemy's unit-of-work would otherwise
            # emit the re-inserts (below, same portfolio_id+symbol) before the
            # deletes within one flush and trip the unique constraint.
            session.flush()
            for holding in portfolio.holdings.values():
                record.holdings.append(
                    HoldingRecord(
                        symbol=holding.symbol,
                        quantity=holding.quantity,
                        avg_cost=holding.avg_cost,
                        current_price=holding.current_price,
                        market=holding.market,
                    )
                )

            record.transactions.clear()
            for tx in portfolio.transactions:
                record.transactions.append(
                    TransactionRecord(
                        symbol=tx.symbol,
                        transaction_type=tx.transaction_type.value,
                        quantity=tx.quantity,
                        price=tx.price,
                        date=tx.date,
                        fees=tx.fees,
                        notes=tx.notes,
                        market=tx.market or None,
                    )
                )

            session.flush()
            portfolio.id = record.id

    def create_portfolio(self, name: str, currency: str = "USD", kind: Optional[str] = None) -> Portfolio:
        """Create a new portfolio ("stocks" or "funds")."""
        if name in self.portfolios:
            raise ValueError(f"Portfolio '{name}' already exists")

        portfolio = Portfolio(name=name, currency=currency, kind=kind)
        self.portfolios[name] = portfolio
        self.save_portfolio(portfolio)
        return portfolio

    def delete_portfolio(self, name: str) -> None:
        """Delete a portfolio."""
        if name not in self.portfolios:
            raise ValueError(f"Portfolio '{name}' not found")

        with self._db.get_session() as session:
            record = session.query(PortfolioRecord).filter_by(name=name).one_or_none()
            if record is not None:
                session.delete(record)

        del self.portfolios[name]

    def rename_portfolio(self, name: str, new_name: str) -> Portfolio:
        """Rename a portfolio, keeping its holdings and history."""
        new_name = new_name.strip()
        if name not in self.portfolios:
            raise ValueError(f"Portfolio '{name}' not found")
        if not new_name:
            raise ValueError("Portfolio name cannot be empty")
        if new_name == name:
            return self.portfolios[name]
        if new_name in self.portfolios:
            raise ValueError(f"Portfolio '{new_name}' already exists")

        with self._db.get_session() as session:
            record = session.query(PortfolioRecord).filter_by(name=name).one()
            record.name = new_name

        portfolio = self.portfolios.pop(name)
        portfolio.name = new_name
        self.portfolios[new_name] = portfolio
        return portfolio

    @staticmethod
    def _replay(transactions: list[Transaction], previous: dict[str, Holding]) -> dict[str, Holding]:
        """Rebuild holdings from the transaction history, in order. Raises
        ValueError if a sell would exceed what was held at that point."""
        holdings: dict[str, Holding] = {}
        for t in transactions:
            if t.transaction_type == TransactionType.BUY:
                h = holdings.get(t.symbol)
                if h is None:
                    old = previous.get(t.symbol)
                    holdings[t.symbol] = Holding(
                        symbol=t.symbol,
                        quantity=t.quantity,
                        avg_cost=t.price,
                        current_price=old.current_price if old else 0.0,
                        market=t.market or (old.market if old else "US"),
                    )
                else:
                    total_cost = h.cost_basis + t.total_cost
                    h.quantity += t.quantity
                    h.avg_cost = total_cost / h.quantity
            elif t.transaction_type == TransactionType.SELL:
                h = holdings.get(t.symbol)
                if h is None or t.quantity > h.quantity + 1e-9:
                    held = h.quantity if h else 0
                    raise ValueError(
                        f"Can't remove it: the later sell of {t.quantity:g} {t.symbol} would have only "
                        f"{held:g} shares to sell - delete that sell first"
                    )
                h.quantity -= t.quantity
                if h.quantity <= 1e-9:
                    del holdings[t.symbol]
            elif t.transaction_type == TransactionType.SPLIT and t.symbol in holdings:
                _apply_split(holdings[t.symbol], t.quantity)
        return holdings

    def delete_transaction(self, portfolio_name: str, index: int) -> None:
        """Remove one transaction (e.g. a typo) and rebuild the holdings
        from the remaining history."""
        if portfolio_name not in self.portfolios:
            raise ValueError(f"Portfolio '{portfolio_name}' not found")
        portfolio = self.portfolios[portfolio_name]
        if not 0 <= index < len(portfolio.transactions):
            raise IndexError(f"Transaction {index} not found")

        remaining = portfolio.transactions[:index] + portfolio.transactions[index + 1:]
        portfolio.holdings = self._replay(remaining, portfolio.holdings)
        portfolio.transactions = remaining
        self.save_portfolio(portfolio)

    def add_transaction(
        self,
        portfolio_name: str,
        symbol: str,
        transaction_type: TransactionType,
        quantity: float,
        price: float,
        date: Optional[datetime] = None,
        fees: float = 0.0,
        notes: str = "",
        market: str = "US",
    ) -> None:
        """Add a transaction to a portfolio."""
        if portfolio_name not in self.portfolios:
            raise ValueError(f"Portfolio '{portfolio_name}' not found")

        portfolio = self.portfolios[portfolio_name]

        # Validate first: a rejected sell or split must not stay in the in-memory
        # history, where the next save would write it to the database.
        if transaction_type == TransactionType.SELL:
            if symbol not in portfolio.holdings:
                raise ValueError(f"No holding for {symbol}")
            if quantity > portfolio.holdings[symbol].quantity:
                raise ValueError(f"Cannot sell {quantity} shares, only {portfolio.holdings[symbol].quantity} available")
        elif transaction_type == TransactionType.SPLIT:
            if symbol not in portfolio.holdings:
                raise ValueError(f"No holding for {symbol} to split")
            if quantity <= 0:
                raise ValueError("Split ratio must be above 0")

        transaction = Transaction(
            symbol=symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            price=price,
            date=date or datetime.now(),
            fees=fees,
            notes=notes,
            market=market,
        )
        portfolio.transactions.append(transaction)

        # Update holdings
        if transaction_type == TransactionType.BUY:
            if symbol in portfolio.holdings:
                holding = portfolio.holdings[symbol]
                total_cost = holding.cost_basis + transaction.total_cost
                total_qty = holding.quantity + quantity
                holding.avg_cost = total_cost / total_qty
                holding.quantity = total_qty
            else:
                portfolio.holdings[symbol] = Holding(
                    symbol=symbol,
                    quantity=quantity,
                    avg_cost=price,
                    market=market,
                )
        elif transaction_type == TransactionType.SELL:
            holding = portfolio.holdings[symbol]
            holding.quantity -= quantity
            if holding.quantity == 0:
                del portfolio.holdings[symbol]
        elif transaction_type == TransactionType.SPLIT:
            _apply_split(portfolio.holdings[symbol], quantity)

        self.save_portfolio(portfolio)

    def update_prices(self, portfolio_name: str) -> None:
        """Update current prices for all holdings in a portfolio."""
        if portfolio_name not in self.portfolios:
            raise ValueError(f"Portfolio '{portfolio_name}' not found")

        portfolio = self.portfolios[portfolio_name]

        for symbol, holding in portfolio.holdings.items():
            if (holding.market or "").lower() == "mf":
                from ..services.mf_holdings import latest

                info = latest(symbol)
                if info:
                    holding.current_price = info["nav"]
                continue
            if (holding.market or "").lower() == "india":
                close = nse_official_close(symbol)
                if close:
                    holding.current_price = close
                    continue
            try:
                market = Markets(holding.market.lower()) if holding.market else Markets.US
                fetcher = self._fetchers.get(market, self._fetchers[Markets.US])
                quote = fetcher.get_quote(symbol)
                holding.current_price = quote["price"]
            except Exception as e:
                print(f"Error updating price for {symbol}: {e}")

    def get_portfolio_summary(self, portfolio_name: str) -> dict:
        """Get a summary of the portfolio."""
        if portfolio_name not in self.portfolios:
            raise ValueError(f"Portfolio '{portfolio_name}' not found")

        portfolio = self.portfolios[portfolio_name]
        self.update_prices(portfolio_name)

        return portfolio.to_dict()

    def get_all_portfolios(self) -> list[str]:
        """Get list of all portfolio names."""
        return list(self.portfolios.keys())


def nse_official_close(symbol: str, now: Optional[datetime] = None, rows: Optional[dict] = None) -> Optional[float]:
    """NSE's official closing price while the market is shut, else None.

    After the close, brokers show the official close (the volume-weighted
    price of the last 30 minutes) rather than the last single trade that a
    live quote returns, so a valuation at the last trade drifts a few paise
    a share from the broker's. Uses the bhavcopy close from the listing,
    but only once it is the latest session's: between 15:30 and the evening
    publication the listing still holds yesterday's close, so return None
    and let the live quote stand. Exchange holidays are not modelled, so on
    a weekday holiday evening this also returns None.
    """
    from zoneinfo import ZoneInfo

    from ..trading.market_hours import is_open

    tz = ZoneInfo("Asia/Kolkata")
    local = now.astimezone(tz) if now else datetime.now(tz)
    if is_open("india", local):
        return None
    if rows is None:
        from ..data.listings import get_store

        found = get_store().lookup([("india", "stock", symbol), ("india", "etf", symbol)])
        rows = {k[2]: v for k, v in found.items()}
    row = rows.get(symbol)
    if not row or not row.get("price") or not row.get("close_date"):
        return None
    after_close_today = local.weekday() < 5 and local.time() > datetime.strptime("15:30", "%H:%M").time()
    if after_close_today and row["close_date"] != local.date().isoformat():
        return None  # today's official close is not published yet
    return float(row["price"])


def _apply_split(holding: Holding, ratio: float) -> None:
    """Split or bonus: `ratio` = shares held now for each share before (5 for a
    1:5 split, 2 for a 1:1 bonus). Same money invested, so the average cost falls."""
    if ratio <= 0:
        raise ValueError("Split ratio must be above 0")
    holding.quantity *= ratio
    holding.avg_cost /= ratio
