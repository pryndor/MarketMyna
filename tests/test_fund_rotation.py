"""Mutual fund rotation: categories, fund houses and single funds placed in
leading / weakening / lagging / improving vs a benchmark, from weekly NAVs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.services import fund_rotation as F

DAYS = pd.bdate_range("2025-10-01", periods=260)


def _row(code, name, amc, sector, category="Equity", plan="Direct", option="Growth"):
    return {"symbol": str(code), "name": name, "type": "mf", "amc": amc, "sector": sector,
            "category": category, "plan": plan, "option": option}


def _series(drift):
    return pd.Series(100 * np.cumprod(1 + np.full(len(DAYS), drift)), index=DAYS)


def test_groups_drill_and_dedupe():
    rows = [
        _row(1, "Alpha Large Cap Fund - Direct Plan - Growth", "Alpha MF", "Large Cap Fund"),
        _row(2, "Beta Large Cap Fund - Direct Plan - Growth", "Beta MF", "Large Cap Fund"),
        _row(3, "Gamma Large Cap Fund - Direct Plan - Growth", "Gamma MF", "Large Cap Fund"),
        _row(4, "Alpha Small Cap Fund - Direct Plan - Growth", "Alpha MF", "Small Cap Fund"),
        _row(5, "Beta Small Cap Fund - Direct Plan - Growth", "Beta MF", "Small Cap Fund"),
        _row(6, "Gamma Small Cap Fund - Direct Plan - Growth", "Gamma MF", "Small Cap Fund"),
        _row(7, "Gamma Small Cap Fund - Direct Plan - Growth", "Gamma MF", "Small Cap Fund"),  # merged duplicate
        _row(8, "Alpha Large Cap Fund - Regular Plan - Growth", "Alpha MF", "Large Cap Fund", plan="Regular"),
        _row(9, "Alpha Liquid Fund - Direct Plan - Growth", "Alpha MF", "Liquid Fund", category="Debt"),
    ]
    # Small caps outrun the benchmark, large caps trail it; small caps accelerate lately.
    def nav(code):
        if code in (4, 5, 6, 7):
            s = _series(0.0015)
            s.iloc[-40:] *= np.cumprod(np.full(40, 1.002))
            return s
        return _series(0.0002)

    bench = lambda: F._weekly(_series(0.0008))  # noqa: E731
    out = F.build("category", rows=rows, nav=nav, bench=bench)
    by_name = {i["name"]: i for i in out["items"]}
    assert set(by_name) == {"Large Cap Fund", "Small Cap Fund"}
    assert by_name["Small Cap Fund"]["ratio"] > 100 > by_name["Large Cap Fund"]["ratio"]
    assert by_name["Small Cap Fund"]["funds"] == 3  # duplicate scheme counted once; Regular / debt excluded
    assert all(i["quadrant"] in ("leading", "weakening", "lagging", "improving") for i in out["items"])
    assert len(by_name["Small Cap Fund"]["tail"]) == 8

    drill = F.build("category", "Small Cap Fund", rows=rows, nav=nav, bench=bench)
    assert [i["name"] for i in drill["items"]] == ["Alpha Small Cap Fund", "Beta Small Cap Fund", "Gamma Small Cap Fund"] or \
        sorted(i["name"] for i in drill["items"]) == ["Alpha Small Cap Fund", "Beta Small Cap Fund", "Gamma Small Cap Fund"]

    houses = F.build("amc", rows=rows, nav=nav, bench=bench)
    assert {i["name"] for i in houses["items"]} == set()  # every house has < 3 equity funds here
