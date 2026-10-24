"""New-idea screening, mutual-fund snapshots, report sections and notification routing."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.core.config import Config
from src.data.listings import _row
from src.services.ideas import find_ideas, screen
from src.services.report import ReportPrefs, build_report


def _stock(symbol, category="Technology", price=100.0, low=60.0, high=110.0, cap=5e11, change=1.0, volume=1e6):
    return _row(symbol, f"{symbol} Ltd", "india", "stock", category=category, price=price, low_52w=low,
                high_52w=high, market_cap=cap, change_percent=change, volume=volume, currency="INR")


ROWS = [
    _stock("GOOD"),                                  # uptrend, ~80% of range
    _stock("DOWN", price=65.0),                      # near 52w low -> dropped
    _stock("MICRO", cap=1e9),                        # micro cap -> dropped
    _stock("CRASH", change=-9.0),                    # crashing today -> dropped
    _stock("FARM", category="Agriculture"),
    _stock("OWNED"),                                 # already on the watchlist
]


def test_screen_filters_and_ranks():
    picked = [r["symbol"] for r in screen(ROWS, ["Technology"], exclude={"OWNED"})]
    assert picked == ["GOOD"]
    assert {r["symbol"] for r in screen(ROWS, [], exclude=set())} == {"GOOD", "FARM", "OWNED"}
    guessed = {**_stock("GUESS"), "category_inferred": True}
    assert screen([guessed], [], exclude=set()) == []


def test_find_ideas_rule_based_without_llm():
    tech = {"score": 12.0, "rsi": 58.0, "return_1m": 6.0, "return_3m": 12.0, "above_sma50_pct": 4.2,
            "above_sma200_pct": 11.0}
    ideas = find_ideas("india", ["Technology", "Agriculture"], count=2, exclude=["OWNED"], config=Config(),
                       rows=ROWS, check=lambda row: tech if row["symbol"] != "FARM" else None)
    assert [i["symbol"] for i in ideas] == ["GOOD"]
    assert "uptrend: +4.2% vs 50-day, +11.0% vs 200-day average" in ideas[0]["reason"]
    assert "RSI 58" in ideas[0]["reason"]
    assert "9% below 52-week high" in ideas[0]["reason"]


def test_find_ideas_uses_llm_choice(monkeypatch):
    from src.services import ideas as ideas_mod

    tech = {"score": 5.0, "rsi": 55.0, "return_1m": 3.0, "return_3m": 5.0, "above_sma50_pct": 2.0,
            "above_sma200_pct": 6.0}
    monkeypatch.setattr(ideas_mod, "_llm_pick",
                        lambda finalists, count, market, cats, config: [{**finalists[-1], "reason": "AI says so"}])
    ideas = find_ideas("india", [], count=1, config=Config(), rows=ROWS, check=lambda row: tech)
    assert ideas[0]["reason"] == "AI says so"


def test_report_ideas_funds_and_market_take():
    prefs = ReportPrefs(sections=["market", "ideas", "funds"], ideas_market="india", ideas_categories=["Technology"])
    ideas = [{"symbol": "GOOD", "name": "Good Ltd", "market": "india", "price": 100.0, "change_percent": 1.0,
              "reason": "3 of 5 indicators bullish"}]
    funds = [{"name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "nav": 89.6034,
              "change_percent": -0.82, "return_1m": 2.1, "return_1y": 14.2}]
    overview = [{"name": "NIFTY 50", "price": 23095.4, "change_percent": 0.14}]
    _, text = build_report([], prefs, "en", overview=overview, funds=funds, ideas=ideas,
                           market_take="Indices edged higher.", now=datetime(2026, 9, 25, tzinfo=ZoneInfo("Asia/Kolkata")))
    assert "New ideas to research" not in text and "GOOD" not in text  # no stock ideas of our own
    assert "💼 Mutual funds" in text
    assert "NAV ₹89.6034 (-0.82%) · 1M +2.10% · 1Y +14.20%" in text
    assert "🤖 Indices edged higher." in text
    _, hindi = build_report([], prefs, "hi", funds=funds, ideas=ideas)
    assert "शोध के लिए नए शेयर" not in hindi and "म्यूचुअल फंड" in hindi


def test_fund_snapshot(monkeypatch):
    from src.services import funds

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
    from src.notifiers.dispatcher import NotificationDispatcher

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

    from api.deps import get_config_dep
    from api.v1.endpoints import system_config

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


def test_trend_check_rules(monkeypatch):
    import pandas as pd

    from src.agent import agents
    from src.services import ideas as ideas_mod

    def fetcher_for(closes):
        class F:
            def get_history(self, symbol, period="1y"):
                return pd.DataFrame({"close": closes})
        return lambda market: F()

    steady = [100 * (1.0012 ** i) + (1.5 if i % 2 else -1.5) for i in range(250)]  # gentle uptrend
    monkeypatch.setattr(agents, "_resolve_fetcher", fetcher_for(steady))
    tech = ideas_mod.technical_check({"symbol": "X", "market": "us"})
    assert tech is not None and tech["return_3m"] > 0 and 45 <= tech["rsi"] <= 72

    falling = [200 * (0.998 ** i) for i in range(250)]
    monkeypatch.setattr(agents, "_resolve_fetcher", fetcher_for(falling))
    assert ideas_mod.technical_check({"symbol": "Y", "market": "us"}) is None
