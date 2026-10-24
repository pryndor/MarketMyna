"""Market mood gauge (marketmyna/services/market_mood.py), offline."""

import numpy as np
import pandas as pd
import pytest

from marketmyna.services import market_mood as mm

IDX = pd.bdate_range("2025-10-01", periods=260)


def _up(n=30):
    return {f"S{i}": pd.Series(np.linspace(100, 150, len(IDX)), index=IDX) for i in range(n)}


def _down(n=30):
    return {f"S{i}": pd.Series(np.linspace(150, 100, len(IDX)), index=IDX) for i in range(n)}


def test_rising_market_reads_greed():
    vol = pd.Series(np.linspace(30, 12, len(IDX)), index=IDX)  # calm now
    parts = mm.readings(_up(), [1.0] * 25 + [-1.0] * 5, pd.Series(np.linspace(100, 130, len(IDX)), index=IDX), vol, "VIX")
    by = {p["key"]: p for p in parts}
    assert by["breadth"]["score"] == pytest.approx(25 / 30 * 100)
    assert by["above_50"]["score"] == 100 and by["above_200"]["score"] == 100
    assert by["highs_lows"]["score"] == 100
    assert by["momentum"]["score"] > 50 and by["volatility"]["score"] > 90
    assert mm.label(sum(p["score"] for p in parts) / len(parts)) == "Extreme greed"


def test_falling_market_reads_fear_and_missing_parts_drop_out():
    parts = mm.readings(_down(), [-1.0] * 20, pd.Series(np.linspace(130, 100, len(IDX)), index=IDX), None, None)
    by = {p["key"]: p for p in parts}
    assert "volatility" not in by
    assert by["above_200"]["score"] == 0 and by["highs_lows"]["score"] == 0 and by["momentum"]["score"] < 50
    assert mm.label(10) == "Extreme fear" and mm.label(50) == "Neutral" and mm.label(60) == "Greed"


def test_build_uses_largest_stocks():
    rows = [{"symbol": f"S{i}", "type": "stock", "market_cap": 1000 - i, "change_percent": 1.0} for i in range(30)]
    data = {f"S{i}.NS": s for i, s in enumerate(_up().values())}
    data["^NSEI"] = pd.Series(np.linspace(100, 120, len(IDX)), index=IDX)
    d = mm.build("india", fetch=lambda tickers: {t: data[t] for t in tickers if t in data}, rows=rows, use_cache=False)
    assert d["score"] > 75 and d["label"] == "Extreme greed" and "30 largest" in d["universe"]
    with pytest.raises(ValueError):
        mm.build("crypto", rows=rows, use_cache=False)
