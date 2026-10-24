"""Tests for the Trade section: indicators, chart payload, alerts, journal (offline)."""

from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from marketmyna.core.config import Config
from marketmyna.trading import indicators as ind
from marketmyna.trading.alerts import AlertMonitor, measure, step
from marketmyna.trading.chart import build_chart, clamp_period
from marketmyna.trading.journal import r_multiple, stats, trade_pnl
from marketmyna.trading.market_hours import is_open

IST = ZoneInfo("Asia/Kolkata")


def _intraday(days=2, bars=75, start=100.0, drift=0.05):
    frames = []
    for d in range(days):
        idx = pd.date_range(datetime(2026, 9, 24 + d, 9, 15), periods=bars, freq="5min", tz=IST)
        close = start + d + np.arange(bars) * drift
        frames.append(pd.DataFrame({"Open": close - 0.1, "High": close + 0.3, "Low": close - 0.3,
                                    "Close": close, "Volume": np.full(bars, 1000.0)}, index=idx))
    return pd.concat(frames)


def _daily(n=60, start=100.0, step_=1.0):
    idx = pd.date_range(end=datetime(2026, 9, 24), periods=n, freq="B")
    close = start + np.arange(n) * step_
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close,
                         "volume": np.full(n, 1_000_000.0)}, index=idx)


class TestIndicators:
    def test_pivots(self):
        p = ind.pivots(110, 90, 100)
        assert p["P"] == 100 and p["R1"] == 110 and p["S1"] == 90 and p["R2"] == 120 and p["S2"] == 80

    def test_vwap_resets_each_session(self):
        df = _intraday().rename(columns=str.lower)
        v = ind.vwap(df)
        first_bar_day2 = df.index[75]
        typical = (df.loc[first_bar_day2, "high"] + df.loc[first_bar_day2, "low"] + df.loc[first_bar_day2, "close"]) / 3
        assert v.loc[first_bar_day2] == pytest.approx(typical)

    def test_supertrend_follows_trend(self):
        up = _daily(80).rename(columns=str.lower)
        _, direction = ind.supertrend(up)
        assert direction.iloc[-1] == 1
        down = _daily(80, start=200, step_=-1.0)
        _, direction = ind.supertrend(down)
        assert direction.iloc[-1] == -1

    def test_rsi_bounds(self):
        r = ind.rsi(pd.Series(100 + np.sin(np.arange(100)) * 5)).dropna()
        assert ((r >= 0) & (r <= 100)).all()
        assert ind.rsi(pd.Series(np.arange(1.0, 40.0))).iloc[-1] == 100

    def test_opening_range(self):
        df = _intraday().rename(columns=str.lower)
        rng = ind.opening_range(df, 15)
        day2 = df.iloc[75:78]
        assert rng == {"high": pytest.approx(day2["high"].max()), "low": pytest.approx(day2["low"].min())}


class TestChart:
    def test_payload(self):
        out = build_chart(_intraday(), "5m", ["vwap", "ema9", "supertrend"])
        assert len(out["bars"]) == 150
        # Exchange wall clock: first bar reads 09:15 whatever the viewer's timezone.
        assert datetime.fromtimestamp(out["bars"][0]["time"], ZoneInfo("UTC")).strftime("%H:%M") == "09:15"
        assert {"vwap", "ema9", "supertrend_up"} <= set(out["series"])
        assert out["pivots"]["P"] > 0 and out["opening_range"]
        assert len(out["series"]["ema9"]) == 150 - 8  # warm-up bars dropped

    def test_period_clamped(self):
        assert clamp_period("1m", "1y") == "5d"
        assert clamp_period("1d", None) == "1y"
        assert clamp_period("5m", "5d") == "5d"


class TestMarketHours:
    def test_sessions(self):
        assert is_open("india", datetime(2026, 9, 25, 10, 0, tzinfo=IST))
        assert not is_open("india", datetime(2026, 9, 25, 16, 0, tzinfo=IST))
        assert not is_open("india", datetime(2026, 9, 26, 10, 0, tzinfo=IST))  # Saturday
        assert is_open("crypto", datetime(2026, 9, 26, 3, 0, tzinfo=IST))


NOW = datetime(2026, 9, 25, 11, 0)


class TestAlertRules:
    def test_price_and_pct(self):
        q = {"price": 105.0, "change_percent": -3.2}
        assert measure("price_above", 100, q, None, "india", NOW)[1]
        assert not measure("price_below", 100, q, None, "india", NOW)[1]
        assert measure("pct_down", 3, q, None, "india", NOW)[1]
        assert not measure("pct_up", 3, q, None, "india", NOW)[1]

    def test_breakout_ignores_todays_bar(self):
        daily = _daily(30)  # last completed high = 130
        assert measure("high_breakout", 20, {"price": 131.0}, daily, "india", NOW.replace(tzinfo=IST))[1]
        assert not measure("high_breakout", 20, {"price": 129.0}, daily, "india", NOW.replace(tzinfo=IST))[1]

    def test_volume_spike(self):
        met = measure("volume_spike", 2, {"price": 1.0, "volume": 2_500_000}, _daily(30), "india", NOW)
        assert met[1] and met[0] == pytest.approx(2.5)

    def test_one_shot_fires_once(self):
        fire, upd = step({"armed": True, "repeat": False}, True, NOW)
        assert fire and upd["status"] == "triggered" and upd["trigger_count"] == 1

    def test_repeat_rearms_after_clearing(self):
        a = {"armed": True, "repeat": True, "cooldown_minutes": 0}
        fire, upd = step(a, True, NOW)
        assert fire and upd["armed"] is False
        a.update(upd)
        assert step(a, True, NOW + timedelta(minutes=1))[0] is False  # still above: no spam
        fire, upd = step(a, False, NOW + timedelta(minutes=2))
        assert not fire and upd["armed"] is True

    def test_repeat_cooldown(self):
        a = {"armed": True, "repeat": True, "cooldown_minutes": 30, "last_triggered_at": NOW}
        assert step(a, True, NOW + timedelta(minutes=5))[0] is False
        assert step(a, True, NOW + timedelta(minutes=31))[0] is True

    def test_expiry(self):
        assert step({"expires_at": NOW - timedelta(minutes=1)}, True, NOW) == (False, {"status": "expired"})


class FakeDispatcher:
    def __init__(self):
        self.sent = []

    def send_all(self, message, title=None, purpose=None):
        self.sent.append((title, message, purpose))
        return {"telegram": True}


class TestMonitor:
    def test_tick_fires_and_records(self, tmp_path):
        from marketmyna.storage import (
            DatabaseManager,
            PriceAlertEventRecord,
            PriceAlertRecord,
            get_db_url,
        )

        config = replace(Config(), db_path=tmp_path / "t.db")
        db = DatabaseManager.instance(get_db_url(config=config))
        with db.get_session() as s:
            s.add_all([
                PriceAlertRecord(symbol="TCS", market="india", kind="price_below", value=3000, note="buy point"),
                PriceAlertRecord(symbol="TCS", market="india", kind="price_above", value=5000),
                PriceAlertRecord(symbol="AAPL", market="us", kind="price_above", value=1),
            ])
        d = FakeDispatcher()
        quotes = []
        monitor = AlertMonitor(config, quote_fn=lambda s, m: quotes.append(s) or {"price": 2990.0, "change_percent": -1.0},
                               daily_fn=lambda s, m: _daily(), dispatcher=d)
        # 11:00 IST: India open, US closed.
        out = monitor.tick(now=datetime(2026, 9, 25, 11, 0, tzinfo=IST))
        assert [f["symbol"] for f in out["fired"]] == ["TCS"] and out["skipped_closed"] == 1
        assert quotes == ["TCS"]  # one quote per symbol, not per alert
        assert d.sent[0][2] == "alert" and "buy point" in d.sent[0][1] and "2,990.00" in d.sent[0][1]
        with db.get_session() as s:
            statuses = {r.value: r.status for r in s.query(PriceAlertRecord)}
            assert statuses[3000] == "triggered" and statuses[5000] == "active"
            assert s.query(PriceAlertEventRecord).count() == 1
        # Check now ignores market hours.
        assert monitor.tick(now=datetime(2026, 9, 25, 11, 0, tzinfo=IST), force=True)["skipped_closed"] == 0


class TestJournal:
    def test_pnl_and_r(self):
        t = {"side": "long", "quantity": 10, "entry_price": 100, "exit_price": 110, "stop": 95, "fees": 10}
        assert trade_pnl(t) == 90 and r_multiple(t) == pytest.approx(1.8)
        short = {**t, "side": "short", "exit_price": 90, "stop": 105}
        assert trade_pnl(short) == 90

    def test_stats(self):
        base = {"side": "long", "quantity": 1, "entry_price": 100, "fees": 0}
        trades = [
            {**base, "exit_price": 110, "exit_at": datetime(2026, 9, 1), "setup": "breakout"},
            {**base, "exit_price": 95, "exit_at": datetime(2026, 9, 2), "setup": "breakout"},
            {**base, "exit_price": 97, "exit_at": datetime(2026, 9, 3), "setup": "pullback"},
            {**base, "exit_price": None},
        ]
        s = stats(trades)
        assert s["closed"] == 3 and s["open"] == 1 and s["win_rate"] == pytest.approx(33.3)
        assert s["total_pnl"] == 2 and s["profit_factor"] == 1.25 and s["max_losing_streak"] == 2
        assert s["equity"][-1]["pnl"] == 2
        assert s["by_setup"][0] == {"setup": "breakout", "trades": 2, "win_rate": 50.0, "pnl": 5}


class TestApi:
    @pytest.fixture
    def client(self, tmp_path):
        testclient = pytest.importorskip("fastapi.testclient")
        from fastapi import FastAPI

        from marketmyna.api.deps import get_config_dep
        from marketmyna.api.v1.endpoints import trade

        config = replace(Config(), db_path=tmp_path / "t.db")
        app = FastAPI()
        app.include_router(trade.router, prefix="/api/v1")
        app.dependency_overrides[get_config_dep] = lambda: config
        app.state.alert_monitor = AlertMonitor(config, quote_fn=lambda s, m: {"price": 50.0},
                                               daily_fn=lambda s, m: _daily(), dispatcher=FakeDispatcher())
        return testclient.TestClient(app)

    def test_alert_lifecycle(self, client):
        r = client.post("/api/v1/trade/alerts", json={"symbol": "tcs", "market": "india", "kind": "price_below", "value": 60})
        assert r.status_code == 201 and r.json()["symbol"] == "TCS"
        assert "falls to or below 60" in r.json()["description"]
        assert client.post("/api/v1/trade/alerts", json={"symbol": "X", "kind": "nope", "value": 1}).status_code == 400
        fired = client.post("/api/v1/trade/alerts/check").json()["fired"]
        assert [f["symbol"] for f in fired] == ["TCS"]
        alert = client.get("/api/v1/trade/alerts").json()[0]
        assert alert["status"] == "triggered"
        assert client.patch(f"/api/v1/trade/alerts/{alert['id']}", json={"status": "active"}).json()["armed"] is True
        assert len(client.get("/api/v1/trade/alerts/events").json()) == 1
        assert client.delete(f"/api/v1/trade/alerts/{alert['id']}").status_code == 204
        assert client.get("/api/v1/trade/alerts").json() == []

    def test_journal(self, client):
        r = client.post("/api/v1/trade/journal", json={"symbol": "infy", "market": "india", "quantity": 10,
                                                        "entry_price": 1500, "stop": 1470, "setup": "breakout"})
        tid = r.json()["id"]
        assert r.json()["pnl"] is None
        closed = client.patch(f"/api/v1/trade/journal/{tid}", json={"exit_price": 1560, "fees": 20}).json()
        assert closed["pnl"] == 580 and closed["exit_at"]
        data = client.get("/api/v1/trade/journal?market=india").json()
        assert data["stats"]["win_rate"] == 100 and data["markets"] == ["india"]
        assert client.post("/api/v1/trade/journal", json={"symbol": "X", "quantity": 0, "entry_price": 1}).status_code == 422


def test_market_status_next_change():
    from marketmyna.trading.market_hours import status

    fri_evening = datetime(2026, 9, 25, 19, 0, tzinfo=IST)
    s = status("india", fri_evening)
    assert not s["open"] and s["next_change_label"] == "Mon 09:15"
    s = status("india", datetime(2026, 9, 25, 10, 0, tzinfo=IST))
    assert s["open"] and s["next_change_label"] == "Fri 15:30"
    s = status("india", datetime(2026, 9, 28, 8, 0, tzinfo=IST))
    assert not s["open"] and s["next_change_label"] == "Mon 09:15"
    assert status("crypto")["always_open"]


def test_quote_stream_ends_so_reloads_never_block(monkeypatch):
    testclient = pytest.importorskip("fastapi.testclient")
    from fastapi import FastAPI

    from marketmyna.api.v1.endpoints import trade
    from marketmyna.trading import alerts

    monkeypatch.setattr(trade, "STREAM_SECONDS", 0.5)
    monkeypatch.setattr(alerts, "_default_quote", lambda s, m: {"price": 101.5, "change_percent": 1.2})
    app = FastAPI()
    app.include_router(trade.router, prefix="/api/v1")
    with testclient.TestClient(app) as client:
        with client.stream("GET", "/api/v1/trade/stream?symbols=india:TCS&every=5") as r:
            body = "".join(r.iter_text())  # returns only because the stream closes itself
    assert body.startswith("retry: 1000") and '"price": 101.5' in body and '"open":' in body
