"""Tests for the scheduler's "what to run" sources: watchlists, portfolio, custom."""

from dataclasses import replace
from datetime import datetime

from marketmyna.core.config import Config
from marketmyna.services.runtime_scheduler import RuntimeSchedulerService
from marketmyna.services.schedule_config import (
    ScheduleConfig,
    ScheduleConfigStore,
    resolve_targets,
    source_catalog,
)
from marketmyna.storage import (
    DatabaseManager,
    HoldingRecord,
    PortfolioRecord,
    WatchlistItemRecord,
    WatchlistRecord,
    get_db_url,
)


def _config(tmp_path):
    config = replace(Config(), db_path=tmp_path / "t.db")
    db = DatabaseManager.instance(get_db_url(config=config))
    with db.get_session() as s:
        core = WatchlistRecord(name="Core")
        swing = WatchlistRecord(name="Swing")
        s.add_all([core, swing])
        s.flush()
        s.add_all([
            WatchlistItemRecord(watchlist_id=core.id, symbol="TCS", market="india", type="stock"),
            WatchlistItemRecord(watchlist_id=core.id, symbol="122639", market="india", type="mf"),
            WatchlistItemRecord(watchlist_id=swing.id, symbol="AAPL", market="us", type="stock"),
        ])
        pf = PortfolioRecord(name="Main", currency="INR")
        s.add(pf)
        s.flush()
        s.add_all([
            HoldingRecord(portfolio_id=pf.id, symbol="reliance", quantity=10, market="INDIA"),
            HoldingRecord(portfolio_id=pf.id, symbol="TCS", quantity=5, market="INDIA"),
            HoldingRecord(portfolio_id=pf.id, symbol="SOLD", quantity=0, market="INDIA"),
        ])
    return config


def _pairs(targets):
    return [(t.symbol, t.market) for t in targets]


def test_catalog_skips_funds_and_closed_positions(tmp_path):
    cat = source_catalog(_config(tmp_path))
    assert [w["name"] for w in cat["watchlists"]] == ["Core", "Swing"]
    assert cat["watchlists"][0]["symbols"] == [{"symbol": "TCS", "market": "india"}]
    assert cat["portfolios"][0]["symbols"] == [
        {"symbol": "RELIANCE", "market": "india"}, {"symbol": "TCS", "market": "india"},
    ]


def test_both_sources_deduplicated(tmp_path):
    config = _config(tmp_path)
    cfg = ScheduleConfig(sources=["watchlist", "portfolio"])
    assert _pairs(resolve_targets(cfg, config)) == [("RELIANCE", "india"), ("TCS", "india"), ("AAPL", "us")]


def test_selected_watchlist_only(tmp_path):
    config = _config(tmp_path)
    swing = next(w["id"] for w in source_catalog(config)["watchlists"] if w["name"] == "Swing")
    cfg = ScheduleConfig(sources=["watchlist"], watchlist_ids=[swing])
    assert _pairs(resolve_targets(cfg, config)) == [("AAPL", "us")]


def test_legacy_config_is_custom(tmp_path):
    cfg = ScheduleConfig(symbols=["msft"], market="us")
    assert cfg.run_sources() == ["custom"]
    assert _pairs(resolve_targets(cfg, _config(tmp_path))) == [("MSFT", "us")]


def test_due_without_custom_symbols(tmp_path):
    now = datetime(2026, 9, 25, 10, 0)
    assert RuntimeSchedulerService.is_due(ScheduleConfig(enabled=True, sources=["portfolio"], interval_minutes=60), now)
    assert not RuntimeSchedulerService.is_due(ScheduleConfig(enabled=True, sources=["custom"], interval_minutes=60), now)


def test_run_now_uses_sources(tmp_path, monkeypatch):
    config = _config(tmp_path)
    ScheduleConfigStore(config=config).update(sources=["portfolio"], symbols=["IGNORED"])
    seen = []
    svc = RuntimeSchedulerService(config)
    monkeypatch.setattr(svc, "_run_one_symbol", lambda sym, mkt, mode, sections=None: seen.append((sym, mkt)) or
                        {"ok": False, "symbol": sym, "market": mkt, "error": "offline"})
    monkeypatch.setattr("marketmyna.services.runtime_scheduler.deliver_report", lambda *a, **k: ({}, {}))
    monkeypatch.setattr("marketmyna.services.runtime_scheduler.notify_failure", lambda *a, **k: None)
    svc.run_now()
    assert seen == [("RELIANCE", "india"), ("TCS", "india")]


def test_rate_limited_stocks_get_one_more_try(tmp_path, monkeypatch):
    config = _config(tmp_path)
    ScheduleConfigStore(config=config).update(sources=["portfolio"])
    calls = []

    def run(sym, mkt, mode, sections=None):
        calls.append(sym)
        if sym == "TCS" and calls.count("TCS") == 1:
            return {"ok": False, "symbol": sym, "market": mkt, "error": "All sources exhausted for india.get_quote"}
        if sym == "RELIANCE":
            return {"ok": False, "symbol": sym, "market": mkt, "error": "No data found, symbol may be delisted"}
        return {"ok": True, "symbol": sym, "market": mkt, "dashboard": {}}

    svc = RuntimeSchedulerService(config)
    monkeypatch.setattr(svc, "_run_one_symbol", run)
    monkeypatch.setattr("marketmyna.services.runtime_scheduler.RETRY_PAUSE", 0)
    monkeypatch.setattr("marketmyna.services.runtime_scheduler.deliver_report", lambda *a, **k: ({}, {}))
    monkeypatch.setattr("marketmyna.services.runtime_scheduler.notify_failure", lambda *a, **k: None)
    out = svc.run_now()
    assert sorted(calls) == ["RELIANCE", "TCS", "TCS"]  # only the rate-limited one is retried
    assert {r["symbol"]: r["ok"] for r in out["results"]} == {"RELIANCE": False, "TCS": True}


def test_start_run_now_runs_in_background_once(tmp_path, monkeypatch):
    import threading

    svc = RuntimeSchedulerService(_config(tmp_path))
    release = threading.Event()
    monkeypatch.setattr(svc, "run_now", lambda: release.wait(5) and {"status": "ok", "results": [], "summary": "done"})
    assert svc.start_run_now() is True
    assert svc.run_now_state()["running"] is True
    assert svc.start_run_now() is False  # already going
    release.set()
    for _ in range(100):
        if not svc.run_now_state()["running"]:
            break
        threading.Event().wait(0.02)
    assert svc.run_now_state() == {"running": False, "result": {"status": "ok", "results": [], "summary": "done"}}


def test_report_keeps_only_the_schedules_area_sections():
    sections = ["calls", "portfolio", "hot_trade", "hot_invest", "levels", "alerts", "ai"]
    investor = ScheduleConfig(report_sections=sections, area="investor").report_prefs()
    assert investor.sections == ["calls", "portfolio", "hot_invest", "ai"]
    trader = ScheduleConfig(report_sections=sections, area="trader").report_prefs()
    assert trader.sections == ["calls", "alerts", "hot_trade", "levels", "ai"]  # report order
    assert len(ScheduleConfig(report_sections=sections).report_prefs().sections) == len(sections)  # no area yet: as saved
