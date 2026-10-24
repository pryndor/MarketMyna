"""Financial statements from NSE XBRL filings (marketmyna/data/india_filings.py), offline."""

from datetime import date

import pytest

from marketmyna.data import india_filings as F


def _xbrl(contexts: str, facts: str) -> bytes:
    return f"""<?xml version="1.0"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:x="http://www.sebi.gov.in/xbrl/in-capmkt"
  xmlns:xbrldi="http://xbrl.org/2006/xbrldi">{contexts}{facts}</xbrli:xbrl>""".encode()


def _ctx(cid, start=None, end=None, instant=None, member=False):
    period = (f"<xbrli:instant>{instant}</xbrli:instant>" if instant
              else f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>")
    seg = '<xbrli:segment><xbrldi:explicitMember dimension="x:Seg">x:Seg1</xbrldi:explicitMember></xbrli:segment>' if member else ""
    return f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>{seg}</xbrli:entity><xbrli:period>{period}</xbrli:period></xbrli:context>'


def test_parse_redates_year_to_date_and_skips_segments():
    xml = _xbrl(
        _ctx("OneD", "2024-01-01", "2024-03-31") + _ctx("FourD", "2024-01-01", "2024-03-31")  # old-format mistake
        + _ctx("OneI", instant="2024-03-31") + _ctx("SegD", "2024-01-01", "2024-03-31", member=True),
        '<x:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-7">100</x:RevenueFromOperations>'
        '<x:RevenueFromOperations contextRef="FourD" unitRef="INR" decimals="-7">400</x:RevenueFromOperations>'
        '<x:Assets contextRef="OneI" unitRef="INR" decimals="-7">900</x:Assets>'
        '<x:SegmentRevenue contextRef="SegD" unitRef="INR" decimals="-7">50</x:SegmentRevenue>'
        '<x:NameOfCompany contextRef="OneD">Acme</x:NameOfCompany>',
    )
    facts = F.parse(xml)
    assert ("RevenueFromOperations", "2024-01-01", "2024-03-31", 100.0) in facts
    assert ("RevenueFromOperations", "2023-04-01", "2024-03-31", 400.0) in facts  # the full year
    assert ("Assets", None, "2024-03-31", 900.0) in facts
    assert all(f[0] != "SegmentRevenue" for f in facts)

    quarter, instants = F._period_values(facts, date(2024, 3, 31), F.QUARTER_DAYS)
    year, _ = F._period_values(facts, date(2024, 3, 31), F.YEAR_DAYS)
    assert quarter["RevenueFromOperations"] == 100 and year["RevenueFromOperations"] == 400
    assert instants["Assets"] == 900


def test_income_rows_follow_yfinance_names():
    row = F._income({"RevenueFromOperations": 1000, "CostOfMaterialsConsumed": 600, "OtherIncome": 20,
                     "FinanceCosts": 30, "ProfitBeforeExceptionalItemsAndTax": 110, "ProfitBeforeTax": 110,
                     "DepreciationDepletionAndAmortisationExpense": 40, "ProfitLossForPeriod": 80,
                     "ProfitOrLossAttributableToOwnersOfParent": 75})
    assert row["Gross Profit"] == 400 and row["Operating Income"] == 120 and row["EBITDA"] == 160
    assert row["Net Income"] == 75  # owners' share, not the minority's


def test_eps_is_restated_after_a_bonus_issue():
    income = {date(2024, 3, 31): {"Diluted EPS": 102.9, "Basic EPS": 102.9},
              date(2025, 3, 31): {"Diluted EPS": 51.47, "Basic EPS": 51.47}}
    F._restate_eps(income, {date(2024, 3, 31): 676.6, date(2025, 3, 31): 1353.2})
    assert income[date(2024, 3, 31)]["Diluted EPS"] == 51.45
    assert income[date(2025, 3, 31)]["Diluted EPS"] == 51.47


def test_statements_need_two_readable_years(monkeypatch):
    monkeypatch.setattr(F, "filings", lambda s: [{"end": date(2025, 3, 31), "consolidated": True, "url": "u"}])
    monkeypatch.setattr(F, "_facts", lambda url: [("RevenueFromOperations", "2024-04-01", "2025-03-31", 1.0)])
    with pytest.raises(RuntimeError):
        F.statements("ACME")


def test_financials_fall_back_to_yahoo(monkeypatch):
    from marketmyna.services import financials

    monkeypatch.setattr(F, "statements", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("NSE blocked")))
    assert financials._india_filings("RELIANCE", "india", False) is None
    assert financials._india_filings("AAPL", "us", False) is None
