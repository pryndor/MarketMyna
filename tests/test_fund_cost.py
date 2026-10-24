"""Tests for mutual fund cost (Direct vs Regular) and tax classes (offline)."""

import pandas as pd
import pytest

from src.services import fund_cost as fc

ROWS = [
    {"symbol": "1", "type": "mf", "name": "Acme Flexi Cap Fund - Direct Plan - Growth", "plan": "Direct",
     "option": "Growth", "amc": "Acme MF", "sector": "Flexi Cap Fund"},
    {"symbol": "2", "type": "mf", "name": "Acme Flexi Cap Fund - Regular Plan - Growth", "plan": "Regular",
     "option": "Growth", "amc": "Acme MF", "sector": "Flexi Cap Fund"},
    {"symbol": "3", "type": "mf", "name": "Acme Flexi Cap Fund - Regular Plan - IDCW", "plan": "Regular",
     "option": "IDCW", "amc": "Acme MF", "sector": "Flexi Cap Fund"},
]


def _nav(rate, years=4):
    idx = pd.date_range("2022-01-01", periods=int(365.25 * years), freq="D")
    t = (idx - idx[0]).days / 365.25
    return pd.Series(10 * (1 + rate) ** t, index=idx)


@pytest.mark.parametrize("category,name,want", [
    ("Flexi Cap Fund", "", "equity"), ("ELSS", "", "equity"), ("Arbitrage Fund", "", "equity"),
    ("Liquid Fund", "", "debt"), ("Gilt Fund", "", "debt"), ("Conservative Hybrid Fund", "", "debt"),
    ("Index Funds", "UTI Nifty 50 Index Fund", "equity"), ("Index Funds", "Bharat Bond Index Fund", "debt"),
    ("Index Funds", "Motilal Nasdaq 100 Index Fund", "other"), ("Gold ETF", "Nippon Gold ETF", "other"),
    ("Dynamic Asset Allocation or Balanced Advantage", "", "other"),
])
def test_tax_class(category, name, want):
    assert fc.tax_class(category, name) == want


def test_sibling_matches_plan_and_option():
    assert fc.sibling(ROWS[0], ROWS)["symbol"] == "2"
    assert fc.sibling(ROWS[1], ROWS)["symbol"] == "1"
    assert fc.sibling(ROWS[2], ROWS)["symbol"] == "1"  # no Direct IDCW: falls back to Direct Growth


def test_build_measures_the_gap_and_costs_it():
    navs = {"1": _nav(0.12), "2": _nav(0.11)}
    out = fc.build("2", rows=ROWS, nav=lambda code: navs.get(code))
    assert out["tax_class"] == "equity" and out["tax"]["long_rate"] == 12.5
    assert out["plans"]["gap"] == pytest.approx(1.0, abs=0.02) and out["plans"]["direct_code"] == "1"
    c = out["cost"]
    assert c["assumed_return"] == 12.0
    assert c["lumpsum_direct"] == pytest.approx(100000 * 1.12 ** 10, rel=1e-6)
    assert c["lumpsum_direct"] - c["lumpsum_regular"] > 15000 and c["sip_direct"] > c["sip_regular"]
    assert fc.build("9", rows=ROWS, nav=lambda c: None)["status"] == "unknown"
