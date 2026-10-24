"""Live quotes cache: answers instantly from cache, refreshes upstream in the
background at most once per interval for everything being watched."""

from __future__ import annotations

import time

from marketmyna.services import live_quotes as L


def test_cached_answers_and_one_batched_refresh(monkeypatch):
    monkeypatch.setattr(L, "_markets", {})
    calls: list[list[str]] = []

    def fake_yahoo(symbols, market):
        calls.append(sorted(symbols))
        return {s: {"price": 100.0, "change": 1.0, "change_percent": 1.0, "volume": 5.0, "time": time.time()}
                for s in symbols}

    monkeypatch.setattr(L, "_fetch_yahoo", fake_yahoo)
    monkeypatch.setattr("marketmyna.trading.market_hours.is_open", lambda m, now=None: True)

    first = L.get("us", ["aapl", "MSFT"])
    assert first["quotes"] == {}  # never blocks on the upstream call
    for _ in range(50):
        if L.get("us", ["AAPL", "MSFT"])["quotes"]:
            break
        time.sleep(0.02)
    out = L.get("us", ["AAPL", "MSFT"])
    assert set(out["quotes"]) == {"AAPL", "MSFT"} and out["last_trade"] is not None
    # Asking again within the refresh interval doesn't hit the source again.
    for _ in range(5):
        L.get("us", ["AAPL", "MSFT"])
    assert calls == [["AAPL", "MSFT"]]


def test_failure_keeps_last_prices(monkeypatch):
    monkeypatch.setattr(L, "_markets", {})
    monkeypatch.setattr("marketmyna.trading.market_hours.is_open", lambda m, now=None: True)
    m = L._market("crypto")
    m.quotes["BTC-USD"] = {"price": 1.0, "time": time.time()}
    m.watched["BTC-USD"] = time.monotonic()

    def boom(symbols):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(L, "_fetch_crypto", boom)
    L._refresh("crypto")
    out = L.get("crypto", ["BTC-USD"])
    assert out["quotes"]["BTC-USD"]["price"] == 1.0 and out["error"]


def test_angel_login_quotes_and_live_routing(monkeypatch, tmp_path):
    """Angel One: TOTP login, token map, quote parsing, and India routed to it."""
    from dataclasses import replace

    from marketmyna.core.config import Config
    from marketmyna.services.brokers import angel

    config = replace(Config(), app_dir=tmp_path, angel_api_key="k", angel_client_code="A123",
                     angel_pin="1234", angel_totp_secret="JBSWY3DPEHPK3PXP")
    posts: list[tuple[str, dict]] = []

    class Resp:
        def __init__(self, data, status=200):
            self._d, self.status_code = data, status

        def json(self):
            return self._d

        def raise_for_status(self):
            pass

    def fake_post(url, headers=None, data=None, timeout=None):
        import json

        body = json.loads(data)
        posts.append((url, body))
        if url.endswith("loginByPassword"):
            assert headers["X-PrivateKey"] == "k" and body["clientcode"] == "A123" and len(body["totp"]) == 6
            return Resp({"status": True, "data": {"jwtToken": "jwt-1"}})
        assert headers["Authorization"] == "Bearer jwt-1"
        assert body == {"mode": "FULL", "exchangeTokens": {"NSE": ["2885"]}}
        return Resp({"status": True, "data": {"fetched": [{
            "symbolToken": "2885", "ltp": 1171.5, "netChange": 3.8, "percentChange": 0.33,
            "tradeVolume": 1200000, "exchFeedTime": "02-Oct-2026 15:29:59"}], "unfetched": []}})

    def fake_get(url, timeout=None):
        return Resp([{"token": "2885", "symbol": "RELIANCE-EQ", "exch_seg": "NSE", "instrumenttype": ""},
                     {"token": "999", "symbol": "RELIANCE24OCTFUT", "exch_seg": "NFO", "instrumenttype": "FUTSTK"}])

    monkeypatch.setattr("requests.post", fake_post)
    monkeypatch.setattr("requests.get", fake_get)
    monkeypatch.setattr(angel, "_client", None)

    q = angel.client(config).quotes(["reliance", "UNKNOWN"])
    assert q == {"RELIANCE": {"price": 1171.5, "change": 3.8, "change_percent": 0.33, "volume": 1200000.0,
                              "time": q["RELIANCE"]["time"]}}
    assert sum(u.endswith("loginByPassword") for u, _ in posts) == 1

    # India now goes to Angel One, every second; Yahoo is not touched.
    monkeypatch.setattr(L, "_broker_config", lambda: config)
    monkeypatch.setattr(L, "_broker_failed_at", 0.0)
    monkeypatch.setattr(L, "_fetch_yahoo", lambda s, m: (_ for _ in ()).throw(AssertionError("no yahoo")))
    assert L.refresh_seconds("india") == L.BROKER_REFRESH and L.source("india") == "Broker feed, live"
    assert L._fetch_india(["RELIANCE"])["RELIANCE"]["price"] == 1171.5


def test_angel_rate_limit_does_not_relogin_and_pacing(monkeypatch, tmp_path):
    from dataclasses import replace

    import pytest

    from marketmyna.core.config import Config
    from marketmyna.services.brokers import angel

    config = replace(Config(), app_dir=tmp_path, angel_api_key="k", angel_client_code="A1",
                     angel_pin="1", angel_totp_secret="JBSWY3DPEHPK3PXP")
    logins = []

    class Resp:
        def __init__(self, data, status=200):
            self._d, self.status_code = data, status

        def json(self):
            if self._d is None:
                raise ValueError
            return self._d

    def fake_post(url, headers=None, data=None, timeout=None):
        if url.endswith("loginByPassword"):
            logins.append(1)
            return Resp({"status": True, "data": {"jwtToken": "t"}})
        return Resp(None, status=403)  # "Access denied because of exceeding rate limit"

    monkeypatch.setattr("requests.post", fake_post)
    c = angel.AngelClient(config)
    c._tokens, c._tokens_at = {"SBIN": "3045"}, __import__("time").time()
    with pytest.raises(angel.AngelError, match="rate limit"):
        c.quotes(["SBIN"])
    assert len(logins) == 1  # no extra login on a rate-limit error

    # 120 watched symbols = 3 batches: refresh slows to stay under 5000 calls/hour.
    monkeypatch.setattr(L, "_markets", {})
    monkeypatch.setattr(L, "_broker_config", lambda: config)
    monkeypatch.setattr(L, "_broker_failed_at", 0.0)
    m = L._market("india")
    for i in range(120):
        m.watched[f"S{i}"] = 0.0
    secs = L.refresh_seconds("india")
    assert secs >= 3 / angel.CALLS_PER_SECOND and 3600 / secs * 3 <= 5000

    # Over the limit: Yahoo answers, and Angel is left alone for the next minute.
    angel_calls = []
    monkeypatch.setattr(angel, "client", lambda cfg: angel_calls.append(1) or (_ for _ in ()).throw(
        angel.AngelError("Angel One answered HTTP 403 (rate limit exceeded)", http=403)))
    monkeypatch.setattr(L, "_fetch_yahoo", lambda s, m: {x: {"price": 1.0} for x in s})
    assert L._fetch_india(["SBIN"]) == {"SBIN": {"price": 1.0}}
    assert L._fetch_india(["SBIN"]) == {"SBIN": {"price": 1.0}}
    assert len(angel_calls) == 1
    assert L.source("india") != "Angel One, live" and L.refresh_seconds("india") == L.REFRESH["india"]


def test_finnhub_stream_end_to_end_with_fake_server(monkeypatch):
    """Real connect / subscribe / receive against a local server speaking
    Finnhub's protocol; REST quote gives the previous close."""
    import json
    import threading

    from websockets.sync.server import serve

    from marketmyna.services.brokers import finnhub

    subscribed: list[str] = []

    def handler(ws):
        assert "token=KEY" in ws.request.path
        for raw in ws:
            msg = json.loads(raw)
            if msg["type"] == "subscribe":
                subscribed.append(msg["symbol"])
                ws.send(json.dumps({"type": "ping"}))
                ws.send(json.dumps({"type": "trade", "data": [
                    {"s": msg["symbol"], "p": 231.5, "t": 1790000000000, "v": 10}]}))

    server = serve(handler, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.socket.getsockname()[1]
    monkeypatch.setattr(finnhub, "WS_URL", f"ws://127.0.0.1:{port}")

    class Resp:
        status_code, ok = 200, True

        def json(self):
            return {"c": 230.0, "pc": 225.0, "t": 1789990000}

    monkeypatch.setattr("requests.get", lambda url, params=None, timeout=None: Resp())

    s = finnhub.FinnhubStream("KEY")
    s.start()
    try:
        s.want(["aapl"])
        for _ in range(100):
            q = s.quotes(["AAPL"]).get("AAPL")
            if q and q["price"] == 231.5 and q["change_percent"] is not None:
                break
            time.sleep(0.05)
        assert subscribed == ["AAPL"]
        assert q["price"] == 231.5 and q["change"] == 6.5 and q["change_percent"] == 2.89
    finally:
        s.stop()
        server.shutdown()


def test_us_routes_to_finnhub_when_key_set(monkeypatch):
    from dataclasses import replace

    from marketmyna.core.config import Config
    from marketmyna.services.brokers import finnhub

    config = replace(Config(), finnhub_api_key="KEY")

    class FakeStream:
        def want(self, symbols):
            self.wanted = symbols

        def quotes(self, symbols):
            return {"AAPL": {"price": 1.0, "change": None, "change_percent": None, "volume": None, "time": 0}}

    monkeypatch.setattr(L, "_finnhub_config", lambda: config)
    monkeypatch.setattr(finnhub, "stream", lambda cfg: FakeStream())
    monkeypatch.setattr(L, "_yahoo_us_at", 0.0)
    filled = []
    monkeypatch.setattr(L, "_fetch_yahoo", lambda s, m: filled.append(s) or {})
    assert L.refresh_seconds("us") == 1.0 and L.source("us") == "Real-time feed"
    out = L._fetch_us(["AAPL", "MSFT"])
    assert out["AAPL"]["price"] == 1.0 and filled == [["MSFT"]]  # only the one without a Finnhub price
    L._fetch_us(["AAPL", "MSFT"])
    assert filled == [["MSFT"]]  # Yahoo fill stays at its 15 s pace
