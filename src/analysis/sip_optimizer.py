"""SIP (Systematic Investment Plan) Optimization Module."""

from dataclasses import dataclass
from typing import Optional

import sys
sys.path.insert(0, str(__file__).rsplit('/src/', 1)[0])

from src.data.mutual_funds import MutualFundDataFetcher




@dataclass
class StepUpSIPProjection:
    """Step-up SIP projection."""
    base_amount: float
    annual_increase_pct: float
    duration_years: int
    expected_return_pct: float
    total_invested: float
    projected_corpus: float
    projected_gain: float
    yearly_breakdown: list[dict]



class SIPOptimizer:
    """SIP optimization and analysis tools."""

    def __init__(self, data_fetcher: Optional[MutualFundDataFetcher] = None):
        self.data_fetcher = data_fetcher or MutualFundDataFetcher()




    def calculate_step_up_sip(
        self,
        base_amount: float,
        annual_increase_pct: float,
        duration_years: int,
        expected_return_pct: float,
    ) -> StepUpSIPProjection:
        """
        Calculate step-up SIP projection where SIP amount increases annually.
        """
        monthly_rate = expected_return_pct / 100 / 12

        total_invested = 0
        corpus = 0
        yearly_breakdown = []
        current_amount = base_amount

        for year in range(1, duration_years + 1):
            year_invested = 0
            year_start_corpus = corpus

            for month in range(12):
                # Add this month's investment
                corpus = corpus * (1 + monthly_rate) + current_amount
                year_invested += current_amount
                total_invested += current_amount

            yearly_breakdown.append({
                'year': year,
                'monthly_sip': current_amount,
                'year_invested': year_invested,
                'year_end_corpus': corpus,
                'year_growth': corpus - year_start_corpus - year_invested,
            })

            # Increase for next year
            current_amount = current_amount * (1 + annual_increase_pct / 100)

        projected_gain = corpus - total_invested

        return StepUpSIPProjection(
            base_amount=base_amount,
            annual_increase_pct=annual_increase_pct,
            duration_years=duration_years,
            expected_return_pct=expected_return_pct,
            total_invested=total_invested,
            projected_corpus=corpus,
            projected_gain=projected_gain,
            yearly_breakdown=yearly_breakdown,
        )
