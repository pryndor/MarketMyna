"""World markets card (marketmyna/services/world_markets.py) with canned series."""

import pandas as pd

from marketmyna.services import world_markets as wm


def _series(start: float, end: float, days: int = 400, last: pd.Timestamp | None = None) -> pd.Series:
    last = last or pd.Timestamp.today().normalize()
    idx = pd.date_range(end=last, periods=days, freq="D")
    return pd.Series([start + (end - start) * i / (days - 1) for i in range(days)], index=idx)


def _fetch(tickers):
    out = {t: _series(100, 110) for t in tickers}
    out["^TNX"] = _series(4.0, 5.0)
    out["^VIX"] = _series(20, 25)
    out["^VIX3M"] = _series(20, 20)
    out.pop("^BVSP")  # one market missing
    return out


def test_build_rows_changes_and_term_structure():
    d = wm.build(fetch=_fetch, cboe=lambda s: {}, fear_greed=lambda: None, use_cache=False)
    by = {r["key"]: r for r in d["items"]}
    assert d["failed"] == ["Bovespa"]
    spx = by["^GSPC"]
    assert spx["change_unit"] == "%" and round(spx["change_1y"], 1) == round((110 / (100 + 10 * 34 / 399) - 1) * 100, 1)
    tnx = by["^TNX"]  # yields change in points
    assert tnx["change_unit"] == "points" and round(tnx["change_1y"], 2) == round(365 / 399, 2)
    assert d["vix_term"]["shape"] == "backwardation" and d["vix_term"]["ratio"] == 1.25
    assert len(spx["spark"]) <= 93


def test_cboe_value_replaces_todays_bar_or_appends():
    today = pd.Timestamp.today().normalize()

    def fetch(tickers):
        out = {t: _series(10, 12) for t in tickers}
        out["^VIX9D"] = _series(10, 12, last=today - pd.Timedelta(days=1))
        return out

    d = wm.build(fetch=fetch, cboe=lambda s: {"^VIX": 30.0, "^VIX9D": 9.0}, fear_greed=lambda: None, use_cache=False)
    by = {r["key"]: r for r in d["items"]}
    assert by["^VIX"]["price"] == 30.0 and by["^VIX"]["as_of"] == str(today.date())
    assert by["^VIX9D"]["price"] == 9.0 and by["^VIX9D"]["change_1d"] == -3.0


def test_fetch_failure_gives_empty_card_not_error():
    def boom(tickers):
        raise RuntimeError("Yahoo down")

    mood = {"value": 40, "label": "Fear"}
    d = wm.build(fetch=boom, cboe=lambda s: {}, fear_greed=lambda: mood, use_cache=False)
    assert d["items"] == [] and d["vix_term"] is None and d["crypto_mood"] == mood
    assert len(d["failed"]) == len(wm.ITEMS)
