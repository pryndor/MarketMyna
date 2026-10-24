"""Crypto market mood (src/services/crypto_mood.py), offline."""

import numpy as np
import pandas as pd

from src.services import crypto_mood as cm

IDX = pd.date_range("2026-04-01", periods=180)


def _coins(start, end, n=30):
    return {f"C{i}-USD": pd.Series(np.linspace(start, end, len(IDX)), index=IDX) for i in range(n)}


def test_rally_reads_greed_and_selloff_fear():
    up = cm.readings(_coins(100, 200), [3.0] * 25 + [-1.0] * 5, pd.Series(np.linspace(50, 100, len(IDX)), index=IDX), 40.0)
    by = {p["key"]: p for p in up}
    assert by["above_50"]["score"] == 100 and by["highs_lows"]["score"] == 100
    assert by["momentum"]["score"] > 50 and by["funding"]["score"] > 90
    assert cm.label(sum(p["score"] for p in up) / len(up)) in ("Greed", "Extreme greed")

    down = cm.readings(_coins(200, 100), [-3.0] * 30, pd.Series(np.linspace(100, 50, len(IDX)), index=IDX), -5.0)
    by = {p["key"]: p for p in down}
    assert by["breadth"]["score"] == 0 and by["above_100"]["score"] == 0 and by["funding"]["score"] < 20


def test_build_uses_screens_universe_and_skips_missing_funding():
    rows = [{"symbol": f"C{i}-USD", "name": f"C{i}", "volume": 1000 - i, "change_percent": 1.0} for i in range(30)]
    rows.append({"symbol": "USDT-USD", "name": "Tether", "volume": 10**9, "change_percent": 0.0})
    closes = {**_coins(100, 120), "BTC-USD": pd.Series(np.linspace(50, 60, len(IDX)), index=IDX)}
    out = cm.build(rows, fetch=lambda t: {k: closes[k] for k in t if k in closes}, funding=lambda: None, use_cache=False)
    assert out["market"] == "crypto" and out["score"] is not None
    assert "funding" not in {p["key"] for p in out["readings"]}
    assert "31 most-traded" in out["universe"]  # 30 coins + Bitcoin, which the universe always adds
