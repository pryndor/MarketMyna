"""Tests for the trade scanner, saved scans and daily risk rules (offline)."""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from src.core.config import Config
from src.trading.risk import compute
from src.trading.scanner import SCANS, BarCache, Target, evaluate, run_saved_scans, run_scan

IST = ZoneInfo("Asia/Kolkata")


def _daily(n=260, start=100.0, step=0.2):
    idx = pd.date_range(end=datetime(2026, 9, 25), periods=n, freq="B")
    close = start + np.arange(n) * step
    return pd.DataFrame({"open": close - 0.1, "high": close + 0.5, "low": close - 0.5, "close": close,
                         "volume": np.full(n, 1000.0)}, index=idx)


def _with_today(df, **today):
    df = df.copy()
    for k, v in today.items():
        df.iloc[-1, df.columns.get_loc(k)] = v
    return df


class TestEvaluate:
    def test_gap_volume_and_52w_high(self):
        d = _daily()
        prev = d["close"].iloc[-2]
        d = _with_today(d, open=prev * 1.03, high=prev * 1.06, low=prev * 1.03, close=prev * 1.05, volume=3000)
        metrics, hits = evaluate(d, None, list(SCANS), {})
        assert {"gap_up", "big_mover", "volume_surge", "high_52w", "breakout_20d", "uptrend", "open_low"} <= set(hits)
        assert "gap_down" not in hits and "low_52w" not in hits
        assert metrics["gap_percent"] == pytest.approx(3.0)
        assert metrics["volume_ratio"] == pytest.approx(3.0)

    def test_params_change_thresholds(self):
        d = _daily()
        prev = d["close"].iloc[-2]
        d = _with_today(d, open=prev * 1.03, close=prev * 1.03, high=prev * 1.03, low=prev * 1.02)
        assert "gap_up" not in evaluate(d, None, ["gap_up"], {"gap_up": 5})[1]
        assert "gap_up" in evaluate(d, None, ["gap_up"], {"gap_up": 2})[1]

    def test_only_requested_scans(self):
        d = _daily()
        prev = d["close"].iloc[-2]
        d = _with_today(d, open=prev * 1.03, close=prev * 1.05, high=prev * 1.06, low=prev * 1.03)
        assert set(evaluate(d, None, ["gap_up"], {})[1]) == {"gap_up"}

    def test_inside_day_and_nr7(self):
        d = _daily()
        c = d["close"].iloc[-2]
        d = _with_today(d, open=c, high=c + 0.1, low=c - 0.1, close=c)
        hits = evaluate(d, None, ["inside_day", "nr7"], {})[1]
        assert set(hits) == {"inside_day", "nr7"}

    def test_intraday_orb_and_vwap(self):
        d = _daily()
        idx = pd.date_range(datetime(2026, 9, 25, 9, 15), periods=30, freq="5min", tz=IST)
        close = np.full(30, 100.0)
        close[-1] = 104.0  # breaks out on the last bar
        intra = pd.DataFrame({"open": close, "high": close + 0.2, "low": close - 0.2, "close": close,
                              "volume": np.full(30, 500.0)}, index=idx)
        hits = evaluate(d, intra, ["orb_up", "vwap_cross_up", "orb_down"], {})[1]
        assert set(hits) == {"orb_up", "vwap_cross_up"}


class TestRunScan:
    def test_batched_fetch_match_all_and_failures(self):
        calls = []
        up = _daily()
        prev = up["close"].iloc[-2]
        up = _with_today(up, open=prev * 1.03, close=prev * 1.05, high=prev * 1.06, low=prev * 1.03, volume=5000)

        def fetch(tickers, interval, period):
            calls.append((tuple(tickers), interval))
            return {"AAA.NS": up, "BBB.NS": _daily()}

        cache = BarCache(fetch)
        targets = [Target("AAA", "india"), Target("BBB", "india"), Target("CCC", "india")]
        out = run_scan(targets, ["gap_up", "volume_surge"], match="all", cache=cache)
        assert [r["symbol"] for r in out["rows"]] == ["AAA"]
        assert out["failed"] == ["CCC"] and out["scanned"] == 2
        assert calls == [(("AAA.NS", "BBB.NS", "CCC.NS"), "1d")]  # one batched request
        run_scan(targets, ["gap_up"], cache=cache)
        assert len(calls) == 2  # only the missing ticker is re-requested
        assert calls[1] == (("CCC.NS",), "1d")


class FakeDispatcher:
    def __init__(self):
        self.sent = []

    def send_all(self, message, title=None, purpose=None):
        self.sent.append((title, message, purpose))
        return {"telegram": True}


def test_saved_scan_notifies_only_new_matches(tmp_path, monkeypatch):
    from src.storage import DatabaseManager, SavedScanRecord, get_db_url

    config = replace(Config(), db_path=tmp_path / "t.db")
    with DatabaseManager.instance(get_db_url(config=config)).get_session() as s:
        s.add(SavedScanRecord(name="Gappers", universe={"sources": ["custom"], "market": "india", "symbols": ["AAA"]},
                              scans=["gap_up"], notify=True, interval_minutes=15))
    up = _daily()
    prev = up["close"].iloc[-2]
    up = _with_today(up, open=prev * 1.03, close=prev * 1.04, high=prev * 1.05, low=prev * 1.03)
    cache = BarCache(lambda t, i, p: {"AAA.NS": up})
    d = FakeDispatcher()
    now = datetime(2026, 9, 25, 10, 0, tzinfo=IST)
    first = run_saved_scans(config, now=now, dispatcher=d, cache=cache)
    assert first[0]["new"] == ["AAA"] and len(d.sent) == 1 and "Gappers" in d.sent[0][0]
    # Not due yet 5 minutes later; due after 15 but AAA was already sent today.
    assert run_saved_scans(config, now=datetime(2026, 9, 25, 10, 5, tzinfo=IST), dispatcher=d, cache=cache) == []
    again = run_saved_scans(config, now=datetime(2026, 9, 25, 10, 20, tzinfo=IST), dispatcher=d, cache=cache)
    assert again[0]["new"] == [] and len(d.sent) == 1
    # Market closed: nothing runs.
    assert run_saved_scans(config, now=datetime(2026, 9, 25, 18, 0, tzinfo=IST), dispatcher=d, cache=cache) == []


class TestRisk:
    SETTINGS = {"market": "india", "capital": 100000, "daily_loss_limit_pct": 2, "max_open_risk_pct": 5,
                "max_trades_per_day": 3}
    NOW = datetime(2026, 9, 25, 12, 0)

    def _t(self, id_, **kw):
        base = {"id": id_, "symbol": "TCS", "market": "india", "side": "long", "quantity": 10, "entry_price": 3000,
                "stop": 2950, "exit_price": None, "exit_at": None, "entry_at": self.NOW, "fees": 0}
        return {**base, **kw}

    def test_ok_and_open_risk(self):
        r = compute([self._t(1)], self.SETTINGS, {"TCS": 3010}, self.NOW)
        assert r["status"] == "ok" and r["unrealized"] == 100 and r["open_risk"] == 600  # (3010-2950)*10
        assert r["loss_limit"] == 2000

    def test_stop_when_limit_hit(self):
        trades = [self._t(1, exit_price=2850, exit_at=self.NOW)]  # -1500 realized
        r = compute(trades + [self._t(2, symbol="INFY", entry_price=1500, stop=1400, quantity=10)], self.SETTINGS,
                    {"INFY": 1450}, self.NOW)  # -500 open
        assert r["status"] == "stop" and r["day_pnl"] == -2000 and r["limit_used_pct"] == 100

    def test_warnings(self):
        trades = [self._t(i, symbol=f"S{i}", stop=None) for i in range(3)]
        r = compute(trades, self.SETTINGS, {}, self.NOW)
        assert r["status"] == "warn"
        assert any("maximum of 3" in x for x in r["reasons"]) and any("No stop" in x for x in r["reasons"])

    def test_other_markets_and_days_ignored(self):
        trades = [self._t(1, market="us", exit_price=1, exit_at=self.NOW),
                  self._t(2, exit_price=1, exit_at=datetime(2026, 9, 24, 12), entry_at=datetime(2026, 9, 24, 10))]
        r = compute(trades, self.SETTINGS, {}, self.NOW)
        assert r["status"] == "ok" and r["realized"] == 0 and r["trades_today"] == 0


def test_risk_alert_once_per_day(tmp_path):
    from src.storage import DatabaseManager, TradeRecord, get_db_url
    from src.trading.risk import check_daily_limit, save_settings

    config = replace(Config(), db_path=tmp_path / "t.db")
    save_settings(config, market="india", capital=10000, daily_loss_limit_pct=1)
    now = datetime(2026, 9, 25, 11, 0)
    with DatabaseManager.instance(get_db_url(config=config)).get_session() as s:
        s.add(TradeRecord(symbol="TCS", market="india", quantity=10, entry_price=100, exit_price=80,
                          entry_at=now, exit_at=now))
    d = FakeDispatcher()
    ist_now = now.replace(tzinfo=IST)
    assert check_daily_limit(config, now=ist_now, dispatcher=d, quote_fn=lambda s, m: None)["status"] == "stop"
    assert check_daily_limit(config, now=ist_now, dispatcher=d, quote_fn=lambda s, m: None) is None
    assert len(d.sent) == 1 and "Daily loss limit" in d.sent[0][0]


def test_bot_trade_commands(tmp_path):
    from src.bot.models import IncomingMessage
    from src.bot.registry import build_default_dispatcher

    config = replace(Config(), db_path=tmp_path / "t.db")
    bot = build_default_dispatcher(config)
    say = lambda text: bot.dispatch(IncomingMessage(platform="test", chat_id="1", text=text)).text  # noqa: E731
    assert "Alert #1 set: RELIANCE (india) Price falls to or below 1,210.00" in say("/alert RELIANCE below 1210 buy zone")
    assert "AAPL (us)" in say("/alert us:AAPL rsi< 30")
    assert "Unknown condition" in say("/alert TCS sideways 5")
    listing = say("/alerts")
    assert "#1 RELIANCE" in listing and "buy zone" in listing and "#2 AAPL" in listing
    assert say("/alerts pause 2") == "Alert #2 paused"
    assert "[paused]" in say("/alerts")
    assert say("/alerts delete 1") == "Alert #1 deleted"
    assert "Risk: OK" in say("/risk")
    assert "No saved scans" in say("/scan")
    assert "/alert" in say("/help")
