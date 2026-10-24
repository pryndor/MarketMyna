"""Valuation meter: multiples against the sector median (offline)."""

import pytest

from src.services import valuation


def _rows_and_info():
    rows, info = [], {}
    for i, pe in enumerate([10, 12, 14, 16, 18]):  # an ordinary sector, median P/E 14
        sym = f"P{i}"
        rows.append({"symbol": sym, "type": "stock", "market_cap": 1000 - i})
        info[f"{sym}.NS"] = {"sector": "Industrials", "trailingPE": pe, "priceToBook": 2.0,
                             "priceToSalesTrailing12Months": 1.0}
    rows.append({"symbol": "LOSS", "type": "stock", "market_cap": 10})
    info["LOSS.NS"] = {"sector": "Industrials", "trailingPE": -3, "priceToBook": 9}
    return rows, info


def _medians():
    rows, info = _rows_and_info()
    return valuation.sector_medians("india", info_fetch=lambda t: info.get(t, {}), rows=rows)


def test_sector_medians_skip_loss_makers():
    m = _medians()["Industrials"]
    assert m["n"] == 5 and m["pe"] == 14 and m["pb"] == 2.0 and m["ps"] == 1.0


@pytest.mark.parametrize("pe,pb,ps,expected", [
    (28, 4.0, 2.0, "above"),   # everything 2x the sector
    (14, 2.0, 1.0, "in_line"),
    (7, 1.0, 0.5, "below"),
])
def test_zone_from_combined_multiples(pe, pb, ps, expected):
    stock = {"sector": "Industrials", "trailingPE": pe, "priceToBook": pb, "priceToSalesTrailing12Months": ps,
             "earningsGrowth": 0.2, "revenueGrowth": 0.1, "returnOnEquity": 0.2, "debtToEquity": 50.0}
    out = valuation.meter("X", "india", info_fetch=lambda t: stock, medians=_medians())
    assert out["status"] == "ok" and out["zone"] == expected
    assert out["multiples"][0]["sector_median"] == 14


def test_growth_check_reports_peg_and_rules():
    stock = {"sector": "Industrials", "trailingPE": 20, "priceToBook": 2, "earningsGrowth": 0.25,
             "revenueGrowth": 0.12, "returnOnEquity": 0.22, "debtToEquity": 40.0}
    g = valuation.meter("X", "india", info_fetch=lambda t: stock, medians=_medians())["garp"]
    assert g["peg"] == pytest.approx(20 / 25)
    assert g["passed"] == g["total"] == 5


def test_unknown_sector_is_unavailable_with_reason():
    stock = {"sector": "Utilities", "trailingPE": 20}
    out = valuation.meter("X", "india", info_fetch=lambda t: stock, medians=_medians())
    assert out["status"] == "unavailable" and "Too few profitable Utilities" in out["reason"]


def test_crypto_is_unavailable():
    assert valuation.meter("BTC", "crypto")["status"] == "unavailable"


def test_missing_figure_is_not_counted_as_a_fail():
    stock = {"sector": "Industrials", "trailingPE": 20, "priceToBook": 2, "earningsGrowth": 0.25,
             "revenueGrowth": 0.12, "debtToEquity": 40.0}  # no returnOnEquity
    g = valuation.meter("X", "india", info_fetch=lambda t: stock, medians=_medians())["garp"]
    assert (g["passed"], g["total"], g["missing"]) == (4, 4, 1)
    assert [r["pass"] for r in g["rules"] if r["field"] == "roe"] == [None]
