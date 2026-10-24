"""EIA weekly oil inventories (marketmyna/services/eia_stocks.py), offline."""

import pandas as pd

from marketmyna.services import eia_stocks


def _weekly(last_value: float, base: float = 400_000.0) -> pd.Series:
    idx = pd.date_range("2020-01-03", "2026-10-02", freq="W-FRI")
    s = pd.Series(base, index=idx)
    s.iloc[-2] = base + 2_000
    s.iloc[-1] = last_value
    return s


def test_level_change_and_five_year_gap():
    d = eia_stocks.build(fetch=lambda sid: _weekly(440_000.0), use_cache=False)
    crude = next(i for i in d["items"] if i["key"] == "WCESTUS1")
    assert crude["value"] == 440.0 and crude["change_1w"] == 38.0  # million barrels
    assert crude["avg_5y"] == 400.0 and crude["vs_avg_5y"] == 10.0
    assert crude["week_ending"] == "2026-10-02" == d["week_ending"]
    assert 50 <= len(crude["spark"]) <= 54


def test_refinery_use_in_points():
    s = _weekly(93.0, base=90.0)
    d = eia_stocks.build(fetch=lambda sid: s, use_cache=False)
    refinery = next(i for i in d["items"] if i["key"] == "WPULEUS3")
    assert refinery["value"] == 93.0 and refinery["vs_avg_5y"] == 3.0


def test_short_history_has_no_average_and_failures_drop_out():
    short = pd.Series([1000.0, 1100.0], index=pd.DatetimeIndex(["2026-09-25", "2026-10-02"]))

    def fetch(sid):
        if sid == "WCSSTUS1":
            raise ConnectionError("eia down")
        return short

    d = eia_stocks.build(fetch=fetch, use_cache=False)
    assert all(i["avg_5y"] is None for i in d["items"])
    assert "WCSSTUS1" not in {i["key"] for i in d["items"]} and len(d["items"]) == 5
