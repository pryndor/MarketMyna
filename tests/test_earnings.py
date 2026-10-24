"""Tests for the earnings preview / review and the results-out message (offline)."""

from dataclasses import replace
from datetime import datetime, timezone

import pandas as pd
import pytest

from marketmyna.services import earnings as er


def _dates(rows):
    idx = pd.to_datetime([t for t, *_ in rows], utc=True).tz_convert("America/New_York").rename("Earnings Date")
    return pd.DataFrame({"EPS Estimate": [r[1] for r in rows], "Reported EPS": [r[2] for r in rows],
                         "Surprise(%)": [r[3] for r in rows]}, index=idx)


CLOSES = pd.Series([100, 101, 110, 108, 108, 95, 96], index=pd.DatetimeIndex(
    ["2026-07-28", "2026-07-29", "2026-07-30", "2026-07-31", "2026-10-20", "2026-10-21", "2026-10-22"]), dtype=float)


def fetch(_):
    return {"dates": _dates([
        ("2026-11-05 16:05:00-05:00", 0.48, None, None),         # upcoming, after the close
        ("2026-10-21 08:00:00-04:00", 0.50, 0.40, -20.0),       # before the open: same-day move
        ("2026-07-29 16:30:00-04:00", 0.45, 0.50, 11.1),        # after the close: next-day move
        ("2026-04-29 16:30:00-04:00", 1.90, 0.42, -77.9),       # yearly estimate vs quarterly actual, no prices
    ]), "closes": CLOSES, "sector": "Technology", "industry": "Software", "currency": "USD"}


def test_reaction_uses_the_right_session():
    out = er.build("ACME", "us", fetch=fetch, with_options=False, use_cache=False, estimates_fetch=lambda _: None,
                   now=datetime(2026, 10, 22, 21, tzinfo=timezone.utc))
    h = {e["date"]: e for e in out["history"]}
    assert h["2026-10-21"]["reaction"]["move"] == pytest.approx(95 / 108 * 100 - 100)  # 20 Oct close -> 21 Oct close
    assert h["2026-07-29"]["reaction"]["move"] == pytest.approx(110 / 101 * 100 - 100)  # 29 Jul close -> 30 Jul close
    assert h["2026-04-29"]["unusual"] and h["2026-04-29"]["reaction"] is None
    assert out["stats"]["beats"] == 1 and out["stats"]["misses"] == 1  # the unusual one is left out
    assert out["next"]["date"] == "2026-11-05" and out["days_to_next"] == 14
    assert out["latest"]["date"] == "2026-10-21"  # reported a day ago: "results are out"
    assert "Revenue vs consensus" in out["watch"] and any("deal wins" in w for w in out["watch"])


def test_results_line():
    out = er.build("ACME", "us", fetch=fetch, with_options=False, use_cache=False, estimates_fetch=lambda _: None,
                   now=datetime(2026, 10, 22, 21, tzinfo=timezone.utc))
    line = er.results_line("ACME", out)
    assert line.startswith("ACME results: EPS 0.40 vs 0.50 expected (missed by 20.0%)")
    assert "stock -12.0% on the day" in line
    old = er.build("ACME", "us", fetch=fetch, with_options=False, use_cache=False, estimates_fetch=lambda _: None,
                   now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert old["latest"] is None and er.results_line("ACME", old) is None


def test_no_data():
    out = er.build("ZZZ", "us", fetch=lambda _: {"dates": None, "closes": None}, with_options=False, use_cache=False, estimates_fetch=lambda _: None)
    assert out["available"] is False and out["history"] == [] and out["stats"] is None


class FakeDispatcher:
    def __init__(self):
        self.sent = []

    def send_all(self, message, title=None, purpose=None):
        self.sent.append((message, title))
        return {"telegram": True}


@pytest.fixture
def config(tmp_path, monkeypatch):
    from marketmyna.core.config import Config
    from marketmyna.services import calendar

    monkeypatch.setattr(calendar, "followed_symbols", lambda config=None, *a, **kw: {("ACME", "us"): []})
    monkeypatch.setattr(calendar, "_earnings_checked", {})
    return replace(Config(), db_path=tmp_path / "cal.db")


def test_results_message_sent_once(config):
    from marketmyna.services import calendar

    d = FakeDispatcher()
    now = datetime(2026, 10, 22, 21, tzinfo=timezone.utc)

    def build(symbol, market, **kw):
        return er.build(symbol, market, fetch=fetch, with_options=False, use_cache=False, estimates_fetch=lambda _: None, now=now)

    reports = lambda config, followed, day: [("ACME", "us")]  # noqa: E731
    lines = calendar.check_earnings_results(config, now, d, reports=reports, build=build)
    assert lines and "ACME results" in d.sent[0][0] and d.sent[0][1] == "Results are out"
    calendar._earnings_checked.clear()
    assert calendar.check_earnings_results(config, now, d, reports=reports, build=build) is None  # same day
    calendar._earnings_checked.clear()
    later = datetime(2026, 10, 24, 9, tzinfo=timezone.utc)  # a new day keeps the company marker
    assert calendar.check_earnings_results(config, later, d, reports=reports, build=build) is None
    assert len(d.sent) == 1
    calendar.save_settings(config, hidden_events="earnings")
    calendar._earnings_checked.clear()
    assert calendar.check_earnings_results(config, now, d, reports=reports, build=build) is None
