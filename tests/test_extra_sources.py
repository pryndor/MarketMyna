"""Backup data sources (Tencent, Finnhub, Alpha Vantage) with canned responses."""

import pytest

from marketmyna.core.constants import TimeFrame
from marketmyna.data import extra_sources as xs


class _Resp:
    def __init__(self, payload=None, content=b"", status=200):
        self._payload, self.content, self.status_code = payload, content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._payload


QUOTE = ('v_sh600519="1~贵州茅台~600519~1237.00~1251.24~1250.01~31239~13918~17321' + "~0" * 22
         + '~-14.24~-1.14~1256.13~1231.05~1237.00/31239~31239";').encode("gbk")


def test_tencent_symbols():
    assert xs.tencent_symbol("600519", "china_a") == "sh600519"
    assert xs.tencent_symbol("000001", "china_a") == "sz000001"
    assert xs.tencent_symbol("830799", "china_a") == "bj830799"
    assert xs.tencent_symbol("700", "hong_kong") == "hk00700"


def test_tencent_quote(monkeypatch):
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp(content=QUOTE))
    q = xs.tencent_quote("600519", "china_a")
    assert q["name"] == "贵州茅台"
    assert q["price"] == 1237.0 and q["previous_close"] == 1251.24
    assert q["change"] == -14.24 and q["change_percent"] == -1.14
    assert q["day_high"] == 1256.13 and q["day_low"] == 1231.05
    assert q["volume"] == 3123900  # lots -> shares


def test_tencent_history(monkeypatch):
    payload = {"data": {"hk00700": {"qfqday": [
        ["2026-09-23", "430.0", "438.4", "440.0", "428.0", "1000"],
        ["2026-09-24", "438.4", "434.2", "436.2", "431.2", "2000", {"extra": 1}],
    ]}}}
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp(payload))
    df = xs.tencent_history("00700", "hong_kong", period="1mo")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].tolist() == [438.4, 434.2]
    assert df["volume"].tolist() == [1000, 2000]
    with pytest.raises(ValueError):
        xs.tencent_history("00700", "hong_kong", interval=TimeFrame.WEEK_1)


def test_finnhub_needs_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with pytest.raises(ValueError):
        xs.finnhub_quote("AAPL")
    monkeypatch.setenv("FINNHUB_API_KEY", "k")
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp({"c": 335.9, "pc": 337, "o": 336, "h": 338, "l": 334, "d": -1.1, "dp": -0.33}))
    q = xs.finnhub_quote("AAPL")
    assert q["price"] == 335.9 and q["change_percent"] == -0.33


def test_alphavantage_rate_limit_is_an_error(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "k")
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp({"Information": "rate limit reached"}))
    with pytest.raises(ValueError, match="rate limit"):
        xs.alphavantage_quote("AAPL")


def test_alphavantage_history(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "k")
    from datetime import date, timedelta

    d1, d2 = (date.today() - timedelta(days=2)).isoformat(), (date.today() - timedelta(days=1)).isoformat()
    series = {d: {"1. open": "1", "2. high": "2", "3. low": "0.5", "4. close": c, "5. volume": "10"}
              for d, c in ((d2, "1.5"), (d1, "1.2"))}
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp({"Time Series (Daily)": series}))
    df = xs.alphavantage_history("AAPL", period="1mo")
    assert df["close"].tolist() == [1.2, 1.5]  # sorted oldest first


def test_china_chain_uses_tencent_when_akshare_missing(monkeypatch):
    from marketmyna.data.china import ChinaAFetcher

    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp(content=QUOTE))
    import marketmyna.data.china as china

    monkeypatch.setattr(china, "tencent_quote", lambda code, market: {"price": 1237.0, "source": "tencent"})
    fetcher = ChinaAFetcher()
    monkeypatch.setattr(fetcher, "_fetch_quote_akshare", lambda s: (_ for _ in ()).throw(ImportError("no akshare")))
    assert fetcher.get_quote("600519")["source"] == "tencent"


def _recent(days_ago: int) -> str:
    from datetime import date, timedelta

    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_key_prefers_env_then_saved_config(monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    monkeypatch.delenv("TWELVE_DATA_API_KEY", raising=False)
    monkeypatch.setattr(xs, "_config_key", lambda field: "saved" if field == "twelvedata_api_key" else None)
    xs._key_cache.clear()
    assert xs.twelvedata_key() == "saved"
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "env")
    assert xs.twelvedata_key() == "env"


def test_nasdaq_quote_and_history(monkeypatch):
    from datetime import date, timedelta

    info = {"data": {"primaryData": {"lastSalePrice": "$342.13", "netChange": "+1.16",
                                     "percentageChange": "+0.34%", "volume": "85,570"}}}
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp(info))
    q = xs.nasdaq_quote("AAPL")
    assert q["price"] == 342.13 and q["change"] == 1.16 and q["change_percent"] == 0.34
    assert round(q["previous_close"], 2) == 340.97

    d1, d2 = (date.today() - timedelta(days=2)), (date.today() - timedelta(days=1))
    hist = {"data": {"tradesTable": {"rows": [
        {"date": d2.strftime("%m/%d/%Y"), "close": "$340.97", "volume": "25,900,600", "open": "$338.215",
         "high": "$342.63", "low": "$337.60"},
        {"date": d1.strftime("%m/%d/%Y"), "close": "$336.64", "volume": "37,881,200", "open": "$331.695",
         "high": "$338.61", "low": "$330.70"},
    ]}}}
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp(hist))
    df = xs.nasdaq_history("AAPL", period="1mo")
    assert df["close"].tolist() == [336.64, 340.97]  # oldest first
    assert df["volume"].iloc[-1] == 25900600


def test_nasdaq_no_data_is_an_error(monkeypatch):
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp({"data": None, "status": {
        "bCodeMessage": [{"errorMessage": "Symbol not exists"}]}}))
    with pytest.raises(ValueError, match="not exists"):
        xs.nasdaq_quote("ZZZZ")


def test_twelvedata_india_symbol_and_errors(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")
    seen = {}

    def get(url, params=None, **kw):
        seen.update(params)
        return _Resp({"close": "1412.5", "previous_close": "1400", "open": "1401", "high": "1420", "low": "1398",
                      "volume": "123", "change": "12.5", "percent_change": "0.89"})

    monkeypatch.setattr(xs.requests, "get", get)
    q = xs.twelvedata_quote("RELIANCE.BO", "india")
    assert seen["symbol"] == "RELIANCE" and seen["exchange"] == "BSE"
    assert q["price"] == 1412.5 and q["change_percent"] == 0.89
    xs.twelvedata_quote("TCS", "india")
    assert seen["exchange"] == "NSE"

    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp({"status": "error", "code": 429,
                                                                    "message": "run out of API credits"}))
    with pytest.raises(ValueError, match="credits"):
        xs.twelvedata_quote("AAPL")


def test_twelvedata_history(monkeypatch):
    monkeypatch.setenv("TWELVEDATA_API_KEY", "k")
    values = [{"datetime": _recent(1), "open": "2", "high": "3", "low": "1", "close": "2.5", "volume": "9"},
              {"datetime": _recent(2), "open": "1", "high": "2", "low": "1", "close": "1.5", "volume": "8"}]
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp({"values": values, "status": "ok"}))
    df = xs.twelvedata_history("AAPL", "us", period="1mo")
    assert df["close"].tolist() == [1.5, 2.5]
    with pytest.raises(ValueError):
        xs.twelvedata_history("AAPL", "us", interval=TimeFrame.HOUR_1)


def test_tiingo_uses_adjusted_bars(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "k")
    rows = [{"date": _recent(1) + "T00:00:00.000Z", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 5,
             "adjOpen": 5, "adjHigh": 5.5, "adjLow": 4.5, "adjClose": 5, "adjVolume": 10}]
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp(rows))
    df = xs.tiingo_history("AAPL", period="1mo")
    assert df["close"].tolist() == [5] and df["volume"].tolist() == [10]

    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp([{"tngoLast": 101.0, "prevClose": 100.0,
                                                                     "open": 100.5, "high": 102, "low": 99}]))
    q = xs.tiingo_quote("AAPL")
    assert q["price"] == 101.0 and q["change_percent"] == 1.0


def test_polygon_quote_from_daily_bars(monkeypatch):
    import pandas as pd

    monkeypatch.setenv("POLYGON_KEY", "k")
    # Polygon stamps a daily bar at midnight New York time
    t = lambda d: int(pd.Timestamp(_recent(d), tz="America/New_York").timestamp() * 1000)  # noqa: E731
    rows = [{"t": t(2), "o": 1, "h": 2, "l": 1, "c": 100, "v": 7}, {"t": t(1), "o": 1, "h": 2, "l": 1, "c": 102, "v": 8}]
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp({"status": "OK", "results": rows}))
    q = xs.polygon_quote("AAPL")
    assert q["price"] == 102 and q["previous_close"] == 100 and q["change_percent"] == 2.0
    assert q["as_of"] == _recent(1)


def test_us_chain_falls_back_to_nasdaq_without_keys(monkeypatch):
    import marketmyna.data.stocks as stocks

    for var in ("FINNHUB_API_KEY", "TWELVEDATA_API_KEY", "TWELVE_DATA_API_KEY", "TIINGO_API_KEY",
                "ALPHA_VANTAGE_KEY", "ALPHAVANTAGE_API_KEY", "POLYGON_KEY", "POLYGON_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    from marketmyna.data.resilience import CircuitBreaker, FallbackChain

    breaker = CircuitBreaker()  # failures here must not trip the shared breaker
    monkeypatch.setattr(stocks, "FallbackChain", lambda method: FallbackChain(method, breaker))
    monkeypatch.setattr(stocks, "nasdaq_quote", lambda s: {"symbol": s, "price": 5.0, "source": "nasdaq"})
    fetcher = stocks.StockDataFetcher()
    monkeypatch.setattr(fetcher, "_fetch_quote_yfinance", lambda s: (_ for _ in ()).throw(RuntimeError("429")))
    assert fetcher.get_quote("AAPL")["source"] == "nasdaq"
    # index symbols have no backups
    with pytest.raises(Exception):
        fetcher.get_quote("^GSPC")


def test_coingecko_id_picks_best_ranked_exact_symbol(monkeypatch):
    xs._coin_ids.clear()
    calls = []

    def get(url, params=None, **kw):
        calls.append(url)
        if url.endswith("/search"):
            return _Resp({"coins": [{"id": "solv-protocol", "symbol": "SOLV", "market_cap_rank": 801},
                                    {"id": "fake-sol", "symbol": "SOL", "market_cap_rank": 3000},
                                    {"id": "solana", "symbol": "SOL", "market_cap_rank": 7}]})
        return _Resp([{"current_price": 108.0, "price_change_24h": -4.0, "price_change_percentage_24h": -3.6,
                       "high_24h": 112, "low_24h": 102, "total_volume": 9}])

    monkeypatch.setattr(xs.requests, "get", get)
    assert xs.coin_base("SOL-USD") == xs.coin_base("SOLUSDT") == xs.coin_base("sol") == "SOL"
    q = xs.coingecko_quote("SOL-USD")
    assert q["price"] == 108.0 and q["previous_close"] == 112.0
    xs.coingecko_quote("SOLUSDT")
    assert sum(u.endswith("/search") for u in calls) == 1  # id cached


def test_coingecko_history_dates_midnight_points_to_previous_day(monkeypatch):
    import pandas as pd

    xs._coin_ids["BTC"] = "bitcoin"
    day = pd.Timestamp.today().normalize()
    ms = lambda ts: int(ts.timestamp() * 1000)  # noqa: E731
    prices = [[ms(day - pd.Timedelta(days=1)), 100.0], [ms(day), 110.0], [ms(day + pd.Timedelta(hours=5)), 105.0]]
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp({"prices": prices, "total_volumes": []}))
    df = xs.coingecko_history("BTC-USD", period="1mo")
    assert df["close"].tolist() == [100.0, 110.0, 105.0]
    assert df.index[-1] == day and df.index[-2] == day - pd.Timedelta(days=1)
    assert df["open"].tolist()[1:] == [100.0, 110.0]


def test_crypto_fear_greed(monkeypatch):
    monkeypatch.setattr(xs.requests, "get", lambda *a, **k: _Resp({"data": [
        {"value": "57", "value_classification": "Greed", "timestamp": "1791849600"}]}))
    rows = xs.crypto_fear_greed(1)
    assert rows == [{"date": "2026-10-13", "value": 57, "label": "Greed"}]
