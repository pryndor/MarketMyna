"""Finnhub: real-time US stock prices for the Markets / Watchlist tables.

Free key at finnhub.io (Dashboard -> API key). Uses:
- the trades WebSocket (wss://ws.finnhub.io) for every US symbol on
  screen: each trade updates the price immediately;
- the REST quote (/api/v1/quote, free tier 60 calls/min) once per symbol per
  day for the previous close (to compute % change) and a starting price.

One connection is shared by all users. The free plan streams a limited
number of symbols at once (about 50), so the most recently viewed ones are
subscribed first.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.finnhub.io"
REST = "https://finnhub.io/api/v1/quote"
MAX_SUBSCRIPTIONS = int(os.environ.get("FINNHUB_MAX_SYMBOLS", 50))
REST_GAP = 1.1  # seconds between REST calls: stays under 60/min


def configured(config) -> bool:
    return bool(getattr(config, "finnhub_api_key", None))


def _us_date(epoch: float):
    return datetime.fromtimestamp(epoch, ZoneInfo("America/New_York")).date()


class FinnhubStream:
    def __init__(self, key: str):
        self.key = key
        self.trades: dict[str, dict] = {}  # symbol -> {price, time}
        self.base: dict[str, dict] = {}  # symbol -> {prev_close, price, time, day} from REST
        self.wanted: list[str] = []  # most recent first
        self.subscribed: set[str] = set()
        self.error: Optional[str] = None
        self._lock = threading.Lock()
        self._ws = None
        self._stop = threading.Event()
        self._rest_queue: deque[str] = deque()
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        for target, name in ((self._run_ws, "finnhub-ws"), (self._run_rest, "finnhub-rest")):
            t = threading.Thread(target=target, name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        ws = self._ws
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    # ------------------------------------------------------------ demand
    def want(self, symbols: list[str]) -> None:
        """Symbols currently on screen; newest demand first, capped."""
        with self._lock:
            fresh = list(dict.fromkeys(s.upper() for s in symbols))
            self.wanted = (fresh + [s for s in self.wanted if s not in set(fresh)])[:MAX_SUBSCRIPTIONS]
            today = _us_date(time.time())
            for s in self.wanted:
                b = self.base.get(s)
                if (b is None or b.get("day") != today) and s not in self._rest_queue:
                    self._rest_queue.append(s)
        self._sync()

    def _sync(self) -> None:
        ws = self._ws
        if ws is None:
            return
        with self._lock:
            target = set(self.wanted)
            add, drop = target - self.subscribed, self.subscribed - target
        try:
            for s in drop:
                ws.send(json.dumps({"type": "unsubscribe", "symbol": s}))
            for s in add:
                ws.send(json.dumps({"type": "subscribe", "symbol": s}))
            with self._lock:
                self.subscribed = (self.subscribed - drop) | add
        except Exception as exc:
            logger.debug("Finnhub subscribe failed: %s", exc)

    # ------------------------------------------------------------ snapshot
    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        out = {}
        with self._lock:
            for s in (x.upper() for x in symbols):
                b, t = self.base.get(s), self.trades.get(s)
                price = t["price"] if t else (b or {}).get("price")
                if not price:
                    continue
                prev = (b or {}).get("prev_close")
                when = t["time"] if t else (b or {}).get("time") or time.time()
                out[s] = {
                    "price": price,
                    "change": round(price - prev, 4) if prev else None,
                    "change_percent": round((price - prev) / prev * 100, 2) if prev else None,
                    "volume": None,  # Finnhub trades carry per-trade size, not the day's volume
                    "time": when,
                }
        return out

    # ------------------------------------------------------------ workers
    def _run_ws(self) -> None:
        from websockets.sync.client import connect

        backoff = 2.0
        while not self._stop.is_set():
            try:
                with connect(f"{WS_URL}?token={self.key}", open_timeout=15, close_timeout=2) as ws:
                    self._ws, self.error, backoff = ws, None, 2.0
                    with self._lock:
                        self.subscribed = set()
                    self._sync()
                    while not self._stop.is_set():
                        try:
                            raw = ws.recv(timeout=5)
                        except TimeoutError:
                            self._sync()
                            continue
                        self._on_message(raw)
            except Exception as exc:
                self.error = f"Finnhub stream: {exc}"
                logger.warning("Finnhub WebSocket dropped: %s", exc)
            finally:
                self._ws = None
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 60)

    def _on_message(self, raw) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("type") == "error":
            self.error = f"Finnhub: {msg.get('msg')}"
            return
        if msg.get("type") != "trade":
            return  # "ping" keep-alives
        with self._lock:
            for t in msg.get("data") or []:
                sym, price, ms = t.get("s"), t.get("p"), t.get("t")
                if not sym or not price:
                    continue
                cur = self.trades.get(sym)
                when = (ms or 0) / 1000 or time.time()
                if cur is None or when >= cur["time"]:
                    self.trades[sym] = {"price": float(price), "time": when}

    def _run_rest(self) -> None:
        import requests

        while not self._stop.is_set():
            with self._lock:
                sym = self._rest_queue.popleft() if self._rest_queue else None
            if sym is None:
                self._stop.wait(0.5)
                continue
            try:
                r = requests.get(REST, params={"symbol": sym, "token": self.key}, timeout=10)
                if r.status_code == 429:
                    with self._lock:
                        self._rest_queue.appendleft(sym)
                    self._stop.wait(10)
                    continue
                q = r.json() if r.ok else {}
                if q.get("c"):
                    with self._lock:
                        self.base[sym] = {"prev_close": q.get("pc"), "price": q.get("c"),
                                          "time": q.get("t") or time.time(), "day": _us_date(time.time())}
            except Exception as exc:
                logger.debug("Finnhub quote %s failed: %s", sym, exc)
            self._stop.wait(REST_GAP)


_stream: Optional[FinnhubStream] = None
_stream_lock = threading.Lock()


def stream(config) -> FinnhubStream:
    """The shared stream; restarted when the key changes."""
    global _stream
    key = config.finnhub_api_key
    with _stream_lock:
        if _stream is None or _stream.key != key:
            if _stream is not None:
                _stream.stop()
            _stream = FinnhubStream(key)
            _stream.start()
        return _stream
