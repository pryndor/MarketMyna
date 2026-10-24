"""Portfolio valuation uses NSE's official close once the market has shut."""

from datetime import datetime
from zoneinfo import ZoneInfo

from marketmyna.portfolio.manager import nse_official_close

IST = ZoneInfo("Asia/Kolkata")
ROWS = {"GAEL": {"price": 157.69, "close_date": "2026-10-01"}}


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def test_weekend_uses_official_close():
    assert nse_official_close("GAEL", at(2026, 10, 3, 11, 0), ROWS) == 157.69  # Saturday


def test_market_hours_use_live_quote():
    assert nse_official_close("GAEL", at(2026, 10, 5, 11, 0), ROWS) is None  # Monday session


def test_evening_before_bhavcopy_keeps_live_quote():
    # Monday 16:00: listing still holds Thursday's close.
    assert nse_official_close("GAEL", at(2026, 10, 5, 16, 0), ROWS) is None
    fresh = {"GAEL": {"price": 160.0, "close_date": "2026-10-05"}}
    assert nse_official_close("GAEL", at(2026, 10, 5, 19, 0), fresh) == 160.0


def test_before_open_uses_previous_session_close():
    assert nse_official_close("GAEL", at(2026, 10, 5, 8, 30), ROWS) == 157.69


def test_unknown_symbol_or_missing_date():
    assert nse_official_close("NOPE", at(2026, 10, 3, 11, 0), ROWS) is None
    assert nse_official_close("GAEL", at(2026, 10, 3, 11, 0), {"GAEL": {"price": 1.0}}) is None
