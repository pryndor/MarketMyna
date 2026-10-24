"""Stale Yahoo quotes (seen on Indian REITs / InvITs) are never used as a price."""

import pandas as pd

from src.data.india import IndiaDataFetcher, quote_from_bars
from src.data.yahoo_price import MAX_AGE, fresh_price, info_price

NOW = 1_800_000_000


def test_info_price_prefers_current_price():
    assert info_price({"currentPrice": 435.3, "regularMarketPrice": 369.9}, now=NOW) == 435.3


def test_info_price_drops_a_frozen_market_price():
    old = {"regularMarketPrice": 369.92, "regularMarketTime": NOW - MAX_AGE - 1}
    fresh = {"regularMarketPrice": 435.3, "regularMarketTime": NOW - 3600}
    assert info_price(old, now=NOW) is None
    assert info_price(fresh, now=NOW) == 435.3
    assert info_price({"regularMarketPrice": 12.5}, now=NOW) == 12.5  # no timestamp: keep it


def _bars(*closes):
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [100] * len(closes)})


def test_fresh_price_falls_back_to_the_daily_close():
    class Ticker:
        def history(self, **_):
            return _bars(431.21, 435.3)

    assert fresh_price({"regularMarketPrice": 369.92, "regularMarketTime": 1}, Ticker()) == 435.3


def test_india_quote_replaces_a_frozen_quote_with_daily_bars(monkeypatch):
    class Fast:
        last_price, previous_close, open, day_high, day_low, last_volume = 369.92, 431.21, 0, 0, 0, 0

    class Ticker:
        fast_info = Fast()

        def __init__(self, *_):
            pass

        def history(self, **_):
            return _bars(431.21, 435.3)

    import yfinance

    monkeypatch.setattr(yfinance, "Ticker", Ticker)
    q = IndiaDataFetcher.__new__(IndiaDataFetcher)._fetch_quote_yfinance("EMBASSY")
    assert q["price"] == 435.3 and q["previous_close"] == 431.21 and round(q["change_percent"], 2) == 0.95


def test_quote_from_bars_single_bar():
    q = quote_from_bars("X", _bars(100.0))
    assert q["price"] == 100.0 and q["previous_close"] is None and q["change"] == 0
