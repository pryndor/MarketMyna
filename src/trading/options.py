"""Option chains and analytics.

India: NSE's option-chain (v3) API, which needs a browser-like session.
US / global: Yahoo Finance. Greeks and implied volatility use
Black-Scholes (European; fine for index options, an approximation for
American-style US stock options)."""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import date, datetime
from typing import Optional

from ..core.numbers import finite as _f

logger = logging.getLogger(__name__)

NSE_INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}

RATES = {"india": 0.065, "us": 0.045, "global": 0.045, "hong_kong": 0.04}
CACHE_SECONDS = 60


# ------------------------------------------------------------------ Black-Scholes


def _cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _pdf(x: float) -> float:
    return math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def bs(S: float, K: float, T: float, r: float, sigma: float, kind: str) -> dict:
    """Price and Greeks. theta is per calendar day, vega per 1 vol point."""
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, S - K) if kind == "call" else max(0.0, K - S)
        delta = (1.0 if S > K else 0.0) if kind == "call" else (-1.0 if S < K else 0.0)
        return {"price": intrinsic, "delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + sigma * sigma / 2) * T) / sq
    d2 = d1 - sq
    disc = math.exp(-r * T)
    if kind == "call":
        price = S * _cdf(d1) - K * disc * _cdf(d2)
        delta = _cdf(d1)
        theta = -S * _pdf(d1) * sigma / (2 * math.sqrt(T)) - r * K * disc * _cdf(d2)
    else:
        price = K * disc * _cdf(-d2) - S * _cdf(-d1)
        delta = _cdf(d1) - 1
        theta = -S * _pdf(d1) * sigma / (2 * math.sqrt(T)) + r * K * disc * _cdf(-d2)
    return {"price": price, "delta": delta, "gamma": _pdf(d1) / (S * sq), "theta": theta / 365,
            "vega": S * _pdf(d1) * math.sqrt(T) / 100}


def implied_vol(price: float, S: float, K: float, T: float, r: float, kind: str) -> Optional[float]:
    """Bisection on sigma in [0.1%, 500%]; None when price is below intrinsic."""
    if price <= 0 or T <= 0:
        return None
    lo, hi = 0.001, 5.0
    if bs(S, K, T, r, lo, kind)["price"] > price or bs(S, K, T, r, hi, kind)["price"] < price:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs(S, K, T, r, mid, kind)["price"] > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


# ------------------------------------------------------------------ sources


class _NSE:
    BASE = "https://www.nseindia.com"
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain",
    }

    def __init__(self):
        self._session = None
        self._warmed = 0.0
        self._lock = threading.Lock()

    def _get(self, path: str, params: dict) -> dict:
        import requests

        with self._lock:
            if self._session is None or time.time() - self._warmed > 600:
                self._session = requests.Session()
                self._session.headers.update(self.HEADERS)
                self._session.get(f"{self.BASE}/option-chain", timeout=10)  # sets the cookies the API wants
                self._warmed = time.time()
            session = self._session
        r = session.get(f"{self.BASE}/api/{path}", params=params, timeout=15)
        if r.status_code in (401, 403):
            self._session = None
        r.raise_for_status()
        return r.json()

    def expiries(self, symbol: str) -> list[str]:
        return self._get("option-chain-contract-info", {"symbol": symbol}).get("expiryDates", [])

    def chain(self, symbol: str, expiry: str) -> tuple[float, list[dict], str]:
        kind = "Indices" if symbol in NSE_INDICES else "Equity"
        data = self._get("option-chain-v3", {"type": kind, "symbol": symbol, "expiry": expiry})
        rec = data.get("records") or {}
        rows = []
        for item in rec.get("data") or []:
            row = {"strike": float(item.get("strikePrice"))}
            for side, key in (("CE", "call"), ("PE", "put")):
                leg = item.get(side)
                if leg:
                    row[key] = {
                        "ltp": leg.get("lastPrice"), "change": leg.get("change"), "oi": leg.get("openInterest"),
                        "chg_oi": leg.get("changeinOpenInterest"), "volume": leg.get("totalTradedVolume"),
                        "iv": leg.get("impliedVolatility") or None, "bid": leg.get("buyPrice1"), "ask": leg.get("sellPrice1"),
                    }
            rows.append(row)
        return float(rec.get("underlyingValue") or 0), rows, rec.get("timestamp") or ""


_nse = _NSE()
_cache: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def _parse_expiry(text: str) -> date:
    for fmt in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised expiry '{text}'")


def expiries(symbol: str, market: str) -> list[str]:
    symbol = symbol.upper()
    if market == "india":
        return _cached(("exp", symbol), lambda: _nse.expiries(symbol))
    import yfinance as yf

    from ..services.analysis_run import yahoo_symbol

    return list(_cached(("exp", symbol, market), lambda: yf.Ticker(yahoo_symbol(symbol, market)).options))


def _yahoo_chain(symbol: str, market: str, expiry: str) -> tuple[float, list[dict], str]:
    import yfinance as yf

    from ..services.analysis_run import yahoo_symbol

    t = yf.Ticker(yahoo_symbol(symbol, market))
    oc = t.option_chain(expiry)
    from ..agent.agents import _resolve_fetcher

    spot = float((_resolve_fetcher(market).get_quote(symbol) or {}).get("price") or 0)
    rows: dict[float, dict] = {}
    for df, key in ((oc.calls, "call"), (oc.puts, "put")):
        for _, r in df.iterrows():
            strike = float(r["strike"])
            iv = float(r.get("impliedVolatility") or 0) * 100
            rows.setdefault(strike, {"strike": strike})[key] = {
                "ltp": _f(r.get("lastPrice")), "change": _f(r.get("change")), "oi": _f(r.get("openInterest")),
                "chg_oi": None, "volume": _f(r.get("volume")), "iv": iv if iv > 0.5 else None,
                "bid": _f(r.get("bid")), "ask": _f(r.get("ask")),
            }
    return spot, [rows[k] for k in sorted(rows)], datetime.now().strftime("%d-%b-%Y %H:%M")


# ------------------------------------------------------------------ analytics


def max_pain(rows: list[dict]) -> Optional[float]:
    """Strike where option buyers' total payout at expiry is smallest."""
    strikes = [r["strike"] for r in rows]
    if not strikes:
        return None
    best, best_pay = None, None
    for k in strikes:
        pay = 0.0
        for r in rows:
            pay += ((r.get("call") or {}).get("oi") or 0) * max(0.0, k - r["strike"])
            pay += ((r.get("put") or {}).get("oi") or 0) * max(0.0, r["strike"] - k)
        if best_pay is None or pay < best_pay:
            best, best_pay = k, pay
    return best


def analyse(spot: float, rows: list[dict], expiry: str, market: str, today: Optional[date] = None) -> dict:
    today = today or date.today()
    days = max((_parse_expiry(expiry) - today).days, 0)
    T = max(days, 0.5) / 365  # expiry-day options still have hours left
    r = RATES.get(market, 0.05)
    for row in rows:
        for kind in ("call", "put"):
            leg = row.get(kind)
            if not leg:
                continue
            iv = leg.get("iv")
            if not iv and leg.get("ltp") and spot:
                est = implied_vol(float(leg["ltp"]), spot, row["strike"], T, r, kind)
                iv = round(est * 100, 2) if est else None
                leg["iv"] = iv
                leg["iv_estimated"] = iv is not None
            if iv and spot:
                g = bs(spot, row["strike"], T, r, iv / 100, kind)
                leg.update({k: round(g[k], 4) for k in ("delta", "gamma", "theta", "vega")})

    call_oi = sum((x.get("call") or {}).get("oi") or 0 for x in rows)
    put_oi = sum((x.get("put") or {}).get("oi") or 0 for x in rows)
    call_vol = sum((x.get("call") or {}).get("volume") or 0 for x in rows)
    put_vol = sum((x.get("put") or {}).get("volume") or 0 for x in rows)
    atm = min(rows, key=lambda x: abs(x["strike"] - spot))["strike"] if rows and spot else None
    atm_row = next((x for x in rows if x["strike"] == atm), {})
    ivs = [v for v in ((atm_row.get("call") or {}).get("iv"), (atm_row.get("put") or {}).get("iv")) if v]
    atm_iv = sum(ivs) / len(ivs) if ivs else None
    has_oi = (call_oi + put_oi) > 0  # Yahoo often reports zero OI on expiry day
    def top(kind: str) -> Optional[float]:
        # Support: biggest put OI at or below spot; resistance: biggest call OI at or above.
        side = [x for x in rows if (x["strike"] <= spot if kind == "put" else x["strike"] >= spot)] if spot else rows
        if not side or not has_oi:
            return None
        best = max(side, key=lambda x: (x.get(kind) or {}).get("oi") or 0)
        return best["strike"] if (best.get(kind) or {}).get("oi") else None

    return {
        "spot": spot,
        "expiry": expiry,
        "days_to_expiry": days,
        "atm_strike": atm,
        "atm_iv": round(atm_iv, 2) if atm_iv else None,
        "expected_move": round(spot * atm_iv / 100 * math.sqrt(T), 2) if atm_iv and spot else None,
        "pcr_oi": round(put_oi / call_oi, 2) if call_oi else None,
        "pcr_volume": round(put_vol / call_vol, 2) if call_vol else None,
        "max_pain": max_pain(rows) if has_oi else None,
        "support": top("put"),  # biggest put OI: writers defend it
        "resistance": top("call"),
        "call_oi": call_oi,
        "put_oi": put_oi,
        "rate": r,
    }


def _smile_iv(rows: list[dict]) -> list[tuple[float, float]]:
    """(strike, IV %) where either leg has an IV, out-of-the-money side preferred
    (the liquid one), sorted by strike."""
    out = []
    for row in rows:
        c, p = (row.get("call") or {}).get("iv"), (row.get("put") or {}).get("iv")
        if c or p:
            out.append((row["strike"], c or p, p or c))
    return sorted(out)


def _iv_at(smile: list[tuple[float, float, float]], strike: float, spot: float) -> Optional[float]:
    """IV for a strike from its neighbours (linear), for legs with no solvable IV
    (deep in the money, or expiry day)."""
    if not smile:
        return None
    pick = (lambda t: t[2] if t[0] < spot else t[1])  # puts below spot, calls above
    below = [t for t in smile if t[0] <= strike]
    above = [t for t in smile if t[0] >= strike]
    if not below:
        return pick(above[0])
    if not above:
        return pick(below[-1])
    a, b = below[-1], above[0]
    if a[0] == b[0]:
        return pick(a)
    w = (strike - a[0]) / (b[0] - a[0])
    return pick(a) + (pick(b) - pick(a)) * w


def gamma_exposure(spot: float, rows: list[dict], days: int, rate: float, multiplier: float) -> Optional[dict]:
    """Dealer gamma exposure by strike, in money per 1% move of the underlying.

    Usual convention (as published market-wide gamma estimates use): dealers
    are long the calls and short the puts that customers hold, so call gamma
    counts positive and put gamma negative. Each contract's gamma x open
    interest x contract size x spot^2 x 1%. The zero-gamma level is where the
    total would change sign if the underlying moved there, IVs held fixed.
    """
    if not spot or not rows:
        return None
    T = max(days, 0.5) / 365
    smile = _smile_iv(rows)
    if not smile:
        return None
    legs = []  # (strike, kind, oi, sigma)
    for row in rows:
        for kind in ("call", "put"):
            leg = row.get(kind) or {}
            oi = leg.get("oi") or 0
            if oi <= 0:
                continue
            iv = leg.get("iv") or _iv_at(smile, row["strike"], spot)
            if iv:
                legs.append((row["strike"], kind, float(oi), iv / 100))
    if not legs:
        return None

    def total_at(s: float, per_strike: Optional[dict] = None) -> float:
        tot = 0.0
        for k, kind, oi, sigma in legs:
            g = bs(s, k, T, rate, sigma, kind)["gamma"] * oi * multiplier * s * s * 0.01
            g = g if kind == "call" else -g
            tot += g
            if per_strike is not None:
                d = per_strike.setdefault(k, {"strike": k, "call": 0.0, "put": 0.0})
                d[kind] += g
        return tot

    by: dict[float, dict] = {}
    total = total_at(spot, by)
    # zero gamma: scan +-20% around spot, take the sign change nearest the spot
    grid = [spot * (0.8 + 0.4 * i / 160) for i in range(161)]
    vals = [total_at(x) for x in grid]
    flips = []
    for (x0, v0), (x1, v1) in zip(zip(grid, vals), zip(grid[1:], vals[1:])):
        if v0 == 0 or (v0 < 0) != (v1 < 0):
            flips.append(x0 + (x1 - x0) * (abs(v0) / (abs(v0) + abs(v1)) if v0 != v1 else 0))
    zero = min(flips, key=lambda x: abs(x - spot)) if flips else None
    strikes = [dict(d, net=d["call"] + d["put"]) for d in sorted(by.values(), key=lambda d: d["strike"])]
    peak = max(strikes, key=lambda d: abs(d["net"])) if strikes else None
    return {
        "total": round(total, 2),
        "zero_gamma": round(zero, 2) if zero else None,
        "peak_strike": peak["strike"] if peak else None,
        "multiplier": multiplier,
        "by_strike": [{k: round(v, 2) if k != "strike" else v for k, v in d.items()} for d in strikes],
        "interpolated_iv": any(not ((r.get(k) or {}).get("iv")) and (r.get(k) or {}).get("oi") for r in rows for k in ("call", "put")),
    }


def implied_forward(spot: float, rows: list[dict], T: float, rate: float) -> Optional[float]:
    """Forward level from put-call parity, F = K + (C - P) e^(rT), median of the
    three strikes nearest spot that have both prices."""
    both = [r for r in rows if (r.get("call") or {}).get("ltp") and (r.get("put") or {}).get("ltp")]
    both.sort(key=lambda r: abs(r["strike"] - spot))
    fs = sorted(r["strike"] + (float(r["call"]["ltp"]) - float(r["put"]["ltp"])) * math.exp(rate * T) for r in both[:3])
    if not fs:
        return None
    f = fs[len(fs) // 2]
    return f if abs(f / spot - 1) < 0.1 else None  # stale quotes: ignore


def smile(spot: float, rows: list[dict], days: int, rate: float) -> Optional[dict]:
    """IV by strike from out-of-the-money options (puts below the forward, calls
    above), solved against the parity-implied forward so calls and puts agree.
    Exchanges' own IVs use spot, which leaves a gap the size of the carry
    between call and put IVs at the same strike."""
    if not spot or not rows:
        return None
    T = max(days, 0.5) / 365
    fwd = implied_forward(spot, rows, T, rate)
    base = fwd or spot
    s_adj = base * math.exp(-rate * T) if fwd else spot  # Black-76 through Black-Scholes
    points = []
    for row in rows:
        k = row["strike"]
        if abs(k / base - 1) > 0.1:
            continue
        kind = "put" if k < base else "call"
        ltp = (row.get(kind) or {}).get("ltp")
        if not ltp:
            continue
        iv = implied_vol(float(ltp), s_adj, k, T, rate, kind)
        if iv:
            points.append({"strike": k, "iv": round(iv * 100, 2), "side": kind})
    if len(points) < 3:
        return None
    return {"forward": round(fwd, 2) if fwd else None, "points": points, "same_day": days < 1}


def _after_nse_close() -> bool:
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    return (now.hour, now.minute) >= (15, 30)


def _lot(symbol: str, expiry: str) -> Optional[int]:
    """Exchange lot size from the brokers' instrument files (src/trading/lots.py)."""
    from .lots import lot_size

    try:
        return lot_size(symbol, _parse_expiry(expiry))
    except Exception as exc:
        logger.warning("Lot size for %s unavailable: %s", symbol, exc)
        return None


def chain(symbol: str, market: str, expiry: Optional[str] = None) -> dict:
    symbol = symbol.upper()
    exps = expiries(symbol, market)
    if not exps:
        raise ValueError(f"No listed options for {symbol}")
    if expiry not in exps:
        upcoming = [e for e in exps if _parse_expiry(e) >= date.today()]
        # After the close on expiry day that series is finished: show the next one
        if market == "india" and len(upcoming) > 1 and _parse_expiry(upcoming[0]) == date.today() and _after_nse_close():
            upcoming = upcoming[1:]
        expiry = (upcoming or exps)[0]
    fetch = (lambda: _nse.chain(symbol, expiry)) if market == "india" else (lambda: _yahoo_chain(symbol, market, expiry))
    spot, rows, stamp = _cached(("chain", symbol, market, expiry), fetch)
    rows = [{**r, **{k: dict(r[k]) for k in ("call", "put") if k in r}} for r in rows]  # don't mutate the cache
    summary = analyse(spot, rows, expiry, market)
    lot = _lot(symbol, expiry) if market == "india" else 100
    try:
        gex = gamma_exposure(spot, rows, summary["days_to_expiry"], summary["rate"], float(lot or 1))
    except Exception as exc:  # analytics must never take the chain down
        logger.warning("Gamma exposure for %s failed: %s", symbol, exc)
        gex = None
    try:
        iv_smile = smile(spot, rows, summary["days_to_expiry"], summary["rate"])
    except Exception as exc:
        logger.warning("Smile for %s failed: %s", symbol, exc)
        iv_smile = None
    return {
        "symbol": symbol, "market": market, "expiries": exps, "timestamp": stamp,
        "lot_size": lot, "rows": rows, "summary": summary, "gex": gex, "smile": iv_smile,
        # Expiry-day IV is dominated by hours of time value: no IV vs RV reading
        "vol_compare": vol_compare(symbol, market, summary.get("atm_iv") if summary["days_to_expiry"] >= 1 else None),
    }


# ------------------------------------------------------------------ implied vs realized

# Option underlyings whose Yahoo ticker is not symbol + suffix.
_UNDERLYING = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
               "MIDCPNIFTY": "NIFTY_MID_SELECT.NS", "SENSEX": "^BSESN", "SPX": "^SPX", "NDX": "^NDX", "RUT": "^RUT"}


def _daily_bars(symbol: str, market: str):
    from ..services.analysis_run import yahoo_symbol
    from .scanner import _cache

    ticker = _UNDERLYING.get(symbol) or yahoo_symbol(symbol, market)
    return _cache.get([ticker], "1d", "1y").get(ticker)


def compare_vol(atm_iv: Optional[float], bars) -> Optional[dict]:
    """ATM implied vol (%) vs realized vol of the underlying. Pure, testable."""
    from .volatility import realized

    if bars is None or len(bars) < 70:
        return None
    rv = realized(bars.rename(columns=str.lower), 20).dropna() * 100
    rv60 = realized(bars.rename(columns=str.lower), 60).dropna() * 100
    if rv.empty:
        return None
    now = float(rv.iloc[-1])
    out = {"rv_20": round(now, 2), "rv_60": round(float(rv60.iloc[-1]), 2) if len(rv60) else None,
           "rv_20_low": round(float(rv.quantile(0.1)), 2), "rv_20_high": round(float(rv.quantile(0.9)), 2),
           "atm_iv": atm_iv, "ratio": None, "iv_vs_rv_range_pct": None, "verdict": None}
    if atm_iv:
        ratio = atm_iv / now if now else None
        out["ratio"] = round(ratio, 2) if ratio else None
        out["iv_vs_rv_range_pct"] = round(float((rv <= atm_iv).mean() * 100), 1)
        if ratio:
            out["verdict"] = ("expensive" if ratio >= 1.25 else "cheap" if ratio <= 0.85 else "fair")
    return out


def vol_compare(symbol: str, market: str, atm_iv: Optional[float]) -> Optional[dict]:
    try:
        return compare_vol(atm_iv, _daily_bars(symbol, market))
    except Exception as exc:
        logger.info("Realized vol for %s unavailable: %s", symbol, exc)
        return None


# ------------------------------------------------------------------ strategy payoff


def payoff(legs: list[dict], spot: float, days: float, rate: float, width_pct: float = 20, points: int = 121) -> dict:
    """legs: {type: call|put|stock, side: buy|sell, strike, premium, quantity, iv (%)}.
    Returns P&L at expiry and today (Black-Scholes) across a price range."""
    lo, hi = spot * (1 - width_pct / 100), spot * (1 + width_pct / 100)
    prices = [lo + (hi - lo) * i / (points - 1) for i in range(points)]
    T = max(days, 0) / 365

    def leg_value(leg: dict, S: float, t: float) -> float:
        if leg["type"] == "stock":
            return S
        if t <= 0:
            return max(0.0, S - leg["strike"]) if leg["type"] == "call" else max(0.0, leg["strike"] - S)
        return bs(S, leg["strike"], t, rate, max((leg.get("iv") or 20) / 100, 0.001), leg["type"])["price"]

    def pnl(S: float, t: float) -> float:
        total = 0.0
        for leg in legs:
            sign = 1 if leg["side"] == "buy" else -1
            total += sign * (leg_value(leg, S, t) - leg["premium"]) * leg["quantity"]
        return total

    at_expiry = [pnl(S, 0) for S in prices]
    today = [pnl(S, T) for S in prices]
    breakevens = []
    for i in range(1, len(prices)):
        a, b = at_expiry[i - 1], at_expiry[i]
        if (a < 0 <= b) or (a > 0 >= b):
            breakevens.append(round(prices[i - 1] + (prices[i] - prices[i - 1]) * (-a) / (b - a), 2) if b != a else prices[i])

    # Slope beyond the range tells whether profit / loss is unlimited.
    def slope(S: float) -> float:
        net = 0.0
        for leg in legs:
            sign = 1 if leg["side"] == "buy" else -1
            if leg["type"] == "stock":
                net += sign * leg["quantity"]
            elif leg["type"] == "call" and S > leg["strike"]:
                net += sign * leg["quantity"]
            elif leg["type"] == "put" and S < leg["strike"]:
                net -= sign * leg["quantity"]
        return net

    far_up = slope(hi * 10)
    at_zero = pnl(0.0, 0)  # prices stop at zero, so the downside is always bounded
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        sign = (1 if leg["side"] == "buy" else -1) * leg["quantity"]
        if leg["type"] == "stock":
            greeks["delta"] += sign
            continue
        g = bs(spot, leg["strike"], max(T, 1 / 365), rate, max((leg.get("iv") or 20) / 100, 0.001), leg["type"])
        for k in greeks:
            greeks[k] += sign * g[k]
    net_premium = sum((1 if l["side"] == "sell" else -1) * l["premium"] * l["quantity"] for l in legs if l["type"] != "stock")
    return {
        "points": [{"price": round(S, 2), "expiry": round(e, 2), "today": round(t, 2)} for S, e, t in zip(prices, at_expiry, today)],
        "breakevens": breakevens,
        "max_profit": None if far_up > 0 else round(max(max(at_expiry), at_zero), 2),
        "max_loss": None if far_up < 0 else round(min(min(at_expiry), at_zero), 2),
        "net_premium": round(net_premium, 2),  # + = credit received
        "greeks": {k: round(v, 4) for k, v in greeks.items()},
    }
