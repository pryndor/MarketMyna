"""Shared mutable state passed through the agent pipeline.

One AgentContext is created per orchestrator run and threaded through
every agent in the chain: each agent reads what earlier agents put on
it (e.g. RiskAgent reads the history TechnicalAgent already fetched
rather than fetching it again) and appends its own AgentOpinion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import pandas as pd


@dataclass
class AgentOpinion:
    """One agent's contribution to the pipeline: a narrative summary
    (usually LLM-generated) plus whatever structured signal it computed."""

    agent_name: str
    summary: str
    signal: Optional[str] = None
    confidence: Optional[float] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "summary": self.summary,
            "signal": self.signal,
            "confidence": self.confidence,
            "details": self.details,
        }


@dataclass
class AgentContext:
    symbol: str
    market: str
    mode: str = "standard"
    # "trader" / "investor" (the login area) shapes the final decision;
    # None = the original, area-neutral prompt (bot, scheduler, reports).
    area: Optional[str] = None

    quote: Optional[dict] = None
    history: Optional[pd.DataFrame] = None
    info: Optional[dict] = None
    technical_summary: Optional[dict] = None
    fundamental_summary: Optional[dict] = None
    risk_metrics: Optional[dict] = None
    # Recent headlines (src/data/news_search.py dicts), set by NewsAgent.
    news: Optional[list] = None
    # What people say online (src/agent/sentiment.py): {"summary", "excerpts"}; None when not run or no posts.
    social: Optional[dict] = None

    opinions: list[AgentOpinion] = field(default_factory=list)
    generated_at: datetime = field(default_factory=datetime.now)

    def add_opinion(self, opinion: AgentOpinion) -> None:
        self.opinions.append(opinion)

    def get_opinion(self, agent_name: str) -> Optional[AgentOpinion]:
        for opinion in self.opinions:
            if opinion.agent_name == agent_name:
                return opinion
        return None
