"""The login area shapes the final AI summary: a trader's leads with price
action and gets the price levels as facts, an investor's with the business."""

import numpy as np
import pandas as pd
import pytest

from marketmyna.agent.agents import DecisionAgent
from marketmyna.agent.context import AgentContext
from marketmyna.agent.dashboard import build_dashboard


@pytest.fixture(autouse=True)
def _no_macro(monkeypatch):
    monkeypatch.setattr("marketmyna.services.macro.cached_context", lambda: [])


def _history():
    close = 100 + np.cumsum(np.random.default_rng(1).normal(0, 1, 250))
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1e6})


def _run(monkeypatch, area, reply):
    seen = {}

    def fake(backend, system, prompt, scope=None):
        seen.update(system=system, prompt=prompt)
        return reply

    monkeypatch.setattr("marketmyna.agent.agents._call_llm", fake)
    ctx = AgentContext(symbol="AAPL", market="us", area=area, quote={"price": 100.0}, history=_history())
    ctx.add_opinion(DecisionAgent().run(ctx, None))
    return ctx, seen


def test_no_area_keeps_original_prompt(monkeypatch):
    _, seen = _run(monkeypatch, None, '{"decision": "hold", "rationale": "x"}')
    assert "trader" not in seen["system"] and "long-term investor" not in seen["system"]


def test_trader_gets_price_levels_as_facts_and_an_outlook(monkeypatch):
    ctx, seen = _run(monkeypatch, "trader", '{"outlook": "bullish", "rationale": "x", "entry": 99, "timeframe": "1 week"}')
    assert "short-term trader" in seen["system"] and "Support:" in seen["prompt"]
    d = build_dashboard(ctx)
    assert d["outlook"] == "bullish" and not {"entry", "timeframe", "target_price", "stop_loss"} & set(d)
