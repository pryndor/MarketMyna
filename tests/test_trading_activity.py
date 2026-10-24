"""Order book parsing, delivery file parsing and the stock-page activity endpoint (offline)."""

import pytest

from marketmyna.services import delivery, live_quotes
from marketmyna.services.brokers import angel

FULL = {
    "ltp": 1209.0, "totBuyQuan": 412000, "totSellQuan": 365500, "avgPrice": 1216.71, "lastTradeQty": 15,
    "upperCircuit": 1322.2, "lowerCircuit": 1081.8,
    "depth": {
        "buy": [{"price": 1208.9, "quantity": 120, "orders": 4}, {"price": 1208.8, "quantity": 300, "orders": 9},
                {"price": 0, "quantity": 0, "orders": 0}],
        "sell": [{"price": 1209.1, "quantity": 80, "orders": 2}],
    },
}

CSV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
RELIANCE, EQ, 21-Oct-2026, 1202.00, 1212.00, 1234.30, 1199.30, 1209.00, 1209.00, 1216.71, 17607823, 214235.87, 316700, 8160605, 46.35
RELIANCE, N1, 21-Oct-2026, 1, 1, 1, 1, 1, 1, 1, 5, 1, 1, -, -
OFSS, EQ, 21-Oct-2026, 10214.00, 10219.00, 10374.00, 10181.00, 10263.00, 10263.00, 10252.87, 200256, 20531.98, 41871, 98230, 49.05
"""


def test_order_book_parses_and_drops_empty_levels():
    book = angel.order_book(FULL)
    assert book["buy_qty"] == 412000 and book["sell_qty"] == 365500 and book["upper_circuit"] == 1322.2
    assert [lv["price"] for lv in book["depth"]["buy"]] == [1208.9, 1208.8]
    assert book["depth"]["sell"] == [{"price": 1209.1, "quantity": 80, "orders": 2}]
    assert angel.order_book({"ltp": 5}) == {}


def test_delivery_parse_keeps_normal_series():
    rows = delivery.parse(CSV)
    assert set(rows) == {"RELIANCE", "OFSS"}
    assert rows["RELIANCE"]["percent"] == pytest.approx(46.35) and rows["RELIANCE"]["delivered"] == 8160605
    assert rows["OFSS"]["traded"] == 200256


def test_table_poll_hides_depth_but_activity_shows_it(monkeypatch, app_client):
    m = live_quotes._market("india")
    with m.lock:
        m.quotes["RELIANCE"] = {"price": 1209.0, "volume": 17_600_000, **angel.order_book(FULL)}
        m.fetched_at = 10**12  # fresh: no background refresh
    monkeypatch.setattr(delivery, "get", lambda sym: {"date": "2026-10-21", "loading": False, "percent": 46.35})
    try:
        table = live_quotes.get("india", ["RELIANCE"])["quotes"]["RELIANCE"]
        assert "depth" not in table and table["buy_qty"] == 412000
        import marketmyna.api.v1.endpoints.listings as ep

        monkeypatch.setitem(ep._KNOWN, "india", (10**12, frozenset({"RELIANCE"})))
        client = app_client()
        junk = client.get("/api/v1/listings/activity", params={"market": "india", "symbol": "NOT A STOCK"}).json()
        assert junk["quote"] is None and "NOT A STOCK" not in m.watched
        resp = client.get("/api/v1/listings/activity", params={"market": "india", "symbol": "reliance.ns"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["symbol"] == "RELIANCE" and body["quote"]["depth"]["buy"][0]["price"] == 1208.9
        assert body["delivery"]["percent"] == 46.35
    finally:
        with m.lock:
            m.quotes.pop("RELIANCE", None)
            m.fetched_at = 0.0


def test_yahoo_live_handles_one_symbol_with_nested_columns(monkeypatch):
    import pandas as pd
    import yfinance as yf

    idx = pd.to_datetime(["2026-10-21 15:29", "2026-10-22 09:15", "2026-10-22 09:16"]).tz_localize("Asia/Kolkata")
    flat = pd.DataFrame({"Close": [100.0, 101.0, 102.0], "Volume": [5, 10, 20]}, index=idx)
    nested = pd.concat({"RELIANCE.NS": flat}, axis=1)  # current yfinance shape for one ticker
    for frame in (nested, flat):
        monkeypatch.setattr(yf, "download", lambda *a, frame=frame, **k: frame)
        q = live_quotes._fetch_yahoo(["RELIANCE"], "india")["RELIANCE"]
        assert q["price"] == 102.0 and q["volume"] == 30 and q["change_percent"] == 2.0


def test_unknown_symbols_do_not_trip_the_quote_breaker(monkeypatch):
    import yfinance as yf

    from marketmyna.data import india
    from marketmyna.data.resilience import CircuitBreaker, DataSourceUnavailable, default_breaker

    class Info:
        @property
        def last_price(self):
            raise KeyError("currentTradingPeriod")  # what Yahoo does for a symbol it doesn't know

    class Ticker:
        def __init__(self, symbol):
            self.fast_info = Info()

    monkeypatch.setattr(yf, "Ticker", Ticker)
    monkeypatch.setattr(default_breaker, "_states", {})
    fetcher = india.IndiaDataFetcher()
    fetcher._use_jugaad = False
    for _ in range(5):
        with pytest.raises(DataSourceUnavailable):
            fetcher.get_quote("360 ONE BALANCED HYBRID FUND")
    assert default_breaker.status().get("yfinance:india.get_quote", CircuitBreaker.CLOSED) == CircuitBreaker.CLOSED


def test_delivery_file_is_rechecked_only_when_a_newer_session_can_exist():
    from datetime import datetime

    ist = delivery.IST
    monday_morning = datetime(2026, 10, 19, 10, 0, tzinfo=ist)
    assert not delivery._newer_due("2026-10-16", monday_morning)  # Friday's file is the newest
    assert delivery._newer_due("2026-10-16", datetime(2026, 10, 19, 18, 30, tzinfo=ist))  # Monday's is out
    assert not delivery._newer_due("2026-10-19", datetime(2026, 10, 20, 9, 0, tzinfo=ist))
    assert delivery._newer_due(None, monday_morning)
