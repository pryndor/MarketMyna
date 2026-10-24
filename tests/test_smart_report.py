"""Tests for smart messaging: levels, ranking, short message, full report (offline)."""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from marketmyna.core.config import Config
from marketmyna.services.analysis_run import Target
from marketmyna.services.report import ReportPrefs
from marketmyna.services.smart_report import (
    build_rows,
    compute_snapshot,
    html_report,
    run_smart,
    smart_message,
    without_calls,
)

NOW = datetime(2026, 9, 25, 16, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


def _history(closes, volume_last=1.0):
    closes = np.asarray(closes, dtype=float)
    volume = np.full(len(closes), 1_000_000.0)
    volume[-1] *= volume_last
    return pd.DataFrame({"close": closes, "high": closes * 1.01, "low": closes * 0.99, "volume": volume})


def _row(symbol, attention, action="hold", **extra):
    return {
        "symbol": symbol, "market": "india", "price": 100.0, "change_percent": 1.0,
        "normal_low": 95.0, "normal_high": 105.0, "buy_point": 96.0, "sell_point": 104.0, "stop_loss": 94.0,
        "week_low": 97.0, "week_high": 103.0, "rsi": 50.0, "trend": "sideways", "valuation": None, "pe": None,
        "action": action, "attention": attention, "reasons": [], **extra,
    }


class FakeDispatcher:
    def __init__(self, channels):
        self.channels = channels
        self.sent = None

    def configured_channels(self, purpose="report"):
        return list(self.channels)

    def send_each(self, messages, purpose=None, files=None):
        self.sent, self.files = messages, files
        return {ch: True for ch in messages}


class TestSnapshot:
    def test_levels_are_ordered(self):
        rng = np.random.default_rng(1)
        snap = compute_snapshot(_history(100 + np.cumsum(rng.normal(0, 1, 250))))
        assert snap["stop_loss"] < snap["buy_point"] <= snap["price"] * 1.05
        assert snap["normal_low"] < snap["normal_high"]
        assert snap["week_low"] < snap["price"] < snap["week_high"]
        assert snap["action"] in ("buy", "hold", "sell")
        assert 0 <= snap["rsi"] <= 100

    def test_steady_uptrend_is_not_sell(self):
        snap = compute_snapshot(_history(np.linspace(50, 150, 250)))
        assert snap["trend"] == "uptrend"
        assert snap["action"] != "sell"

    def test_crash_with_volume_ranks_high(self):
        closes = list(np.full(249, 100.0) + np.sin(np.arange(249)))
        calm = compute_snapshot(_history(closes + [closes[-1]]))
        crash = compute_snapshot(_history(closes + [closes[-1] * 0.9], volume_last=3))
        assert crash["attention"] > calm["attention"]
        assert any("volume" in r for r in crash["reasons"])
        assert any("moved" in r for r in crash["reasons"])

    def test_short_history_rejected(self):
        with pytest.raises(ValueError):
            compute_snapshot(_history(np.linspace(1, 2, 10)))


class TestRows:
    def test_ai_only_for_top_k(self):
        scores = {"A": 1, "B": 5, "C": 3, "D": 0}
        called = []

        def snap(symbol, market):
            return _row(symbol, scores[symbol])

        def analyze(symbol, market, mode, config):
            called.append(symbol)
            return {"dashboard": {"outlook": "bullish", "analysis_summary": "AI says yes"}}

        rows = build_rows([Target(s, "india") for s in scores], Config(), ai_top=2, analyze=analyze, snap=snap)
        assert [r["symbol"] for r in rows] == ["B", "C", "A", "D"]
        assert called == ["B", "C"]
        assert rows[0]["ai"] and rows[0]["action"] == "buy" and "ai_target" not in rows[0]
        assert "ai" not in rows[2]

    def test_errors_sink_and_skip_ai(self):
        def snap(symbol, market):
            return {"symbol": symbol, "market": market, "error": "no data"} if symbol == "BAD" else _row(symbol, 1)

        rows = build_rows([Target("BAD", "india"), Target("OK", "india")], Config(), ai_top=5,
                          analyze=lambda *a: {"dashboard": {}}, snap=snap)
        assert rows[-1]["symbol"] == "BAD"


class TestMessage:
    def test_only_top_n_and_link(self):
        rows = [without_calls(_row(f"S{i}", 10 - i, action="buy" if i == 0 else "hold")) for i in range(8)]
        prefs = ReportPrefs(smart=True, smart_top_n=3)
        title, body = smart_message(rows, prefs, "en", "https://sp.example/r/tok", NOW)
        assert "Top 3 stocks to watch today" in body
        assert "S0" in body and "S2" in body and "S3" not in body
        assert "▲ S0" in body and "Indicators: bullish" in body and "Normal range ₹95.00" in body
        assert "BUY" not in body and "Buy ≤" not in body and "Sell ≥" not in body
        assert "Full report for all 8 stocks: https://sp.example/r/tok" in body
        assert len(body.splitlines()) < 20

    def test_translated_labels(self):
        _, body = smart_message([_row("A", 1)], ReportPrefs(smart_top_n=5), "hi", None, NOW)
        assert "Top 1 stocks" not in body

    def test_html_has_every_stock(self):
        rows = [_row(f"S{i}", i) for i in range(12)] + [{"symbol": "BAD", "market": "india", "error": "x"}]
        page = html_report(rows, "T", NOW, None)
        assert all(f">S{i}<" in page or f"S{i}" in page for i in range(12))
        assert "<table" in page


class TestRunSmart:
    def _run(self, tmp_path, channels, **prefs):
        config = replace(Config(), db_path=tmp_path / "t.db")
        prefs = ReportPrefs(smart=True, smart_top_n=2, smart_ai_top=0, report_base_url="https://sp.example/",
                            **{"smart_file": "none", **prefs})
        dispatcher = FakeDispatcher(channels)
        out = run_smart([Target(s, "india") for s in "ABCD"], prefs, config, dispatcher=dispatcher,
                        snap=lambda s, m: _row(s, ord(s)))
        return out, dispatcher

    def test_email_gets_full_html_chat_gets_short(self, tmp_path):
        (reports, delivery, rows, token, full_html), d = self._run(tmp_path, ["telegram", "email"])
        assert token and delivery == {"telegram": True, "email": True}
        assert len(d.sent["telegram"]) == 2
        title, body, html = d.sent["email"]
        assert html == full_html and "<table" in html
        assert f"https://sp.example/r/{token}" in body

    def test_email_full_off(self, tmp_path):
        (_, _, _, _, full_html), d = self._run(tmp_path, ["email"], smart_email_full=False)
        assert full_html is None and len(d.sent["email"]) == 2

    def test_report_file_goes_only_to_the_chosen_channels(self, tmp_path, monkeypatch):
        from marketmyna.services import smart_file

        monkeypatch.setattr(smart_file, "report_file", lambda rows, prefs, config, now, title: ("r.pdf", b"%PDF"))
        _, d = self._run(tmp_path, ["telegram", "email"], smart_file="pdf", smart_file_channels=["telegram"])
        assert d.files == {"telegram": [("r.pdf", b"%PDF")]}
        _, d = self._run(tmp_path, ["telegram", "email"], smart_file="pdf", smart_file_channels=[])
        assert d.files == {}


class TestReportsApi:
    def test_saved_report_roundtrip(self, tmp_path):
        testclient = pytest.importorskip("fastapi.testclient")
        from fastapi import FastAPI

        from marketmyna.api.deps import get_config_dep
        from marketmyna.api.v1.endpoints import reports
        from marketmyna.services.smart_report import save_report

        config = replace(Config(), db_path=tmp_path / "t.db")
        token = save_report(config, [_row("A", 1)], "My report", {"markets": ["india"]})

        app = FastAPI()
        app.include_router(reports.router, prefix="/api/v1")
        app.dependency_overrides[get_config_dep] = lambda: config
        client = testclient.TestClient(app)

        listed = client.get("/api/v1/reports").json()
        assert listed[0]["token"] == token and listed[0]["stock_count"] == 1
        detail = client.get(f"/api/v1/reports/{token}").json()
        assert detail["title"] == "My report" and detail["rows"][0]["symbol"] == "A"
        assert client.get("/api/v1/reports/nope").status_code == 404
