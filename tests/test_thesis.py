"""Tests for the thesis tracker (offline)."""

from dataclasses import replace
from datetime import date

import pytest

from marketmyna.core.config import Config
from marketmyna.services import thesis


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(thesis, "_last_run", {})
    return replace(Config(), db_path=tmp_path / "t.db")


def _new(config, **kw):
    fields = {"statement": "Margins expand as the mix shifts to software",
              "pillars": [{"text": "Revenue growth >20%", "status": "on_track"}, {"text": "Margin up", "status": "watch"}],
              "risks": ["Price war"], "exit_below": 80.0, "target": 150.0, "conviction": "high"}
    fields.update(kw)
    return thesis.save(config, "ACME", "us", **fields)


def test_save_validates_and_updates(config):
    with pytest.raises(thesis.ThesisError):
        thesis.save(config, "ACME", "us", pillars=[])  # no statement
    with pytest.raises(thesis.ThesisError):
        _new(config, exit_below=200.0)  # exit above target
    with pytest.raises(thesis.ThesisError):
        _new(config, pillars=[{"text": "x", "status": "dunno"}])
    t = _new(config)
    assert t["pillars"][1]["status"] == "watch" and t["reviewed_at"] == date.today().isoformat()
    t = thesis.save(config, "ACME", "us", conviction="low")
    assert t["conviction"] == "low" and t["statement"].startswith("Margins")
    assert len(thesis.list_all(config)) == 1


def test_log_is_newest_first_and_counts_as_review(config):
    t = _new(config)
    thesis.add_log(config, t["id"], "Q3 revenue +22%", "strengthens", day="2026-01-10")
    t = thesis.add_log(config, t["id"], "CFO left", "weakens", "medium", day="2026-02-10")
    assert [e["note"] for e in t["log"]] == ["CFO left", "Q3 revenue +22%"]
    assert t["conviction"] == "medium" and t["reviewed_at"] == "2026-02-10"
    with pytest.raises(thesis.ThesisError):
        thesis.add_log(config, t["id"], "x", "maybe")
    assert thesis.add_log(config, 999, "x", "neutral") is None


def test_check_signals():
    t = {"exit_below": 80.0, "target": 150.0, "reviewed_at": "2026-01-01", "created_at": "2026-01-01",
         "pillars": [{"text": "a", "status": "broken"}, {"text": "b", "status": "on_track"}],
         "log": [{"impact": "weakens"}, {"impact": "weakens"}, {"impact": "neutral"}]}
    earnings = {"next": {"date": "2026-05-05"}, "days_to_next": 5,
                "consensus": {"momentum": {"label": "falling"}}}
    sig = {s["key"]: s for s in thesis.check(t, 75.0, earnings, today=date(2026, 4, 30))}
    assert sig["exit"]["tone"] == "down" and "broken" in sig["exit"]["text"]
    assert sig["target"]["tone"] == "info" and "is 100.0% above the price" in sig["target"]["text"]
    assert sig["pillars"]["tone"] == "down" and sig["log"]["tone"] == "warn"
    assert "119 days ago" in sig["review"]["text"] and "in 5 days" in sig["earnings"]["text"]
    assert sig["estimates"]["tone"] == "warn"
    ok = {s["key"] for s in thesis.check({**t, "pillars": [], "log": [], "reviewed_at": "2026-04-01"}, 120.0,
                                         today=date(2026, 4, 30))}
    assert ok == {"exit", "target"}


class FakeDispatcher:
    def __init__(self):
        self.sent = []

    def send_all(self, message, title=None, purpose=None):
        self.sent.append(message)
        return {"telegram": True}


def test_alerts_fire_once_and_rearm(config):
    _new(config)
    d = FakeDispatcher()
    prices = {"p": 79.0}
    run = lambda day: thesis.check_alerts(config, d, today=day, price=lambda s, m: prices["p"], force=True)  # noqa: E731
    assert run(date.today())[0].startswith("• ACME: price 79.00 is at or below your exit level")
    assert run(date.today()) == []  # once
    prices["p"] = 85.0  # back above exit + 3%: re-armed
    run(date.today())
    prices["p"] = 79.0
    assert len(run(date.today())) == 1
    prices["p"] = 151.0
    assert "reached your target" in run(date.today())[0]
    later = date.fromordinal(date.today().toordinal() + 95)
    prices["p"] = 151.0
    assert any("quarterly review" in line for line in run(later))
    assert run(later) == []  # the review reminder repeats monthly, not daily
    assert len(d.sent) == 4


def test_api_round_trip(config, app_client, monkeypatch):
    from marketmyna.api.deps import get_config_dep

    monkeypatch.setattr(thesis, "_price", lambda s, m: 100.0)
    monkeypatch.setattr(thesis, "_earnings", lambda s, m: None)
    client = app_client()
    client.app.dependency_overrides[get_config_dep] = lambda: config
    assert client.get("/api/v1/theses/ACME?market=us").json() == {"thesis": None}
    r = client.put("/api/v1/theses", json={"symbol": "acme", "market": "us", "statement": "Cheap and growing",
                                           "pillars": [{"text": "Growth", "status": "on_track"}], "target": 140})
    assert r.status_code == 200 and r.json()["thesis"]["symbol"] == "ACME" and r.json()["thesis"]["price"] == 100.0
    tid = r.json()["thesis"]["id"]
    assert client.put("/api/v1/theses", json={"symbol": "ACME", "market": "us", "conviction": "sure"}).status_code == 400
    r = client.put("/api/v1/theses", json={"symbol": "ACME", "market": "us", "clear_target": True})
    assert r.json()["thesis"]["target"] is None
    r = client.post(f"/api/v1/theses/{tid}/log", json={"note": "Beat", "impact": "strengthens"})
    assert r.json()["thesis"]["log"][0]["note"] == "Beat"
    assert client.post(f"/api/v1/theses/{tid}/reviewed").status_code == 200
    assert len(client.get("/api/v1/theses?check=true").json()) == 1
    assert client.delete(f"/api/v1/theses/{tid}").status_code == 204
    assert client.delete(f"/api/v1/theses/{tid}").status_code == 404
