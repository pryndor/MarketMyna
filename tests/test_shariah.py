"""Shariah screen: listing rules, the listings filter, and the full
per-stock profile (yfinance mocked)."""

import pandas as pd
import pytest

from src.data.categories import enrich
from src.data.listings import _row, query
from src.data.shariah import DOUBTFUL, HALAL, HARAM, UNKNOWN, screen_row, stamp


def _status(*args, **fields):
    return screen_row(enrich([_row(*args, **fields)])[0])[0]


class TestListingRules:
    @pytest.mark.parametrize("symbol,name,sector", [
        ("HDFCBANK", "HDFC Bank Limited", "Financial Services"),
        ("BAJFINANCE", "Bajaj Finance Limited", "Financial Services"),
        ("UBL", "United Breweries Limited", "Fast Moving Consumer Goods"),
        ("ITC", "ITC Limited", "Fast Moving Consumer Goods"),
        ("LICI", "Life Insurance Corporation Of India", "Financial Services"),
    ])
    def test_india_prohibited(self, symbol, name, sector):
        assert _status(symbol, name, "india", "stock", sector=sector) == HARAM

    def test_india_permissible(self):
        assert _status("TCS", "Tata Consultancy Services Limited", "india", "stock", sector="Information Technology") == HALAL

    def test_hotels_are_doubtful(self):
        assert _status("INDHOTEL", "The Indian Hotels Company Limited", "india", "stock", sector="Consumer Services") == DOUBTFUL

    def test_us_industries(self):
        assert _status("JPM", "JP Morgan Chase & Co.", "us", "stock", sector="Finance", industry="Major Banks") == HARAM
        assert _status("PM", "Philip Morris International", "us", "stock", sector="Consumer Staples", industry="Tobacco") == HARAM
        assert _status("LVS", "Las Vegas Sands Corp.", "us", "stock", sector="Consumer Discretionary",
                       industry="Hotels/Resorts") == HARAM
        assert _status("O", "Realty Income", "us", "stock", sector="Real Estate",
                       industry="Real Estate Investment Trusts") == DOUBTFUL
        assert _status("AAPL", "Apple Inc.", "us", "stock", sector="Technology", industry="Computer Manufacturing") == HALAL

    def test_holding_word_only_matters_without_a_sector(self):
        assert _status("ASML", "ASML Holding N.V.", "us", "stock", sector="Technology",
                       industry="Industrial Machinery/Components") == HALAL
        assert _status("X1", "Futian Holdings", "hong_kong", "stock") == DOUBTFUL

    def test_chinese_names(self):
        assert _status("601398", "工商银行", "china_a", "stock") == HARAM
        assert _status("600519", "贵州茅台", "china_a", "stock") == HARAM

    def test_unclassified(self):
        assert _status("00700", "Tencent", "hong_kong", "stock") == UNKNOWN

    def test_shariah_funds(self):
        assert _status("119172", "Tata Ethical Fund - Direct Plan - Growth Option", "india", "mf",
                       fund_group="Equity Scheme - Sectoral/ Thematic") == HALAL
        assert _status("154197", "UTI Nifty500 Shariah Index Fund - Direct Plan - Growth", "india", "mf") == HALAL
        assert _status("HLAL", "Wahed FTSE USA Shariah ETF", "us", "etf") == HALAL
        assert _status("SPUS", "SP Funds S&P 500 Sharia Industry Exclusions ETF", "us", "etf") == HALAL

    def test_ethical_outside_india_is_not_shariah(self):
        assert _status("ESGX", "Some Ethical Leaders ETF", "us", "etf") == HARAM

    def test_interest_and_conventional_funds(self):
        assert _status("1", "HDFC Liquid Fund - Direct Plan - Growth", "india", "mf",
                       fund_group="Debt Scheme - Liquid Fund") == HARAM
        assert _status("NIFTYBEES", "Nifty 50 ETF", "india", "etf") == HARAM
        assert _status("GOLDBEES", "Nippon India ETF Gold BeES", "india", "etf") == DOUBTFUL

    def test_no_false_hits_inside_words(self):
        # "Grumman" contains "umma", "Osprey" contains "spre".
        assert _status("NOC", "Northrop Grumman Corporation", "us", "stock", sector="Industrials",
                       industry="Aerospace") == HALAL


class TestQueryFilter:
    def _rows(self):
        return stamp(enrich([
            _row("TCS", "Tata Consultancy Services Limited", "india", "stock", sector="Information Technology", market_cap=3.0),
            _row("HDFCBANK", "HDFC Bank Limited", "india", "stock", sector="Financial Services", market_cap=2.0),
            _row("INDHOTEL", "The Indian Hotels Company Limited", "india", "stock", sector="Consumer Services", market_cap=1.0),
        ]))

    def test_filter_and_facets(self):
        res = query(self._rows(), shariah=["halal"])
        assert [r["symbol"] for r in res["rows"]] == ["TCS"]
        # The Shariah facet ignores its own filter so every chip keeps a count.
        assert res["facets"]["shariah"] == {"halal": 1, "haram": 1, "doubtful": 1}
        assert res["facets"]["types"] == {"stock": 1}

    def test_multiple_statuses(self):
        res = query(self._rows(), shariah=["halal", "doubtful"])
        assert {r["symbol"] for r in res["rows"]} == {"TCS", "INDHOTEL"}


YEARS = [pd.Timestamp(f"{y}-03-31") for y in (2026, 2025)]


def _frame(rows: dict) -> pd.DataFrame:
    return pd.DataFrame(rows, index=YEARS).T


@pytest.fixture
def ticker(monkeypatch):
    import yfinance as yf

    from src.services import shariah

    shariah._cache.clear()
    state = {
        "info": {"longName": "Test Corp", "sector": "Technology", "industry": "Software - Application",
                 "marketCap": 1000.0, "currency": "INR", "financialCurrency": "INR"},
        "balance": _frame({
            "Total Assets": [800.0, 700.0],
            "Total Debt": [100.0, 120.0],
            "Cash Cash Equivalents And Short Term Investments": [150.0, 100.0],
            "Accounts Receivable": [100.0, 90.0],
        }),
        "income": _frame({"Total Revenue": [500.0, 450.0], "Interest Income Non Operating": [10.0, 8.0]}),
    }

    class Ticker:
        def __init__(self, symbol):
            self.info = state["info"]
            self.balance_sheet = state["balance"]
            self.income_stmt = state["income"]

        def history(self, period=None, interval=None):
            return pd.DataFrame({"Close": [100.0] * 36})

    monkeypatch.setattr(yf, "Ticker", Ticker)
    return state


class TestProfile:
    def test_compliant(self, ticker):
        from src.services.shariah import build_shariah_profile

        d = build_shariah_profile("TEST", "india")
        assert d["verdict"] == "halal"
        by_key = {c["key"]: c for c in d["checks"]}
        assert by_key["debt"]["value"] == 10.0
        assert by_key["cash"]["value"] == 15.0
        assert by_key["receivables"]["value"] == 25.0
        assert by_key["interest_income"]["value"] == 2.0
        assert d["purification_pct"] == 2.0

    def test_high_debt_fails(self, ticker):
        from src.services.shariah import build_shariah_profile

        ticker["balance"].loc["Total Debt"] = [400.0, 400.0]
        d = build_shariah_profile("TEST", "india")
        assert d["verdict"] == "haram"
        assert d["purification_pct"] is None

    def test_between_aaoifi_and_sp_is_doubtful(self, ticker):
        from src.services.shariah import build_shariah_profile

        ticker["balance"].loc["Total Debt"] = [315.0, 300.0]
        d = build_shariah_profile("TEST", "india")
        assert d["verdict"] == "doubtful"
        assert {c["key"]: c["status"] for c in d["checks"]}["debt"] == "borderline"

    def test_prohibited_business(self, ticker):
        from src.services.shariah import build_shariah_profile

        ticker["info"] = {**ticker["info"], "sector": "Financial Services", "industry": "Banks - Regional"}
        assert build_shariah_profile("TEST", "india")["verdict"] == "haram"

    def test_crypto_rejected(self, ticker):
        from src.services.shariah import build_shariah_profile

        with pytest.raises(ValueError):
            build_shariah_profile("BTC", "crypto")
