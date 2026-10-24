"""Tests for trading charges, F&O lot sizes and journal auto-fees (offline)."""

from dataclasses import replace
from datetime import date

import pytest

from marketmyna.core.config import Config
from marketmyna.trading.charges import estimate, for_trade
from marketmyna.trading.lots import lot_size


def test_india_intraday_matches_broker_calculator():
    # Zerodha's calculator: buy 1,00,000 / sell 1,01,000 intraday -> ~82.7
    c = estimate("india", 100000, 101000, product="intraday")
    assert c["total"] == pytest.approx(82.73, abs=0.05)
    assert c["parts"]["Brokerage"] == 40 and c["parts"]["STT"] == pytest.approx(25.25)


def test_india_delivery_and_options():
    d = estimate("india", 100000, 101000, product="delivery")
    assert d["parts"]["Brokerage"] == 0 and d["parts"]["STT"] == pytest.approx(201)
    o = estimate("india", 5000, 6000, product="options")
    assert o["parts"]["Brokerage"] == 40 and o["parts"]["STT"] == pytest.approx(6)  # 0.1% of sell premium


def test_entry_side_only_for_open_trades():
    open_trade = estimate("india", 100000, 0, product="intraday")
    assert open_trade["parts"]["STT"] == 0 and open_trade["parts"]["Brokerage"] == 20


def test_us_fees_on_sells():
    c = estimate("us", 10000, 10500, 30)
    assert c["parts"]["SEC fee"] == pytest.approx(0.29, abs=0.01) and c["parts"]["Commission"] == 0
    assert estimate("us", 10000, 0, 30)["total"] == 0


def test_for_trade_short_swaps_sides():
    long_ = for_trade({"market": "india", "side": "long", "quantity": 100, "entry_price": 1000, "exit_price": 1010, "product": "intraday"})
    short = for_trade({"market": "india", "side": "short", "quantity": 100, "entry_price": 1010, "exit_price": 1000, "product": "intraday"})
    assert long_ == pytest.approx(short, abs=0.02)


def test_lot_size_by_expiry():
    data = {"NIFTY": {"2026-09-29": 75, "2026-10-27": 65, "2026-12-29": 65}}
    assert lot_size("nifty", date(2026, 9, 29), data) == 75
    assert lot_size("NIFTY", date(2026, 10, 1), data) == 65  # nearest upcoming expiry
    assert lot_size("NIFTY", date(2027, 6, 1), data) == 65  # past the last one
    assert lot_size("UNKNOWN", None, data) is None


def test_journal_auto_fees(tmp_path):
    testclient = pytest.importorskip("fastapi.testclient")
    from fastapi import FastAPI

    from marketmyna.api.deps import get_config_dep
    from marketmyna.api.v1.endpoints import trade

    config = replace(Config(), db_path=tmp_path / "t.db")
    app = FastAPI()
    app.include_router(trade.router, prefix="/api/v1")
    app.dependency_overrides[get_config_dep] = lambda: config
    client = testclient.TestClient(app)

    t = client.post("/api/v1/trade/journal", json={"symbol": "TCS", "market": "india", "quantity": 100,
                                                    "entry_price": 1000, "product": "intraday"}).json()
    assert t["fees_auto"] and t["fees"] == pytest.approx(estimate("india", 100000, 0, product="intraday")["total"])
    closed = client.patch(f"/api/v1/trade/journal/{t['id']}", json={"exit_price": 1010}).json()
    assert closed["fees"] == pytest.approx(estimate("india", 100000, 101000, product="intraday")["total"])
    assert closed["pnl"] == pytest.approx(1000 - closed["fees"])
    manual = client.post("/api/v1/trade/journal", json={"symbol": "INFY", "market": "india", "quantity": 1,
                                                         "entry_price": 100, "fees": 5}).json()
    assert manual["fees"] == 5 and not manual["fees_auto"]
    assert client.post("/api/v1/trade/charges", json={"market": "india", "product": "delivery",
                                                      "buy_value": 1000, "sell_value": 0}).json()["total"] > 0
