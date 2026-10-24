"""AI-powered portfolio optimization."""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple


@dataclass
class OptimizationResult:
    """Result of portfolio optimization."""
    optimal_weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    suggestions: list[str]
    rebalance_trades: list[dict]
    risk_metrics: dict
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "optimal_weights": self.optimal_weights,
            "expected_return": self.expected_return,
            "expected_volatility": self.expected_volatility,
            "sharpe_ratio": self.sharpe_ratio,
            "suggestions": self.suggestions,
            "rebalance_trades": self.rebalance_trades,
            "risk_metrics": self.risk_metrics,
            "timestamp": self.timestamp.isoformat(),
        }


class PortfolioOptimizer:
    """
    AI-powered portfolio optimization using Modern Portfolio Theory
    and Monte Carlo simulation.
    """

    def __init__(self, risk_free_rate: float = 0.05):
        self.risk_free_rate = risk_free_rate

    def calculate_returns(self, prices_df: pd.DataFrame) -> pd.DataFrame:
        """Calculate daily returns from price data."""
        return prices_df.pct_change().dropna()

    def calculate_portfolio_metrics(
        self,
        weights: np.ndarray,
        returns: pd.DataFrame,
    ) -> Tuple[float, float, float]:
        """
        Calculate portfolio expected return, volatility, and Sharpe ratio.

        Returns:
            (expected_return, volatility, sharpe_ratio)
        """
        mean_returns = returns.mean() * 252  # Annualized
        cov_matrix = returns.cov() * 252  # Annualized

        portfolio_return = np.dot(weights, mean_returns)
        portfolio_volatility = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
        sharpe_ratio = (portfolio_return - self.risk_free_rate) / portfolio_volatility

        return portfolio_return, portfolio_volatility, sharpe_ratio

    def monte_carlo_optimization(
        self,
        returns: pd.DataFrame,
        num_portfolios: int = 10000,
    ) -> Tuple[np.ndarray, float, float, float]:
        """
        Find optimal portfolio using Monte Carlo simulation.

        Returns:
            (optimal_weights, max_sharpe_return, max_sharpe_vol, max_sharpe)
        """
        num_assets = len(returns.columns)
        results = np.zeros((3, num_portfolios))
        weights_record = np.zeros((num_portfolios, num_assets))

        for i in range(num_portfolios):
            # Random weights
            weights = np.random.random(num_assets)
            weights /= np.sum(weights)
            weights_record[i, :] = weights

            portfolio_return, portfolio_vol, sharpe = self.calculate_portfolio_metrics(
                weights, returns
            )

            results[0, i] = portfolio_return
            results[1, i] = portfolio_vol
            results[2, i] = sharpe

        # Find max Sharpe ratio portfolio
        max_sharpe_idx = np.argmax(results[2])
        optimal_weights = weights_record[max_sharpe_idx, :]

        return (
            optimal_weights,
            results[0, max_sharpe_idx],
            results[1, max_sharpe_idx],
            results[2, max_sharpe_idx],
        )

    def mean_variance_optimization(
        self,
        returns: pd.DataFrame,
        target_return: Optional[float] = None,
        max_weight: float = 1.0,
    ) -> np.ndarray:
        """
        Mean-variance optimization using scipy.

        Returns:
            Optimal weights array
        """
        try:
            from scipy.optimize import minimize

            num_assets = len(returns.columns)
            mean_returns = returns.mean() * 252
            cov_matrix = returns.cov() * 252

            def neg_sharpe(weights):
                port_return = np.dot(weights, mean_returns)
                port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
                return -(port_return - self.risk_free_rate) / port_vol

            constraints = [
                {'type': 'eq', 'fun': lambda x: np.sum(x) - 1}  # Weights sum to 1
            ]

            if target_return:
                constraints.append(
                    {'type': 'eq', 'fun': lambda x: np.dot(x, mean_returns) - target_return}
                )

            # A cap below 1/n cannot sum to 1, so never go under equal weight
            cap = max(min(max_weight, 1.0), 1 / num_assets)
            bounds = tuple((0, cap) for _ in range(num_assets))
            initial_weights = np.array([1 / num_assets] * num_assets)

            result = minimize(
                neg_sharpe,
                initial_weights,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
            )

            return result.x

        except ImportError:
            # Fallback to equal weights
            return np.array([1 / len(returns.columns)] * len(returns.columns))

    def calculate_var(
        self,
        returns: pd.DataFrame,
        weights: np.ndarray,
        confidence: float = 0.95,
        days: int = 1,
    ) -> float:
        """Calculate Value at Risk (VaR)."""
        portfolio_returns = returns.dot(weights)
        var = np.percentile(portfolio_returns, (1 - confidence) * 100) * np.sqrt(days)
        return abs(var)

    def calculate_cvar(
        self,
        returns: pd.DataFrame,
        weights: np.ndarray,
        confidence: float = 0.95,
    ) -> float:
        """Calculate Conditional VaR (Expected Shortfall)."""
        portfolio_returns = returns.dot(weights)
        var = np.percentile(portfolio_returns, (1 - confidence) * 100)
        cvar = portfolio_returns[portfolio_returns <= var].mean()
        return abs(cvar)

    def calculate_max_drawdown(self, returns: pd.DataFrame, weights: np.ndarray) -> float:
        """Calculate maximum drawdown."""
        portfolio_returns = returns.dot(weights)
        cumulative = (1 + portfolio_returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        return abs(drawdown.min())


    def optimize(
        self,
        prices_df: pd.DataFrame,
        current_weights: Optional[dict[str, float]] = None,
        portfolio_value: float = 10000,
        method: str = "monte_carlo",
        max_weight: float = 1.0,
    ) -> OptimizationResult:
        """
        Optimize portfolio allocation.

        Args:
            prices_df: DataFrame with columns as symbols and prices as values
            current_weights: Current portfolio weights (optional)
            portfolio_value: Total portfolio value
            method: "monte_carlo" or "mean_variance"
            max_weight: Per-asset weight cap for mean_variance (1.0 = uncapped)

        Returns:
            OptimizationResult with optimal allocation
        """
        returns = self.calculate_returns(prices_df)
        symbols = list(returns.columns)

        # Optimize
        if method == "monte_carlo":
            weights, exp_return, exp_vol, sharpe = self.monte_carlo_optimization(returns)
        else:
            weights = self.mean_variance_optimization(returns, max_weight=max_weight)
            exp_return, exp_vol, sharpe = self.calculate_portfolio_metrics(weights, returns)

        # Create weights dict
        optimal_weights = {symbol: float(w) for symbol, w in zip(symbols, weights)}

        # Calculate risk metrics
        var_95 = self.calculate_var(returns, weights, 0.95)
        cvar_95 = self.calculate_cvar(returns, weights, 0.95)
        max_dd = self.calculate_max_drawdown(returns, weights)

        risk_metrics = {
            "var_95": var_95 * portfolio_value,
            "cvar_95": cvar_95 * portfolio_value,
            "max_drawdown": max_dd,
            "var_95_percent": var_95 * 100,
        }

        # Generate rebalance trades
        rebalance_trades = []
        suggestions = []

        if current_weights:
            for symbol in symbols:
                current = current_weights.get(symbol, 0)
                target = optimal_weights.get(symbol, 0)
                diff = target - current

                if abs(diff) > 0.02:  # More than 2% difference
                    trade_value = diff * portfolio_value
                    rebalance_trades.append({
                        "symbol": symbol,
                        "action": "buy" if diff > 0 else "sell",
                        "current_weight": current,
                        "target_weight": target,
                        "trade_value": abs(trade_value),
                    })

        # Generate suggestions
        # High concentration warning
        max_weight = max(optimal_weights.values())
        if max_weight > 0.3:
            max_symbol = max(optimal_weights, key=optimal_weights.get)
            suggestions.append(f"High concentration in {max_symbol} ({max_weight:.1%}). Consider diversifying.")

        # Risk level suggestions
        if exp_vol > 0.25:
            suggestions.append("Portfolio volatility is high. Consider adding bonds or stable assets.")
        elif exp_vol < 0.10:
            suggestions.append("Portfolio is conservative. May underperform in bull markets.")

        # Sharpe ratio assessment
        if sharpe > 1.5:
            suggestions.append(f"Excellent risk-adjusted returns (Sharpe: {sharpe:.2f})")
        elif sharpe < 0.5:
            suggestions.append(f"Consider adjusting allocation for better risk-adjusted returns (Sharpe: {sharpe:.2f})")

        # Diversification suggestion
        non_zero_positions = sum(1 for w in weights if w > 0.01)
        if non_zero_positions < 5:
            suggestions.append("Consider adding more positions for diversification.")

        return OptimizationResult(
            optimal_weights=optimal_weights,
            expected_return=exp_return,
            expected_volatility=exp_vol,
            sharpe_ratio=sharpe,
            suggestions=suggestions,
            rebalance_trades=rebalance_trades,
            risk_metrics=risk_metrics,
            timestamp=datetime.now(),
        )


    def risk_parity_optimization(self, returns: pd.DataFrame) -> np.ndarray:
        """
        Risk parity optimization - equal risk contribution from each asset.
        """
        try:
            from scipy.optimize import minimize

            num_assets = len(returns.columns)
            cov_matrix = returns.cov() * 252

            def risk_budget_objective(weights):
                portfolio_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
                marginal_contrib = np.dot(cov_matrix, weights)
                risk_contrib = weights * marginal_contrib / portfolio_vol

                # We want equal risk contribution
                target_risk = portfolio_vol / num_assets
                return np.sum((risk_contrib - target_risk) ** 2)

            constraints = [{'type': 'eq', 'fun': lambda x: np.sum(x) - 1}]
            bounds = tuple((0.01, 1) for _ in range(num_assets))
            initial_weights = np.array([1 / num_assets] * num_assets)

            result = minimize(
                risk_budget_objective,
                initial_weights,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
            )

            return result.x

        except ImportError:
            return np.array([1 / len(returns.columns)] * len(returns.columns))
