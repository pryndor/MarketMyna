"""ECB reference rates as a backup for Yahoo currency pairs (src/data/ecb_fx.py), offline."""

from datetime import date

import pandas as pd
import pytest

from src.data import ecb_fx

PAYLOAD = {"base": "USD", "rates": {
    "2026-10-08": {"EUR": 0.9, "INR": 90.0, "HKD": 7.8},
    "2026-10-09": {"EUR": 0.8, "INR": 96.0, "HKD": 7.8},
}}


@pytest.fixture(autouse=True)
def _clear():
    ecb_fx._cache.clear()
    yield
    ecb_fx._cache.clear()


def _fetch(calls=None):
    def fetch(start, symbols):
        if calls is not None:
            calls.append(symbols)
        return PAYLOAD
    return fetch


def test_pair_names():
    assert ecb_fx.pair("EURUSD=X") == ("EUR", "USD")
    assert ecb_fx.pair("HKD=X") == ("USD", "HKD")
    assert ecb_fx.pair("^GSPC") is None and ecb_fx.pair("DX-Y.NYB") is None


def test_direct_inverse_and_cross_rates():
    s = ecb_fx.series(["USDINR=X", "EURUSD=X", "EURINR=X"], fetch=_fetch())
    assert s["USDINR=X"].iloc[-1] == 96.0
    assert s["EURUSD=X"].iloc[-1] == pytest.approx(1.25)
    assert s["EURINR=X"].iloc[-1] == pytest.approx(120.0)
    assert s["USDINR=X"].attrs["source"] == ecb_fx.SOURCE


def test_fill_only_missing_or_stale_pairs():
    fresh = pd.Series([1.1, 1.2], index=pd.DatetimeIndex(["2026-10-08", "2026-10-09"]))
    calls = []
    data = {"EURUSD=X": fresh}
    ecb_fx.fill(data, ["EURUSD=X", "^GSPC"], fetch=_fetch(calls), today=date(2026, 10, 10))
    assert calls == [] and data["EURUSD=X"] is fresh  # Yahoo fresh: no request

    stale = pd.Series([90.0, 91.0], index=pd.DatetimeIndex(["2026-09-01", "2026-09-02"]))
    data = {"USDINR=X": stale}
    ecb_fx.fill(data, ["USDINR=X", "HKD=X"], fetch=_fetch(calls), today=date(2026, 10, 10))
    assert data["USDINR=X"].iloc[-1] == 96.0 and data["HKD=X"].iloc[-1] == 7.8


def test_guarded_keeps_currencies_when_yahoo_fails(monkeypatch):
    def boom():
        raise RuntimeError("yahoo down")

    monkeypatch.setattr(ecb_fx, "_fetch", _fetch())
    out = ecb_fx.guarded(boom, ["^GSPC", "USDINR=X"])
    assert list(out) == ["USDINR=X"]
    with pytest.raises(RuntimeError):
        ecb_fx.guarded(boom, ["^GSPC"])


def test_backup_failure_leaves_data(monkeypatch):
    def down(start, symbols):
        raise ConnectionError("no network")

    data = {}
    assert ecb_fx.fill(data, ["USDINR=X"], fetch=down) == {}
