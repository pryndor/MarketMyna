"""Tests for portfolio reconciliation against broker statements (offline)."""

from datetime import date, datetime

import pytest

from marketmyna.services import reconcile as rc

ZERODHA = b"""Client ID,AB1234
Statement,Holdings as on 2026-10-14

Symbol,ISIN,Sector,Quantity Available,Quantity Discrepant,Average Price,Previous Closing Price
TCS,INE467B01029,IT,10,0,3200.5,3100
INFY-EQ,INE009A01021,IT,20,0,1500,1400
NEWCO,INE000X01011,Misc,5,0,100,110
Total,,,35,,,
"""

GROWW = b"""Stock Name,ISIN,Quantity,Average buy price,Closing price
Tata Consultancy Services Limited,INE467B01029,10,3200.5,3100
Some Unknown Ltd,INE999Z01019,3,50,55
"""

LISTINGS = [
    {"symbol": "TCS", "name": "Tata Consultancy Services Limited", "isin": "INE467B01029"},
    {"symbol": "INFY", "name": "Infosys Limited", "isin": "INE009A01021"},
    {"symbol": "NEWCO", "name": "New Co Limited", "isin": "INE000X01011"},
]


def test_read_zerodha_with_preamble_and_total_row():
    rows = rc.read_table("holdings.csv", ZERODHA)
    assert [(r["symbol"], r["quantity"], r["avg_cost"]) for r in rows] == [
        ("TCS", 10, 3200.5), ("INFY-EQ", 20, 1500), ("NEWCO", 5, 100)]
    done, unknown = rc.resolve(rows, LISTINGS)
    assert [r["symbol"] for r in done] == ["TCS", "INFY", "NEWCO"] and not unknown


def test_read_groww_names_resolve_by_isin():
    done, unknown = rc.resolve(rc.read_table("holdings.csv", GROWW), LISTINGS)
    assert [r["symbol"] for r in done] == ["TCS"]
    assert [u["name"] for u in unknown] == ["Some Unknown Ltd"]


def test_bad_file():
    with pytest.raises(rc.StatementError):
        rc.read_table("x.csv", b"just,some\nwords,here\n")


def _app(**kw):
    out = {}
    for sym, (qty, avg) in kw.items():
        out[sym] = {"quantity": qty, "avg_cost": avg, "market": "india", "current_price": 1000.0,
                    "first_date": date(2023, 1, 1)}
    return out


def test_compare_classifies_every_break():
    stmt = [{"symbol": "TCS", "quantity": 10, "avg_cost": 3300.0, "market": "india"},   # cost differs only
            {"symbol": "INFY", "quantity": 20, "avg_cost": 750.0, "market": "india"},   # 1:1 bonus not recorded
            {"symbol": "NEWCO", "quantity": 5, "avg_cost": 100.0, "market": "india"},   # not in app
            {"symbol": "HDFC", "quantity": 15, "avg_cost": 1500.0, "market": "india"},  # 5 more than recorded
            {"symbol": "ITC", "quantity": 4, "avg_cost": 400.0, "market": "india"}]     # 6 fewer
    app = _app(TCS=(10, 3200.0), INFY=(10, 1500.0), HDFC=(10, 1400.0), ITC=(10, 400.0), WIPRO=(8, 500.0))
    actions = lambda sym, market, since: [(date(2024, 6, 1), 2.0)] if sym == "INFY" else []  # noqa: E731
    out = rc.compare(app, stmt, actions, today=date(2026, 10, 14))
    kinds = {b["symbol"]: b for b in out["breaks"]}
    assert set(kinds) == {"INFY", "NEWCO", "HDFC", "ITC", "WIPRO"}
    assert kinds["INFY"]["kind"] == "split" and kinds["INFY"]["fixes"] == [
        {"type": "split", "quantity": 2.0, "price": 0.0, "date": "2024-06-01", "notes": "Split / bonus ×2 (reconciliation)"}]
    assert kinds["NEWCO"]["kind"] == "not_in_app" and kinds["NEWCO"]["fixes"][0]["price"] == 100.0
    hdfc = kinds["HDFC"]
    assert hdfc["kind"] == "short" and hdfc["fixes"][0]["quantity"] == 5
    assert hdfc["fixes"][0]["price"] == pytest.approx((15 * 1500 - 10 * 1400) / 5)  # cost of the missing lot
    assert kinds["ITC"]["kind"] == "excess" and kinds["ITC"]["fixes"][0] == {
        "type": "sell", "quantity": 6, "price": 1000.0, "date": "2026-10-14", "notes": "Reconciliation 2026-10-14",
        "needs_price": True}
    assert kinds["WIPRO"]["kind"] == "not_in_statement"
    assert [m["symbol"] for m in out["matches"]] == ["TCS"]
    assert [c["symbol"] for c in out["cost_differences"]] == ["TCS"]


def test_same_symbol_on_two_lines_is_one_position():
    stmt = [{"symbol": "TCS", "quantity": 4, "avg_cost": 3000.0, "market": "india"},
            {"symbol": "TCS", "quantity": 6, "avg_cost": 3500.0, "market": "india"}]
    out = rc.compare(_app(TCS=(10, 3300.0)), stmt, None)
    assert [m["symbol"] for m in out["matches"]] == ["TCS"] and not out["cost_differences"]


def test_ledger_check_and_apply_round_trip(tmp_path):
    from marketmyna.portfolio.manager import PortfolioManager
    from marketmyna.portfolio.models import Holding
    from marketmyna.portfolio.models import TransactionType as T

    pm = PortfolioManager(tmp_path)
    pm.create_portfolio("P", currency="INR")
    pm.add_transaction("P", "INFY", T.BUY, 10, 1500.0, date=datetime(2023, 1, 1), market="india")
    p = pm.portfolios["P"]
    assert rc.ledger_check(p) == []
    p.holdings["GHOST"] = Holding(symbol="GHOST", quantity=3, avg_cost=10, market="india")
    assert rc.ledger_check(p) == [{"symbol": "GHOST", "stored": 3, "from_history": 0.0,
                                   "issue": "Holding with no transactions behind it"}]
    del p.holdings["GHOST"]
    # the proposed bonus fix brings the records in line with the statement
    pm.add_transaction("P", "INFY", T.SPLIT, 2.0, 0.0, date=datetime(2024, 6, 1), market="india")
    stmt = [{"symbol": "INFY", "quantity": 20, "avg_cost": 750.0, "market": "india"}]
    out = rc.compare(rc.holdings_for(p, "broker"), stmt, None)
    assert [m["symbol"] for m in out["matches"]] == ["INFY"] and not out["breaks"] and not out["cost_differences"]


def test_read_excel_with_preamble():
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Holdings Statement"])
    ws.append(["Client", "AB1234"])
    ws.append([])
    ws.append(["Symbol", "ISIN", "Quantity Available", "Average Price"])
    ws.append(["TCS", "INE467B01029", 10, 3200.5])
    buf = io.BytesIO()
    wb.save(buf)
    rows = rc.read_table("holdings.xlsx", buf.getvalue())
    assert rows == [{"symbol": "TCS", "name": "", "isin": "INE467B01029", "quantity": 10.0, "avg_cost": 3200.5}]
