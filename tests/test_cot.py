"""CFTC commitments of traders (marketmyna/services/cot.py), offline."""

from datetime import date, timedelta

from marketmyna.services import cot


def _rows(code: str, nets: list[int], oi: int = 1000) -> list[dict]:
    start = date(2023, 10, 3)
    return [{
        "cftc_contract_market_code": code + " ",
        "report_date_as_yyyy_mm_dd": f"{start + timedelta(weeks=i)}T00:00:00.000",
        "open_interest_all": str(oi),
        "m_money_positions_long_all": str(500 + n),
        "m_money_positions_short_all": "500",
        "prod_merc_positions_long": "100",
        "prod_merc_positions_short": "300",
    } for i, n in enumerate(nets)]


def test_net_change_share_of_oi_and_3y_index():
    nets = list(range(0, 156)) + [150]  # this week a little under the 3-year high
    d = cot.build(fetch=lambda codes, since: _rows("088691", nets), use_cache=False)
    gold = d["items"][0]
    assert gold["label"] == "Gold" and len(d["items"]) == 1
    assert gold["managed_money_net"] == 150 and gold["net_change_1w"] == -5
    assert gold["net_pct_oi"] == 15.0 and gold["producer_net"] == -200
    assert gold["index_3y"] == 97 and "most long" in gold["reading"]
    assert len(gold["history"]) == 52 and d["as_of"] == gold["as_of"]


def test_short_history_has_no_index():
    d = cot.build(fetch=lambda codes, since: _rows("084691", [10, -20, 5]), use_cache=False)
    assert d["items"][0]["index_3y"] is None and d["items"][0]["reading"] == ""


def test_fetch_failure_returns_empty():
    def boom(codes, since):
        raise ConnectionError("cftc down")

    d = cot.build(fetch=boom, use_cache=False)
    assert d["items"] == [] and d["as_of"] is None


def test_readings():
    assert cot.reading(5).startswith("Funds near their most short")
    assert cot.reading(50) == "Fund positioning mid-range"
