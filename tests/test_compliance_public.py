"""Public (analytics) deploys never carry a call, target, stop or recommended
mix (docs/future/sebi-compliance-mode.md, step 12); the owner still does."""

import pytest

from src.agent.context import AgentContext, AgentOpinion
from src.agent.dashboard import build_dashboard
from src.core import compliance
from src.services.overview import public_view

CALL_WORDS = ("decision_type", "target_price", "stop_loss", "buy_point", "sell_point")


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "analytics")


def _ctx():
    ctx = AgentContext(symbol="TCS", market="india")
    ctx.opinions = [
        AgentOpinion("technical", "RSI 62, above the 200-day average.", signal="buy", confidence=0.7,
                     details={"overall_signal": "BUY", "buy_signals": 5, "indicators": {"rsi": {"value": 62.0, "signal": "buy"}}}),
        AgentOpinion("news", "Results beat estimates.", signal="bullish"),
        AgentOpinion("decision", "Strong quarter.", signal="buy", details={"target_price": 4200, "stop_loss": 3700}),
    ]
    return ctx


def test_dashboard_has_no_calls_in_public_mode(public):
    d = build_dashboard(_ctx())
    assert d["compliance"] == "analytics"
    assert not {"decision_type", "target_price", "stop_loss", "technical_signal", "technical_confidence"} & set(d)
    tech, news, decision = d["opinions"]
    assert tech["signal"] == "bullish" and tech["confidence"] is None  # what the indicators read, not a call
    assert tech["details"] == {"indicators": {"rsi": {"value": 62.0, "signal": "bullish"}}}
    assert news["signal"] == "positive"  # the tone of the news, not a view on the stock
    assert decision["signal"] is None and "target_price" not in decision["details"]


def test_overview_public_view_shows_readings_not_calls():
    raw = {
        "technical": {"overall": "buy", "counts": {"buy": 3, "sell": 0, "neutral": 8}, "trend": "uptrend",
                      "indicators": [{"key": "rsi", "value": 55, "signal": "neutral"}],
                      "patterns": [{"key": "engulfing", "name": "Bullish engulfing", "bias": "bullish"}]},
        "fundamentals": {"score": 60, "valuation_status": "overvalued"},
        "analysts": {"recommendation": "buy", "count": 39},
    }
    out = public_view(raw)
    t = out["technical"]
    assert t["overall"] == "bullish" and t["counts"]["buy"] == 3 and t["trend"] == "uptrend"
    assert t["indicators"][0] == {"key": "rsi", "value": 55, "signal": "neutral"}
    assert t["patterns"][0]["bias"] == "bullish"
    assert "valuation_status" not in out["fundamentals"]
    assert out["analysts"]["recommendation"] == "bullish" and out["analysts"]["count"] == 39  # a direction, not a call


def test_calls_are_off_whatever_the_environment(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "personal")  # the old switch does nothing
    assert compliance.mode() == "analytics" and compliance.mode_for(1) == "analytics"
    assert compliance.NO_CALLS_RULE in compliance.guard_prompt("Explain RSI.")
    assert "bullish, neutral or bearish outlook" in compliance.NO_CALLS_RULE


def test_outlook_turns_ratings_into_directions():
    assert [compliance.outlook(r) for r in ("strong_buy", "buy", "HOLD", "sell", "strong_sell")] == [
        "bullish", "bullish", "neutral", "bearish", "bearish"]
    assert compliance.outlook("bearish") == "bearish" and compliance.outlook(None) is None
    assert compliance.outlook("review") is None


def test_dashboard_carries_the_outlook_not_the_call():
    d = build_dashboard(_ctx())
    assert d["outlook"] == "bullish" and "decision_type" not in d and "target_price" not in d


def test_trade_levels_endpoint_drops_buy_sell_stop(public, monkeypatch):
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from fastapi import FastAPI

    from api.v1.endpoints import trade

    monkeypatch.setattr("src.services.smart_report.snapshot", lambda symbol, market: {
        "symbol": symbol, "price": 100.0, "normal_low": 95.0, "normal_high": 105.0, "week_low": 97.0,
        "buy_point": 96.0, "sell_point": 108.0, "stop_loss": 92.0, "action": "buy"})
    app = FastAPI()
    app.include_router(trade.router, prefix="/api/v1")
    row = fastapi_testclient.TestClient(app).get("/api/v1/trade/levels", params={"symbol": "TCS", "market": "india"}).json()
    assert not any(k in row for k in (*CALL_WORDS, "action"))
    assert row["normal_low"] == 95.0 and row["week_low"] == 97.0


def test_portfolio_analytics_hides_the_optimizer_publicly(public, monkeypatch, app_client, tmp_path):
    from dataclasses import replace

    from api.deps import get_config_dep
    from src.core.config import Config
    from src.portfolio.manager import PortfolioManager

    monkeypatch.setattr(PortfolioManager, "update_prices", lambda self, name: None)
    monkeypatch.setattr("src.portfolio.analytics.analyze", lambda holdings: {
        "holdings": [], "warnings": [], "optimizer": {"max_sharpe": {"weights": {"A": 1.0}}}})
    client = app_client()
    config = replace(Config(), db_path=tmp_path / "c.db")
    client.app.dependency_overrides[get_config_dep] = lambda: config
    client.post("/api/v1/portfolio", json={"name": "P", "currency": "INR"})
    client.post("/api/v1/portfolio/P/transactions", json={"symbol": "TCS", "transaction_type": "buy",
                                                          "quantity": 1, "price": 100, "market": "INDIA"})
    out = client.get("/api/v1/portfolio/P/analytics").json()
    assert out["compliance"] == "analytics" and out["optimizer"] is None


class _FakeOrchestrator:
    """Runs no agents: reports the scope it ran in and replays _ctx()'s opinions."""

    def __init__(self):
        self.scope = "unset"

    def run(self, symbol, market, mode="standard", on_stage=None, area=None):
        from src.core import tenant

        self.scope = tenant.current()
        ctx = _ctx()
        for op in ctx.opinions:
            on_stage("stage_done", op.agent_name, op)
        return ctx


def _stream(orchestrator):
    import json

    from api.v1.endpoints.agent import AnalyzeRequest, stream_agent_events

    lines = stream_agent_events(orchestrator, AnalyzeRequest(symbol="TCS", market="india"))
    return [json.loads(line[len("data: "):]) for line in lines]


def test_stream_has_no_calls_in_public_mode(public):
    events = _stream(_FakeOrchestrator())
    tech, _news, decision = (e["opinion"] for e in events if e["event"] == "stage_done")
    assert tech["signal"] == "bullish" and "overall_signal" not in tech["details"]
    assert decision["signal"] is None and "target_price" not in decision["details"]


def test_stream_runs_in_the_callers_user_scope():
    from src.core import tenant

    orchestrator = _FakeOrchestrator()
    with tenant.user_scope(42):
        _stream(orchestrator)
    assert orchestrator.scope == 42
