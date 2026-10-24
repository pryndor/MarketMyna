"""Tests for the macro dashboard shaping (offline, synthetic FRED series)."""

import pandas as pd
import pytest

from marketmyna.services import macro


def _monthly(values, start="2021-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float)


def test_yoy_transform_and_changes():
    cpi = _monthly([100 * 1.003 ** i for i in range(60)])
    item = macro.shape("CPIAUCSL", "CPI", "us", "%", "yoy", "", cpi)
    assert item["value"] == pytest.approx((1.003 ** 12 - 1) * 100)
    assert item["change_1y"] == pytest.approx(0, abs=1e-9)
    assert len(item["spark"]) == 36


def test_level_changes():
    rate = _monthly([1.0] * 48 + [2.0] * 11 + [3.0])
    item = macro.shape("FEDFUNDS", "Fed", "us", "%", "level", "", rate)
    assert item["value"] == 3.0 and item["change_1m"] == 1.0 and item["change_1y"] == 2.0


def test_build_reports_failures_and_curve():
    def fetch(series_id, start):
        if series_id == "DGS2":
            raise RuntimeError("down")
        if series_id == "T10Y2Y":
            return _monthly([0.5] * 30 + [-0.2] * 30)
        return _monthly([2.0] * 60)

    out = macro.build(fetch, use_cache=False)
    assert "US 2-year yield" in out["failed"]
    assert out["signals"]["us_curve_inverted"] is True
    assert len(out["series"]) == len(macro.SERIES) - 1
    assert any("Fed funds rate: 2.00%" in line for line in macro.context_lines(out))


def test_yield_curve_shape_and_history():
    import pandas as pd

    from marketmyna.services import macro as m

    idx = pd.bdate_range(end="2026-09-30", periods=300)
    def fetch(sid, start):
        years = next(y for i, _, y in m.CURVE if i == sid)
        # inverted a year ago, normal now: slope rises linearly through time
        slope = pd.Series(range(len(idx)), index=idx) / len(idx) - 0.6
        return 4 + slope * min(years, 10) / 10
    out = m.yield_curve(fetch, use_cache=False)
    assert [p["tenor"] for p in out["points"]][:3] == ["1M", "3M", "6M"]
    assert out["as_of"] == "2026-09-30"
    ten = next(p for p in out["points"] if p["tenor"] == "10Y")
    assert ten["now"] > ten["month_ago"] > ten["year_ago"]
    assert out["shape"]["label"] in ("flat", "normal") and out["shape"]["spread_10y_3m"] > 0


def test_yield_curve_all_failed():
    from marketmyna.services import macro as m

    def boom(*_):
        raise RuntimeError("down")
    assert m.yield_curve(boom, use_cache=False)["points"] == []
