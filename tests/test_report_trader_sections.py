"""Report sections added for the Trader / Investor split: your portfolio's
day, your price alerts, trade levels (public-safe) and hot stocks."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from marketmyna.services import analysis_run
from marketmyna.services.report import SECTION_AREAS, SECTION_IDS, ReportPrefs, build_report
from marketmyna.storage import (
    DatabaseManager,
    HoldingRecord,
    PortfolioRecord,
    PriceAlertEventRecord,
    PriceAlertRecord,
    get_db_url,
)


@pytest.fixture
def config(tmp_path):
    cfg = SimpleNamespace(db_path=tmp_path / "r.db")
    DatabaseManager.instance(get_db_url(cfg))  # creates the tables
    return cfg


def _session(cfg):
    return DatabaseManager.instance(get_db_url(cfg)).get_session()


def test_every_area_tag_is_a_known_section():
    assert set(SECTION_AREAS) <= set(SECTION_IDS)
    assert set(SECTION_AREAS.values()) <= {"trader", "investor"}


def test_portfolio_snapshot_uses_report_quotes(config):
    with _session(config) as s:
        p = PortfolioRecord(name="Core")
        s.add(p)
        s.flush()
        s.add_all([HoldingRecord(portfolio_id=p.id, symbol="TCS", quantity=10, avg_cost=3000, market="india"),
                   HoldingRecord(portfolio_id=p.id, symbol="INFY", quantity=5, avg_cost=1500, market="india")])
    results = [{"symbol": "TCS", "market": "india", "quote": {"price": 3500, "change": 50}}]
    snap = analysis_run.portfolio_snapshots([], results, config,
                                            quote=lambda sym, mkt: {"price": 1400, "change": -20})
    assert len(snap) == 1
    core = snap[0]
    assert core["value"] == 10 * 3500 + 5 * 1400
    assert core["day_change"] == 10 * 50 + 5 * -20
    assert core["gain"] == core["value"] - (10 * 3000 + 5 * 1500)
    assert core["currency_symbol"] == "₹" and core["movers"][0]["symbol"] == "TCS"
    assert analysis_run.portfolio_snapshots(["Other"], results, config) == []


def test_alert_digest_fired_and_near(config):
    now = datetime(2026, 10, 9, 15, 0)
    with _session(config) as s:
        s.add_all([
            PriceAlertRecord(symbol="TCS", market="india", kind="price_above", value=3550, status="active"),
            PriceAlertRecord(symbol="INFY", market="india", kind="price_below", value=1000, status="active"),
            PriceAlertEventRecord(symbol="SBIN", market="india", kind="pct_up", message="SBIN up 3%",
                                  created_at=now - timedelta(hours=2)),
            PriceAlertEventRecord(symbol="OLD", market="india", kind="pct_up", message="old", created_at=now - timedelta(days=3)),
        ])
    results = [{"symbol": "TCS", "market": "india", "quote": {"price": 3500}}]
    d = analysis_run.alert_digest(results, config, now=now, quote=lambda sym, mkt: {"price": 1400})
    assert [e["symbol"] for e in d["fired"]] == ["SBIN"]
    assert [a["symbol"] for a in d["near"]] == ["TCS"]  # 1.4% away; INFY is 28% away
    assert d["active"] == 2
    body = build_report([], ReportPrefs(sections=["alerts"]), alerts=d, now=now)[1]
    assert "SBIN up 3%" in body and "TCS" in body


def _levels_body(monkeypatch, mode):
    monkeypatch.setenv("COMPLIANCE_MODE", mode)
    r = {"symbol": "TCS", "market": "india", "ok": True, "quote": {"price": 3500}, "dashboard": {},
         "extras": {"levels": {"price": 3500, "buy_point": 3400, "sell_point": 3700, "stop_loss": 3350, "atr": 50,
                               "normal_low": 3380, "normal_high": 3650, "week_low": 3420, "week_high": 3580}}}
    return build_report([r], ReportPrefs(sections=["levels"]))[1]


def test_levels_public_shows_ranges_only(monkeypatch):
    body = _levels_body(monkeypatch, "analytics")
    assert "Support" not in body and "Stop" not in body and "R:R" not in body
    assert "Normal range ₹3,380.00" in body and "ATR" in body


def test_hot_blocks_pick_three_rows_per_board(monkeypatch):
    from marketmyna.services import hot_stocks

    board = lambda key: {"key": key, "title": key, "rows": [{"symbol": f"S{i}"} for i in range(10)]}  # noqa: E731
    monkeypatch.setattr(hot_stocks, "trader", lambda m: {"boards": [board("momentum"), board("bounces")]})
    out = analysis_run.hot_blocks([{"symbol": "TCS", "market": "india"}], {"hot_trade"})
    assert out[0]["section"] == "hot_trade"
    boards = out[0]["markets"]["india"]
    assert [b["key"] for b in boards] == ["momentum"] and len(boards[0]["rows"]) == 3
