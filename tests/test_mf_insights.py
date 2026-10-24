"""Tests for the mutual fund health check (offline, synthetic NAV)."""

import numpy as np
import pandas as pd

from marketmyna.services import mf_insights as mi

IDX = pd.bdate_range(end="2026-09-30", periods=250)


def _nav(seed, base=None, noise=0.01):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0004, noise, len(IDX)) if base is None else base + rng.normal(0, noise / 10, len(IDX))
    return pd.Series(100 * np.cumprod(1 + r), index=IDX), r


def _fund(sym, name, cat, value):
    return {"symbol": sym, "name": name, "category": cat, "market_value": value}


def test_classes():
    assert mi.asset_class("Equity Scheme - Mid Cap Fund") == "Equity"
    assert mi.asset_class("Other Scheme - Index Funds", "UTI Nifty 50 Index Fund") == "Equity"
    assert mi.asset_class("Other Scheme - Index Funds", "Bharat Bond ETF FOF April 2030") == "Debt"
    assert mi.asset_class("Other Scheme - Gold ETF", "Nippon India Gold ETF") == "Commodity"
    assert mi.asset_class("Debt Scheme - Liquid Fund") == "Debt"
    assert mi.sub_category("Equity Scheme - Large Cap Fund") == "Large Cap Fund"


def test_clean_portfolio_scores_well():
    a, _ = _nav(1)
    b, _ = _nav(2)
    funds = [_fund("1", "A Flexi Cap Fund - Direct Plan - Growth", "Equity Scheme - Flexi Cap Fund", 6000),
             _fund("2", "B Short Duration - Direct Plan - Growth", "Debt Scheme - Short Duration Fund", 4000)]
    out = mi.insights(funds, {"1": a, "2": b})
    assert out["score"] == 100 and out["grade"] == "Good" and out["issues"] == []
    assert out["asset_classes"][0] == {"name": "Equity", "weight": 0.6}


def test_duplicates_lockstep_and_regular_flagged():
    a, ra = _nav(1)
    b, _ = _nav(2, base=ra)       # moves with a
    c, _ = _nav(3)
    funds = [_fund("1", "Alpha Large Cap Fund - Regular Plan - Growth", "Equity Scheme - Large Cap Fund", 4000),
             _fund("2", "Beta Large Cap Fund - Direct Plan - Growth", "Equity Scheme - Large Cap Fund", 4000),
             _fund("3", "Gamma Small Cap Fund - Direct Plan - IDCW", "Equity Scheme - Small Cap Fund", 2000)]
    out = mi.insights(funds, {"1": a, "2": b, "3": c})
    text = " ".join(out["issues"])
    assert "same category (Large Cap Fund)" in text
    assert "lockstep" in text and out["similar_pairs"][0]["a_name"] == "Alpha Large Cap Fund"
    assert "Regular-plan" in text and "IDCW" in text and "100% is in Equity" in text
    assert out["score"] < 80


def test_no_funds():
    assert mi.insights([], {}) == {"funds": 0}
