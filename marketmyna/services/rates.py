"""Rates & bullion for markets other than India (India has its own,
richer card: marketmyna/services/india_rates.py).

- us:        Fed funds, SOFR, Treasury 3M/2Y/10Y/30Y, 10y-2y, 30y mortgage
             (FRED) + gold / silver in dollars (Yahoo futures).
- hong_kong: HKMA base rate, HIBOR overnight / 1M / 3M (HKMA open API),
             USD/HKD peg + gold / silver in HK dollars.
- china_a:   China 3M interbank (FRED/OECD, monthly), USD/CNY + gold per
             gram and silver per kg in yuan.
- crypto:    perpetual-futures funding rates (Binance, Bybit fallback),
             annualised - crypto's closest thing to an interest rate - plus
             Bitcoin priced in gold.

Every block is fetched independently; a failed block is reported and the
rest still render. Cached for an hour per market.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

CACHE_SECONDS = 3600
TROY_OZ_G = 31.1034768
TAEL_OZ = 1.20337  # 1 HK tael (37.429 g) in troy ounces
HKMA = "https://api.hkma.gov.hk/public/market-data-and-statistics"
FUNDING_COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB"]

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _get_json(url: str, params: Optional[dict] = None) -> dict:
    import requests

    r = requests.get(url, params=params, timeout=20, headers={"User-Agent": "Mozilla/5.0 MarketMyna"})
    r.raise_for_status()
    return r.json()


def _fred(series_id: str, start: date) -> pd.Series:
    from .macro import _fred as fred

    return fred(series_id, start)


def _yahoo(tickers: list[str]) -> dict[str, pd.Series]:
    import yfinance as yf

    from ..data import ecb_fx
    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    def download() -> dict[str, pd.Series]:
        with YF_DOWNLOAD_LOCK:
            df = yf.download(tickers, period="13mo", interval="1d", progress=False, auto_adjust=True, threads=True)
        closes = df["Close"]
        if isinstance(closes, pd.Series):
            closes = closes.to_frame(tickers[0])
        return {t: closes[t].dropna() for t in tickers if t in closes and closes[t].notna().sum()}

    return ecb_fx.guarded(download, tickers, days=400)


# ---------------------------------------------------------------- helpers


def _naive(s: pd.Series) -> pd.Series:
    idx = pd.DatetimeIndex(s.index)
    return pd.Series(s.to_numpy(), index=idx.tz_localize(None) if idx.tz is not None else idx).sort_index()


def _ago(s: pd.Series, days: int) -> Optional[float]:
    past = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
    return float(past.iloc[-1]) if len(past) else None


def item(label: str, s: Optional[pd.Series], unit: str, note: str = "", scale: float = 1.0,
         change: str = "points", digits: int = 2) -> Optional[dict]:
    """One stat from a series: latest value, 1-month and 1-year change.

    change="points" for rates (difference), "pct" for prices (% change)."""
    if s is None or s.dropna().empty:
        return None
    s = _naive(s.dropna()) * scale
    now = float(s.iloc[-1])

    def delta(days: int) -> Optional[float]:
        past = _ago(s, days)
        if past is None:
            return None
        return now - past if change == "points" else (now / past - 1) * 100 if past else None

    return {"label": label, "value": round(now, digits), "unit": unit, "note": note,
            "change_1m": delta(30), "change_1y": delta(365), "change_kind": change,
            "as_of": str(s.index[-1].date()),
            "spark": [round(float(v), digits) for v in s.resample("W").last().dropna().tail(52)]}


def _section(title: str, items: list[Optional[dict]], note: str = "", source: str = "") -> Optional[dict]:
    items = [i for i in items if i]
    return {"title": title, "note": note, "source": source, "items": items} if items else None


def _run(blocks: dict[str, Callable[[], Optional[dict]]]) -> tuple[list[dict], list[str]]:
    sections, errors = [], []
    with ThreadPoolExecutor(max_workers=len(blocks)) as pool:
        futures = {name: pool.submit(fn) for name, fn in blocks.items()}
        for name, fut in futures.items():
            try:
                sec = fut.result()
            except Exception as exc:
                logger.warning("Rates block %s failed: %s", name, exc)
                errors.append(f"{name} unavailable right now")
                continue
            if sec:
                sections.append(sec)
            else:
                errors.append(f"{name} unavailable right now")
    return sections, errors


def _bullion(currency: str, fx: Optional[str], unit_note: str, *, per: str = "oz",
             yahoo: Callable = _yahoo) -> Optional[dict]:
    tickers = ["GC=F", "SI=F"] + ([fx] if fx else [])
    data = yahoo(tickers)
    gold, silver = data.get("GC=F"), data.get("SI=F")
    if gold is None:
        return None
    gold, silver = _naive(gold), _naive(silver) if silver is not None else None
    if fx:
        rate = _naive(data[fx]) if fx in data else None
        if rate is None:
            return None
        gold = pd.concat([gold, rate], axis=1).ffill().dropna().prod(axis=1)
        silver = pd.concat([silver, rate], axis=1).ffill().dropna().prod(axis=1) if silver is not None else None
    if per == "g":
        g_item = item(f"Gold ({currency}/g)", gold, currency, unit_note, scale=1 / TROY_OZ_G, change="pct")
        s_item = item(f"Silver ({currency}/kg)", silver, currency, "", scale=1000 / TROY_OZ_G, change="pct", digits=0)
    elif per == "tael":
        g_item = item(f"Gold ({currency}/tael)", gold, currency, unit_note, scale=TAEL_OZ, change="pct", digits=0)
        s_item = item(f"Silver ({currency}/oz)", silver, currency, "", change="pct")
    else:
        g_item = item(f"Gold ({currency}/oz)", gold, currency, unit_note, change="pct", digits=0)
        s_item = item(f"Silver ({currency}/oz)", silver, currency, "", change="pct")
    ratio = None
    if silver is not None:
        both = pd.concat([gold, silver], axis=1, keys=["g", "s"]).ffill().dropna()
        ratio = item("Gold / silver ratio", both["g"] / both["s"], "x",
                     "Ounces of silver one ounce of gold buys; high = silver cheap vs gold", change="points", digits=1)
    return _section("Bullion", [g_item, s_item, ratio], source="COMEX futures, market data feed")


# ---------------------------------------------------------------- markets


def _us(fred=_fred, yahoo=_yahoo) -> dict:
    start = date.today() - timedelta(days=400)

    def series(*ids):
        return {i: fred(i, start) for i in ids}

    def policy():
        s = series("DFF", "SOFR", "MORTGAGE30US")
        return _section("Policy & money market", [
            item("Fed funds (effective)", s["DFF"], "%", "Overnight rate the Fed steers"),
            item("SOFR", s["SOFR"], "%", "Secured overnight rate; benchmark for most US loans"),
            item("30-year mortgage", s["MORTGAGE30US"], "%", "Freddie Mac weekly average"),
        ], source="Official US rates data")

    def treasuries():
        s = series("DGS3MO", "DGS2", "DGS10", "DGS30", "T10Y2Y")
        return _section("Treasury yields", [
            item("3-month", s["DGS3MO"], "%", "Cash-like yield"),
            item("2-year", s["DGS2"], "%", "Tracks expected Fed moves"),
            item("10-year", s["DGS10"], "%", "Benchmark for valuations and mortgages"),
            item("30-year", s["DGS30"], "%"),
            item("10y − 2y spread", s["T10Y2Y"], "pts", "Below 0 (inverted) has preceded most recessions"),
        ], note="Full curve: see the Macro tab.", source="Official US Treasury constant-maturity yields")

    sections, errors = _run({"Policy rates": policy, "Treasuries": treasuries,
                             "Bullion": lambda: _bullion("$", None, "COMEX front-month", yahoo=yahoo)})
    return {"sections": sections, "errors": errors}


def _hkma_series(path: str, fields: dict[str, str], date_key: str, pages: int = 400) -> dict[str, pd.Series]:
    data = _get_json(f"{HKMA}/{path}", {"pagesize": pages, "sortby": date_key, "sortorder": "desc"})
    records = (data.get("result") or {}).get("records") or []
    out = {}
    for key in fields:
        pts = {pd.Timestamp(r[date_key]): r[key] for r in records if r.get(key) is not None}
        if pts:
            out[key] = pd.Series(pts).sort_index().astype(float)
    return out


def _hong_kong(yahoo=_yahoo) -> dict:
    def money():
        daily = _hkma_series("daily-monetary-statistics/daily-figures-interbank-liquidity",
                             {"disc_win_base_rate": "", "hibor_overnight": "", "hibor_fixing_1m": ""}, "end_of_date")
        curve = _hkma_series("monthly-statistical-bulletin/er-ir/hk-interbank-ir-daily",
                             {"ir_3m": "", "ir_12m": ""}, "end_of_day")
        return _section("HKMA & HIBOR", [
            item("Base rate", daily.get("disc_win_base_rate"), "%", "HKMA discount-window base rate; follows the Fed under the peg"),
            item("HIBOR overnight", daily.get("hibor_overnight"), "%", "Swings with HK dollar liquidity"),
            item("HIBOR 1M", daily.get("hibor_fixing_1m"), "%", "Prices most HK mortgages (HIBOR-linked plans)"),
            item("HIBOR 3M", curve.get("ir_3m"), "%"),
            item("HIBOR 12M", curve.get("ir_12m"), "%"),
        ], source="HKMA open API")

    def peg():
        data = yahoo(["HKD=X"])
        return _section("Currency peg", [
            item("USD / HKD", data.get("HKD=X"), "HK$", "Pegged in the 7.75 – 7.85 band; near 7.85 = weak side, HKMA drains liquidity",
                 change="points", digits=4),
        ], source="Market data feed")

    sections, errors = _run({"HKMA rates": money, "Currency peg": peg,
                             "Bullion": lambda: _bullion("HK$", "HKD=X", "Spot in HK dollars", per="tael", yahoo=yahoo)})
    return {"sections": sections, "errors": errors}


def _china(fred=_fred, yahoo=_yahoo) -> dict:
    start = date.today() - timedelta(days=800)

    def money():
        return _section("Money market", [
            item("3-month interbank", fred("IR3TIB01CNM156N", start), "%", "Monthly (OECD); lags a few months"),
        ], source="Official central bank and OECD statistics")

    def fx():
        data = yahoo(["CNY=X"])
        return _section("Currency", [
            item("USD / CNY", data.get("CNY=X"), "¥", "Higher = weaker yuan; PBoC manages it in a daily band",
                 change="points", digits=4),
        ], source="Market data feed")

    sections, errors = _run({"Money market": money, "Currency": fx,
                             "Bullion": lambda: _bullion("¥", "CNY=X", "Spot converted to yuan", per="g", yahoo=yahoo)})
    return {"sections": sections, "errors": errors}


def _funding_binance() -> list[dict]:
    rows = _get_json("https://fapi.binance.com/fapi/v1/premiumIndex")
    by = {r["symbol"]: r for r in rows if isinstance(r, dict)}
    out = []
    for coin in FUNDING_COINS:
        r = by.get(f"{coin}USDT")
        if r and r.get("lastFundingRate") not in (None, ""):
            out.append({"coin": coin, "rate_8h": float(r["lastFundingRate"]), "mark": float(r["markPrice"]),
                        "next": int(r.get("nextFundingTime") or 0)})
    return out


def _funding_bybit() -> list[dict]:
    data = _get_json("https://api.bybit.com/v5/market/tickers", {"category": "linear"})
    by = {r["symbol"]: r for r in (data.get("result") or {}).get("list") or []}
    out = []
    for coin in FUNDING_COINS:
        r = by.get(f"{coin}USDT")
        if r and r.get("fundingRate") not in (None, ""):
            out.append({"coin": coin, "rate_8h": float(r["fundingRate"]), "mark": float(r["markPrice"]),
                        "next": int(r.get("nextFundingTime") or 0)})
    return out


def _crypto(yahoo=_yahoo, funding_sources=(_funding_binance, _funding_bybit)) -> dict:
    def funding():
        rows, source = [], ""
        for fn in funding_sources:
            try:
                rows = fn()
            except Exception as exc:
                logger.warning("Funding rates via %s failed: %s", fn.__name__, exc)
                continue
            if rows:
                source = "Crypto exchange futures data"
                break
        items = []
        for r in rows:
            annual = r["rate_8h"] * 3 * 365 * 100
            items.append({
                "label": f"{r['coin']} funding", "value": round(annual, 1), "unit": "% / yr",
                "note": f"{r['rate_8h'] * 100:.4f}% per 8h · "
                        + ("longs pay shorts (bullish leverage)" if r["rate_8h"] > 0 else "shorts pay longs (bearish leverage)"),
                "change_1m": None, "change_1y": None, "change_kind": "points", "as_of": str(date.today()), "spark": [],
                "tone": "up" if annual > 0 else "down",
            })
        return _section("Perpetual funding rates", items,
                        note="What leveraged longs pay shorts, annualised. Very high = crowded longs; negative = crowded shorts.",
                        source=f"{source} USDT perpetuals" if source else "")

    def btc_gold():
        data = yahoo(["BTC-USD", "GC=F"])
        if "BTC-USD" not in data or "GC=F" not in data:
            return None
        both = pd.concat([_naive(data["BTC-USD"]), _naive(data["GC=F"])], axis=1, keys=["b", "g"]).ffill().dropna()
        return _section("Bitcoin vs gold", [
            item("BTC in gold ounces", both["b"] / both["g"], "oz", "How many ounces of gold one bitcoin buys", change="pct", digits=1),
            item("Gold ($/oz)", data["GC=F"], "$", "COMEX front-month", change="pct", digits=0),
        ], source="Market data feed")

    sections, errors = _run({"Funding rates": funding, "Bitcoin vs gold": btc_gold})
    return {"sections": sections, "errors": errors}


BUILDERS: dict[str, Callable[[], dict]] = {
    "us": _us, "hong_kong": _hong_kong, "china_a": _china, "crypto": _crypto,
}
TITLES = {"us": "US rates & bullion", "hong_kong": "Hong Kong rates & bullion",
          "china_a": "China rates & bullion", "crypto": "Funding rates & gold"}


def build(market: str, use_cache: bool = True) -> dict:
    market = market.lower()
    builder = BUILDERS.get(market)
    if builder is None:
        return {"market": market, "sections": [], "errors": ["Not available for this market"]}
    if use_cache:
        with _lock:
            hit = _cache.get(market)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    out = {"market": market, "title": TITLES[market], **builder()}
    if use_cache and out["sections"]:
        with _lock:
            _cache[market] = (time.time(), out)
    return out
