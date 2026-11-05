import json
from datetime import date

import numpy as np
import pandas as pd

from marketmyna.services import stocks_to_watch as w


def _series(values, volumes=None):
    idx = pd.bdate_range("2025-01-01", periods=len(values))
    vols = volumes if volumes is not None else [1000.0] * len(values)
    return pd.Series(values, index=idx, dtype=float), pd.Series(vols, index=idx, dtype=float)


def test_measure_returns_and_volume():
    closes = list(np.linspace(100, 120, 260)) + [126.0]  # +5% today
    vols = [1000.0] * 260 + [3000.0]
    m = w.measure(*_series(closes, vols))
    assert round(m["r1d"], 1) == 5.0
    assert round(m["vol_day"], 1) == 3.0
    assert m["above_50"] and m["above_200"]
    assert m["price"] > m["high_20"]  # breaking out


def test_measure_needs_history():
    assert w.measure(*_series([100.0] * 10)) is None


def _item(symbol, closes, vols=None):
    m = w.measure(*_series(closes, vols))
    return ({"symbol": symbol, "name": symbol, "price": closes[-1], "change_percent": m["r1d"]}, m)


def test_day_boards_pick_heavy_volume_moves():
    flat = [100.0] * 260
    up = _item("UP", flat + [104.0], [1000.0] * 260 + [5000.0])
    quiet = _item("QUIET", flat + [104.0], [1000.0] * 261)
    boards = {b["key"]: b for b in w.day_boards([up, quiet])}
    assert [r["symbol"] for r in boards["up_volume"]["rows"]] == ["UP"]
    assert "today on 5.0× usual volume" in boards["up_volume"]["rows"][0]["why"]
    assert boards["up_volume"]["rows"][0]["watch_high"] == 100.0


def test_bounce_measures_the_sessions_before_today():
    closes = [100.0] * 255 + [100.0, 97.0, 95.0, 93.0, 92.0, 95.0]  # -8% over 4 sessions, +3.3% today
    boards = {b["key"]: b for b in w.day_boards([_item("B", closes)])}
    row = boards["bounce"]["rows"][0]
    assert "-8.0% over the 4 sessions before" in row["why"]


def test_month_trend_turning_up():
    closes = list(np.linspace(120, 90, 246)) + list(np.linspace(90, 105, 15))  # crossed up within the month
    boards = {b["key"]: b for b in w.month_boards([_item("T", closes)])}
    assert [r["symbol"] for r in boards["turning_up"]["rows"]] == ["T"]


def test_ideas_ignore_one_off_growth():
    closes = list(np.linspace(80, 120, 261))
    item = _item("G", closes)
    funda = {"G": {"earnings_growth": 900.0, "pe": 10.0, "roe": 20.0, "debt_equity": 0.2}}
    boards = {b["key"]: b for b in w.idea_boards([item], funda)}
    assert boards["growth_fair_price"]["rows"] == []
    funda["G"]["earnings_growth"] = 30.0
    boards = {b["key"]: b for b in w.idea_boards([item], funda)}
    assert [r["symbol"] for r in boards["growth_fair_price"]["rows"]] == ["G"]


def test_mark_new_against_last_week(tmp_path):
    def boards(*symbols):
        return [{"key": "k", "rows": [{"symbol": s} for s in symbols]}]

    first = boards("A", "B")
    w.mark_new("india", first, today=date(2026, 11, 1), store=tmp_path)
    assert not any(r["new"] for r in first[0]["rows"])  # nothing to compare with yet
    later = boards("A", "C")
    w.mark_new("india", later, today=date(2026, 11, 9), store=tmp_path)
    flags = {r["symbol"]: (r["new"], r["since"]) for r in later[0]["rows"]}
    assert flags["A"] == (False, "2026-11-01")
    assert flags["C"] == (True, "2026-11-09")
    saved = json.loads((tmp_path / "ideas-india.json").read_text())
    assert sorted(saved) == ["2026-11-01", "2026-11-09"]


class _Result:
    def __init__(self, text):
        self.text = text


class _Backend:
    calls = 0

    def generate(self, prompt, cfg, system_prompt=None):
        _Backend.calls += 1
        return _Result('{"summary": "Banks lead.", "stocks": [{"symbol": "A", "note": "Watch 110."}, '
                       '{"symbol": "ZZZ", "note": "not on the list"}]}')


def _board():
    return {"key": "k", "title": "T", "description": "D",
            "rows": [{"symbol": "A", "name": "A", "sector": "Banks", "price": 100, "why": "x",
                      "watch_high": 110.0, "watch_low": 90.0, "rsi": 55}]}


def test_notes_cached_and_symbols_checked(monkeypatch):
    from marketmyna.llm import backend_factory

    w._notes.clear()
    _Backend.calls = 0
    monkeypatch.setattr(backend_factory, "create_generation_backend", lambda config, tier="deep": _Backend())
    out = w.notes("india", "ideas", _board(), config=object())
    assert out["summary"] == "Banks lead." and out["stocks"] == {"A": "Watch 110."}
    w.notes("india", "ideas", _board(), config=object())
    assert _Backend.calls == 1  # second reader gets the shared note
