"""BSE listings whose Yahoo history is cut short (RELIANCE.BO: one day) fall
back to the same company's NSE history, so charts and indicators work."""

import pandas as pd

from src.data.india import BSE_MIN_BARS, IndiaDataFetcher


def _bars(n):
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": range(n), "volume": 1}, index=idx)


def test_short_bse_history_uses_nse(monkeypatch):
    f = IndiaDataFetcher()
    f._use_jugaad = False
    monkeypatch.setattr(f, "_fetch_history_yfinance",
                        lambda symbol, **kw: _bars(1) if symbol.endswith(".BO") else _bars(120))
    h = f.get_history("RELIANCE.BO", period="6mo")
    assert len(h) == 120 and h.attrs["history_from"] == "NSE"


def test_full_bse_history_is_kept(monkeypatch):
    f = IndiaDataFetcher()
    f._use_jugaad = False
    monkeypatch.setattr(f, "_fetch_history_yfinance", lambda symbol, **kw: _bars(BSE_MIN_BARS + 5))
    h = f.get_history("TCS.BO", period="6mo")
    assert len(h) == BSE_MIN_BARS + 5 and "history_from" not in h.attrs
