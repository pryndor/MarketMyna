"""SEC XBRL company facts to Yahoo-style statements (marketmyna/data/sec_facts.py), offline."""

import pandas as pd
import pytest

from marketmyna.data import sec_facts


def _flow(start, end, val, form="10-Q", filed="2026-01-01"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed}


def _inst(end, val, form="10-K", fp="FY", filed="2026-01-01"):
    return {"end": end, "val": val, "form": form, "fp": fp, "filed": filed}


def _facts(tags: dict) -> dict:
    return {"facts": {"us-gaap": {t: {"units": {unit: rows}} for t, (unit, rows) in tags.items()}}}


# Fiscal year 2025-01-01..2025-12-31, three 10-Q quarters, cash flow only as year to date
FACTS = _facts({
    "Revenues": ("USD", [
        _flow("2024-01-01", "2024-12-31", 360.0, "10-K"),
        _flow("2025-01-01", "2025-12-31", 400.0, "10-K"),
        _flow("2025-01-01", "2025-03-31", 90.0),
        _flow("2025-04-01", "2025-06-30", 100.0),
        _flow("2025-07-01", "2025-09-30", 105.0),
    ]),
    "NetIncomeLoss": ("USD", [
        _flow("2024-01-01", "2024-12-31", 36.0, "10-K"),
        _flow("2025-01-01", "2025-12-31", 40.0, "10-K"),
        # restated in a later filing: the newer figure wins
        _flow("2024-01-01", "2024-12-31", 35.0, "10-K", filed="2026-02-01"),
    ]),
    "EarningsPerShareDiluted": ("USD/shares", [
        _flow("2025-01-01", "2025-12-31", 4.0, "10-K"),
        _flow("2025-01-01", "2025-03-31", 0.9),
        _flow("2025-04-01", "2025-06-30", 1.0),
        _flow("2025-07-01", "2025-09-30", 1.05),
    ]),
    "NetCashProvidedByUsedInOperatingActivities": ("USD", [
        _flow("2025-01-01", "2025-12-31", 80.0, "10-K"),
        _flow("2025-01-01", "2025-03-31", 15.0),
        _flow("2025-01-01", "2025-06-30", 35.0),
        _flow("2025-01-01", "2025-09-30", 60.0),
    ]),
    "PaymentsToAcquirePropertyPlantAndEquipment": ("USD", [
        _flow("2025-01-01", "2025-12-31", 20.0, "10-K"),
    ]),
    "Assets": ("USD", [_inst("2025-12-31", 1000.0), _inst("2024-12-31", 900.0),
                       _inst("2025-09-30", 950.0, "10-Q", "Q3")]),
    "CashAndCashEquivalentsAtCarryingValue": ("USD", [_inst("2025-12-31", 50.0)]),
    "LongTermDebtNoncurrent": ("USD", [_inst("2025-12-31", 200.0)]),
    "LongTermDebtCurrent": ("USD", [_inst("2025-12-31", 30.0)]),
})


def test_annual_statements_like_yahoo():
    inc, bal, cf = sec_facts.statements("TEST", facts=FACTS)
    assert list(inc.columns) == [pd.Timestamp("2025-12-31"), pd.Timestamp("2024-12-31")]
    col = pd.Timestamp("2025-12-31")
    assert inc.at["Total Revenue", col] == 400.0
    assert inc.at["Net Income", pd.Timestamp("2024-12-31")] == 35.0  # restatement
    assert bal.at["Total Assets", col] == 1000.0
    assert bal.at["Total Debt", col] == 230.0 and bal.at["Net Debt", col] == 180.0
    assert cf.at["Capital Expenditure", col] == -20.0  # outflow made negative
    assert cf.at["Free Cash Flow", col] == 60.0


def test_quarterly_fourth_quarter_and_year_to_date():
    inc, bal, cf = sec_facts.statements("TEST", quarterly=True, facts=FACTS)
    q4, q3 = pd.Timestamp("2025-12-31"), pd.Timestamp("2025-09-30")
    assert inc.at["Total Revenue", q4] == 105.0  # 400 - 90 - 100 - 105
    assert cf.at["Operating Cash Flow", q3] == 25.0  # 60 - 35 year to date
    assert cf.at["Operating Cash Flow", q4] == 20.0  # 80 - 15 - 20 - 25
    # EPS is not a sum over time: no derived fourth quarter
    assert pd.isna(inc.at["Diluted EPS", q4]) and inc.at["Diluted EPS", q3] == 1.05
    assert bal.at["Total Assets", q3] == 950.0


def test_net_income_sets_periods_when_revenue_tag_stops():
    facts = _facts({
        "Revenues": ("USD", [_flow("2014-01-01", "2014-03-31", 9.0)]),
        "NetIncomeLoss": ("USD", [_flow("2026-01-01", "2026-03-31", 2.0)]),
    })
    inc, _, _ = sec_facts.statements("BANK", quarterly=True, facts=facts)
    assert inc.columns[0] == pd.Timestamp("2026-03-31")


def test_no_tagged_statements_raises():
    with pytest.raises(ValueError):
        sec_facts.statements("NONE", facts={"facts": {}})
