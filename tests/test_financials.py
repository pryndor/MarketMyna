"""Three-statement analysis - yfinance mocked."""

import pandas as pd
import pytest

from marketmyna.services import financials

YEARS = [pd.Timestamp(f"{y}-03-31") for y in (2026, 2025, 2024, 2023)]


def _frame(rows: dict, cols=YEARS) -> pd.DataFrame:
    return pd.DataFrame(rows, index=cols).T


INCOME = _frame({
    "Total Revenue": [1200.0, 1000.0, 900.0, 800.0],
    "Gross Profit": [600.0, 480.0, 430.0, 380.0],
    "Operating Income": [300.0, 220.0, 200.0, 170.0],
    "EBITDA": [360.0, 270.0, 240.0, 210.0],
    "Interest Expense": [10.0, 10.0, 10.0, 10.0],
    "Pretax Income": [290.0, 210.0, 190.0, 160.0],
    "Tax Provision": [70.0, 50.0, 45.0, 40.0],
    "Net Income": [220.0, 160.0, 145.0, 120.0],
    "Diluted EPS": [22.0, 16.0, 14.5, 12.0],
})
BALANCE = _frame({
    "Total Assets": [3000.0, 2800.0, 2600.0, 2400.0],
    "Current Assets": [1000.0, 900.0, 850.0, 800.0],
    "Current Liabilities": [500.0, 480.0, 470.0, 460.0],
    "Cash Cash Equivalents And Short Term Investments": [600.0, 500.0, 400.0, 300.0],
    "Inventory": [100.0, 90.0, 80.0, 70.0],
    "Total Debt": [300.0, 320.0, 340.0, 360.0],
    "Stockholders Equity": [1500.0, 1300.0, 1150.0, 1000.0],
    "Total Liabilities Net Minority Interest": [1500.0, 1500.0, 1450.0, 1400.0],
    "Ordinary Shares Number": [10.0, 10.0, 10.0, 10.0],
})
CASHFLOW = _frame({
    "Operating Cash Flow": [280.0, 200.0, 180.0, 150.0],
    "Capital Expenditure": [-80.0, -70.0, -60.0, -50.0],
    "Cash Dividends Paid": [-50.0, -40.0, -35.0, -30.0],
})


@pytest.fixture
def ticker(monkeypatch):
    import yfinance as yf

    state = {"info": {"longName": "Test Corp", "financialCurrency": "INR", "sector": "Technology"},
             "income": INCOME, "balance": BALANCE, "cashflow": CASHFLOW}

    class Ticker:
        def __init__(self, symbol):
            state["symbol"] = symbol
            self.info = state["info"]
            self.income_stmt = self.quarterly_income_stmt = state["income"]
            self.balance_sheet = self.quarterly_balance_sheet = state["balance"]
            self.cashflow = self.quarterly_cashflow = state["cashflow"]

    monkeypatch.setattr(yf, "Ticker", Ticker)
    return state


def test_healthy_company_reads_strong(ticker):
    d = financials.build_financials("TEST", "india")
    assert ticker["symbol"] == "TEST.NS"
    assert d["periods"] == ["2026-03-31", "2025-03-31", "2024-03-31", "2023-03-31"]
    assert d["currency"] == "INR" and d["name"] == "Test Corp"

    inc = d["income"]["metrics"]
    assert inc["revenue_growth"] == pytest.approx(20.0)
    assert inc["net_margin"] == pytest.approx(220 / 12)
    assert inc["gross_margin"] == pytest.approx(50.0)
    assert inc["interest_coverage"] == pytest.approx(30.0)
    assert inc["revenue_cagr"] == pytest.approx(((1200 / 800) ** (1 / 3) - 1) * 100, rel=0.01)

    bal = d["balance"]["metrics"]
    assert bal["current_ratio"] == pytest.approx(2.0)
    assert bal["quick_ratio"] == pytest.approx(1.8)
    assert bal["debt_to_equity"] == pytest.approx(0.2)
    assert bal["roe"] == pytest.approx(220 / 1400 * 100)

    cf = d["cashflow"]["metrics"]
    assert cf["free_cf"] == 200.0  # derived: OCF + capex
    assert cf["cash_conversion"] == pytest.approx(280 / 220)
    assert cf["fcf_payout"] == pytest.approx(25.0)
    assert any(r["key"] == "free_cf" for r in d["cashflow"]["rows"])

    for key in ("income", "balance", "cashflow"):
        assert d[key]["verdict"]["label"] == "strong", d[key]["findings"]
    assert d["overall"]["label"] == "strong"
    assert d["summary"].startswith("Test Corp looks financially strong")


def test_distressed_company_reads_weak(ticker):
    ticker["income"] = _frame({
        "Total Revenue": [800.0, 1000.0, 1100.0, 1200.0],
        "Operating Income": [20.0, 90.0, 120.0, 150.0],
        "Interest Expense": [40.0, 35.0, 30.0, 30.0],
        "Net Income": [-60.0, 30.0, 60.0, 90.0],
    })
    ticker["balance"] = _frame({
        "Total Assets": [2000.0, 2100.0, 2200.0, 2300.0],
        "Current Assets": [300.0, 400.0, 500.0, 600.0],
        "Current Liabilities": [500.0, 450.0, 400.0, 350.0],
        "Total Debt": [1500.0, 1300.0, 1100.0, 900.0],
        "Stockholders Equity": [500.0, 600.0, 700.0, 800.0],
        "Ordinary Shares Number": [15.0, 13.0, 11.0, 10.0],
    })
    ticker["cashflow"] = _frame({
        "Operating Cash Flow": [-50.0, 20.0, 60.0, 100.0],
        "Capital Expenditure": [-60.0, -60.0, -60.0, -60.0],
    })
    d = financials.build_financials("BAD", "us")
    texts = " ".join(f["text"] for k in ("income", "balance", "cashflow") for f in d[k]["findings"])
    assert "loss-making" in texts and "dilution" in texts and "burned" in texts
    assert d["overall"]["label"] == "weak"


def test_bank_skips_non_comparable_ratios(ticker):
    ticker["info"] = {"longName": "Test Bank", "sector": "Financial Services"}
    d = financials.build_financials("BANK", "india")
    assert d["financial_sector"] is True
    assert not any("leverage" in f["text"].lower() for f in d["balance"]["findings"])
    assert [f["tone"] for f in d["cashflow"]["findings"]] == ["info"]
    assert "debt/equity" not in d["summary"]


def test_half_year_cash_flow_not_divided_by_quarter_profit(ticker):
    quarters = [pd.Timestamp(d) for d in ("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30")]
    ticker["income"] = _frame({"Total Revenue": [300.0, 290.0, 280.0, 270.0, 250.0],
                               "Net Income": [50.0, 48.0, 46.0, 44.0, 40.0]}, cols=quarters)
    halves = [pd.Timestamp("2026-03-31"), pd.Timestamp("2025-09-30")]
    ticker["cashflow"] = _frame({"Operating Cash Flow": [120.0, 100.0], "Capital Expenditure": [-20.0, -20.0]}, cols=halves)
    ticker["balance"] = _frame({"Total Assets": [1000.0, 900.0]}, cols=halves)
    d = financials.build_financials("TEST", "india", "quarterly")
    assert d["income"]["metrics"]["revenue_growth"] == pytest.approx(20.0)  # same quarter last year
    assert d["income"]["metrics"]["compare_label"] == "same quarter last year"
    assert d["cashflow"]["metrics"]["cash_conversion"] is None
    assert d["cashflow"]["as_of"] == "2026-03-31"


def test_crypto_and_empty_raise(ticker):
    with pytest.raises(ValueError):
        financials.build_financials("BTC", "crypto")
    ticker["income"] = ticker["balance"] = ticker["cashflow"] = pd.DataFrame()
    with pytest.raises(ValueError):
        financials.build_financials("NONE", "us")


def test_us_falls_back_to_sec_filings(ticker, monkeypatch):
    ticker["income"] = ticker["balance"] = ticker["cashflow"] = pd.DataFrame()
    ticker["info"] = {}
    monkeypatch.setattr(financials, "_sec_filings", lambda symbol, quarterly: (INCOME, BALANCE, CASHFLOW))
    d = financials.build_financials("TEST", "us")
    assert d["source"] == "Company filings with the SEC (XBRL)" and d["currency"] == "USD"
    assert len(d["periods"]) == 4
    monkeypatch.setattr(financials, "_sec_filings", lambda symbol, quarterly: None)
    with pytest.raises(ValueError):
        financials.build_financials("TEST", "us")


def test_nse_filings_are_rupees_whatever_yahoo_says(ticker, monkeypatch):
    # Yahoo lists Infosys's financial currency as USD (its US listing); NSE filings are in rupees.
    ticker["info"] = {"longName": "Infosys", "financialCurrency": "USD", "currency": "INR"}
    monkeypatch.setattr(financials, "_india_filings", lambda symbol, market, quarterly: (INCOME, BALANCE, CASHFLOW))
    d = financials.build_financials("INFY", "india")
    assert d["source"] == "Company filings on NSE (XBRL)" and d["currency"] == "INR"
