"""Tests for the commodities snapshot (offline)."""

import numpy as np
import pandas as pd
import pytest

from marketmyna.services import commodities as cm

IDX = pd.bdate_range(end="2026-09-30", periods=300)


def _fetch(tickers):
    out = {t: pd.Series(np.linspace(100, 110, len(IDX)), index=IDX) for t in tickers if t != "NG=F"}
    out["GC=F"] = pd.Series(np.full(len(IDX), 3110.34768), index=IDX)
    out["USDINR=X"] = pd.Series(np.full(len(IDX), 85.0), index=IDX)
    return out


def test_build_rows_changes_and_rupee_gold():
    out = cm.build(_fetch, use_cache=False)
    keys = [r["key"] for r in out["items"]]
    assert "NG=F" not in keys  # missing ticker skipped
    wti = next(r for r in out["items"] if r["key"] == "CL=F")
    assert wti["price"] == pytest.approx(110)
    assert wti["change_1y"] > 0 and wti["change_1d"] > 0 and wti["spark"]
    gold_inr = next(r for r in out["items"] if r["key"] == "GC=F:INR")
    assert gold_inr["unit"] == "₹/10g"
    assert gold_inr["price"] == pytest.approx(3110.34768 * 85 / cm.TROY_OZ_G * 10)  # = 85,000
    assert out["usd_inr"] == 85.0


def test_fetch_failure_returns_empty():
    def boom(_):
        raise RuntimeError("down")
    assert cm.build(boom, use_cache=False)["items"] == []
