"""Lumpsum window check: conditions measured against the fund's own history."""

import numpy as np
import pandas as pd

from src.services import mf_lumpsum as ml


def _series(path):
    idx = pd.bdate_range(end="2026-10-01", periods=len(path))
    return pd.Series(path, index=idx)


def _with_dips(end_dip: float):
    """Steady 12%/yr growth with a 20% dip-and-recovery every 2 years, ending
    `end_dip` below the high."""
    days = 252 * 8
    t = np.arange(days)
    base = 100 * np.exp(0.12 / 252 * t)
    dip = np.zeros(days)
    for start in range(200, days - 300, 504):
        dip[start:start + 120] = np.linspace(0, -0.20, 120)
        dip[start + 120:start + 240] = np.linspace(-0.20, 0, 120)
    path = base * (1 + dip)
    tail = np.linspace(0, end_dip, 80)
    path[-80:] = path[-81] * (1 + tail)
    return _series(path)


def test_deep_unusual_dip_after_paying_dips_is_strong():
    out = ml.assess(_with_dips(-0.18))
    assert out["status"] == "ok"
    keys = {c["key"]: c["pass"] for c in out["conditions"]}
    assert keys["dip"] and keys["trend"] and keys["history"]
    assert out["level"] == "strong" and out["met"] == 3
    assert out["below_high"] < -0.15 and out["recovery_days"] is not None


def test_near_the_high_is_none():
    out = ml.assess(_series(100 * np.exp(0.12 / 252 * np.arange(252 * 4))))
    assert out["level"] == "none" and out["below_high"] > -0.01


def test_market_condition_added_when_given():
    nifty = _with_dips(-0.12)
    out = ml.assess(_with_dips(-0.18), market=nifty)
    assert out["total"] == 4 and any(c["key"] == "market" for c in out["conditions"])


def test_short_history_and_debt_funds():
    assert ml.assess(_series(np.linspace(100, 110, 300)))["status"] == "short"
    assert ml.assess_fund("1", category="Debt Scheme - Liquid Fund")["status"] == "skipped"


def test_portfolio_funds_view(monkeypatch):
    from src.services import mf_holdings, sip_days

    monkeypatch.setattr(mf_holdings, "latest", lambda code: {
        "name": "Small Cap Fund - Direct Growth", "amc": "X MF", "category": "Equity Scheme - Small Cap Fund",
        "nav": 150.0, "nav_date": "01-Oct-2026"})
    monkeypatch.setattr(ml, "assess_fund", lambda code, category="", name="": {"status": "ok", "level": "watch"})
    monkeypatch.setattr(sip_days, "load", lambda market: {"120716": {"best_day": 12, "edge": "no_edge"}})
    summary = {
        "holdings": {
            "120716": {"symbol": "120716", "market": "mf", "quantity": 100, "cost_basis": 10000, "market_value": 15000,
                       "unrealized_gain": 5000, "unrealized_gain_percent": 50, "current_price": 150},
            "AAPL": {"symbol": "AAPL", "market": "us", "quantity": 1},
        },
        "transactions": [{"symbol": "120716", "transaction_type": "buy", "quantity": 100, "price": 100,
                          "fees": 0, "date": "2023-10-01T12:00:00"}],
    }
    out = ml.portfolio_funds(summary)
    (f,) = out["funds"]
    assert f["category"] == "Small Cap Fund" and f["asset_class"] == "Equity" and f["best_sip_day"] == 12
    assert 14 < f["xirr_pct"] < 15  # 10k -> 15k over 3 years ~ 14.5% a year
    assert out["total"]["value"] == 15000 and out["total"]["gain"] == 5000
    assert f["lumpsum"]["level"] == "watch" and "_flows" not in f


def test_dip_alerts_fire_on_rise_and_weekly_reminder(monkeypatch):
    from datetime import date

    from src.services import mf_holdings

    sent = []
    disp = type("D", (), {"send_all": lambda self, m, title=None, purpose=None: sent.append(title)})()
    monkeypatch.setattr(ml, "held_funds", lambda config: ["120716"])
    monkeypatch.setattr(mf_holdings, "latest", lambda code: {"name": "Small Cap Fund", "category": "Equity Scheme"})
    a = {"status": "ok", "level": "watch", "met": 2, "total": 4, "below_high": -0.09, "deeper_than_pct": 70,
         "after_dips_1y": 0.2, "typical_1y": 0.1, "turning": False}
    monkeypatch.setattr(ml, "assess_fund", lambda *args, **kw: a)
    state = {}
    d0 = date(2026, 10, 1)
    assert ml.check_dips(None, state, "7", disp, today=d0) == ["120716"]
    assert ml.check_dips(None, state, "7", disp, today=d0) == []  # same level: quiet
    a["level"] = "strong"
    assert ml.check_dips(None, state, "7", disp, today=d0) == ["120716"]  # rose
    assert ml.check_dips(None, state, "7", disp, today=date(2026, 10, 5)) == []
    assert ml.check_dips(None, state, "7", disp, today=date(2026, 10, 8)) == ["120716"]  # weekly reminder
    assert all(title.startswith("📉 Dip check") for title in sent) and len(sent) == 3
    a["level"] = "none"
    ml.check_dips(None, state, "7", disp, today=date(2026, 10, 9))
    assert "120716" not in state["7"]


def test_public_alert_wording_has_no_opportunity():
    a = {"level": "strong", "met": 3, "total": 4, "below_high": -0.14, "deeper_than_pct": 96,
         "after_dips_1y": 0.6, "typical_1y": 0.11, "turning": True}
    title, body = ml.alert_text("Small Cap Fund", a)
    assert title == "📉 Dip check 3 of 4: Small Cap Fund"
    assert "opportunity" not in body.lower() and "not investment advice" in body


def _fake_backend(monkeypatch, text):
    from types import SimpleNamespace

    from src.llm import backend_factory

    captured = {}

    class B:
        def generate(self, prompt, cfg, system_prompt=""):
            captured["system"] = system_prompt
            return SimpleNamespace(text=text)

    monkeypatch.setattr(backend_factory, "create_generation_backend", lambda config: B())
    return captured


def test_ai_review_has_no_view(monkeypatch):
    from src.services import mf_holdings

    monkeypatch.setattr(mf_holdings, "latest", lambda code: {"name": "Small Cap", "category": "Equity Scheme"})
    monkeypatch.setattr(ml, "assess_fund", lambda *a, **k: {
        "status": "ok", "conditions": [{"label": "Unusual dip", "pass": True, "detail": "14% below high"}],
        "turning": True, "rsi": 31, "recovery_days": 120, "as_of": "2026-10-01"})
    reply = '{"view": "strong window", "summary": "Deep dip for this fund.", "reasons": ["a", "b"], "risk": "more falls"}'
    cap = _fake_backend(monkeypatch, reply)
    out = ml.ai_review("120716", config=None)
    assert out["view"] is None and "Never recommend" in cap["system"]
