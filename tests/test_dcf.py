"""DCF, reverse DCF and Graham number (src/services/dcf.py), offline."""

import math

import pytest

from src.services import dcf


def _fin(ocf, capex, revenue, cash=100.0, debt=300.0, financial=False):
    def st(rows):
        return {"rows": [{"key": k, "values": v} for k, v in rows.items()]}
    return {"name": "Test", "currency": "USD", "periods": ["2025", "2024", "2023", "2022"], "source": "Yahoo Finance",
            "financial_sector": financial,
            "income": st({"revenue": revenue}), "balance": st({"cash": [cash], "total_debt": [debt], "shares": [100.0]}),
            "cashflow": st({"operating_cf": ocf, "capex": capex})}


INFO = {"currency": "USD", "currentPrice": 50.0, "sharesOutstanding": 100.0, "trailingEps": 4.0, "bookValue": 20.0}


def test_model_value_by_hand():
    # no growth at all: value = sum of a flat 100 discounted at 10%, plus terminal 100/0.1
    v = dcf.model_value(100.0, 0.0, 0.10, 0.0, 0.0, 1.0)
    assert v == pytest.approx(1000.0)
    assert dcf.model_value(100.0, 0.05, 0.03, 0.04, 0.0, 1.0) is None  # discount <= terminal


def test_implied_growth_round_trip():
    v = dcf.model_value(200.0, 0.12, 0.09, 0.025, -500.0, 50.0)
    g = dcf.implied_growth(v, 200.0, 0.09, 0.025, -500.0, 50.0)
    assert g == pytest.approx(0.12, abs=1e-6)
    assert dcf.implied_growth(1e12, 200.0, 0.09, 0.025, 0.0, 50.0) is None


def test_graham_number():
    assert dcf.graham_number(4.0, 20.0) == pytest.approx(math.sqrt(22.5 * 80))
    assert dcf.graham_number(-1.0, 20.0) is None


def test_build_defaults_and_outputs():
    fin = _fin([500.0, 450.0, 400.0, 380.0], [-100.0, -90.0, -80.0, -80.0], [2662.0, 2420.0, 2200.0, 2000.0])
    d = dcf.build("TEST", "us", financials=fin, info=INFO, use_cache=False)
    x = d["dcf"]
    assert x["base_fcf"] == 400.0 and x["net_cash"] == -200.0 and x["shares"] == 100.0
    assert x["defaults"]["growth"] == pytest.approx(0.1, abs=1e-3)  # revenue CAGR
    assert x["defaults"]["discount"] == 0.09 and x["defaults"]["terminal"] == 0.025
    assert x["value"] == pytest.approx(dcf.model_value(400.0, x["defaults"]["growth"], 0.09, 0.025, -200.0, 100.0), abs=0.01)
    assert d["graham"]["value"] == pytest.approx(42.43, abs=0.01)


def test_negative_cash_flow_and_banks():
    fin = _fin([50.0, 100.0, 80.0], [-100.0, -40.0, -30.0], [1.0, 1.0, 1.0])  # -50, 60, 50
    d = dcf.build("TEST", "us", financials=fin, info=INFO, use_cache=False)
    assert d["dcf"]["base_label"].startswith("3-year average")
    fin = _fin([-500.0, -100.0, -80.0], [-100.0, -40.0, -30.0], [1.0, 1.0, 1.0])
    assert dcf.build("TEST", "us", financials=fin, info=INFO, use_cache=False)["dcf"] is None
    bank = dcf.build("BANK", "us", financials=_fin([1.0], [0.0], [1.0], financial=True), info=INFO, use_cache=False)
    assert bank["dcf"] is None and "banks" in bank["note"] and bank["graham"]


def test_stock_pay_is_a_cost_and_long_term_investments_are_cash():
    fin = _fin([500.0, 450.0, 400.0, 380.0], [-100.0, -90.0, -80.0, -80.0], [2662.0, 2420.0, 2200.0, 2000.0])
    fin["cashflow"]["rows"].append({"key": "sbc", "values": [60.0, 50.0, 40.0, 30.0]})
    fin["balance"]["rows"].append({"key": "long_term_investments", "values": [250.0]})
    x = dcf.build("TEST", "us", financials=fin, info=INFO, use_cache=False)["dcf"]
    assert x["base_fcf"] == 340.0 and x["sbc"] == 60.0  # 500 - 100 - 60
    assert x["fcf_history"] == [340.0, 310.0, 280.0, 270.0]
    assert x["net_cash"] == 50.0 and x["long_term_investments"] == 250.0  # 100 + 250 - 300
