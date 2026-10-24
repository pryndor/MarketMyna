"""Tests for the scheduled-analysis report, env config and headless runner (offline)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.core.config import Config
from src.services import analysis_run
from src.services.analysis_run import is_trading_day, parse_targets
from src.services.report import DEFAULT_SECTIONS, PUBLIC_HIDDEN, SECTION_IDS, ReportPrefs, build_report, render_reports


def _result(symbol, market="india", decision="buy", ok=True, **dash):
    dashboard = {
        "decision_type": decision,
        "outlook": {"buy": "bullish", "hold": "neutral", "sell": "bearish"}.get(decision),
        "analysis_summary": "Uptrend intact above the 50-day average.",
        "target_price": 1300,
        "stop_loss": 1150,
        "technical_signal": "bullish",
        "technical_confidence": 0.72,
        "risk_level": "medium",
        "opinions": [],
        **dash,
    }
    return {"symbol": symbol, "market": market, "ok": ok, "dashboard": dashboard,
            "quote": {"price": 1219.4, "change_percent": 0.5}}


class TestTargets:
    def test_default_market_and_prefix_override(self):
        targets = parse_targets("reliance, TCS ,us:aapl,crypto:BTC-USD,TCS", "india")
        assert [(t.symbol, t.market) for t in targets] == [
            ("RELIANCE", "india"), ("TCS", "india"), ("AAPL", "us"), ("BTC-USD", "crypto"),
        ]

    def test_unknown_prefix_is_part_of_symbol(self):
        assert parse_targets("NSE:RELIANCE", "india")[0].symbol == "NSE:RELIANCE"

    def test_trading_day(self):
        saturday = datetime(2026, 9, 26, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        friday = datetime(2026, 9, 25, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert not is_trading_day("india", saturday)
        assert is_trading_day("india", friday)
        assert is_trading_day("crypto", saturday)


class TestReport:
    NOW = datetime(2026, 9, 25, 8, 30, tzinfo=ZoneInfo("Asia/Kolkata"))

    def test_default_sections(self):
        _, text = build_report([_result("RELIANCE")], ReportPrefs(), "en", now=self.NOW)
        assert "📊 India · Standard analysis" in text
        assert "25 Sep 2026, 08:30 IST" in text
        assert "🧭 AI outlook" in text and "▲ Bullish: RELIANCE" in text
        assert "📌 RELIANCE — ▲ Bullish" in text
        assert "Price ₹1,219.40 (+0.50%)" in text
        for word in ("Buy", "BUY", "Target", "Stop"):
            assert word not in text
        assert "72%" not in text  # no technical verdict or confidence, only indicator values
        assert "⚖️ Risk: medium" in text
        assert "📰" not in text  # news is opt-in

    def test_partial_result_shows_reason(self):
        partial = _result("TCS", decision=None, ok=False, analysis_summary=None)
        partial["error"] = "No llm_model configured"
        _, text = build_report([partial, _result("AAPL", market="us", decision="sell")], ReportPrefs(mode="quick"),
                               now=self.NOW)
        assert "India + US" in text
        assert "⚠️ TCS [India]" in text
        assert "AI summary unavailable: No llm_model configured" in text
        assert "▼ Bearish: AAPL" in text and "📌 AAPL — ▼ Bearish [US]" in text

    def test_optional_sections_render_extras(self):
        r = _result("RELIANCE")
        r["extras"] = {
            "high_52w": 1600, "low_52w": 1100,
            "fundamentals": {"overall_score": 62, "valuation": {"status": "fair", "value": 22.7},
                             "profitability": {"roe": {"value": 14.2}}, "financial_health": {"rating": "good"},
                             "growth": {"revenue_growth": {"value": 8.0}}, "dividend": {"yield": 0.4}},
            "analysts": {"recommendation": "strong_buy", "target_mean": 1676.8, "count": 26},
            "events": {"earnings_date": "2999-10-16", "ex_dividend_date": "2000-01-01"},
            "news": [{"title": "Reliance expands retail", "source": "Mint"}],
        }
        prefs = ReportPrefs(sections=list(SECTION_IDS))
        _, text = build_report([r], prefs, now=self.NOW)
        assert "52-week range: ₹1,100.00 – ₹1,600.00" in text
        assert "🏦 Fundamentals: Score 62/100 · P/E 22.7 · ROE 14.2%" in text
        assert "🎯 Broker consensus of third-party analysts: bullish (26 analysts)" in text
        assert "strong buy" not in text and "target" not in text
        assert "📅 Upcoming: Earnings 16 Oct 2999" in text
        assert "Ex-dividend" not in text  # past dates are dropped
        assert "• Reliance expands retail — Mint" in text

    def test_per_stock_sections_override(self):
        prefs = ReportPrefs(sections=["price"], stock_sections={"TCS": ["risk"]})
        _, text = build_report([_result("RELIANCE"), _result("TCS")], prefs, now=self.NOW)
        reliance, tcs = text.split("📌 TCS")
        assert "Price ₹" in reliance and "Risk" not in reliance
        assert "Risk: medium" in tcs and "Price ₹" not in tcs

    def test_builtin_language_labels(self):
        title, text = build_report([_result("RELIANCE")], ReportPrefs(), "ta", now=self.NOW)
        assert title == "MarketMyna தினசரி அறிக்கை"
        assert "ஏற்றம்: RELIANCE" in text
        assert "இது முதலீட்டு ஆலோசனை அல்ல" in text
        assert "₹1,219.40" in text  # numbers untouched

    def test_no_llm_adds_english_note(self):
        reports = render_reports([_result("RELIANCE")], ReportPrefs(), ["hi", "en"], config=Config(), now=self.NOW)
        assert set(reports) == {"hi", "en"}
        assert "अंग्रेज़ी" in reports["hi"][1]
        assert "Some details are in English" not in reports["en"][1]

    def test_llm_translation_is_used(self, monkeypatch):
        from src.services import report

        monkeypatch.setattr(report, "translate_report", lambda text, lang, config: f"[{lang}] {text}")
        reports = render_reports([_result("RELIANCE")], ReportPrefs(), ["ja"], config=Config(), now=self.NOW)
        assert reports["ja"][1].startswith("[ja] ")


class TestI18n:
    def test_every_builtin_language_has_every_label(self):
        from src.services import report_i18n as i18n

        for lang in i18n.BUILTIN_LANGUAGES:
            if lang == "en":
                continue
            assert set(i18n._STRINGS[lang]) | i18n.PENDING_TRANSLATION == set(i18n._EN), lang
            assert set(i18n._VALUES[lang]) == set(i18n._EN_VALUES), lang

    def test_normalize_language(self):
        from src.services.report_i18n import normalize_language

        assert normalize_language("TA") == "ta"
        assert normalize_language("hi-IN") == "hi"
        assert normalize_language("Tamil") == "ta"
        assert normalize_language("日本語") == "ja"
        assert normalize_language("klingon") == "en"

    def test_channel_languages(self):
        prefs = ReportPrefs(language="en", channel_languages={"telegram": "ta"})
        assert prefs.languages_needed(["telegram", "email"]) == {"ta": ["telegram"], "en": ["email"]}


class TestEnvConfig:
    def test_env_overrides_and_types(self):
        cfg = Config().apply_env({
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "TELEGRAM_CHAT_ID": "42",
            "EMAIL_RECEIVERS": "a@x.com, b@y.com",
            "EMAIL_SMTP_PORT": "465",
            "EMAIL_SMTP_SSL": "false",
            "LLM_TEMPERATURE": "0.2",
            "LLM_MODEL": "",  # empty = unset GitHub secret, must not override
        })
        assert cfg.telegram_bot_token == "123:abc"
        assert cfg.email_receivers == ["a@x.com", "b@y.com"]
        assert cfg.email_smtp_port == 465
        assert cfg.email_smtp_ssl is False
        assert cfg.llm_temperature == 0.2
        assert cfg.llm_model is None

    def test_bad_value_names_the_variable(self):
        with pytest.raises(ValueError, match="EMAIL_SMTP_PORT"):
            Config().apply_env({"EMAIL_SMTP_PORT": "abc"})


class TestTelegramSplit:
    def test_split_keeps_lines_and_limit(self):
        from src.notifiers.telegram import split_message

        text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
        chunks = split_message(text, 4096)
        assert all(len(c) <= 4096 for c in chunks)
        assert "\n".join(chunks) == text


class TestRunner:
    @pytest.fixture
    def env(self, monkeypatch, tmp_path):
        for key in ("STOCK_LIST", "MARKET", "ANALYSIS_MODE", "TRADING_DAY_CHECK_ENABLED",
                    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "REPORT_LANGUAGE", "REPORT_SECTIONS",
                    "STOCK_SECTIONS", "CHANNEL_LANGUAGES"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setattr(analysis_run, "_quote", lambda s, m: {"price": 100.0, "change_percent": 1.0})
        return tmp_path

    def _patch_analysis(self, monkeypatch, ok=True):
        from src.cli import scheduled_run

        def fake(symbol, market, mode, config, orchestrator=None, sections=None):
            return _result(symbol, market=market, ok=ok, decision="buy" if ok else None)

        monkeypatch.setattr(scheduled_run, "analyze_symbol", fake)
        monkeypatch.setattr(analysis_run, "market_overview", lambda markets: [])
        from src.services import ideas

        monkeypatch.setattr(ideas, "find_ideas", lambda *a, **k: [])
        monkeypatch.setattr(scheduled_run, "_saved_prefs", lambda config: None)
        monkeypatch.setattr(scheduled_run.Config, "load", classmethod(lambda cls: Config()))
        return scheduled_run

    def test_no_symbols_exits_1(self, env, monkeypatch):
        runner = self._patch_analysis(monkeypatch)
        assert runner.main(["--output-dir", str(env)]) == 1

    def test_dry_run_writes_report(self, env, monkeypatch, capsys):
        runner = self._patch_analysis(monkeypatch)
        code = runner.main(["--symbols", "RELIANCE,us:AAPL", "--force-run", "--dry-run", "--output-dir", str(env)])
        assert code == 0
        assert "📌 RELIANCE — ▲ Bullish" in capsys.readouterr().out
        assert len(list(env.glob("marketmyna-*-en.txt"))) == 1

    def test_sends_to_configured_channels(self, env, monkeypatch):
        runner = self._patch_analysis(monkeypatch)
        sent = {}

        class FakeDispatcher:
            def __init__(self, config):
                pass

            def configured_channels(self, purpose=None):
                return ["telegram"]

            def send_each(self, messages, purpose=None):
                sent.update(messages)
                return {name: True for name in messages}

        monkeypatch.setattr(runner, "NotificationDispatcher", FakeDispatcher)
        assert runner.main(["--symbols", "TCS", "--force-run", "--output-dir", str(env)]) == 0
        assert "TCS — ▲ Bullish" in sent["telegram"][1]

    def test_all_channels_failing_exits_2(self, env, monkeypatch):
        runner = self._patch_analysis(monkeypatch)

        class FailingDispatcher:
            def __init__(self, config):
                pass

            def configured_channels(self, purpose=None):
                return ["telegram"]

            def send_each(self, messages, purpose=None):
                return {name: False for name in messages}

            def send_all(self, message, title=None, purpose=None):
                return {}

        monkeypatch.setattr(runner, "NotificationDispatcher", FailingDispatcher)
        assert runner.main(["--symbols", "TCS", "--force-run", "--output-dir", str(env)]) == 2

    def test_channel_languages_from_env(self, env, monkeypatch):
        runner = self._patch_analysis(monkeypatch)
        monkeypatch.setenv("CHANNEL_LANGUAGES", "telegram:hi")
        monkeypatch.setenv("REPORT_SECTIONS", "calls,price")
        monkeypatch.setenv("STOCK_SECTIONS", "INFY=risk+news")
        sent = {}

        class TwoChannels:
            def __init__(self, config):
                pass

            def configured_channels(self, purpose=None):
                return ["telegram", "email"]

            def send_each(self, messages, purpose=None):
                sent.update(messages)
                return {name: True for name in messages}

        monkeypatch.setattr(runner, "NotificationDispatcher", TwoChannels)
        assert runner.main(["--symbols", "TCS,INFY", "--force-run", "--output-dir", str(env)]) == 0
        assert sent["telegram"][0] == "MarketMyna दैनिक रिपोर्ट"
        assert "तेज़ी: TCS, INFY" in sent["telegram"][1]
        assert sent["email"][0] == "MarketMyna daily report"
        tcs, infy = sent["email"][1].split("📌 INFY")
        assert "Price" in tcs and "Risk" not in tcs
        assert "Risk: medium" in infy and "Price" not in infy
        assert {p.name.rsplit("-", 1)[1] for p in env.glob("marketmyna-*.txt")} == {"en.txt", "hi.txt"}


class TestSchedulerReportApi:
    @pytest.fixture
    def client(self, tmp_path):
        from dataclasses import replace

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.deps import get_config_dep
        from api.v1.endpoints import scheduler

        config = replace(Config(), db_path=tmp_path / "test.db")
        app = FastAPI()
        app.include_router(scheduler.router, prefix="/api/v1")
        app.dependency_overrides[get_config_dep] = lambda: config
        return TestClient(app)

    def test_options(self, client):
        body = client.get("/api/v1/scheduler/report-options").json()
        codes = {lang["code"] for lang in body["languages"]}
        assert {"en", "hi", "ta", "zh", "es", "it"} <= codes
        assert [s["id"] for s in body["sections"] if s["default"]] == [s for s in DEFAULT_SECTIONS if s not in PUBLIC_HIDDEN]
        assert body["channels"] == []

    def test_save_and_validate_prefs(self, client):
        assert client.get("/api/v1/scheduler/config").json()["report_sections"] == DEFAULT_SECTIONS
        resp = client.put("/api/v1/scheduler/config", json={
            "report_language": "ta",
            "report_sections": ["news", "bogus", "price"],
            "stock_sections": {" tcs ": ["risk"]},
            "channel_languages": {"telegram": "hi", "email": ""},
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["report_language"] == "ta"
        assert body["report_sections"] == ["price", "news"]
        assert body["stock_sections"] == {"TCS": ["risk"]}
        assert body["channel_languages"] == {"telegram": "hi"}
        assert client.put("/api/v1/scheduler/config", json={"report_language": "xx"}).status_code == 400

    def test_smart_file_settings(self, client):
        body = client.get("/api/v1/scheduler/config").json()
        assert body["smart_file"] == "pdf" and body["smart_file_channels"] == ["email", "telegram"]  # defaults
        body = client.put("/api/v1/scheduler/config", json={
            "smart_file": "xlsx", "smart_file_channels": ["telegram", "bogus"]}).json()
        assert body["smart_file"] == "xlsx" and body["smart_file_channels"] == ["telegram"]
        assert client.put("/api/v1/scheduler/config", json={"smart_file": "docx"}).status_code == 400
