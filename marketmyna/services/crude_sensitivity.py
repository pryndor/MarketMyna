"""How oil-linked stocks react to crude - India, US, Hong Kong, China A.

For each stock, weekly returns over two years are regressed on the local
index and on crude in local currency together (India: Nifty 50 and Brent
in rupees; US: S&P 500 and WTI; HK: Hang Seng and Brent; China: Shanghai Composite
and Brent in yuan):

    r_stock = a + b_mkt * r_index + b_crude * r_crude_local + e

b_crude is the crude sensitivity net of the market: a b_crude of -0.3 means a
10% rise in rupee Brent has gone with the stock doing about 3% worse than its
market exposure alone would suggest. Weekly bars sidestep the time-zone gap
between NSE and ICE closes. Plain numpy OLS with ordinary standard errors.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600
BRENT, FX, NIFTY = "BZ=F", "USDINR=X", "^NSEI"

# group, why it is linked to crude, [(symbol, name)]
GROUPS = [
    ("Oil marketing (OMCs)", "Buy crude, sell fuel at prices the government leans on: costlier crude squeezes margins",
     [("BPCL", "Bharat Petroleum"), ("HINDPETRO", "Hindustan Petroleum"), ("IOC", "Indian Oil")]),
    ("Upstream producers", "Sell the crude they pump: higher prices lift revenue (windfall taxes cap it)",
     [("ONGC", "ONGC"), ("OIL", "Oil India")]),
    ("Refining & petchem", "Margins track the spread between crude and products",
     [("RELIANCE", "Reliance Industries"), ("MRPL", "MRPL"), ("CHENNPETRO", "Chennai Petroleum")]),
    ("Paints", "Many raw materials are crude derivatives",
     [("ASIANPAINT", "Asian Paints"), ("BERGEPAINT", "Berger Paints"), ("KANSAINER", "Kansai Nerolac")]),
    ("Aviation", "Jet fuel is the largest cost line",
     [("INDIGO", "InterGlobe Aviation")]),
    ("Tyres", "Synthetic rubber and carbon black come from crude",
     [("MRF", "MRF"), ("APOLLOTYRE", "Apollo Tyres"), ("CEATLTD", "CEAT")]),
    ("Gas", "City gas buys LNG priced partly off crude and sells at regulated prices; GAIL also trades it",
     [("IGL", "Indraprastha Gas"), ("MGL", "Mahanagar Gas"), ("GAIL", "GAIL")]),
]

US_GROUPS = [
    ("Integrated majors", "Pump, refine and sell: revenue rides the crude price, refining softens it",
     [("XOM", "Exxon Mobil"), ("CVX", "Chevron")]),
    ("Producers (E&P)", "Sell the crude they pump: the purest upside to higher oil",
     [("COP", "ConocoPhillips"), ("EOG", "EOG Resources"), ("OXY", "Occidental"), ("DVN", "Devon Energy")]),
    ("Oil services", "Drilling budgets follow the oil price with a lag",
     [("SLB", "SLB"), ("HAL", "Halliburton"), ("BKR", "Baker Hughes")]),
    ("Refiners", "Margins track the spread between crude and fuel, not crude itself",
     [("VLO", "Valero"), ("MPC", "Marathon Petroleum"), ("PSX", "Phillips 66")]),
    ("Airlines", "Jet fuel is one of the two biggest costs",
     [("DAL", "Delta"), ("UAL", "United"), ("AAL", "American"), ("LUV", "Southwest")]),
    ("Cruise lines", "Bunker fuel is a big cost and higher pump prices squeeze customers",
     [("CCL", "Carnival"), ("RCL", "Royal Caribbean"), ("NCLH", "Norwegian Cruise")]),
    ("Chemicals", "Feedstock is oil and gas derivatives",
     [("DOW", "Dow"), ("LYB", "LyondellBasell")]),
    ("Parcel & trucking", "Diesel and jet fuel costs, partly passed on through surcharges",
     [("UPS", "UPS"), ("FDX", "FedEx"), ("ODFL", "Old Dominion")]),
]

HK_GROUPS = [
    ("Oil majors", "China's big three: upstream profits rise with crude, refining and retail cushion it",
     [("00857", "PetroChina"), ("00386", "Sinopec"), ("00883", "CNOOC")]),
    ("Airlines", "Jet fuel is one of the largest costs",
     [("00293", "Cathay Pacific"), ("00753", "Air China"), ("00670", "China Eastern"), ("01055", "China Southern")]),
    ("Shipping", "Bunker fuel costs; freight rates often move with energy demand",
     [("01919", "COSCO Shipping"), ("00316", "OOIL"), ("02866", "COSCO Shipping Dev")]),
    ("City gas", "Buy gas priced partly off oil, sell at regulated tariffs",
     [("00003", "HK & China Gas"), ("01193", "China Resources Gas"), ("02688", "ENN Energy")]),
]

CHINA_GROUPS = [
    ("Oil majors", "Upstream profits rise with crude; state-set fuel prices cap the refining side",
     [("601857", "PetroChina"), ("600028", "Sinopec"), ("600938", "CNOOC")]),
    ("Oilfield services", "Spending follows the oil price",
     [("600871", "Sinopec Oilfield"), ("601808", "China Oilfield Services")]),
    ("Airlines", "Jet fuel is one of the largest costs",
     [("601111", "Air China"), ("600115", "China Eastern"), ("600029", "China Southern")]),
    ("Chemicals & refining", "Crude is the feedstock",
     [("600309", "Wanhua Chemical"), ("002493", "Rongsheng Petrochem"), ("600346", "Hengli Petrochem")]),
]

# market -> index, crude contract, FX to local (None = priced in USD), labels.
# Group symbols are the app's own (00857, 601857); yahoo_symbol maps them.
MARKETS = {
    "india": {"index": NIFTY, "index_name": "Nifty 50", "crude": BRENT, "crude_name": "Brent", "fx": FX,
              "currency": "₹", "groups": GROUPS},
    "us": {"index": "^GSPC", "index_name": "S&P 500", "crude": "CL=F", "crude_name": "WTI", "fx": None,
           "currency": "$", "groups": US_GROUPS},
    "hong_kong": {"index": "^HSI", "index_name": "Hang Seng", "crude": BRENT, "crude_name": "Brent", "fx": "HKD=X",
                  "currency": "HK$", "groups": HK_GROUPS},
    "china_a": {"index": "000001.SS", "index_name": "Shanghai Composite", "crude": BRENT, "crude_name": "Brent", "fx": "CNY=X",
                "currency": "¥", "groups": CHINA_GROUPS},
}

Fetch = Callable[[list[str]], dict[str, pd.Series]]

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


def _yahoo(tickers: list[str]) -> dict[str, pd.Series]:
    import yfinance as yf

    from ..data import ecb_fx
    from ..utils.yf_lock import YF_DOWNLOAD_LOCK

    def download() -> dict[str, pd.Series]:
        with YF_DOWNLOAD_LOCK:
            df = yf.download(tickers, period="2y", interval="1d", progress=False, auto_adjust=True, threads=True)
        closes = df["Close"]
        return {t: closes[t].dropna() for t in tickers if t in closes and closes[t].notna().sum()}

    return ecb_fx.guarded(download, tickers)


def _weekly(s: pd.Series) -> pd.Series:
    s = s.copy()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None) if getattr(s.index, "tz", None) else pd.DatetimeIndex(s.index)
    return s.resample("W-FRI").last()


def regress(stock: pd.Series, nifty: pd.Series, crude: pd.Series) -> Optional[dict]:
    """Weekly two-factor OLS. Inputs are daily closes."""
    df = pd.concat([_weekly(stock), _weekly(nifty), _weekly(crude)], axis=1, keys=["s", "m", "c"]).pct_change().dropna()
    if len(df) < 40:
        return None
    y = df["s"].to_numpy()
    x = np.column_stack([np.ones(len(df)), df["m"].to_numpy(), df["c"].to_numpy()])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    dof = len(y) - x.shape[1]
    s2 = float(resid @ resid) / dof
    se = np.sqrt(np.diag(s2 * np.linalg.inv(x.T @ x)))
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - float(resid @ resid) / tss if tss else None
    # R2 of the market-only model, to show what crude adds
    xm = x[:, :2]
    bm, *_ = np.linalg.lstsq(xm, y, rcond=None)
    rm = y - xm @ bm
    r2_mkt = 1 - float(rm @ rm) / tss if tss else None
    t = float(beta[2] / se[2]) if se[2] else 0.0
    return {
        "weeks": len(df),
        "beta_market": float(beta[1]),
        "beta_crude": float(beta[2]),
        "t_crude": t,
        "significant": abs(t) >= 2,
        "corr_crude": float(np.corrcoef(df["s"], df["c"])[0, 1]),
        "r2": r2,
        "r2_added": (r2 - r2_mkt) if r2 is not None and r2_mkt is not None else None,
    }


def _change(s: pd.Series, days: int) -> Optional[float]:
    s = s.dropna()
    if s.empty:
        return None
    idx = pd.DatetimeIndex(s.index).tz_localize(None) if getattr(s.index, "tz", None) else pd.DatetimeIndex(s.index)
    s = pd.Series(s.to_numpy(), index=idx)
    past = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
    return float(s.iloc[-1] / past.iloc[-1] - 1) * 100 if len(past) else None


def build(fetch: Fetch = _yahoo, use_cache: bool = True, market: str = "india") -> dict:
    cfg = MARKETS.get(market)
    if cfg is None:
        return {"groups": [], "market": market, "error": "Oil sensitivity is not available for this market"}
    if use_cache:
        with _lock:
            hit = _cache.get(market)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]

    index, crude_t, fx = cfg["index"], cfg["crude"], cfg["fx"]
    from .analysis_run import yahoo_symbol

    tickers = [yahoo_symbol(sym, market) for _, _, members in cfg["groups"] for sym, _ in members]
    tickers += [crude_t, index] + ([fx] if fx else [])
    try:
        data = fetch(tickers)
    except Exception as exc:
        logger.warning("Crude sensitivity fetch failed: %s", exc)
        return {"groups": [], "market": market, "error": "Price data unavailable right now"}
    if crude_t not in data or index not in data or (fx and fx not in data):
        return {"groups": [], "market": market, "error": f"{cfg['crude_name']}, FX or {cfg['index_name']} history unavailable"}

    if fx:
        both = pd.concat([data[crude_t], data[fx]], axis=1, keys=["b", "fx"]).ffill().dropna()
        crude_local = both["b"] * both["fx"]
    else:
        crude_local = data[crude_t]
    crude_1m = _change(crude_local, 30)

    groups = []
    for name, why, members in cfg["groups"]:
        rows = []
        for sym, label in members:
            s = data.get(yahoo_symbol(sym, market))
            if s is None:
                continue
            r = regress(s, data[index], crude_local)
            if r is None:
                continue
            r.update(symbol=sym, name=label,
                     change_1m=_change(s, 30),
                     # what crude's last month implies on its own, holding the market flat
                     crude_implied_1m=r["beta_crude"] * crude_1m if crude_1m is not None else None)
            rows.append(r)
        if rows:
            groups.append({"name": name, "why": why,
                           "avg_beta_crude": float(np.mean([r["beta_crude"] for r in rows])),
                           "stocks": rows})
    local = "" if not fx else {"india": " in rupees", "hong_kong": " in HK dollars", "china_a": " in yuan"}[market]
    crude_label = f"{cfg['crude_name']}{local}"
    out = {
        "market": market,
        "groups": groups,
        "crude_label": crude_label,
        "currency": cfg["currency"],
        "index_name": cfg["index_name"],
        "crude": float(crude_local.iloc[-1]),
        "crude_change_1m": crude_1m,
        "crude_change_1y": _change(crude_local, 365),
        "method": f"Weekly returns over 2 years, regressed on the {cfg['index_name']} and {crude_label} together.",
    }
    if market == "india":  # older field names, kept for existing clients
        out.update(brent_inr=out["crude"], brent_inr_change_1m=crude_1m, brent_inr_change_1y=out["crude_change_1y"])
    if use_cache and groups:
        with _lock:
            _cache[market] = (time.time(), out)
    return out
