"""Public (analytics) deploys: reports, the decision agent and the dashboard
carry facts and explanations only - no buy / hold / sell, target or stop
(docs/future/sebi-compliance-mode.md)."""

from types import SimpleNamespace

import pytest

from src.agent.agents import DecisionAgent
from src.agent.dashboard import build_dashboard
from src.services import report
from src.services.report import ReportPrefs, build_report, section_catalog
from tests.test_report_delivery import NOW, _full_result


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "analytics")


def _body(sections):
    other = _full_result()
    other.update(symbol="TCS", quote={"price": 3000, "change_percent": -2.1}, extras={"high_52w": 3050, "low_52w": 2500})
    return build_report([_full_result(), other], ReportPrefs(sections=sections), now=NOW,
                        ideas=[{"symbol": "COFORGE", "market": "india", "price": 1749.1, "reason": "uptrend"}])[1]


def test_public_report_has_no_calls_targets_or_stops(public):
    body = _body([s for s in report.SECTION_IDS])
    for banned in ("BUY", "Buy", "Sell", "strong buy", "Today's calls", "Target", "Stop", "🟢", "🔴", "Overvalued",
                   "Valuation fair"):
        assert banned not in body, banned
    assert "📊 Movers in your list" in body
    assert "▲ Up most: RELIANCE +0.50%" in body and "▼ Down most: TCS -2.10%" in body
    assert "Within 3% of 52-week high: TCS" in body
    assert "🤖 AI summary:" in body
    assert "📈 Technical readings: RSI 41.20" in body
    assert "🎯 Broker consensus of third-party analysts:" in body
    assert "⚖️ Valuation vs sector: P/E 21.1 vs 8.6 → 1.49× (Above sector)" in body
    assert "💡" not in body  # our own stock ideas are not sent on public deploys


def test_public_catalog_relabels_and_hides_ideas(public):
    cat = {sid: label for sid, label, _, _ in section_catalog()}
    assert cat["calls"] == "Movers & AI outlook" and "ideas" not in cat
    assert "valuation" in cat


class _Backend:
    def __init__(self, text):
        self.text = text

    def generate(self, prompt, config, system_prompt=""):
        self.system = system_prompt
        return SimpleNamespace(text=self.text)


def test_public_decision_agent_explains_without_a_call(public, monkeypatch):
    monkeypatch.setattr("src.agent.agents._call_llm",
                        lambda backend, system, prompt, scope=None: '{"rationale": "Revenue grew 6%; margins steady; watch debt."}')
    ctx = SimpleNamespace(symbol="AAPL", market="us", quote={"price": 333}, opinions=[], news=[])
    op = DecisionAgent().run(ctx, None)
    assert op.signal is None and op.details == {}
    assert op.summary.startswith("Revenue grew")


def test_public_dashboard_blanks_decision_target_and_stop(public):
    decision = SimpleNamespace(signal="buy", summary="x", details={"target_price": 400, "stop_loss": 300},
                               to_dict=lambda: {})
    ctx = SimpleNamespace(symbol="AAPL", market="us", mode="standard", opinions=[], generated_at=NOW,
                          get_opinion=lambda name: decision if name == "decision" else None)
    d = build_dashboard(ctx)
    assert d["compliance"] == "analytics"
    assert not {"decision_type", "target_price", "stop_loss"} & set(d)


def test_fund_dip_line_in_report(monkeypatch):
    fund = {"name": "Small Cap Fund", "nav": 150.0, "change_percent": -0.5,
            "lumpsum": {"status": "ok", "level": "strong", "met": 3, "total": 4, "below_high": -0.142}}
    body = build_report([_full_result()], ReportPrefs(sections=["funds"]), now=NOW, funds=[dict(fund)])[1]
    assert "📉 Dip check 3/4 · 14.2% below high" in body and "opportunity" not in body.lower()
