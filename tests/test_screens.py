"""Tests for fundamental screen presets (offline)."""

import pytest

from marketmyna.services import screens

ROWS = [{"symbol": s, "name": s, "type": "stock", "market_cap": cap, "price": 100}
        for s, cap in [("CHEAP", 900), ("PRICEY", 800), ("DIV", 700), ("QUAL", 600), ("LOSS", 500)]]
INFO = {
    "CHEAP.NS": {"trailingPE": 10, "priceToBook": 1.5, "returnOnEquity": 0.15, "earningsGrowth": 0.05,
                 "debtToEquity": 80.0, "dividendYield": 2.0, "currentPrice": 100, "fiftyTwoWeekHigh": 150, "fiftyTwoWeekLow": 95},
    "PRICEY.NS": {"trailingPE": 60, "priceToBook": 12, "returnOnEquity": 0.30, "earningsGrowth": 0.25, "revenueGrowth": 0.2,
                  "debtToEquity": 10.0, "operatingMargins": 0.3},
    "DIV.NS": {"trailingPE": 12, "dividendYield": 5.5, "debtToEquity": 20.0, "payoutRatio": 0.6, "returnOnEquity": 0.18},
    "QUAL.NS": {"trailingPE": 28, "returnOnEquity": 0.25, "operatingMargins": 0.25, "debtToEquity": 5.0,
                "revenueGrowth": 0.12, "earningsGrowth": 0.18},
    "LOSS.NS": {"trailingPE": -5, "returnOnEquity": -0.1},
}


def _run(key):
    return screens.run(key, "india", info_fetch=lambda t: INFO.get(t, {}), rows=ROWS)


def test_metrics_units():
    m = screens.metrics(INFO["CHEAP.NS"])
    assert m["roe"] == pytest.approx(15) and m["debt_equity"] == pytest.approx(0.8)
    assert m["from_high"] == pytest.approx(-33.33, abs=0.01) and m["from_low"] == pytest.approx(5.26, abs=0.01)


def test_presets_pick_expected():
    assert [r["symbol"] for r in _run("undervalued_large")["results"]] == ["CHEAP"]
    assert [r["symbol"] for r in _run("dividend")["results"]] == ["DIV"]
    assert [r["symbol"] for r in _run("quality")["results"]] == ["PRICEY", "QUAL"]  # sorted by ROE
    assert [r["symbol"] for r in _run("garp")["results"]] == ["QUAL"]  # PRICEY fails P/E < 30
    out = _run("near_low")
    assert [r["symbol"] for r in out["results"]] == ["CHEAP"] and out["scanned"] == 5


def test_unknown_and_listing():
    with pytest.raises(ValueError):
        screens.run("nope", "india", info_fetch=lambda t: {}, rows=ROWS)
    assert {p["key"] for p in screens.list_presets()} == set(screens.PRESETS)


def _sector_rows(n_peers=6):
    rows, info = [], {}
    for i in range(n_peers):  # an ordinary IT sector around P/E 20
        sym = f"PEER{i}"
        rows.append({"symbol": sym, "name": sym, "type": "stock", "market_cap": 1000 - i, "price": 10})
        info[f"{sym}.NS"] = {"trailingPE": 18 + i, "priceToBook": 4, "earningsGrowth": 0.12, "sector": "Technology"}
    for sym, pe, growth in [("RICH", 60, 0.10), ("RICHGROW", 60, 0.40), ("RICHSHRINK", 45, -0.05)]:
        rows.append({"symbol": sym, "name": sym, "type": "stock", "market_cap": 500, "price": 10})
        info[f"{sym}.NS"] = {"trailingPE": pe, "priceToBook": 12, "earningsGrowth": growth, "sector": "Technology"}
    return rows, info


def test_expensive_vs_sector_needs_both_high_multiple_and_weak_growth():
    rows, info = _sector_rows()
    out = screens.run("expensive_sector", "india", info_fetch=lambda t: info.get(t, {}), rows=rows)
    picked = [r["symbol"] for r in out["results"]]
    # RICHGROW is dear but growing 40% a year (PEG 1.5), so it is not flagged.
    assert picked == ["RICH", "RICHSHRINK"]  # sorted by P/E vs sector, highest first
    top = out["results"][0]
    # Median of all 9 profitable Technology P/Es (18..23, 45, 60, 60) = 22.
    assert top["sector_pe"] == pytest.approx(22) and top["pe_vs_sector"] == pytest.approx(60 / 22)
    assert out["results"][1]["peg_calc"] is None  # shrinking earnings: no PEG


def test_expensive_vs_sector_skips_thin_sectors():
    rows, info = _sector_rows(n_peers=1)  # 4 profitable: below SECTOR_MIN_PEERS
    out = screens.run("expensive_sector", "india", info_fetch=lambda t: info.get(t, {}), rows=rows)
    assert out["results"] == []


def _custom(rules, **kw):
    return screens.run_custom("india", rules, info_fetch=lambda t: INFO.get(t, {}), rows=ROWS, **kw)


def test_custom_basic_ops_and_columns():
    out = _custom([{"field": "pe", "op": "between", "value": 30, "value2": 0}, {"field": "roe", "op": ">", "value": 14}],
                  columns=["dividend_yield", "nonsense"])
    assert [r["symbol"] for r in out["results"]] == ["QUAL", "DIV", "CHEAP"]  # sorted by first rule, high first
    assert [c["key"] for c in out["columns"]] == ["pe", "roe", "dividend_yield"]
    assert out["rules"][0] == "P/E 0–30" and out["scanned"] == 5
    asc = _custom([{"field": "pe", "op": ">", "value": 0}], sort="pe", descending=False)
    assert [r["symbol"] for r in asc["results"]][:2] == ["CHEAP", "DIV"]


def test_custom_top_bottom_percent():
    top = _custom([{"field": "roe", "op": "top", "value": 40}])  # 5 stocks with ROE -> best 2
    assert [r["symbol"] for r in top["results"]] == ["PRICEY", "QUAL"]
    bottom = _custom([{"field": "pe", "op": "bottom", "value": 20}])
    assert [r["symbol"] for r in bottom["results"]] == ["LOSS"]


def test_custom_sector_relative_and_sector_filter():
    rows, info = _sector_rows()
    rows.append({"symbol": "BANK", "name": "BANK", "type": "stock", "market_cap": 400, "price": 10})
    info["BANK.NS"] = {"trailingPE": 8, "sector": "Financial Services"}
    run = lambda rules, **kw: screens.run_custom("india", rules, info_fetch=lambda t: info.get(t, {}), rows=rows, **kw)
    cheap = run([{"field": "pe", "op": "below_sector", "value": None}])
    assert {r["symbol"] for r in cheap["results"]} == {"PEER0", "PEER1", "PEER2", "PEER3"}  # under the median 22 of 9
    assert "BANK" not in {r["symbol"] for r in cheap["results"]}  # too few peers for a median
    pricey = run([{"field": "pe", "op": "above_sector", "value": 2.5}], sectors=["technology"])
    assert {r["symbol"] for r in pricey["results"]} == {"RICH", "RICHGROW"}
    assert pricey["rules"] == ["Sector: Technology", "P/E above sector median × 2.5"]
    assert pricey["sectors"] == ["Financial Services", "Technology"] and pricey["scanned"] == 9


def test_custom_validation():
    for bad in ([], [{"field": "zzz", "op": ">", "value": 1}], [{"field": "pe", "op": "~", "value": 1}],
                [{"field": "pe", "op": ">", "value": None}], [{"field": "pe", "op": "between", "value": 1}],
                [{"field": "pe", "op": "top", "value": 0}], [{"field": "pe", "op": ">", "value": 1}] * 13):
        with pytest.raises(ValueError):
            screens.validate(bad)


def test_catalogue_and_derived_metrics():
    keys = [m["key"] for g in screens.catalogue() for m in g["metrics"]]
    assert len(keys) == len(set(keys)) and all(k in screens.LABELS for k in keys)
    m = screens.metrics({"trailingPE": 20, "marketCap": 1000, "freeCashflow": 50, "forwardEps": 12, "trailingEps": 10,
                         "targetMeanPrice": 120, "currentPrice": 100})
    assert m["earnings_yield"] == pytest.approx(5) and m["fcf_yield"] == pytest.approx(5)
    assert m["forward_eps_growth"] == pytest.approx(20) and m["target_upside"] == pytest.approx(20)


def test_custom_screen_api(monkeypatch, app_client):
    pytest.importorskip("fastapi.testclient")
    monkeypatch.setattr(screens, "_measure", lambda *a: [])  # validation still runs, no data fetched
    client = app_client()
    groups = client.get("/api/v1/screens/metrics")
    assert groups.status_code == 200 and groups.json()[0]["group"] == "Valuation"
    ok = client.post("/api/v1/screens/custom", json={"market": "us", "rules": [{"field": "pe", "op": "<", "value": 15}]})
    assert ok.status_code == 200 and ok.json()["market"] == "us"
    bad = client.post("/api/v1/screens/custom", json={"market": "us", "rules": [{"field": "pe", "op": "<"}]})
    assert bad.status_code == 400 and bad.json()["message"] == "P/E: enter a number"
    assert client.post("/api/v1/screens/custom", json={"market": "crypto", "rules": []}).status_code == 400


def test_ratios_dropped_when_accounts_and_price_use_different_currencies():
    info = {"trailingPE": 28, "priceToBook": 83, "enterpriseToEbitda": 4, "freeCashflow": 1.2e12, "marketCap": 2.2e12,
            "currency": "USD", "financialCurrency": "TWD"}
    m = screens.metrics(info)
    assert m["pe"] == 28 and m["pb"] is None and m["ev_ebitda"] is None and m["fcf_yield"] is None
    assert screens.metrics({**info, "financialCurrency": "USD"})["pb"] == 83
