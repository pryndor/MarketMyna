"""Tests for sector relative rotation (offline, synthetic closes)."""

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.services import rotation

IDX = pd.date_range(end=datetime(2026, 9, 25), periods=250, freq="B")


def _s(daily_ret, noise_seed):
    r = np.full(len(IDX), daily_ret) + np.random.default_rng(noise_seed).normal(0, 0.002, len(IDX))
    return pd.Series(100 * np.cumprod(1 + r), index=IDX)


def test_quadrants():
    assert rotation.quadrant(101, 101) == "leading"
    assert rotation.quadrant(101, 99) == "weakening"
    assert rotation.quadrant(99, 99) == "lagging"
    assert rotation.quadrant(99, 101) == "improving"


def test_rrg_centred_and_directional():
    bench = _s(0.0005, 1)
    # accelerating out-performance late in the year -> above 100 on both axes
    late = np.r_[np.zeros(200), np.linspace(0, 0.004, 50)] + np.random.default_rng(3).normal(0, 0.002, len(IDX))
    strong = bench * np.cumprod(1 + late)
    path = rotation.rrg(rotation._weekly(strong), rotation._weekly(bench))
    assert path["ratio"].iloc[-1] > 100 and path["ratio"].iloc[-1] > path["ratio"].iloc[-9]


def test_build_baskets_and_payload():
    rows = [{"symbol": f"{c}{i}", "type": "stock", "market_cap": 1000 - i, "category": c}
            for c in ("Tech", "Bank") for i in range(4)]
    rows += [{"symbol": "O1", "type": "stock", "market_cap": 5, "category": "Other"},
             {"symbol": "T1", "type": "stock", "market_cap": 5, "category": "Tiny"}]
    closes = {"^NSEI": _s(0.0004, 9)}
    for i in range(4):
        closes[f"TECH{i}.NS"] = _s(0.0012, i)
        closes[f"BANK{i}.NS"] = _s(-0.0003, 10 + i)
    out = rotation.build("india", rows=rows, fetch=lambda t: {k: closes[k] for k in t if k in closes})
    by = {s["sector"]: s for s in out["sectors"]}
    assert set(by) == {"Tech", "Bank"}  # Other skipped, Tiny has < 3 members
    assert by["Tech"]["members"] == ["Tech0", "Tech1", "Tech2", "Tech3"]
    assert len(by["Tech"]["tail"]) == rotation.TAIL
    assert by["Tech"]["return_4w"] > by["Bank"]["return_4w"]
    assert out["benchmark"]["symbol"] == "^NSEI"


def test_missing_benchmark():
    rows = [{"symbol": f"A{i}", "type": "stock", "market_cap": 10, "category": "X"} for i in range(3)]
    with pytest.raises(ValueError):
        rotation.build("india", rows=rows, fetch=lambda t: {})
