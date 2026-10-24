"""Sequential agent pipeline: builds a mode-specific agent chain, runs
each stage against a shared AgentContext, and tolerates non-critical
stage failures without aborting the whole analysis.

Mode chains, each adding to the one before:

    quick:      [technical, decision]
    standard:   [technical, risk, news, decision]
    full:       [technical, risk, news, sentiment, fundamentals, decision]
    specialist: [technical, risk, news, sentiment, fundamentals, *selected SkillAgents, decision]

"fundamentals" reads the filings, valuation vs sector and analyst estimates.
"sentiment" reads what people say on Reddit, StockTwits, ValuePickr and
Hacker News (marketmyna/agent/sentiment.py); slow, so Full and Specialist only.
"decision" explains the findings and gives an outlook, never a call.

"specialist" mode runs SkillManager.select_skills() (see skills.py and
marketmyna/strategies/README.md) after fundamentals, turning 0-N matched strategy YAML
files into their own SkillAgent stage each, before the final decision.
A skill agent's failure is non-critical, same as risk's.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ..llm.backend_factory import create_generation_backend
from ..llm.protocol import GenerationBackend
from .agents import (
    DecisionAgent,
    FundamentalsAgent,
    NewsAgent,
    RiskAgent,
    SkillAgent,
    TechnicalAgent,
)
from .context import AgentContext, AgentOpinion
from .sentiment import SentimentAgent
from .skills import SkillManager

logger = logging.getLogger(__name__)

MODE_CHAINS = {
    "quick": ["technical", "decision"],
    "standard": ["technical", "risk", "news", "decision"],
    "full": ["technical", "risk", "news", "sentiment", "fundamentals", "decision"],
}

# "specialist" isn't a fixed chain like the others: it runs the analysts,
# then dynamically selects and runs 0-N SkillAgents (see SkillManager),
# then the same decision as "full".
SPECIALIST_BASE_STAGES = ["technical", "risk", "news", "sentiment", "fundamentals"]
SPECIALIST_FINAL_STAGES = ["decision"]

# A failure in a critical stage aborts the whole run; a failure in any
# other stage is logged and skipped, and the pipeline continues with
# whatever opinions it already has.
CRITICAL_STAGES = {"technical", "decision"}

# StageCallback(event, stage_name, payload) - payload is an AgentOpinion
# on "stage_done", an error message string on "stage_skipped", and None
# on "stage_start". A critical-stage failure is NOT reported through this
# callback - it's simply raised, so there is exactly one place a caller
# needs to handle it (a try/except around run()), rather than both a
# callback event and a raised exception for the same failure.
StageCallback = Callable[[str, str, object], None]


class AgentOrchestrator:
    def __init__(self, config=None, backend: Optional[GenerationBackend] = None):
        """`backend` is injectable directly (rather than only resolvable
        via `config`) so tests/callers can hand in a fake GenerationBackend
        without monkeypatching the factory function."""
        self.config = config
        self.backend = backend if backend is not None else create_generation_backend(config)
        self._agents = {
            "technical": TechnicalAgent(),
            "risk": RiskAgent(),
            "news": NewsAgent(),
            "fundamentals": FundamentalsAgent(),
            "sentiment": SentimentAgent(config=config),
            "decision": DecisionAgent(),
        }
        self._skill_manager = SkillManager()
        self._skill_manager.load_builtin_skills()

    def run(
        self,
        symbol: str,
        market: str,
        mode: str = "standard",
        on_stage: Optional[StageCallback] = None,
        market_regime: Optional[str] = None,
        skill_query: Optional[str] = None,
        skill_limit: int = 3,
        ctx: Optional[AgentContext] = None,
        area: Optional[str] = None,
    ) -> AgentContext:
        """market_regime/skill_query/skill_limit only matter for
        mode="specialist" - they select which Skill instructions get
        their own SkillAgent in the chain, run between fundamentals and decision.
        They're accepted (and ignored) for other modes rather than
        rejected, so a caller doesn't need to special-case its own
        request-building around which mode it happens to be calling."""
        if mode == "specialist":
            chain = self._build_specialist_chain(market_regime, skill_query, skill_limit)
        else:
            static_chain = MODE_CHAINS.get(mode)
            if static_chain is None:
                raise ValueError(f"Unknown orchestrator mode '{mode}' (choices: {sorted(MODE_CHAINS) + ['specialist']})")
            chain = [self._agents[name] for name in static_chain]

        # A caller-supplied ctx survives a critical-stage exception, so it
        # can still use whatever the earlier stages gathered.
        if ctx is None:
            ctx = AgentContext(symbol=symbol, market=market, mode=mode, area=area)
        elif area:
            ctx.area = area

        for agent in chain:
            stage_name = agent.agent_name

            if on_stage:
                on_stage("stage_start", stage_name, None)

            try:
                opinion: AgentOpinion = agent.run(ctx, self.backend)
            except Exception as exc:
                if stage_name in CRITICAL_STAGES:
                    logger.error("Critical stage '%s' failed: %s", stage_name, exc)
                    raise
                logger.warning("Non-critical stage '%s' failed, continuing: %s", stage_name, exc)
                if on_stage:
                    on_stage("stage_skipped", stage_name, str(exc))
                continue

            ctx.add_opinion(opinion)
            if on_stage:
                on_stage("stage_done", stage_name, opinion)

        return ctx

    def _build_specialist_chain(
        self, market_regime: Optional[str], skill_query: Optional[str], skill_limit: int
    ) -> list:
        chain = [self._agents[name] for name in SPECIALIST_BASE_STAGES]
        selected = self._skill_manager.select_skills(
            market_regime=market_regime, query=skill_query, limit=skill_limit
        )
        chain.extend(SkillAgent(skill) for skill in selected)
        chain.extend(self._agents[name] for name in SPECIALIST_FINAL_STAGES)
        return chain
