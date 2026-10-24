"""AI fund review: fact sheet, reply parsing and compliance wording."""

import json

import pytest

from marketmyna.llm.protocol import GenerationResult
from marketmyna.services import fund_ai

REPLY = {
    "summary": "Steady returns with lower swings than the Nifty 500.",
    "strengths": ["Beat the benchmark in 95% of 3-year windows"],
    "concerns": ["12% abroad adds currency risk"],
    "sections": {"returns": "Median 3-year return 19%.", "risk": "Volatility 9.9% vs 14.5%."},
    "view": "strong",
    "suits": "Long-term investors.",
}


@pytest.fixture
def services(monkeypatch):
    from marketmyna.services import fund_analytics, fund_cost, fund_holdings, fund_peers, fund_style

    monkeypatch.setattr(fund_peers, "compare", lambda code: {
        "status": "ok", "name": "Acme Flexi Cap - Direct - Growth", "category": "Flexi Cap Fund", "plan": "Direct",
        "ranks": {"r3": {"rank": 16, "of": 36}, "volatility": {"rank": 1, "of": 44}}})
    monkeypatch.setattr(fund_analytics, "build", lambda code: {
        "status": "ok", "category": "Flexi Cap Fund", "nav_from": "2013-05-28", "benchmark": {"name": "Nifty 500"},
        "rolling": {"windows": [{"years": 3, "median": 19.07, "bench_median": 15.18, "beat_pct": 95.1,
                                 "negative_pct": 0.0, "min": 0.74, "max": 37.6}]},
        "risk": {"years": 3, "annual_return": 0.1217, "volatility": 0.0989, "max_drawdown": -0.11, "sharpe": 0.55},
        "drawdowns": {"current": -6.7, "max": -31.2}})
    monkeypatch.setattr(fund_style, "build", lambda code: {"status": "error"})  # a missing part is just left out
    monkeypatch.setattr(fund_cost, "build", lambda code: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(fund_holdings, "for_fund", lambda code: {
        "status": "ok", "scheme": "Acme Flexi Cap", "as_of": "2026-09-30", "count": 56, "top10_weight": 51.0,
        "top": [{"name": "HDFC Bank", "weight": 7.75}], "sectors": [{"name": "Banks", "weight": 20.5}], "mix": []})
    fund_ai._cache.clear()


def test_facts_keep_what_loaded_and_skip_what_failed(services):
    f = fund_ai.facts("122639")
    assert f["name"] == "Acme Flexi Cap - Direct - Growth" and f["benchmark"] == "Nifty 500"
    assert f["rolling_returns_pct"][0]["beat_benchmark_pct_of_windows"] == 95.1
    assert f["risk_last_3y"]["volatility_pct"] == 9.9 and f["rank_among_peers"]["volatility"] == {"rank": 1, "of": 44}
    assert f["portfolio"]["top_holdings"] == ["HDFC Bank 7.8%"]
    assert "style" not in f and "direct_vs_regular" not in f


class _Backend:
    def __init__(self, text):
        self.text, self.calls = text, []

    def generate(self, prompt, config, system_prompt=None):
        self.calls.append(system_prompt)
        return GenerationResult(text=self.text, model="m", provider="p", backend="b")


def _patch_backend(monkeypatch, text):
    backend = _Backend(text)
    monkeypatch.setattr("marketmyna.llm.backend_factory.create_generation_backend", lambda config: backend)
    return backend


def test_public_review_has_no_view_and_no_fit(services, monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "analytics")
    backend = _patch_backend(monkeypatch, json.dumps(REPLY))
    out = fund_ai.review("122639", config=None)
    assert out["summary"].startswith("Steady") and out["strengths"] and out["sections"]["risk"]
    assert out["view"] is None and out["suits"] is None and out["compliance"] == "analytics"
    assert "not registered with SEBI" in backend.calls[0]


def test_unusable_reply_is_none_and_not_cached(services, monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "personal")
    _patch_backend(monkeypatch, "sorry, no JSON")
    assert fund_ai.review("122639", config=None) is None
    assert not fund_ai._cache


def test_no_fund_data_raises_lookup(monkeypatch):
    from marketmyna.services import fund_analytics, fund_cost, fund_holdings, fund_peers, fund_style

    for mod, name in ((fund_peers, "compare"), (fund_analytics, "build"), (fund_style, "build"),
                      (fund_cost, "build"), (fund_holdings, "for_fund")):
        monkeypatch.setattr(mod, name, lambda code: {"status": "error"})
    fund_ai._cache.clear()
    with pytest.raises(LookupError):
        fund_ai.review("999999", config=None)


def test_endpoint_without_ai_key_says_how_to_fix(app_client, monkeypatch):
    monkeypatch.setattr("marketmyna.llm.channels.llm_configured", lambda config: False)
    r = app_client().post("/api/v1/listings/mf/122639/ai-review")
    assert r.status_code == 409 and "AI key" in r.json()["message"]


def test_endpoint_returns_the_review(app_client, services, monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "analytics")
    monkeypatch.setattr("marketmyna.llm.channels.llm_configured", lambda config: True)
    _patch_backend(monkeypatch, json.dumps(REPLY))
    r = app_client().post("/api/v1/listings/mf/122639/ai-review")
    assert r.status_code == 200 and r.json()["view"] is None and r.json()["summary"]


def test_cut_off_reply_still_gives_a_review(services, monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "analytics")
    text = json.dumps(REPLY)
    _patch_backend(monkeypatch, text[: text.index('"risk"') + 20])  # cut inside sections.risk
    out = fund_ai.review("122639", config=None)
    assert out["summary"].startswith("Steady") and out["sections"] == {"returns": "Median 3-year return 19%."}
