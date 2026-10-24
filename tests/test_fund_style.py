"""Tests for fund style and SEBI category drift checks (offline)."""

import pytest

from src.services import fund_style as fs

INFOS = {"A": {"trailingPE": 10, "priceToBook": 1.0, "returnOnEquity": 0.10},
         "B": {"trailingPE": 40, "priceToBook": 8.0, "returnOnEquity": 0.30},
         "L": {"trailingPE": -5, "priceToBook": 2.0}}


def test_weighted_ratios_harmonic_and_skip_losses():
    r = fs.weighted_ratios([(50, INFOS["A"]), (50, INFOS["B"])])
    assert r["pe"] == pytest.approx(100 / (50 / 10 + 50 / 40))  # 16, not the plain 25
    assert r["roe"] == pytest.approx(20) and r["pe_coverage"] == 100
    r = fs.weighted_ratios([(50, INFOS["A"]), (50, INFOS["L"])])
    assert r["pe"] == 10 and r["pe_coverage"] == 50  # the loss-maker is left out of P/E


def test_labels():
    market = {"pe": 20.0, "pb": 3.0}
    assert fs.style_label({"pe": 12, "pb": 2}, market)["label"] == "Value"
    assert fs.style_label({"pe": 30, "pb": 5}, market)["label"] == "Growth"
    assert fs.style_label({"pe": 21, "pb": 3}, market)["label"] == "Blend"
    assert fs.size_label({"large": 80, "mid": 10, "small": 5, "foreign": 0, "other": 0}) == "Large"
    assert fs.size_label({"large": 10, "mid": 20, "small": 60, "foreign": 0, "other": 0}) == "Small"
    assert fs.size_label({"large": 40, "mid": 30, "small": 25, "foreign": 0, "other": 0}) == "Multi"


@pytest.mark.parametrize("category,split,equity,count,want", [
    ("Large Cap Fund", {"large": 78, "mid": 15, "small": 2}, 95, 50, [False]),
    ("Large Cap Fund", {"large": 85, "mid": 10, "small": 2}, 97, 50, [True]),
    ("Large & Mid Cap Fund", {"large": 40, "mid": 30, "small": 20}, 95, 60, [True, False]),
    ("Multi Cap Fund", {"large": 40, "mid": 26, "small": 25}, 95, 80, [True, True]),
    ("Focused Fund", {"large": 70, "mid": 20, "small": 5}, 95, 32, [False, True]),
    ("Liquid Fund", {"large": 0, "mid": 0, "small": 0}, 0, 0, []),
])
def test_rule_checks(category, split, equity, count, want):
    split = {**split, "foreign": 0, "other": 0}
    assert [c["ok"] for c in fs.rule_checks(category, split, equity, count)] == want


def test_build_from_holdings():
    holdings = {"status": "ok", "as_of": "2026-09-30",
                "cap_split": [{"kind": "large", "weight": 82.0}, {"kind": "mid", "weight": 10.0}],
                "holdings": [{"symbol": "A", "kind": "equity", "weight": 60.0},
                             {"symbol": "B", "kind": "equity", "weight": 32.0},
                             {"symbol": None, "kind": "debt", "weight": 8.0}]}
    out = fs.build("1", holdings=holdings, fetch=lambda s: INFOS.get(s, {}), market={"pe": 20.0, "pb": 3.0},
                   category="Large Cap Fund", use_cache=False)
    assert out["size"] == "Large" and out["equity_pct"] == 92 and out["count"] == 2
    assert out["checks"] == [{"rule": "At least 80% in large caps", "ok": True}]
    assert out["style"]["label"] in ("Value", "Blend", "Growth")
    assert fs.build("2", holdings={"status": "missing", "note": "x"}, use_cache=False)["status"] == "missing"
