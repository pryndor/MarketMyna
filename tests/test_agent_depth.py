"""Analysis depth: each mode adds to the one before, and Full / Specialist
really read the business (FundamentalsAgent)."""

import pytest

from src.agent import agents
from src.agent.agents import FundamentalsAgent
from src.agent.context import AgentContext, AgentOpinion
from src.agent.orchestrator import MODE_CHAINS, SPECIALIST_BASE_STAGES, SPECIALIST_FINAL_STAGES, AgentOrchestrator


class NoModel:
    """A backend that always fails: stages fall back to their rule-based text."""

    def generate(self, *args, **kwargs):
        raise RuntimeError("no model")


def test_each_depth_adds_to_the_one_before():
    quick, standard, full = MODE_CHAINS["quick"], MODE_CHAINS["standard"], MODE_CHAINS["full"]
    assert quick == ["technical", "decision"]
    assert set(quick) < set(standard) < set(full)
    assert "fundamentals" in full and "fundamentals" not in standard
    assert SPECIALIST_BASE_STAGES + SPECIALIST_FINAL_STAGES == full  # specialist = full + strategy agents


def test_full_runs_fundamentals_before_the_decision(monkeypatch):
    seen = []

    class Stage:
        def __init__(self, name):
            self.agent_name = name

        def run(self, ctx, backend):
            seen.append(self.agent_name)
            return AgentOpinion(self.agent_name, f"{self.agent_name} done")

    orch = AgentOrchestrator(backend=NoModel())
    orch._agents = {name: Stage(name) for name in orch._agents}
    orch.run("TCS", "india", mode="full")
    assert seen == ["technical", "risk", "news", "sentiment", "fundamentals", "decision"]


def _patch_sources(monkeypatch, fin=None, val=None, est=None):
    monkeypatch.setattr("src.services.financials.build_financials", lambda s, m, p: fin or {})
    monkeypatch.setattr("src.services.valuation.meter", lambda s, m: val or {})
    monkeypatch.setattr("src.services.estimates.build", lambda y: est or {})


def test_fundamentals_agent_reads_filings_valuation_and_estimates(monkeypatch):
    _patch_sources(
        monkeypatch,
        fin={"overall": {"label": "strong", "score": 80},
             "income": {"verdict": {"label": "strong"}, "findings": [{"text": "Revenue grew 12%."}]}},
        val={"status": "ok", "sector": "Technology", "peers": 14, "zone": "in_line",
             "multiples": [{"label": "P/E", "value": 25.0, "sector_median": 26.0}], "garp": {"passed": 3, "total": 5}},
        est={"available": True, "momentum": {"label": "rising"}, "beats": {"beat": 4, "total": 4}, "periods": []},
    )
    op = FundamentalsAgent().run(AgentContext(symbol="TCS", market="india"), NoModel())
    assert op.agent_name == "fundamentals"
    assert set(op.details) == {"financial_statements", "valuation_vs_sector", "analyst_estimates"}
    assert "strong (80/100)" in op.summary and "in line with its Technology sector" in op.summary and "rising" in op.summary


def test_fundamentals_agent_skips_missing_sources_and_crypto(monkeypatch):
    _patch_sources(monkeypatch, val={"status": "ok", "sector": "Energy", "peers": 5, "zone": "above", "multiples": []})
    op = FundamentalsAgent().run(AgentContext(symbol="ONGC", market="india"), NoModel())
    assert list(op.details) == ["valuation_vs_sector"]
    crypto = FundamentalsAgent().run(AgentContext(symbol="BTC-USD", market="crypto"), NoModel())
    assert "don't apply" in crypto.summary
    _patch_sources(monkeypatch)
    with pytest.raises(RuntimeError):  # non-critical stage: the orchestrator skips it
        FundamentalsAgent().run(AgentContext(symbol="XYZ", market="india"), NoModel())


def test_fundamentals_prompt_has_no_calls_rule_publicly(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "analytics")
    captured = {}
    monkeypatch.setattr(agents, "_narrate", lambda backend, system, prompt, fallback, scope=None: captured.setdefault("s", system) or fallback)
    _patch_sources(monkeypatch, fin={"overall": {"label": "mixed", "score": 50}})
    FundamentalsAgent().run(AgentContext(symbol="TCS", market="india"), NoModel())
    assert "Never recommend buying" in captured["s"]
