"""Market valuation card (src/services/market_valuation.py), offline."""

from datetime import date, timedelta

import pytest

from src.services import market_valuation as mv

PAGE = """<table><tr><th>Date</th><th>Value</th></tr>
<tr class="odd"><td>Oct 12, 2026</td><td>
&#x2002;
&#x2020;26.64
</td></tr>
<tr class="even"><td>Sep 1, 2026</td><td>&#x2002;20.00</td></tr>
<tr class="odd"><td>Aug 1, 1989</td><td>&#x2002;10.00</td></tr>
<tr class="even"><td>Jan 1, 1871</td><td>&#x2002;30.00</td></tr></table>"""


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(mv, "_dir", lambda: tmp_path)


def test_parse_multpl_marks_estimates():
    rows = mv.parse_multpl(PAGE)
    assert rows[0] == ("2026-10-12", 26.64, True)
    assert rows[1] == ("2026-09-01", 20.0, False)
    assert len(rows) == 4


def test_us_series_percentiles_exclude_todays_reading():
    item = mv.us_series("s-p-500-pe-ratio", "P/E", "", mv.parse_multpl(PAGE))
    assert item["value"] == 26.64 and item["estimated"]
    assert item["percentile_all"] == round(2 / 3 * 100, 1)  # above 20 and 10, below 30
    assert item["percentile_1990"] == 100.0  # only Sep 2026 is since 1990
    assert item["since"] == "1871-01-01"


def test_us_falls_back_to_saved_copy():
    ok = mv._us(lambda slug: PAGE)
    assert len(ok["series"]) == 4 and not ok["series"][0]["stale"]

    def down(slug):
        raise RuntimeError("blocked")

    again = mv._us(down)
    assert len(again["series"]) == 4 and again["series"][0]["stale"]
    assert again["series"][0]["value"] == 26.64


def _nse(pe):
    return lambda: [{"index": "NIFTY 50", "pe": str(pe), "pb": "2.5", "dy": "1.5", "last": 22000},
                    {"index": "NIFTY BANK", "pe": "-", "pb": "1.6"}]


def test_india_builds_history_and_shows_percentile_after_a_year(monkeypatch):
    monkeypatch.setattr(mv, "MIN_HISTORY_DAYS", 3)
    start = date(2026, 1, 1)
    for i, pe in enumerate([18, 19, 20]):
        mv._india(_nse(pe), today=start + timedelta(days=i))
    first = mv._india(_nse(19.5), today=start + timedelta(days=3))
    nifty = first["indices"][0]
    assert [i["index"] for i in first["indices"]] == ["NIFTY 50"]  # Bank had no P/E
    assert nifty["history_days"] == 4 and nifty["history_from"] == "2026-01-01"
    assert nifty["pe_percentile"] == round(2 / 3 * 100, 1)


def test_india_year_ago_and_stale(monkeypatch):
    mv._india(_nse(25), today=date(2025, 10, 10))
    out = mv._india(_nse(19), today=date(2026, 10, 13))
    assert out["indices"][0]["pe_year_ago"] == 25

    def down():
        raise RuntimeError("403")

    stale = mv._india(down, today=date(2026, 10, 14))
    assert stale["stale"] and stale["as_of"] == "2026-10-13" and stale["indices"][0]["pe"] == 19
