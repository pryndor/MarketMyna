"""Mutual-fund snapshots, report sections and notification routing."""

from datetime import datetime
from zoneinfo import ZoneInfo

from marketmyna.core.config import Config
from marketmyna.services.report import ReportPrefs, build_report


def test_report_funds_and_market_take():
    prefs = ReportPrefs(sections=["market", "funds"])
    funds = [{"name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "nav": 89.6034,
              "change_percent": -0.82, "return_1m": 2.1, "return_1y": 14.2}]
    overview = [{"name": "NIFTY 50", "price": 23095.4, "change_percent": 0.14}]
    _, text = build_report([], prefs, "en", overview=overview, funds=funds,
                           market_take="Indices edged higher.", now=datetime(2026, 9, 25, tzinfo=ZoneInfo("Asia/Kolkata")))
    assert "💼 Mutual funds" in text
    assert "NAV ₹89.6034 (-0.82%) · 1M +2.10% · 1Y +14.20%" in text
    assert "🤖 Indices edged higher." in text
    _, hindi = build_report([], prefs, "hi", funds=funds)
    assert "म्यूचुअल फंड" in hindi


def test_fund_snapshot(monkeypatch):
    from marketmyna.services import funds

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"meta": {"scheme_name": "Test Fund"},
                    "data": [{"date": "24-09-2026", "nav": "110"}, {"date": "23-09-2026", "nav": "100"},
                             {"date": "20-08-2026", "nav": "100"}, {"date": "20-09-2025", "nav": "88"}]}

    monkeypatch.setattr(funds.requests, "get", lambda *a, **k: Resp())
    snap = funds.fund_snapshot("123")
    assert snap["name"] == "Test Fund" and snap["nav"] == 110
    assert round(snap["change_percent"], 2) == 10.0
    assert round(snap["return_1m"], 2) == 10.0
    assert round(snap["return_1y"], 2) == 25.0


def test_routing_by_purpose():
    from marketmyna.notifiers.dispatcher import NotificationDispatcher

    cfg = Config(telegram_bot_token="t", telegram_chat_id="1", ntfy_url="https://ntfy.sh/x",
                 notification_system_error_channels=["telegram"])
    d = NotificationDispatcher(cfg)
    assert set(d.configured_channels()) == {"telegram", "ntfy"}
    assert set(d.configured_channels("report")) == {"telegram", "ntfy"}  # no route = all
    assert d.configured_channels("system_error") == ["telegram"]


def test_routing_api(tmp_path, login_as):
    from dataclasses import replace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from marketmyna.api.deps import get_config_dep
    from marketmyna.api.v1.endpoints import system_config

    config = replace(Config(), telegram_bot_token="t", telegram_chat_id="1", app_dir=tmp_path)
    config.save = lambda *a, **k: None
    app = FastAPI()
    app.include_router(system_config.router, prefix="/api/v1")
    app.dependency_overrides[get_config_dep] = lambda: config
    client = TestClient(app)
    login_as(client)
    body = client.get("/api/v1/system-config/notification-routing").json()
    assert body["channels"] == ["telegram"]
    assert body["routes"] == {"report": [], "alert": [], "system_error": []}
    resp = client.put("/api/v1/system-config/notification-routing", json={"alert": ["telegram"]})
    assert resp.json()["routes"]["alert"] == ["telegram"]
    assert client.put("/api/v1/system-config/notification-routing", json={"alert": ["pigeon"]}).status_code == 400
