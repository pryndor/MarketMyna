"""Stock overview (Analyze page data) - network mocked."""

import numpy as np
import pandas as pd
import pytest

from marketmyna.services import overview


def _history(days=260, drift=0.001):
    idx = pd.date_range("2025-09-01", periods=days, freq="B")
    close = 100 * np.cumprod(1 + drift + 0.01 * np.sin(np.arange(days)))
    return pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
                         "volume": 1_000_000}, index=idx)


INFO = {
    "longName": "Test Corp", "sector": "Technology", "industry": "Software", "country": "India",
    "marketCap": 5e11, "trailingPE": 25.0, "forwardPE": 21.0, "priceToBook": 6.0, "returnOnEquity": 0.18,
    "profitMargins": 0.2, "revenueGrowth": 0.12, "debtToEquity": 40.0, "currentRatio": 1.8,
    "trailingAnnualDividendYield": 0.012, "totalRevenue": 1e11, "beta": 0.9,
    "recommendationKey": "buy", "numberOfAnalystOpinions": 20, "targetMeanPrice": 150.0,
    "targetHighPrice": 180.0, "targetLowPrice": 110.0, "longBusinessSummary": "Makes software.",
}


@pytest.fixture
def patched(monkeypatch):
    import yfinance as yf

    from marketmyna.agent import agents
    from marketmyna.data import news_search

    class Fetcher:
        def get_history(self, symbol, period="1y"):
            return _history()

    class Ticker:
        def __init__(self, symbol):
            self.info = dict(INFO)
            self.calendar = {"Earnings Date": [pd.Timestamp("2026-10-30").date()]}

    monkeypatch.setattr(agents, "_resolve_fetcher", lambda market: Fetcher())
    monkeypatch.setattr(yf, "Ticker", Ticker)
    monkeypatch.setattr(news_search, "stock_news",
                        lambda s, m, limit=8, name=None: [{"title": "Test Corp wins deal", "source": "ET", "url": "u",
                                                           "published": None}])


def test_full_overview(patched):
    o = overview.build_overview("TEST", "india")
    t = o["technical"]
    assert {"rsi", "macd", "ma", "bollinger", "stochastic", "cci", "williams_r", "adx"} <= {i["key"] for i in t["indicators"]}
    assert isinstance(t["patterns"], list)
    assert t["counts"]["buy"] + t["counts"]["sell"] + t["counts"]["neutral"] == len(t["indicators"])
    assert [a["period"] for a in t["averages"]] == [20, 50, 100, 200]
    assert set(t["returns"]) == {"1W", "1M", "3M", "6M", "1Y"}
    assert o["risk"]["level"] in ("low", "medium", "high") and o["risk"]["beta"] == 0.9
    groups = {g["title"]: {i["label"]: i["value"] for i in g["items"]} for g in o["fundamentals"]["groups"]}
    assert groups["Valuation"]["P/E (trailing)"] == 25.0
    assert groups["Profitability"]["Return on equity"] == pytest.approx(18.0)
    assert groups["Financial health"]["Debt / equity"] == pytest.approx(0.4)
    assert groups["Dividend"]["Dividend yield"] == pytest.approx(1.2)
    assert o["analysts"]["recommendation"] == "bullish" and "target_mean" not in o["analysts"]
    assert o["events"]["earnings_date"] == "2026-10-30"
    assert o["profile"]["sector"] == "Technology"
    assert o["news"]["items"][0]["title"] == "Test Corp wins deal"


def test_crypto_marks_fundamentals_not_applicable(patched):
    o = overview.build_overview("BTC-USD", "crypto")
    assert "error" not in o["technical"]
    for key in ("fundamentals", "analysts", "events", "profile"):
        assert o[key] == {"error": "not applicable to crypto"}


def test_one_failing_source_does_not_break_the_page(patched, monkeypatch):
    from marketmyna.agent import agents

    class Broken:
        def get_history(self, symbol, period="1y"):
            raise RuntimeError("all sources exhausted")

    monkeypatch.setattr(agents, "_resolve_fetcher", lambda market: Broken())
    o = overview.build_overview("TEST", "us")
    assert "error" in o["technical"] and "error" in o["risk"]
    assert o["fundamentals"]["score"] is not None  # still there


def test_overview_endpoint(patched):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from marketmyna.api.v1.endpoints import stocks

    app = FastAPI()
    app.include_router(stocks.router, prefix="/api/v1")
    body = TestClient(app).get("/api/v1/stocks/test/overview", params={"market": "india"}).json()
    assert body["symbol"] == "TEST" and body["technical"]["trend"]
