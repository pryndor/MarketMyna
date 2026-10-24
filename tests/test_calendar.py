"""Tests for the event calendar and its daily reminder (offline)."""

from dataclasses import replace
from datetime import date, datetime

import pytest

from src.core.config import Config
from src.services import calendar

TODAY = date(2026, 9, 30)

CALS = {
    "TCS.NS": {"earnings": date(2026, 10, 1), "ex_dividend": date(2026, 10, 20), "dividend": None, "eps_estimate": 34.5},
    "AAPL": {"earnings": date(2026, 10, 30), "ex_dividend": date(2026, 9, 29), "dividend": date(2026, 10, 1)},
    "INFY.NS": {"earnings": date(2027, 1, 15)},
}


def fetch(ticker):
    if ticker == "BOOM":
        raise RuntimeError("down")
    return CALS.get(ticker, {})


SYMBOLS = {("TCS", "india"): ["Portfolio: Main"], ("AAPL", "us"): ["Watchlist: Tech"],
           ("INFY", "india"): ["Watchlist: Tech"], ("BOOM", "us"): ["Watchlist: Tech"]}


def test_collect_window_order_and_fields():
    events = calendar.collect(SYMBOLS, TODAY, 30, fetch)
    got = [(e["symbol"], e["kind"], e["date"]) for e in events]
    # same day: earnings before dividends
    assert got == [("TCS", "earnings", "2026-10-01"), ("AAPL", "dividend", "2026-10-01"),
                   ("TCS", "ex_dividend", "2026-10-20"), ("AAPL", "earnings", "2026-10-30")]
    tcs = events[0]
    assert tcs["days_away"] == 1 and tcs["eps_estimate"] == 34.5 and tcs["followed_in"] == ["Portfolio: Main"]
    assert "eps_estimate" not in events[1]


def test_as_date_handles_yahoo_shapes():
    assert calendar._as_date([date(2026, 10, 1), date(2026, 10, 5)]) == date(2026, 10, 1)
    assert calendar._as_date(datetime(2026, 10, 1, 9)) == date(2026, 10, 1)
    assert calendar._as_date("2026-10-01") == date(2026, 10, 1)
    assert calendar._as_date([]) is None and calendar._as_date("n/a") is None


def test_digest_text():
    text = calendar.digest(calendar.collect(SYMBOLS, TODAY, 1, fetch))
    assert text.startswith("📅 2 upcoming events")
    assert "TCS: Earnings tomorrow (EPS est. 34.50)" in text


class FakeDispatcher:
    def __init__(self):
        self.sent = []

    def send_all(self, message, title=None, purpose=None):
        self.sent.append((message, title, purpose))
        return {"telegram": True}


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar, "followed_symbols", lambda config=None, *a, **kw: SYMBOLS)
    return replace(Config(), db_path=tmp_path / "cal.db")


def test_reminder_once_a_day_after_hour(config):
    d = FakeDispatcher()
    early = datetime(2026, 9, 30, 7, 0)
    assert calendar.check_reminders(config, early, d, fetch, economic_fetch=None) is None and not d.sent
    out = calendar.check_reminders(config, datetime(2026, 9, 30, 8, 5), d, fetch, economic_fetch=None)
    assert len(out["events"]) == 2 and len(d.sent) == 1 and d.sent[0][2] == "alert"
    assert calendar.check_reminders(config, datetime(2026, 9, 30, 20, 0), d, fetch, economic_fetch=None) is None
    assert len(d.sent) == 1
    assert calendar.load_settings(config)["notified_day"] == "2026-09-30"


def test_reminder_respects_off_and_force(config):
    d = FakeDispatcher()
    calendar.save_settings(config, notify=False)
    assert calendar.check_reminders(config, datetime(2026, 9, 30, 9), d, fetch, economic_fetch=None) is None
    out = calendar.check_reminders(config, datetime(2026, 9, 30, 9), d, fetch, force=True, economic_fetch=None)
    assert out["events"] and len(d.sent) == 1
    assert calendar.load_settings(config)["notified_day"] is None  # a test send is not the daily digest


def test_no_events_marks_day_without_sending(config, monkeypatch):
    monkeypatch.setattr(calendar, "followed_symbols", lambda config=None, *a, **kw: {})
    d = FakeDispatcher()
    out = calendar.check_reminders(config, datetime(2026, 9, 30, 9), d, fetch, economic_fetch=None)
    assert out["events"] == [] and not d.sent
    assert calendar.load_settings(config)["notified_day"] == "2026-09-30"


def test_api_settings_validation(config, app_client):
    from api.deps import get_config_dep

    client = app_client()
    client.app.dependency_overrides[get_config_dep] = lambda: config
    resp = client.put("/api/v1/calendar/settings", json={"days_before": 3, "timezone": "America/New_York"})
    assert resp.json() == {"notify": True, "days_before": 3, "notify_hour": 8, "timezone": "America/New_York",
                           "hidden_events": [], "sources": None, "extra_symbols": []}
    resp = client.put("/api/v1/calendar/settings", json={"hidden_events": ["us_ppi", "dividend", "us_ppi"]})
    assert resp.json()["hidden_events"] == ["dividend", "us_ppi"]
    assert client.put("/api/v1/calendar/settings", json={"hidden_events": ["moon"]}).status_code == 400
    assert client.put("/api/v1/calendar/settings", json={"timezone": "Mars/Base"}).status_code == 400
    assert client.put("/api/v1/calendar/settings", json={"notify_hour": 30}).status_code == 422


def test_reminder_skips_hidden_event_types(config):
    d = FakeDispatcher()
    calendar.save_settings(config, hidden_events="earnings,fed")
    seen = {}

    def econ(start, days, tz, followed, off):
        seen["off"] = off
        return []

    out = calendar.check_reminders(config, datetime(2026, 9, 30, 9), d, fetch, economic_fetch=econ)
    assert [e["kind"] for e in out["events"]] == ["dividend"]  # TCS earnings tomorrow is hidden
    assert seen["off"] == {"earnings", "fed"}


def test_release_results_sent_once_and_respect_hidden(config):
    from zoneinfo import ZoneInfo

    events = [{"key": "us_cpi", "title": "US inflation (CPI)", "region": "US", "date": "2026-10-14",
               "time": "07:30", "tz": "America/Chicago"},
              {"key": "us_ppi", "title": "US producer prices (PPI)", "region": "US", "date": "2026-10-14",
               "time": "07:30", "tz": "America/Chicago"}]
    pts = {"us_cpi": {"text": "3.9% YoY in Sep", "period": "2026-09-01", "value": 3.9, "prev": 3.7},
           "us_ppi": {"text": "5.0% YoY in Sep", "period": "2026-09-01", "value": 5.0, "prev": 5.4}}
    calendar.save_settings(config, hidden_events="us_ppi")
    d = FakeDispatcher()
    at = datetime(2026, 10, 14, 9, 0, tzinfo=ZoneInfo("America/Chicago"))
    done = calendar.check_results(config, at, d, lambda day: [dict(e) for e in events], lambda: pts)
    assert [e["key"] for e in done] == ["us_cpi"] and len(d.sent) == 1
    assert "US inflation (CPI) is out: 3.9% YoY in Sep" in d.sent[0][0] and "Your US stocks: AAPL, BOOM" in d.sent[0][0]
    assert calendar.check_results(config, at, d, lambda day: [dict(e) for e in events], lambda: pts) is None
    assert len(d.sent) == 1


CATALOG = {"portfolios": [{"id": 1, "name": "Main", "symbols": [{"symbol": "TCS", "market": "india"}]}],
           "watchlists": [{"id": 7, "name": "Tech", "symbols": [{"symbol": "AAPL", "market": "us"},
                                                                 {"symbol": "BTC", "market": "crypto"}]}]}


def test_followed_symbols_lists_and_extras():
    every = calendar.followed_symbols(catalog=CATALOG)
    assert set(every) == {("TCS", "india"), ("AAPL", "us")}  # crypto has no calendar
    only = calendar.followed_symbols(sources=["w:7"], extra=[{"symbol": "infy", "market": "india"}], catalog=CATALOG)
    assert only == {("AAPL", "us"): ["Watchlist: Tech"], ("INFY", "india"): ["Added for events"]}
    assert calendar.followed_symbols(sources=[], catalog=CATALOG) == {}
    assert [s["id"] for s in calendar.list_sources(catalog=CATALOG)] == ["p:1", "w:7"]


def test_custom_event_repeats():
    monthly = {"title": "SIP", "date": "2026-01-31", "repeat": "monthly"}
    assert calendar.occurrences(monthly, date(2026, 2, 1), 60) == [date(2026, 2, 28), date(2026, 3, 31)]
    yearly = {"title": "AGM", "date": "2024-02-29", "repeat": "yearly"}
    assert calendar.occurrences(yearly, date(2026, 1, 1), 365) == [date(2026, 2, 28)]
    once = {"title": "IPO", "date": "2026-10-03", "repeat": "none"}
    assert calendar.occurrences(once, TODAY, 7) == [date(2026, 10, 3)]
    rows = calendar.custom_events([once, monthly], TODAY, 7)
    assert [(r["title"], r["days_away"]) for r in rows] == [("SIP", 0), ("IPO", 3)]  # the 31st falls on 30 Sep


def test_named_alert_runs_once_with_its_own_stocks_and_types(config):
    d = FakeDispatcher()
    a = calendar.save_alert(config, None, name="India dividends", sources=[], event_types=["ex_dividend", "custom"],
                            symbols=[{"symbol": "tcs", "market": "india"}], days_before=30, notify_hour=9)
    calendar.save_custom(config, None, title="SIP day", date="2026-10-05", repeat="monthly")
    assert calendar.check_event_alerts(config, datetime(2026, 9, 30, 8), d, fetch, economic_fetch=None) == []
    assert calendar.check_event_alerts(config, datetime(2026, 9, 30, 9), d, fetch, economic_fetch=None) == ["India dividends"]
    text, title, _ = d.sent[0]
    assert title == "India dividends" and "SIP day" in text and "TCS: Ex-dividend" in text
    assert "Earnings" not in text and "AAPL" not in text  # only this alert's stocks and types
    assert calendar.check_event_alerts(config, datetime(2026, 9, 30, 20), d, fetch, economic_fetch=None) == []
    assert calendar.save_alert(config, a["id"], notify_hour=21)["notified_day"] is None  # edited: may go again
    assert calendar.delete_alert(config, a["id"]) and calendar.list_alerts(config) == []


def test_api_alerts_and_custom_events(config, app_client):
    from api.deps import get_config_dep

    client = app_client()
    client.app.dependency_overrides[get_config_dep] = lambda: config
    r = client.post("/api/v1/calendar/alerts", json={"name": "US tech", "event_types": ["earnings"], "sources": ["w:7"]})
    assert r.status_code == 201 and r.json()["event_types"] == ["earnings"]
    aid = r.json()["id"]
    back = client.put(f"/api/v1/calendar/alerts/{aid}", json={"all_types": True, "all_lists": True}).json()
    assert back["event_types"] is None and back["sources"] is None
    assert client.post("/api/v1/calendar/alerts", json={"event_types": ["moon"]}).status_code == 400
    assert client.put("/api/v1/calendar/alerts/999", json={"name": "x"}).status_code == 404
    r = client.post("/api/v1/calendar/custom-events", json={"title": " SIP ", "date": "2026-10-05", "repeat": "monthly"})
    assert r.status_code == 201 and r.json()["title"] == "SIP"
    assert client.post("/api/v1/calendar/custom-events", json={"title": "x", "date": "2026-02-30"}).status_code == 400
    assert client.post("/api/v1/calendar/custom-events", json={"title": "x", "date": "2026-02-03", "repeat": "daily"}).status_code == 400
    assert client.delete(f"/api/v1/calendar/custom-events/{r.json()['id']}").status_code == 204
    assert client.delete(f"/api/v1/calendar/alerts/{aid}").status_code == 204
    s = client.put("/api/v1/calendar/settings", json={"sources": ["w:7"], "extra_symbols": [{"symbol": "infy", "market": "india"}]}).json()
    assert s["sources"] == ["w:7"] and s["extra_symbols"] == [{"symbol": "INFY", "market": "india"}]
    assert client.put("/api/v1/calendar/settings", json={"all_lists": True}).json()["sources"] is None
