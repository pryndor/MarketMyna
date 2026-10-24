"""FII / DII flows and participant positioning (src/services/india_flows.py), offline."""

from datetime import date

import pytest

from src.services import india_flows as f

CASH = [
    {"buyValue": "15506.73", "category": "DII", "date": "12-Oct-2026", "netValue": "3045.02", "sellValue": "12461.71"},
    {"buyValue": "12583.21", "category": "FII/FPI", "date": "12-Oct-2026", "netValue": "-1708.48", "sellValue": "14291.69"},
]

CSV = '''""Participant wise Open Interest (no. of contracts) in Equity Derivatives as on Oct 12, 2026"",,,,,,,,,,,,,,
Client Type,Future Index Long,Future Index Short,Future Stock Long,Future Stock Short       ,Option Index Call Long,Option Index Put Long,Option Index Call Short,Option Index Put Short,Option Stock Call Long,Option Stock Put Long,Option Stock Call Short,Option Stock Put Short,Total Long Contracts      ,Total Short Contracts
Client,301068,58139,3422666,189962,4925325,3121305,4537294,3854462,2265485,827417,1246148,1109963,14863266,10995968
FII,32268,328128,3559345,2873767,846118,1158491,1207904,572068,210233,338263,379383,201039,6144718,5562289
TOTAL,436228,436228,8106957,8106957,7380923,5474186,7380923,5474186,3407970,2247391,3407970,2247391,27053655,27053655
'''


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "_dir", lambda: tmp_path)


def test_cash_saved_and_served_when_nse_fails():
    d = f.cash(fetch=lambda: CASH)
    assert d["latest"]["date"] == "2026-10-12" and d["latest"]["fii"]["net"] == -1708.48
    assert d["month_to_date"]["dii"] == 3045.02 and d["stale"] is None

    def down():
        raise ConnectionError("blocked")

    d = f.cash(fetch=down)
    assert d["latest"]["fii"]["net"] == -1708.48 and d["stale"]


def test_history_sums():
    f.save_session({"date": "2026-09-30", "fii": {"net": 500.0}, "dii": {"net": -100.0}})
    f.save_session({"date": "2026-10-09", "fii": {"net": -200.0}, "dii": {"net": 400.0}})
    d = f.cash(fetch=lambda: CASH)
    assert d["sessions_saved"] == 3
    assert d["month_to_date"]["fii"] == pytest.approx(-1908.48) and d["month_to_date"]["sessions"] == 2
    assert d["five_day"]["fii"] == pytest.approx(-1408.48)


def test_participant_positioning():
    g = f._summarise(f.parse_participants(CSV))
    fii = g["FII"]
    assert fii["index_futures_net"] == 32268 - 328128 and fii["index_futures_long_pct"] == 9.0
    assert fii["index_options_net"] == (846118 - 1207904) - (1158491 - 572068)
    d = f.positioning(fetch=lambda day: CSV if day.weekday() < 5 else None, today=date(2026, 10, 13), sessions=5)
    assert d["sessions"] == 5 and d["date"] == "2026-10-13" and d["fii_long_pct_range"] == [9.0, 9.0]
