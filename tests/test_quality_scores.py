"""Piotroski F, Altman Z / Z'' and Beneish M (src/services/quality_scores.py)."""

import pytest

from src.services import quality_scores as qs

# Three years, newest first: a company getting better on every test
INC = {"revenue": [1200.0, 1000.0, 900.0], "gross_profit": [600.0, 450.0, 400.0], "net_income": [150.0, 100.0, 80.0],
       "operating_income": [200.0, 150.0, 120.0], "sga": [200.0, 180.0, 170.0]}
BAL = {"total_assets": [1000.0, 950.0, 900.0], "current_assets": [500.0, 400.0, 380.0],
       "current_liabilities": [200.0, 200.0, 200.0], "total_debt": [100.0, 150.0, 160.0],
       "shares": [10.0, 10.0, 10.0], "total_liabilities": [400.0, 450.0, 450.0], "retained_earnings": [300.0, 200.0, 150.0],
       "equity": [600.0, 500.0, 450.0], "receivables": [120.0, 100.0, 90.0], "ppe": [300.0, 300.0, 290.0]}
CF = {"operating_cf": [200.0, 120.0, 90.0], "depreciation": [30.0, 30.0, 28.0]}


def test_piotroski_all_pass():
    p = qs.piotroski(INC, BAL, CF)
    assert p["score"] == 9 and p["out_of"] == 9 and p["label"] == "strong"


def test_piotroski_failures_and_untestable_margin():
    inc = {**INC, "gross_profit": INC["revenue"]}  # services company: no cost of goods
    bal = {**BAL, "shares": [11.0, 10.0, 10.0]}
    cf = {**CF, "operating_cf": [100.0, 120.0, 90.0]}  # below net income
    p = qs.piotroski(inc, bal, cf)
    by = {t["key"]: t["pass"] for t in p["tests"]}
    assert by["margin"] is None and by["dilution"] is False and by["accruals"] is False
    assert p["out_of"] == 8 and p["score"] == 6


def test_altman_models():
    z = qs.altman(INC, BAL, "Industrials", market_cap=2000.0)
    # 1.2*.3 + 1.4*.3 + 3.3*.2 + 0.6*5 + 1.0*1.2
    assert z["model"].startswith("Z (") and z["score"] == pytest.approx(5.64) and z["zone"] == "safe"
    z2 = qs.altman(INC, BAL, "Real Estate", market_cap=2000.0)
    # 6.56*.3 + 3.26*.3 + 6.72*.2 + 1.05*1.5
    assert z2["model"].startswith("Z''") and z2["score"] == pytest.approx(5.87) and z2["zone"] == "safe"
    assert qs.altman(INC, BAL, "Industrials", market_cap=None)["model"].startswith("Z''")


def test_beneish_and_neutral_ratios():
    b = qs.beneish(INC, BAL, CF)
    assert b["ratios"]["SGI"] == 1.2 and b["neutral"] == [] and b["flag"] is False
    b2 = qs.beneish(INC, {k: v for k, v in BAL.items() if k != "ppe"}, CF)
    assert set(b2["neutral"]) == {"AQI", "DEPI"}
    # receivables doubling against sales and big accruals push it over the line
    bal = {**BAL, "receivables": [400.0, 100.0, 90.0]}
    cf = {**CF, "operating_cf": [-100.0, 120.0, 90.0]}
    assert qs.beneish(INC, bal, cf)["flag"] is True


def test_banks_not_scored():
    out = qs.compute(INC, BAL, CF, sector="Financial Services", financial=True)
    assert out["financial_sector"] and out["note"] and not out["piotroski"] and not out["altman"]
    assert qs.compute({}, {}, {}) is None
