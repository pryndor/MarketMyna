"""Tests for ETF look-through and overlap (offline)."""

import pytest

from src.services import etf

CSV = "﻿Company Name,Industry,Symbol,Series,ISIN Code\nBig Bank Ltd.,Financial Services,BIGBANK,EQ,X1\nSoft Co Ltd.,Information Technology,SOFT,EQ,X2\nOil Ltd.,Oil Gas,OIL,EQ,X3\n"
BANK_CSV = "Company Name,Industry,Symbol,Series,ISIN Code\nBig Bank Ltd.,Financial Services,BIGBANK,EQ,X1\nSmall Bank,Financial Services,SBANK,EQ,X4\n"

ROWS = [
    {"symbol": "N50ETF", "name": "Nifty 50 ETF", "type": "etf"},
    {"symbol": "BANKETF", "name": "Nifty Bank ETF", "type": "etf"},
    {"symbol": "GOLDBEES", "name": "NIP IND ETF GOLD BEES", "type": "stock"},
    {"symbol": "MOMO", "name": "Nifty 200 Momentum 30 ETF", "type": "etf"},
    {"symbol": "BIGBANK", "type": "stock", "market_cap": 600.0},
    {"symbol": "SOFT", "type": "stock", "market_cap": 300.0},
    {"symbol": "OIL", "type": "stock", "market_cap": 100.0},
    {"symbol": "SBANK", "type": "stock", "market_cap": 200.0},
]


def _fetch(url):
    return BANK_CSV if "niftybank" in url else CSV


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    monkeypatch.setattr(etf, "_cache", {})


def test_match_index_rules():
    assert etf.match_index("Nippon India ETF Nifty Bank BeES")[1] == "Nifty Bank"
    assert etf.match_index("Nifty Private Bank Index ETF")[1] == "Nifty Private Bank"
    assert etf.match_index("Mirae Asset Nifty Midcap 150 Etf")[1] == "Nifty Midcap 150"
    assert etf.match_index("Nifty 50 ETF")[1] == "Nifty 50"
    assert etf.match_index("Nifty 100 Low Volatility 30 Index ETF")[2] == "unsupported"
    assert etf.match_index("Gold BeES")[2] == "no_stocks"


def test_india_lookthrough_weights_by_cap():
    out = etf.lookthrough("N50ETF", "india", fetch=_fetch, rows=ROWS)
    assert out["status"] == "ok" and out["index"] == "Nifty 50" and out["count"] == 3
    assert [h["symbol"] for h in out["top"]] == ["BIGBANK", "SOFT", "OIL"]
    assert out["top"][0]["weight"] == pytest.approx(0.6)
    assert out["sectors"][0] == {"name": "Financial Services", "weight": pytest.approx(0.6)}


def test_gold_etf_typed_as_stock_still_recognised():
    out = etf.lookthrough("GOLDBEES", "india", fetch=_fetch, rows=ROWS)
    assert out["is_etf"] and out["status"] == "no_stocks"
    assert etf.lookthrough("MOMO", "india", fetch=_fetch, rows=ROWS)["status"] == "unsupported"
    assert etf.lookthrough("SOFT", "india", fetch=_fetch, rows=ROWS)["is_etf"] is False


def test_overlap_and_snapshot_fallback():
    a = etf.lookthrough("N50ETF", "india", fetch=_fetch, rows=ROWS)
    b = etf.lookthrough("BANKETF", "india", fetch=_fetch, rows=ROWS)
    ov = etf.overlap(a, b)
    assert ov["shared_count"] == 1 and ov["overlap"] == pytest.approx(0.6) and not ov["partial"]
    etf._cache.clear()
    blocked = etf.lookthrough("N50ETF", "india", fetch=lambda u: (_ for _ in ()).throw(RuntimeError("403")), rows=ROWS)
    assert blocked["count"] == 3  # served from the saved list


def test_us_lookthrough_from_yahoo():
    fake = {"top": [{"symbol": "AAPL", "name": "Apple", "weight": 0.07}], "sectors": {"technology": 0.5, "energy": 0.0},
            "assets": {"stockPosition": 0.99}, "category": "Large Growth", "family": "Invesco", "expense_ratio": 0.002}
    out = etf.lookthrough("QQQ", "us", yahoo=lambda s: fake)
    assert out["is_etf"] and out["sectors"] == [{"name": "Technology", "weight": 0.5}]
    assert out["weights"] == "reported" and out["expense_ratio"] == 0.002
    assert etf.lookthrough("AAPL", "us", yahoo=lambda s: {"top": [], "sectors": {}})["is_etf"] is False
