"""Tests for ownership / insider / short-interest shaping (offline, fake Ticker)."""

from datetime import date

import pandas as pd

from src.services import ownership


class FakeTicker:
    info = {"heldPercentInsiders": 0.02, "heldPercentInstitutions": 0.65, "floatShares": 1e9,
            "sharesShort": 1.2e8, "sharesShortPriorMonth": 1.0e8, "shortPercentOfFloat": 0.009,
            "shortRatio": 3.1, "dateShortInterest": 1789430400}
    institutional_holders = pd.DataFrame([{"Holder": "Vanguard", "pctHeld": 0.09, "Shares": 1e8, "Value": 3e10,
                                           "pctChange": 0.01, "Date Reported": pd.Timestamp("2026-06-30")}])
    mutualfund_holders = pd.DataFrame()
    insider_transactions = pd.DataFrame([
        {"Start Date": pd.Timestamp("2026-09-22"), "Insider": "A", "Position": "CFO", "Text": "Sale at price 340 per share.",
         "Transaction": "", "Shares": 1000, "Value": 340000.0},
        {"Start Date": pd.Timestamp("2026-08-01"), "Insider": "B", "Position": "Director", "Text": "Purchase at price 300 per share.",
         "Transaction": "", "Shares": 100, "Value": 30000.0},
        {"Start Date": pd.Timestamp("2026-07-01"), "Insider": "C", "Position": "Officer", "Text": "Stock Gift",
         "Transaction": "", "Shares": 50, "Value": None},
        {"Start Date": pd.Timestamp("2025-01-01"), "Insider": "D", "Position": "CEO", "Text": "Sale", "Transaction": "",
         "Shares": 1, "Value": 1.0},
    ])


def test_classify():
    assert ownership.classify("Sale at price 5 per share.") == "sell"
    assert ownership.classify("Purchase at price 5") == "buy"
    assert ownership.classify("Stock Award(Grant)") == "other"


def test_insider_window_and_bias():
    a = ownership.insider_activity(FakeTicker.insider_transactions, today=date(2026, 9, 30))
    assert [r["insider"] for r in a["recent"]] == ["A", "B", "C"]  # 2025 row outside 180 days
    assert a["buys"] == 1 and a["sells"] == 1 and a["bias"] == "net selling"
    assert a["sell_value"] == 340000.0


def test_build_payload():
    out = ownership.build("AAPL", "us", ticker=FakeTicker())
    assert out["breakdown"]["institutions_pct"] == 65.0
    assert out["institutions"][0]["holder"] == "Vanguard" and out["institutions"][0]["reported"] == "2026-06-30"
    assert out["funds"] == []
    s = out["short"]
    assert round(s["change_pct"]) == 20 and round(s["pct_of_float"], 6) == 0.9 and s["days_to_cover"] == 3.1


def test_no_short_data_outside_us(monkeypatch):
    monkeypatch.setattr(ownership, "_deals", lambda symbol: {"count": 0, "deals": []})
    class Bare:
        info = {"heldPercentInsiders": 0.5}
        institutional_holders = mutualfund_holders = insider_transactions = None

    out = ownership.build("RELIANCE", "india", ticker=Bare())
    assert out["short"] is None and out["insiders"]["bias"] is None and out["breakdown"]["insiders_pct"] == 50.0
    assert out["deals"] == {"count": 0, "deals": []}
