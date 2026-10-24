"""Tests for mutual fund CAS import planning and portfolio pricing (offline)."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

import pytest

from marketmyna.services import mf_holdings as mf


def _scheme(amfi, close, nav, cost, name="Fund"):
    return NS(scheme=name, amfi=amfi, isin="INF000", close=Decimal(str(close)),
              valuation=NS(date=date(2026, 9, 30), nav=Decimal(str(nav)),
                           cost=None if cost is None else Decimal(str(cost)),
                           value=Decimal(str(close * nav))))


def _cas(*folios):
    return NS(folios=list(folios), statement_period=NS(to="30-Sep-2026"), cas_type="DETAILED", parse_warnings=[])


def test_summarise_merges_folios_and_flags_unpriceable():
    cas = _cas(
        NS(amc="HDFC", schemes=[_scheme("118989", 100, 200, 15000), _scheme(None, 5, 10, 40, "Old NFO")]),
        NS(amc="HDFC", schemes=[_scheme("118989", 50, 200, 9000), _scheme("100", 0, 30, 0)]),
    )
    out = mf.summarise(cas)
    first = out["holdings"][0]
    assert first["amfi"] == "118989" and first["folios"] == 2
    assert first["units"] == 150 and first["cost"] == 24000 and first["value"] == 30000
    assert out["holdings"][-1]["units"] == 0  # redeemed scheme kept, sorted last
    assert out["skipped"] == [{"scheme": "Old NFO", "reason": "No AMFI code, cannot price it"}]
    assert out["total_value"] == 30000


def test_unknown_cost_marks_none():
    out = mf.summarise(_cas(NS(amc="X", schemes=[_scheme("1", 10, 5, None)])))
    assert out["holdings"][0]["cost"] is None


def test_plan_first_import_uses_cost_then_only_deltas():
    rows = [{"amfi": "1", "units": 100, "nav": 20, "cost": 1500, "date": "2026-09-30", "scheme": "A"},
            {"amfi": "2", "units": 10, "nav": 50, "cost": None, "date": "2026-09-30", "scheme": "B"}]
    plan = mf.plan_import({}, rows)
    assert [(t["symbol"], t["type"], t["quantity"], t["price"]) for t in plan] == [
        ("1", "buy", 100, 15.0), ("2", "buy", 10, 50.0)]
    again = mf.plan_import({"1": 100, "2": 10}, rows)
    assert again == []
    later = mf.plan_import({"1": 100, "2": 10}, [{**rows[0], "units": 112.5}, {**rows[1], "units": 0}])
    assert [(t["symbol"], t["type"], t["quantity"], t["price"]) for t in later] == [
        ("1", "buy", 12.5, 20.0), ("2", "sell", 10, 50.0)]


def test_sell_never_exceeds_holding():
    plan = mf.plan_import({"1": 3.33333}, [{"amfi": "1", "units": 0, "nav": 10, "date": None}])
    assert plan[0]["quantity"] == pytest.approx(3.33333)


def test_portfolio_prices_and_imports_funds(tmp_path, monkeypatch):
    from datetime import datetime

    from marketmyna.portfolio.manager import PortfolioManager
    from marketmyna.portfolio.models import TransactionType

    monkeypatch.setattr(mf, "latest", lambda code: {"nav": 25.0, "name": "Fund A", "amc": "AMC",
                                                   "category": "Equity Scheme - Large Cap Fund", "nav_date": "2026-09-30"})
    pm = PortfolioManager(tmp_path)
    pm.create_portfolio("MF", currency="INR")
    for t in mf.plan_import({}, [{"amfi": "1", "units": 100, "nav": 20, "cost": 1500, "date": "2026-09-30"}]):
        pm.add_transaction("MF", t["symbol"], TransactionType(t["type"]), t["quantity"], t["price"],
                           date=datetime.fromisoformat(t["date"]), market=mf.MARKET)
    h = pm.get_portfolio_summary("MF")["holdings"]["1"]
    assert h["market"] == "mf" and h["current_price"] == 25.0
    assert h["cost_basis"] == pytest.approx(1500) and h["market_value"] == pytest.approx(2500)


def test_nav_on_uses_the_last_nav_on_or_before_the_date(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"date": "09-10-2026", "nav": "88.9258"}, {"date": "08-10-2026", "nav": "88.1000"}]}

    calls = []
    monkeypatch.setattr(mf.requests, "get", lambda url, timeout: calls.append(url) or _Resp())
    mf._hist.clear()
    assert mf.nav_on("999001", date(2026, 10, 8)) == {"nav": 88.1, "nav_date": "2026-10-08"}
    # Sunday: Friday's NAV, from the cached history.
    assert mf.nav_on("999001", date(2026, 10, 11)) == {"nav": 88.9258, "nav_date": "2026-10-09"}
    assert mf.nav_on("999001", date(2026, 1, 1)) is None
    assert mf.nav_on("not-a-code", date(2026, 10, 8)) is None
    assert len(calls) == 1
