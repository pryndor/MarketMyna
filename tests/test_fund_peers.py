"""A mutual fund against its competitors: same SEBI category and plan, growth
option, one scheme per fund house; returns, risk, ranks and similarity from
NAV history; overlap when both portfolios are loaded."""

import math

import numpy as np
import pandas as pd
import pytest

from src.services import fund_peers


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fund_peers, "_cache_dir", lambda: tmp_path)
    fund_peers._mem.clear()


def _row(code, name, amc, sector="Flexi Cap Fund", plan="Direct", option="Growth"):
    return {"symbol": code, "name": name, "type": "mf", "amc": amc, "sector": sector, "plan": plan, "option": option,
            "category": "Equity"}


ROWS = [
    _row("1", "Alpha Flexi Cap Fund - Direct Plan - Growth", "Alpha MF"),
    _row("2", "Beta Flexi Cap Fund - Direct Plan - Growth", "Beta MF"),
    _row("3", "Gamma Flexi Cap Fund - Direct Plan - Growth", "Gamma MF"),
    _row("4", "Gamma Flexi Cap Fund - Direct Plan - IDCW", "Gamma MF", option="IDCW"),   # not growth
    _row("5", "Delta Flexi Cap Fund - Regular Plan - Growth", "Delta MF", plan="Regular"),  # other plan
    _row("6", "Eps Large Cap Fund - Direct Plan - Growth", "Eps MF", sector="Large Cap Fund"),  # other category
    _row("7", "Zeta Flexi Cap Fund - Direct Plan - Growth", "Zeta MF"),
]


def _series(annual, vol, seed, years=6):
    days = pd.bdate_range(end="2026-10-08", periods=int(252 * years))
    rng = np.random.default_rng(seed)
    daily = rng.normal(annual / 252, vol / math.sqrt(252), len(days))
    return pd.Series(100 * np.exp(np.cumsum(daily)), index=days)


NAVS = {"1": _series(0.15, 0.12, 1), "2": _series(0.10, 0.20, 2), "3": _series(0.05, 0.15, 3),
        "7": _series(0.15, 0.12, 1) * 1.01}  # 7 moves exactly like 1


def test_competitors_are_same_category_plan_and_growth():
    codes = {r["symbol"] for r in fund_peers.candidates(ROWS[0], ROWS)}
    assert codes == {"1", "2", "3", "7"}


def test_compare_ranks_and_similarity():
    out = fund_peers.compare("1", rows=ROWS, fetch=lambda code: NAVS.get(code), holdings=lambda code: {"status": "missing"})
    assert out["status"] == "ok" and out["category"] == "Flexi Cap Fund" and out["count"] == 4
    me = next(r for r in out["rows"] if r["is_self"])
    assert me["r1"] is not None and me["r3"] is not None and me["r5"] is not None
    assert me["volatility"] == pytest.approx(12, abs=2) and me["drawdown"] < 0
    assert out["ranks"]["volatility"]["rank"] <= 2  # one of the two steadiest
    assert out["closest"][0]["code"] == "7" and out["closest"][0]["similarity"] > 0.99


def test_young_fund_has_no_long_returns():
    young = {"1": NAVS["1"].iloc[-300:], "2": NAVS["2"], "3": NAVS["3"]}
    out = fund_peers.compare("1", rows=ROWS[:3], fetch=lambda code: young.get(code), holdings=lambda code: {"status": "missing"})
    me = next(r for r in out["rows"] if r["is_self"])
    assert me["r1"] is not None and me["r3"] is None and me["r5"] is None


def test_overlap_when_both_portfolios_loaded():
    port = {
        "1": {"status": "ok", "holdings": [{"isin": "A", "weight": 10, "kind": "equity"}, {"isin": "B", "weight": 5, "kind": "equity"}]},
        "2": {"status": "ok", "holdings": [{"isin": "A", "weight": 4, "kind": "equity"}, {"isin": "C", "weight": 9, "kind": "equity"}]},
    }
    out = fund_peers.compare("1", rows=ROWS, fetch=lambda code: NAVS.get(code),
                             holdings=lambda code: port.get(code, {"status": "missing"}))
    by = {r["code"]: r for r in out["rows"]}
    assert by["2"]["overlap"] == 4 and by["3"]["overlap"] is None


def test_nav_cache_avoids_refetching():
    calls = []
    fetch = lambda code: calls.append(code) or NAVS["1"]  # noqa: E731
    fund_peers.nav("1", fetch)
    fund_peers._mem.clear()  # a restart: the disk copy is used
    fund_peers.nav("1", fetch)
    assert calls == ["1"]
