"""Central-bank policy rates (src/services/central_banks.py), offline."""

from datetime import date

import pytest

from src.services import central_banks as cb

CSV = """FREQ,REF_AREA,TITLE,TIME_PERIOD,OBS_VALUE
D,US, Central bank policy rates - United States - Daily,2025-09-01,4.375
D,US, Central bank policy rates - United States - Daily,2025-09-18,4.125
D,US, Central bank policy rates - United States - Daily,2026-09-17,3.875
D,US, Central bank policy rates - United States - Daily,2026-10-06,3.875
D,IN, Central bank policy rates - India - Daily,2025-06-06,5.5
D,IN, Central bank policy rates - India - Daily,2026-07-23,5.5
D,PH, Central bank policy rates - Philippines - Daily,2026-10-04,NaN
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "_dir", lambda: tmp_path)
    monkeypatch.setattr(cb, "_inflation", lambda year: {"USA": 3.0})
    monkeypatch.setattr(cb, "_rbi_repo", lambda: None)
    cb._state.clear()
    yield
    cb._state.clear()


def test_parse_skips_gaps():
    areas = cb.parse(CSV)
    assert set(areas) == {"US", "IN"}
    assert areas["US"]["name"] == "United States" and len(areas["US"]["points"]) == 4


def test_last_move_year_change_and_real_rate():
    d = cb.build(fetch=lambda start: CSV, today=date(2026, 10, 13))
    us = next(r for r in d["rows"] if r["area"] == "US")
    assert us["rate"] == 3.875 and us["previous"] == 4.125 and us["direction"] == "cut"
    assert us["last_change"] == "2026-09-17"
    assert us["change_1y"] == -0.25  # vs 4.125 on 2025-09-18
    assert us["real_rate"] == 0.88
    india = next(r for r in d["rows"] if r["area"] == "IN")
    assert india["previous"] is None and india["direction"] is None
    assert [r["area"] for r in d["rows"]][:2] == ["IN", "US"]  # India first


def test_rbi_reading_newer_than_bis_marks_unknown_change_date(monkeypatch):
    monkeypatch.setattr(cb, "_rbi_repo", lambda: ("2026-10-13", 5.75))
    india = next(r for r in cb.build(fetch=lambda s: CSV, today=date(2026, 10, 13))["rows"] if r["area"] == "IN")
    assert india["rate"] == 5.75 and india["direction"] == "hike" and india["previous"] == 5.5
    assert india["last_change"] is None and india["changed_between"] == ["2026-07-23", "2026-10-13"]


def test_rbi_same_rate_keeps_bis_history(monkeypatch):
    monkeypatch.setattr(cb, "_rbi_repo", lambda: ("2026-10-13", 5.5))
    india = next(r for r in cb.build(fetch=lambda s: CSV, today=date(2026, 10, 13))["rows"] if r["area"] == "IN")
    assert india["rate"] == 5.5 and "changed_between" not in india and india["as_of"] == "2026-10-13"


def test_stale_copy_when_bis_fails(tmp_path):
    cb.build(fetch=lambda s: CSV, today=date(2026, 10, 13))
    cb._state.clear()
    import json

    saved = json.loads((tmp_path / "policy-rates.json").read_text(encoding="utf-8"))
    saved["fetched"] = 0
    (tmp_path / "policy-rates.json").write_text(json.dumps(saved), encoding="utf-8")

    def down(start):
        raise RuntimeError("timeout")

    d = cb.build(fetch=down, today=date(2026, 10, 13))
    assert d["stale"] and len(d["rows"]) == 2
