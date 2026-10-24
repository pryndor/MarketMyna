"""Tests for the analyst estimates service (offline)."""

import pandas as pd
import pytest

from marketmyna.services import estimates as est


def _fake(_sym):
    idx = ["0q", "+1q", "0y", "+1y"]
    return {
        "currency": "USD",
        "earnings_estimate": pd.DataFrame({"avg": [2, 3, 9, 10], "low": [1.9, 2.5, 8, 9], "high": [2.1, 3.4, 9.5, 11],
                                           "yearAgoEps": [1.8, 2.8, 8, 9], "numberOfAnalysts": [20, 18, 30, 30],
                                           "growth": [0.11, 0.07, 0.125, 0.11]}, index=idx),
        "revenue_estimate": pd.DataFrame({"avg": [1e9] * 4, "low": [9e8] * 4, "high": [1.1e9] * 4,
                                          "numberOfAnalysts": [10] * 4, "yearAgoRevenue": [9e8] * 4,
                                          "growth": [0.1] * 4}, index=idx),
        "eps_trend": pd.DataFrame({"current": [2, 3, 9, 10], "7daysAgo": [2, 3, 9, 10], "30daysAgo": [2, 3, 8.9, 9.9],
                                   "60daysAgo": [2, 3, 8.7, 9.7], "90daysAgo": [2, 3, 8.5, 9.5]}, index=idx),
        "eps_revisions": pd.DataFrame({"upLast7days": [1, 0, 2, 1], "upLast30days": [5, 1, 6, 4],
                                       "downLast30days": [1, 0, 0, 1], "downLast7Days": [0, 0, 0, 0]}, index=idx),
        "earnings_history": pd.DataFrame({"epsActual": [1.85, 2.84, 2.0], "epsEstimate": [1.77, 2.67, 2.05],
                                          "surprisePercent": [0.045, 0.063, -0.024]},
                                         index=pd.to_datetime(["2025-12-31", "2026-03-31", "2026-06-30"])),
    }


def test_build_estimates():
    out = est.build("X", fetch=_fake)
    assert out["available"] and out["currency"] == "USD"
    assert [p["label"] for p in out["periods"]] == ["Current quarter", "Next quarter", "Current year", "Next year"]
    year = out["periods"][2]
    assert year["eps"]["growth"] == pytest.approx(12.5)
    assert year["trend"]["change_90d"] == pytest.approx((9 / 8.5 - 1) * 100)
    assert year["revisions"]["up_30d"] == 6
    assert out["momentum"]["label"] == "rising"
    assert out["beats"] == {"beat": 2, "total": 3}
    assert out["history"][0] == {"quarter": "2025-12-31", "actual": 1.85, "estimate": 1.77, "surprise": pytest.approx(4.5)}


def test_build_without_coverage():
    out = est.build("X", fetch=lambda s: {t: None for t in est.TABLES})
    assert out == {"currency": None, "periods": [], "history": [], "momentum": None, "beats": None, "available": False}
