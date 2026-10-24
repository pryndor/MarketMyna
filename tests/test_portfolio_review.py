from datetime import datetime

import pytest

from src.portfolio import review


def _h(symbol, value, market="US", gain_pct=10.0, **extra):
    return {"symbol": symbol, "market": market, "market_value": value, "unrealized_gain_percent": gain_pct,
            "unrealized_gain": value * gain_pct / 100, **extra}


def _summary(*holdings, cash=0.0, transactions=None):
    return {"currency": "USD", "cash_balance": cash, "holdings": {h["symbol"]: h for h in holdings},
            "transactions": transactions or []}


def _ids(out):
    return [f["id"] for f in out["findings"]]


def test_empty_portfolio_has_no_score():
    out = review.build(_summary())
    assert out["score"] is None and out["findings"] == []


def test_concentration_sector_and_few_holdings():
    s = _summary(_h("MSFT", 5000), _h("AAPL", 3000), _h("NVDA", 2000))
    out = review.build(s, sectors={"MSFT": "Technology", "AAPL": "Technology", "NVDA": "Technology"})
    ids = _ids(out)
    assert {"concentration", "sector", "few_holdings"} <= set(ids)
    conc = out["findings"][ids.index("concentration")]
    assert conc["severity"] == "high" and conc["symbols"][0] == "MSFT"  # 50% vs 20% limit
    assert ids.index("concentration") < ids.index("few_holdings")  # high before medium
    assert out["score"] < 80


def test_levers_name_no_amount_to_trim():
    s = _summary(_h("MSFT", 5000), _h("AAPL", 5000))
    finding = review.build(s)["findings"][0]
    assert not any("Trim" in lever or "USD" in lever for lever in finding["levers"])


def test_user_limits_change_the_result_and_are_validated():
    s = _summary(*[_h(f"S{i}", 1000) for i in range(5)])  # 20% each
    assert "concentration" not in _ids(review.build(s))
    assert "concentration" in _ids(review.build(s, limits={"max_holding": 15}))
    with pytest.raises(ValueError):
        review.clean_limits({"max_holding": 1})


def test_losers_cash_and_holding_age():
    tx = [{"symbol": "BAD", "transaction_type": "buy", "date": "2024-01-10T00:00:00"}]
    s = _summary(*[_h(f"S{i}", 1000) for i in range(5)], _h("BAD", 1000, gain_pct=-40), cash=4000, transactions=tx)
    out = review.build(s, now=datetime(2026, 1, 20))
    loser = out["findings"][_ids(out).index("losers")]
    assert "BAD -40.0%, held 2y 0m" in loser["fact"]
    assert "cash" in _ids(out)


def test_analytics_risk_share_correlation_and_market_risk():
    s = _summary(*[_h(f"S{i}", 1000) for i in range(5)])
    analytics = {
        "holdings": [{"symbol": "S0", "weight": 0.2, "risk_contribution": 0.45, "volatility": 0.5}]
        + [{"symbol": f"S{i}", "weight": 0.2, "risk_contribution": 0.1375, "volatility": 0.2} for i in range(1, 5)],
        "correlation": {"symbols": ["S0", "S1"], "matrix": [[1, 0.92], [0.92, 1]]},
        "metrics": {"beta": 1.4, "max_drawdown": -0.3},
        "benchmark": {"name": "S&P 500"},
    }
    ids = _ids(review.build(s, analytics=analytics))
    assert {"risk_share", "correlation", "market_risk"} <= set(ids)


def test_fund_issues_map_to_findings_with_levers():
    s = _summary(_h("100", 5000, market="mf", category="Equity Scheme - Large Cap Fund", name="A Fund"),
                 _h("200", 5000, market="mf", category="Equity Scheme - Large Cap Fund", name="B Fund"))
    funds = {"funds": 2, "issues": ["2 funds in the same category"], "issue_kinds": ["same_category"]}
    out = review.build(s, funds=funds)
    f = out["findings"][_ids(out).index("fund_same_category")]
    assert f["levers"] and f["section"] == review.FUND_HEALTH
    assert "concentration" not in _ids(out)  # a 50% fund is a diversified holding, not one stock


def test_no_target_mix_from_the_optimizer():
    s = _summary(_h("A", 6000), _h("B", 4000))
    analytics = {"holdings": [], "optimizer": {"current": {"sharpe": 0.5},
                                               "max_sharpe": {"sharpe": 1.0, "weights": {"A": 0.4, "B": 0.6}}}}
    assert "optimizer" not in _ids(review.build(s, analytics=analytics))


def test_ai_summary_prompt_gives_no_advice(monkeypatch):
    seen = {}

    class Fake:
        def generate(self, prompt, cfg, system_prompt=""):
            seen["system"], seen["prompt"] = system_prompt, prompt
            return type("R", (), {"text": 'ok {"summary": "Too much in MSFT.", "priorities": ["a", "b", "c", "d"], "keep": "low beta"}'})()

    monkeypatch.setattr("src.llm.backend_factory.create_generation_backend", lambda config: Fake())
    rev = review.build(_summary(_h("MSFT", 5000), _h("AAPL", 5000)))
    out = review.ai_summary(rev, config=None)
    assert out == {"summary": "Too much in MSFT.", "priorities": ["a", "b", "c"], "keep": "low beta"}
    assert "Never tell them to buy, sell" in seen["system"] and "One holding is a big share" in seen["prompt"]
