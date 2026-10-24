"""Tests for market discovery (offline, synthetic listing rows)."""

import pytest

from src.services import discovery


def _row(symbol, change, cap, price=100.0, volume=1000, category="Technology", type_="stock", **kw):
    return {"symbol": symbol, "name": symbol, "type": type_, "price": price, "change_percent": change,
            "volume": volume, "market_cap": cap, "currency": "INR", "category": category, **kw}


@pytest.fixture
def rows():
    return [
        _row("BIG1", 3.0, 1000, volume=5000, category="Financials", high_52w=101.0, low_52w=60.0),
        _row("BIG2", -2.0, 900, category="Financials"),
        _row("BIG3", 1.0, 800, price=10.0, volume=100_000, low_52w=9.9, high_52w=20.0),
        _row("BIG4", -4.0, 700, category="Other"),
        _row("TINY", 20.0, 1),  # outside a size-4 universe
        _row("FLAT", 0.0, 600),
        _row("NOVOL", 5.0, 650, volume=0),  # unpriced, ignored everywhere
        _row("FUND", 1.0, 5000, type_="etf"),
    ]


def test_leader_boards_and_breadth(rows, monkeypatch):
    monkeypatch.setattr(discovery, "_indices", lambda m: [])
    out = discovery.build("india", size=4, rows=rows, with_indices=False)
    assert out["universe"] == 6  # size floors at 20, so every priced stock with a cap counts
    out = discovery.build("india", size=20, rows=[r for r in rows if r["symbol"] != "TINY"], with_indices=False)
    assert [r["symbol"] for r in out["gainers"]] == ["BIG1", "BIG3"]
    assert [r["symbol"] for r in out["losers"]] == ["BIG4", "BIG2"]
    assert out["active"][0]["symbol"] == "BIG3" and out["active"][0]["traded_value"] == 1_000_000
    assert out["breadth"] == {"advancers": 2, "decliners": 2, "unchanged": 1, "total": 5}
    assert [r["symbol"] for r in out["near_high"]] == ["BIG1"]
    assert [r["symbol"] for r in out["near_low"]] == ["BIG3"]


def test_sectors_cap_weighted_and_skip_other(rows):
    out = discovery.build("india", rows=rows, with_indices=False)
    sectors = {s["sector"]: s for s in out["sectors"]}
    assert "Other" not in sectors
    fin = sectors["Financials"]
    assert fin["change_percent"] == pytest.approx((3.0 * 1000 - 2.0 * 900) / 1900)
    assert fin["advancers"] == 1 and fin["decliners"] == 1
    assert fin["leader"]["symbol"] == "BIG1" and fin["laggard"]["symbol"] == "BIG2"
    assert [m["symbol"] for m in fin["members"]] == ["BIG1", "BIG2"]  # largest first
    assert out["sectors"][0]["change_percent"] >= out["sectors"][-1]["change_percent"]


def test_crypto_ranks_by_volume_without_sectors():
    rows = [_row(f"C{i}-USD", i - 5.0, None, volume=1000 * i, type_="crypto", category="Crypto") for i in range(1, 30)]
    out = discovery.build("crypto", size=20, rows=rows, with_indices=False)
    assert out["universe"] == 20 and out["sectors"] == []
    assert out["active"][0]["symbol"] == "C29-USD"
    assert all(int(r["symbol"][1:-4]) >= 10 for r in out["gainers"])


def test_endpoint_rejects_unknown_market(app_client):
    resp = app_client().get("/api/v1/listings/discovery", params={"market": "mars"})
    assert resp.status_code == 400
