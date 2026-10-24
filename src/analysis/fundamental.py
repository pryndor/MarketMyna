"""Fundamental analysis metrics and valuation."""

from dataclasses import dataclass
from enum import Enum


class Valuation(Enum):
    """Valuation status."""
    UNDERVALUED = "undervalued"
    FAIR = "fair"
    OVERVALUED = "overvalued"


@dataclass
class FundamentalMetrics:
    """Collection of fundamental metrics."""
    pe_ratio: float = 0
    forward_pe: float = 0
    peg_ratio: float = 0
    price_to_book: float = 0
    price_to_sales: float = 0
    ev_to_ebitda: float = 0
    debt_to_equity: float = 0
    current_ratio: float = 0
    quick_ratio: float = 0
    roe: float = 0
    roa: float = 0
    profit_margin: float = 0
    operating_margin: float = 0
    revenue_growth: float = 0
    earnings_growth: float = 0
    dividend_yield: float = 0
    payout_ratio: float = 0


def yfinance_fundamentals(info: dict) -> dict:
    """Map a raw yfinance `Ticker.info` dict onto the keys (and units)
    FundamentalAnalyzer reads: ratios as fractions, e.g. 0.15 = 15%.

    yfinance's own units are inconsistent: `debtToEquity` is a percent
    (78.4 = 0.784x) and `dividendYield` is now a percent too (0.32 =
    0.32%), while ROE/margins/growth are fractions.
    """
    def num(key):
        value = info.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    from ..data.yahoo_price import info_price  # here: src.data imports this module

    price = info_price(info)
    dividend_yield = num("trailingAnnualDividendYield")
    # A 0 trailing yield is often a data gap (seen on NSE listings), not "no dividend".
    if not dividend_yield and num("dividendRate") and price:
        dividend_yield = num("dividendRate") / price
    if not dividend_yield and num("dividendYield") is not None:
        dividend_yield = num("dividendYield") / 100
    debt_to_equity = num("debtToEquity")

    out = {
        "pe_ratio": num("trailingPE"),
        "forward_pe": num("forwardPE"),
        "peg_ratio": num("trailingPegRatio") or num("pegRatio"),
        "price_to_book": num("priceToBook"),
        "price_to_sales": num("priceToSalesTrailing12Months"),
        "debt_to_equity": debt_to_equity / 100 if debt_to_equity is not None else None,
        "current_ratio": num("currentRatio"),
        "return_on_equity": num("returnOnEquity"),
        "return_on_assets": num("returnOnAssets"),
        "profit_margin": num("profitMargins"),
        "revenue_growth": num("revenueGrowth"),
        "earnings_growth": num("earningsGrowth"),
        "dividend_yield": dividend_yield,
        "payout_ratio": num("payoutRatio"),
    }
    return {k: v for k, v in out.items() if v is not None}


class FundamentalAnalyzer:
    """Fundamental analysis calculator."""

    # Industry average P/E ratios for comparison
    INDUSTRY_PE = {
        "Technology": 25,
        "Healthcare": 20,
        "Financial Services": 15,
        "Consumer Cyclical": 18,
        "Consumer Defensive": 20,
        "Industrials": 18,
        "Energy": 12,
        "Utilities": 16,
        "Real Estate": 35,
        "Basic Materials": 14,
        "Communication Services": 20,
    }

    def __init__(self, stock_info: dict):
        """
        Initialize with stock information.

        Args:
            stock_info: Dictionary containing stock fundamentals from data fetcher
        """
        self.info = stock_info
        self.metrics = self._extract_metrics()

    def _extract_metrics(self) -> FundamentalMetrics:
        """Extract fundamental metrics from stock info."""
        return FundamentalMetrics(
            pe_ratio=self.info.get("pe_ratio", 0) or 0,
            forward_pe=self.info.get("forward_pe", 0) or 0,
            peg_ratio=self.info.get("peg_ratio", 0) or 0,
            price_to_book=self.info.get("price_to_book", 0) or 0,
            price_to_sales=self.info.get("price_to_sales", 0) or 0,
            debt_to_equity=self.info.get("debt_to_equity", 0) or 0,
            current_ratio=self.info.get("current_ratio", 0) or 0,
            roe=self.info.get("return_on_equity", 0) or 0,
            roa=self.info.get("return_on_assets", 0) or 0,
            profit_margin=self.info.get("profit_margin", 0) or 0,
            dividend_yield=self.info.get("dividend_yield", 0) or 0,
            payout_ratio=self.info.get("payout_ratio", 0) or 0,
            revenue_growth=self.info.get("revenue_growth", 0) or 0,
            earnings_growth=self.info.get("earnings_growth", 0) or 0,
        )

    def pe_analysis(self) -> dict:
        """Analyze P/E ratio."""
        pe = self.metrics.pe_ratio
        sector = self.info.get("sector", "")
        industry_pe = self.INDUSTRY_PE.get(sector, 18)

        if pe <= 0:
            return {
                "value": pe,
                "status": "N/A",
                "message": "No P/E ratio available (negative earnings)",
            }

        if pe < industry_pe * 0.7:
            status = Valuation.UNDERVALUED
            message = f"P/E of {pe:.1f} is below industry average of {industry_pe}"
        elif pe > industry_pe * 1.3:
            status = Valuation.OVERVALUED
            message = f"P/E of {pe:.1f} is above industry average of {industry_pe}"
        else:
            status = Valuation.FAIR
            message = f"P/E of {pe:.1f} is near industry average of {industry_pe}"

        return {"value": pe, "status": status.value, "industry_avg": industry_pe, "message": message}

    def peg_analysis(self) -> dict:
        """Analyze PEG ratio (P/E to Growth)."""
        peg = self.metrics.peg_ratio

        if peg <= 0:
            return {
                "value": peg,
                "status": "N/A",
                "message": "No PEG ratio available",
            }

        if peg < 1:
            status = Valuation.UNDERVALUED
            message = "PEG < 1 suggests undervaluation relative to growth"
        elif peg > 2:
            status = Valuation.OVERVALUED
            message = "PEG > 2 suggests overvaluation relative to growth"
        else:
            status = Valuation.FAIR
            message = "PEG between 1-2 suggests fair valuation"

        return {"value": peg, "status": status.value, "message": message}

    def dividend_analysis(self) -> dict:
        """Analyze dividend metrics."""
        div_yield = self.metrics.dividend_yield * 100 if self.metrics.dividend_yield else 0
        payout = self.metrics.payout_ratio * 100 if self.metrics.payout_ratio else 0

        analysis = {
            "yield": div_yield,
            "payout_ratio": payout,
            "sustainable": True,
            "messages": [],
        }

        if div_yield == 0:
            analysis["messages"].append("No dividend paid")
            return analysis

        if div_yield > 6:
            analysis["messages"].append("High yield - verify sustainability")
        elif div_yield > 3:
            analysis["messages"].append("Good dividend yield")
        else:
            analysis["messages"].append("Modest dividend yield")

        if payout > 80:
            analysis["sustainable"] = False
            analysis["messages"].append("High payout ratio - may not be sustainable")
        elif payout > 60:
            analysis["messages"].append("Moderate payout ratio")
        else:
            analysis["messages"].append("Low payout ratio - room for growth")

        return analysis

    def profitability_analysis(self) -> dict:
        """Analyze profitability metrics."""
        return {
            "roe": {
                "value": self.metrics.roe * 100 if self.metrics.roe else 0,
                "rating": "good" if self.metrics.roe and self.metrics.roe > 0.15 else "average"
                if self.metrics.roe and self.metrics.roe > 0.1 else "poor",
            },
            "roa": {
                "value": self.metrics.roa * 100 if self.metrics.roa else 0,
                "rating": "good" if self.metrics.roa and self.metrics.roa > 0.1 else "average"
                if self.metrics.roa and self.metrics.roa > 0.05 else "poor",
            },
            "profit_margin": {
                "value": self.metrics.profit_margin * 100 if self.metrics.profit_margin else 0,
                "rating": "good" if self.metrics.profit_margin and self.metrics.profit_margin > 0.2 else "average"
                if self.metrics.profit_margin and self.metrics.profit_margin > 0.1 else "poor",
            },
        }

    def financial_health(self) -> dict:
        """Analyze financial health metrics."""
        debt_equity = self.metrics.debt_to_equity
        current = self.metrics.current_ratio

        health = {
            "debt_to_equity": debt_equity,
            "current_ratio": current,
            "rating": "good",
            "messages": [],
        }

        if debt_equity > 2:
            health["rating"] = "poor"
            health["messages"].append("High debt levels")
        elif debt_equity > 1:
            health["rating"] = "average"
            health["messages"].append("Moderate debt levels")
        else:
            health["messages"].append("Low debt levels")

        if not current:
            # Not reported (typical for banks/insurers) - don't penalise.
            pass
        elif current < 1:
            health["rating"] = "poor"
            health["messages"].append("Current ratio below 1 - liquidity concern")
        elif current > 2:
            health["messages"].append("Strong liquidity position")
        else:
            health["messages"].append("Adequate liquidity")

        return health

    def growth_analysis(self) -> dict:
        """Analyze growth metrics."""
        rev_growth = self.metrics.revenue_growth * 100 if self.metrics.revenue_growth else 0
        earn_growth = self.metrics.earnings_growth * 100 if self.metrics.earnings_growth else 0

        return {
            "revenue_growth": {
                "value": rev_growth,
                "rating": "high" if rev_growth > 20 else "moderate" if rev_growth > 10 else "low",
            },
            "earnings_growth": {
                "value": earn_growth,
                "rating": "high" if earn_growth > 20 else "moderate" if earn_growth > 10 else "low",
            },
        }


    def get_summary(self) -> dict:
        """Get comprehensive fundamental analysis summary."""
        pe = self.pe_analysis()
        peg = self.peg_analysis()
        dividend = self.dividend_analysis()
        profitability = self.profitability_analysis()
        health = self.financial_health()
        growth = self.growth_analysis()

        # Calculate overall score (0-100)
        scores = []

        # PE Score
        if pe["status"] == Valuation.UNDERVALUED.value:
            scores.append(80)
        elif pe["status"] == Valuation.FAIR.value:
            scores.append(60)
        elif pe["status"] == Valuation.OVERVALUED.value:
            scores.append(30)

        # Profitability Score
        prof_scores = {"good": 80, "average": 50, "poor": 20}
        scores.append(prof_scores.get(profitability["roe"]["rating"], 50))

        # Health Score
        health_scores = {"good": 80, "average": 50, "poor": 20}
        scores.append(health_scores.get(health["rating"], 50))

        # Growth Score
        growth_scores = {"high": 80, "moderate": 50, "low": 30}
        scores.append(growth_scores.get(growth["revenue_growth"]["rating"], 50))

        overall_score = sum(scores) / len(scores) if scores else 50

        return {
            "overall_score": round(overall_score),
            "valuation": pe,
            "peg": peg,
            "dividend": dividend,
            "profitability": profitability,
            "financial_health": health,
            "growth": growth,
            "metrics": {
                "pe_ratio": self.metrics.pe_ratio,
                "price_to_book": self.metrics.price_to_book,
                "debt_to_equity": self.metrics.debt_to_equity,
                "roe": self.metrics.roe,
                "dividend_yield": self.metrics.dividend_yield,
            },
        }
