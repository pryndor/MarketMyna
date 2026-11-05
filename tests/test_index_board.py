import pandas as pd

from marketmyna.services import index_board as b


def _daily(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame({"Close": closes, "High": [c + 1 for c in closes], "Low": [c - 1 for c in closes]}, index=idx)


def _intraday(day_prices, prev_prices):
    prev = pd.date_range("2026-03-01 09:15", periods=len(prev_prices), freq="5min")
    day = pd.date_range("2026-03-02 09:15", periods=len(day_prices), freq="5min")
    return pd.DataFrame({"Close": prev_prices + day_prices, "High": prev_prices + day_prices,
                         "Low": prev_prices + day_prices}, index=prev.append(day))


def test_change_against_previous_daily_close():
    q = b.quote_from(_daily([100.0] * 60 + [110.0]), pd.DataFrame(), now=0)
    assert q["prev_close"] == 100 and q["price"] == 110
    assert round(q["change_pct"], 6) == 10
    assert q["vs_50d"] > 0 and q["rsi14"] == 100.0


def test_falls_back_to_sessions_without_daily_history():
    intra = _intraday([105.0, 106.0, 108.0], [99.0, 100.0])
    q = b.quote_from(_daily([108.0]), intra, now=0)
    assert q["prev_close"] == 100 and q["price"] == 108
    assert q["spark"] == [105.0, 106.0, 108.0]  # only the last session
    assert q["rsi14"] is None


def test_lunch_break_stays_in_one_session():
    morning = pd.date_range("2026-03-02 11:20", periods=3, freq="5min")
    afternoon = pd.date_range("2026-03-02 13:00", periods=3, freq="5min")  # 90 min break
    frame = pd.DataFrame({"Close": [1.0] * 6}, index=morning.append(afternoon))
    assert len(b._sessions(frame)) == 1


def test_every_market_has_a_board():
    for m in ("india", "us", "china_a", "hong_kong", "crypto", "all"):
        assert b.BOARDS[m][0][2], m
