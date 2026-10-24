"""Angel One SmartAPI: live NSE prices for the Markets / Watchlist tables.

Free with an Angel One account (smartapi.angelone.in -> create an app for
the API key). The server logs itself in every day with the client code,
PIN and the TOTP secret shown when enabling TOTP, so prices keep flowing
without a manual morning login.

Only the Market Quote REST endpoint is used (up to 50 symbols per call).
NSE symbols are mapped to Angel's instrument tokens with their public
instrument master, cached on disk for a day.

Note: showing exchange prices to the public needs the exchange's data
licence; check NSE's terms before launch.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import threading
import time
from pathlib import Path
from typing import Optional

from src.core.home import app_home

logger = logging.getLogger(__name__)

API = os.environ.get("ANGEL_API_ROOT", "https://apiconnect.angelone.in")
SCRIP_MASTER = os.environ.get(
    "ANGEL_SCRIP_MASTER", "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json")
BATCH = 50  # symbols per quote call (API limit)
# Market Quote limits per Angel account (docs: RateLimit): 10/s, 500/min,
# 5000/hour. Every app user shares the one account, so stay under the
# hourly cap: about 1.1 calls a second for the tables (~4,000 an hour), which
# leaves room for the Market insights' live prices (services/live_market.py:
# 10 calls a minute for the 500 largest names, ~600 an hour).
CALLS_PER_SECOND = float(os.environ.get("ANGEL_QUOTE_CALLS_PER_SECOND", 1.1))
MASTER_MAX_AGE = 20 * 3600


class AngelError(Exception):
    def __init__(self, message: str, code: str = "", http: int = 0):
        super().__init__(message)
        self.code, self.http = code, http

    @property
    def session_expired(self) -> bool:
        # AG8001 invalid / AG8002 expired / AG8003 missing token (docs: Error Codes).
        return self.http == 401 or self.code in ("AG8001", "AG8002", "AG8003")


def totp(secret: str, now: Optional[float] = None, digits: int = 6, step: int = 30) -> str:
    """RFC 6238 time-based code from a base32 secret (what authenticator apps show)."""
    key = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret.replace(" ", "")) % 8))
    counter = int((now if now is not None else time.time()) // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def configured(config) -> bool:
    return all(getattr(config, f, None) for f in ("angel_api_key", "angel_client_code", "angel_pin", "angel_totp_secret"))


def _headers(config, token: Optional[str] = None) -> dict:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "127.0.0.1",
        "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress": "00:00:00:00:00:00",
        "X-PrivateKey": config.angel_api_key,
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _post(path: str, config, body: dict, token: Optional[str] = None) -> dict:
    import requests

    r = requests.post(API + path, headers=_headers(config, token), data=json.dumps(body), timeout=10)
    try:
        data = r.json()
    except ValueError:
        detail = "rate limit exceeded" if r.status_code == 403 else "no JSON"
        raise AngelError(f"Angel One answered HTTP {r.status_code} ({detail})", http=r.status_code)
    # The docs use both status/errorcode and success/errorCode.
    ok = data.get("status", data.get("success", False))
    code = data.get("errorcode") or data.get("errorCode") or ""
    if r.status_code >= 400 or not ok:
        raise AngelError(data.get("message") or f"Angel One error (HTTP {r.status_code})", code=code, http=r.status_code)
    return data


class AngelClient:
    """One logged-in session, shared; logs in again when it expires."""

    def __init__(self, config):
        self.config = config
        self._token: Optional[str] = None
        self._logged_at = 0.0
        self._lock = threading.Lock()
        self._tokens: dict[str, str] = {}  # NSE symbol -> instrument token
        self._tokens_at = 0.0

    # -------------------------------------------------------------- session
    def login(self) -> str:
        cfg = self.config
        data = _post("/rest/auth/angelbroking/user/v1/loginByPassword", cfg, {
            "clientcode": cfg.angel_client_code, "password": cfg.angel_pin, "totp": totp(cfg.angel_totp_secret),
        })
        token = (data.get("data") or {}).get("jwtToken")
        if not token:
            raise AngelError("Angel One login returned no session token")
        self._token, self._logged_at = token, time.time()
        return token

    def _session(self) -> str:
        with self._lock:
            # A SmartAPI session lasts until 12 midnight (IST): log in again on a new day.
            if not self._token or _ist_date(self._logged_at) != _ist_date(time.time()):
                self.login()
            return self._token

    # -------------------------------------------------------------- symbols
    def _symbol_tokens(self) -> dict[str, str]:
        if self._tokens and time.time() - self._tokens_at < MASTER_MAX_AGE:
            return self._tokens
        path = Path(getattr(self.config, "app_dir", app_home())) / "cache" / "angel_nse_tokens.json"
        data: Optional[dict] = None
        if path.exists() and time.time() - path.stat().st_mtime < MASTER_MAX_AGE:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                data = None
        if data is None:
            import requests

            r = requests.get(SCRIP_MASTER, timeout=60)
            r.raise_for_status()
            data = parse_master(r.json())
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        self._tokens, self._tokens_at = data, time.time()
        return data

    # -------------------------------------------------------------- quotes
    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        """NSE symbol -> {price, change, change_percent, volume, time}."""
        tokens = self._symbol_tokens()
        wanted = {tokens[s.upper()]: s.upper() for s in symbols if s.upper() in tokens}
        out: dict[str, dict] = {}
        ids = list(wanted)
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i + BATCH]
            body = {"mode": "FULL", "exchangeTokens": {"NSE": chunk}}
            try:
                data = _post("/rest/secure/angelbroking/market/v1/quote/", self.config, body, self._session())
            except AngelError as exc:
                if not exc.session_expired:
                    raise  # e.g. rate limit: logging in again would only add calls
                with self._lock:
                    self._token = None
                data = _post("/rest/secure/angelbroking/market/v1/quote/", self.config, body, self._session())
            for q in (data.get("data") or {}).get("fetched") or []:
                sym = wanted.get(str(q.get("symbolToken")))
                ltp = _num(q.get("ltp"))
                if sym and ltp:
                    out[sym] = {
                        "price": ltp,
                        "change": _num(q.get("netChange")),
                        "change_percent": _num(q.get("percentChange")),
                        "volume": _num(q.get("tradeVolume")),
                        "time": _feed_time(q.get("exchFeedTime")) or time.time(),
                        **order_book(q),
                    }
        return out


def order_book(q: dict) -> dict:
    """FULL-mode extras: pending buy / sell quantity, the best five bids and
    offers, average traded price and circuit limits. Missing fields are left out."""
    out = {
        "buy_qty": _num(q.get("totBuyQuan")),
        "sell_qty": _num(q.get("totSellQuan")),
        "avg_price": _num(q.get("avgPrice")),
        "last_qty": _num(q.get("lastTradeQty")),
        "upper_circuit": _num(q.get("upperCircuit")),
        "lower_circuit": _num(q.get("lowerCircuit")),
    }
    out = {k: v for k, v in out.items() if v is not None}
    depth = q.get("depth") or {}
    sides = {}
    for side in ("buy", "sell"):
        levels = [{"price": _num(lv.get("price")), "quantity": _num(lv.get("quantity")), "orders": _num(lv.get("orders"))}
                  for lv in depth.get(side) or [] if isinstance(lv, dict)]
        # Empty levels come back as price 0 (no order at that rank).
        sides[side] = [lv for lv in levels if lv["price"] and lv["quantity"]][:5]
    if sides["buy"] or sides["sell"]:
        out["depth"] = sides
    return out


def parse_master(rows: list[dict]) -> dict[str, str]:
    """NSE cash-market symbols (RELIANCE-EQ, NIFTYBEES-EQ, ...) -> token,
    keyed by the plain symbol MarketMyna uses (RELIANCE)."""
    out: dict[str, str] = {}
    for r in rows:
        # The live file says "NSE"; the docs' sample says "nse_cm".
        if r.get("exch_seg") not in ("NSE", "nse_cm") or r.get("instrumenttype"):
            continue
        sym = str(r.get("symbol", ""))
        for series in ("-EQ", "-BE", "-BZ", "-SM", "-ST"):
            if sym.endswith(series):
                base = sym[: -len(series)]
                # Prefer the normal -EQ series when a symbol trades in several.
                if base not in out or series == "-EQ":
                    out[base] = str(r.get("token"))
                break
    return out


def _ist_date(epoch: float):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.fromtimestamp(epoch, ZoneInfo("Asia/Kolkata")).date()


def _feed_time(text: Optional[str]) -> Optional[float]:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if not text:
        return None
    try:
        return datetime.strptime(text, "%d-%b-%Y %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    except ValueError:
        return None


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_client: Optional[AngelClient] = None
_client_lock = threading.Lock()


def client(config) -> AngelClient:
    """Shared client; rebuilt when the credentials change."""
    global _client
    with _client_lock:
        key = (config.angel_api_key, config.angel_client_code, config.angel_pin, config.angel_totp_secret)
        if _client is None or getattr(_client, "_key", None) != key:
            _client = AngelClient(config)
            _client._key = key  # type: ignore[attr-defined]
        return _client
