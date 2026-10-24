"""AI review of a whole mutual fund portfolio."""

import json

import pytest

from marketmyna.llm.protocol import GenerationResult
from marketmyna.services import fund_holdings
from marketmyna.services import mf_portfolio_ai as ai

FUNDS = {"funds": [
    {"code": "A", "name": "Alpha Flexi Cap - Direct - Growth", "category": "Flexi Cap Fund", "asset_class": "Equity",
     "units": 10, "invested": 600.0, "value": 750.0, "gain_pct": 25.0, "lumpsum": {"status": "ok", "below_high": -0.05}},
    {"code": "B", "name": "Beta Pharma - Direct - Growth", "category": "Sectoral/ Thematic", "asset_class": "Equity",
     "units": 5, "invested": 300.0, "value": 250.0, "gain_pct": -16.7, "lumpsum": {"status": "no_data"}},
]}
HEALTH = {"funds": 2, "score": 70, "grade": "Fair", "asset_classes": [{"name": "Equity", "weight": 1.0}],
          "categories": [{"name": "Flexi Cap Fund", "weight": 0.75, "count": 1}],
          "similar_pairs": [{"a_name": "Alpha", "b_name": "Beta", "correlation": 0.912}], "issues": ["All equity"]}
REPLY = {"summary": "Two equity funds, three quarters in one flexi cap.", "strengths": ["Low overlap"],
         "concerns": ["A quarter in one sector"], "sections": {"mix": "All equity.", "overlap": "Little."},
         "funds": [{"code": "A", "note": "The core holding."}, {"code": "ZZZ", "note": "Made up."}],
         "view": "fair", "actions": ["Add a debt fund"]}


@pytest.fixture(autouse=True)
def holdings(monkeypatch):
    data = {
        "A": {"status": "ok", "holdings": [{"name": "HDFC Bank", "kind": "equity", "weight": 8.0},
                                           {"name": "T-Bill", "kind": "debt", "weight": 5.0}],
              "sectors": [{"name": "Banks", "weight": 20.0}]},
        "B": {"status": "ok", "holdings": [{"name": "Sun Pharma", "kind": "equity", "weight": 10.0},
                                           {"name": "HDFC Bank", "kind": "equity", "weight": 4.0}],
              "sectors": [{"name": "Pharma", "weight": 90.0}]},
    }
    monkeypatch.setattr(fund_holdings, "for_fund", lambda code: data[code])
    ai._cache.clear()


def test_look_through_weights_each_fund_by_its_share():
    lt = ai.look_through({"A": 0.75, "B": 0.25})
    assert lt["covered_pct"] == 100
    assert lt["top_stocks_of_portfolio"][0] == "HDFC Bank 7.0%"  # 0.75*8 + 0.25*4; debt left out
    assert "Pharma 22.5%" in lt["top_sectors_of_portfolio"] and "Banks 15.0%" in lt["top_sectors_of_portfolio"]


def test_facts_sheet():
    f = ai.facts(FUNDS, HEALTH)
    assert f["funds"] == 2 and f["value"] == 1000 and f["gain_pct"] == pytest.approx(11.11, abs=0.01)
    assert f["holdings"][0] == {"code": "A", "fund": "Alpha Flexi Cap", "category": "Flexi Cap Fund",
                                "asset_class": "Equity", "weight_pct": 75.0, "gain_pct": 25.0, "below_high_pct": -5.0}
    assert f["holdings"][1]["below_high_pct"] is None
    assert f["health_check"]["funds_that_move_together"] == ["Alpha & Beta (correlation 0.91)"]


class _Backend:
    def __init__(self, text):
        self.text, self.systems = text, []

    def generate(self, prompt, config, system_prompt=None):
        self.systems.append(system_prompt)
        return GenerationResult(text=self.text, model="m", provider="p", backend="b")


def _backend(monkeypatch, text):
    b = _Backend(text)
    monkeypatch.setattr("marketmyna.llm.backend_factory.create_generation_backend", lambda config: b)
    return b


def test_public_review_has_no_view_and_no_actions(monkeypatch):
    monkeypatch.setenv("COMPLIANCE_MODE", "analytics")
    b = _backend(monkeypatch, json.dumps(REPLY))
    out = ai.review("MF", FUNDS, HEALTH, config=None)
    assert out["view"] is None and out["actions"] == [] and out["compliance"] == "analytics"
    assert "not registered with SEBI" in b.systems[0]
    assert out["funds"] == [{"code": "A", "note": "The core holding.", "name": "Alpha Flexi Cap", "weight_pct": 75.0}]


def test_review_is_cached_until_the_holdings_change(monkeypatch):
    b = _backend(monkeypatch, json.dumps(REPLY))
    ai.review("MF", FUNDS, HEALTH, config=None)
    ai.review("MF", FUNDS, HEALTH, config=None)
    assert len(b.systems) == 1  # second call served from cache
    changed = {"funds": [dict(FUNDS["funds"][0], units=11), FUNDS["funds"][1]]}
    ai.review("MF", changed, HEALTH, config=None)
    assert len(b.systems) == 2  # a trade changes the holdings, so a fresh review


def test_no_funds_and_bad_reply(monkeypatch):
    with pytest.raises(LookupError):
        ai.review("MF", {"funds": []}, {}, config=None)
    monkeypatch.setenv("COMPLIANCE_MODE", "personal")
    _backend(monkeypatch, "no json here")
    assert ai.review("MF", FUNDS, HEALTH, config=None) is None


def test_look_through_left_out_when_most_holdings_are_unknown(monkeypatch):
    monkeypatch.setattr(fund_holdings, "for_fund", lambda code: {"status": "ok", "holdings": [], "sectors": []}
                        if code == "B" else {"status": "missing"})
    lt = ai.facts(FUNDS, HEALTH)["look_through"]
    assert lt["covered_pct"] == 25 and "top_stocks_of_portfolio" not in lt and "note" in lt
