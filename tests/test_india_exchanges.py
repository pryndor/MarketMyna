"""NSE vs BSE listings of the same share (src/data/india.py)."""

from src.data.india import IndiaDataFetcher, is_bse


def test_is_bse():
    assert is_bse("RELIANCE.BO") and is_bse("reliance.bo")
    assert not is_bse("RELIANCE") and not is_bse("RELIANCE.NS")


def _fetcher(calls):
    f = IndiaDataFetcher.__new__(IndiaDataFetcher)
    f._use_jugaad = True
    f._fetch_quote_jugaad = lambda s: calls.append(("jugaad", s)) or {"price": 100.0}
    f._fetch_quote_yfinance = lambda s: calls.append(("yfinance", s)) or {"price": 99.5}
    return f


def test_bse_symbol_skips_the_nse_only_source():
    calls: list = []
    assert _fetcher(calls).get_quote("RELIANCE.BO")["price"] == 99.5
    assert calls == [("yfinance", "RELIANCE.BO")]


def test_nse_symbol_still_tries_nse_first():
    calls: list = []
    assert _fetcher(calls).get_quote("RELIANCE")["price"] == 100.0
    assert calls == [("jugaad", "RELIANCE")]


def test_yahoo_symbol_keeps_the_exchange():
    f = IndiaDataFetcher.__new__(IndiaDataFetcher)
    assert f._get_yf_symbol("RELIANCE") == "RELIANCE.NS"
    assert f._get_yf_symbol("RELIANCE.BO") == "RELIANCE.BO"
