"""IMF country macro (marketmyna/services/country_macro.py), offline."""

import json
from datetime import date

import pytest

from marketmyna.services import country_macro as cm


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "_dir", lambda: tmp_path)
    cm._state.clear()
    yield
    cm._state.clear()


def _fetch(calls=None):
    def fetch(path):
        if calls is not None:
            calls.append(path)
        if path == "countries":
            return {"countries": {"IND": {"label": "India"}, "USA": {"label": "United States"}, "ZZZ": {}}}
        return {"values": {path: {"IND": {"2025": 7.8, "2026": 7.0, "2027": 7.1, "2021": 9.7}, "USA": {"2026": 2.3}}}}
    return fetch


def test_build_three_years_and_unknown_codes_dropped():
    d = cm.build(["ind", "usa", "XXX"], fetch=_fetch(), today=date(2026, 10, 13))
    assert d["years"] == [2025, 2026, 2027] and d["projection_from"] == 2026
    ind, usa = d["rows"]
    assert ind["NGDP_RPCH"] == [7.8, 7.0, 7.1] and ind["fiscal_year"]
    assert usa["PCPIPCH"] == [None, 2.3, None]
    assert [c["code"] for c in d["countries"]] == ["IND", "USA"]  # unlabeled codes left out
    assert [p["year"] for p in ind["NGDP_RPCH_trend"]] == [2021, 2025, 2026, 2027]


def test_cached_for_a_day_then_stale_copy_on_failure(tmp_path):
    calls = []
    cm.build(None, fetch=_fetch(calls))
    n = len(calls)
    cm.build(None, fetch=_fetch(calls))
    assert len(calls) == n  # memory cache

    saved = json.loads((tmp_path / "weo.json").read_text(encoding="utf-8"))
    saved["fetched"] -= 2 * 86400
    (tmp_path / "weo.json").write_text(json.dumps(saved), encoding="utf-8")
    cm._state.clear()

    def down(path):
        raise RuntimeError("403")

    d = cm.build(["IND"], fetch=down)
    assert d["stale"] and d["rows"][0]["NGDP_RPCH"][0] == 7.8


def test_no_data_at_all_raises():
    def down(path):
        raise RuntimeError("403")

    with pytest.raises(RuntimeError):
        cm.build(["IND"], fetch=down)
