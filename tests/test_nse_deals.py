"""Tests for NSE bulk / block deals parsing and the per-day store (offline)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.data import nse_deals

BULK = """Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks
30-SEP-2026,AAREYDRUGS,Aarey Drugs,ARYA RAVI,BUY,"144,423",100.01,-
30-SEP-2026,TCS,Tata Consultancy,BIG FUND,SELL,1000,3000,Promoter
bad-date,X,X,X,BUY,1,1,-
"""
BLOCK = """Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price
29-SEP-2026,TCS,Tata Consultancy,OTHER FUND,BUY,2000,2990
"""


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(nse_deals, "_dir", lambda: tmp_path)
    nse_deals._last.clear()


def fetch(url):
    return BULK if "bulk" in url else BLOCK


def test_parse():
    rows = nse_deals.parse(BULK, "bulk")
    assert len(rows) == 2
    a = rows[0]
    assert a["date"] == "2026-09-30" and a["qty"] == 144423 and a["side"] == "buy" and a["remarks"] is None
    assert rows[1]["remarks"] == "Promoter" and rows[1]["value"] == 3_000_000


def test_store_builds_history_without_duplicates(tmp_path):
    assert nse_deals.refresh(fetch, force=True) == 3
    nse_deals.refresh(fetch, force=True)  # same files again: no duplicates
    out = nse_deals.recent(30, today=date(2026, 9, 30), fetch=fetch)
    assert out["count"] == 3 and out["history_from"] == "2026-09-29" and out["latest"] == "2026-09-30"
    tcs = nse_deals.recent(30, "tcs", today=date(2026, 9, 30), fetch=fetch)
    assert [(d["date"], d["kind"]) for d in tcs["deals"]] == [("2026-09-30", "bulk"), ("2026-09-29", "block")]


def test_fetch_failure_keeps_other_kind():
    def half(url):
        if "block" in url:
            raise RuntimeError("403")
        return BULK

    assert nse_deals.refresh(half, force=True) == 2


def test_maybe_refresh_window(monkeypatch):
    calls = []
    monkeypatch.setattr(nse_deals, "refresh", lambda force=False: calls.append(force))
    ist = ZoneInfo("Asia/Kolkata")
    nse_deals.maybe_refresh(datetime(2026, 9, 30, 11, 0, tzinfo=ist))  # before the close
    nse_deals.maybe_refresh(datetime(2026, 10, 3, 18, 0, tzinfo=ist))  # Saturday
    assert calls == []
    nse_deals.maybe_refresh(datetime(2026, 9, 30, 18, 0, tzinfo=ist))
    nse_deals.maybe_refresh(datetime(2026, 9, 30, 18, 30, tzinfo=ist))  # within the hour
    assert calls == [True]


def test_block_also_listed_as_bulk_is_merged():
    bulk = BULK + "29-SEP-2026,TCS,Tata Consultancy,OTHER FUND,BUY,2000,2990,-\n"
    nse_deals.refresh(lambda url: bulk if "bulk" in url else BLOCK, force=True)
    tcs = nse_deals.recent(30, "TCS", today=date(2026, 9, 30), fetch=fetch)
    assert [d["kind"] for d in tcs["deals"]] == ["bulk", "block & bulk"]
