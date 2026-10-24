"""Big trades outside India (India: NSE bulk/block deals, src/data/nse_deals.py).

- us:        insider open-market buys and sells from the latest SEC Form 4
             filings (EDGAR). Needs SEC_USER_AGENT (name + contact email),
             as SEC's fair-access policy requires.
- china_a:   Shanghai / Shenzhen block trades (大宗交易) with buyer and seller
             branches, via Eastmoney's data centre (same host the listings use).
- hong_kong: Southbound Stock Connect - the HK stocks mainland investors
             bought and sold most each day (Shanghai and Shenzhen links).
- crypto:    no public trade-level whale feed, so the closest free signal:
             Binance futures positioning of the largest accounts (top-trader
             long/short), open interest change and taker buy/sell balance.

Each market is cached for CACHE_SECONDS.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CACHE_SECONDS = 3600
EASTMONEY = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SEC_FEED = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=4&company=&dateb=&owner=include"
            "&start={start}&count=100&output=atom")
POSITION_COINS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "SUI"]

_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


def _json(url: str, params: Optional[dict] = None, headers: Optional[dict] = None):
    import requests

    r = requests.get(url, params=params, timeout=20, headers=headers or {"User-Agent": "Mozilla/5.0 MarketMyna"})
    r.raise_for_status()
    return r.json()


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------- US: Form 4

_ATOM = {"a": "http://www.w3.org/2005/Atom"}


def parse_feed(xml_text: str) -> list[tuple[str, str]]:
    """Atom feed -> unique (cik, accession) of Form 4 filings, issuer entries first."""
    out: dict[str, str] = {}
    for entry in ET.fromstring(xml_text).findall("a:entry", _ATOM):
        link = entry.find("a:link", _ATOM)
        href = link.get("href") if link is not None else ""
        m = re.search(r"/data/(\d+)/(\d{18})/", href or "")
        if m and m.group(2) not in out:
            out[m.group(2)] = m.group(1)
    return [(cik, acc) for acc, cik in out.items()]


def _t(node, path: str) -> str:
    el = node.find(path)
    return (el.text or "").strip() if el is not None and el.text else ""


def parse_form4(xml_text: str) -> list[dict]:
    """Open-market purchases (P) and sales (S) in one Form 4, one row per
    side, shares summed and price volume-weighted."""
    root = ET.fromstring(xml_text)
    symbol = _t(root, "issuer/issuerTradingSymbol").upper()
    issuer = _t(root, "issuer/issuerName")
    owner = _t(root, "reportingOwner/reportingOwnerId/rptOwnerName")
    rel = root.find("reportingOwner/reportingOwnerRelationship")
    roles = []
    if rel is not None:
        if _t(rel, "isDirector") in ("1", "true"):
            roles.append("Director")
        if _t(rel, "isOfficer") in ("1", "true"):
            roles.append(_t(rel, "officerTitle") or "Officer")
        if _t(rel, "isTenPercentOwner") in ("1", "true"):
            roles.append("10% owner")
    sides: dict[str, dict] = {}
    for tx in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
        code = _t(tx, "transactionCoding/transactionCode")
        if code not in ("P", "S"):
            continue  # grants, option exercises, tax withholding... are not market trades
        shares = _num(_t(tx, "transactionAmounts/transactionShares/value")) or 0
        price = _num(_t(tx, "transactionAmounts/transactionPricePerShare/value")) or 0
        side = sides.setdefault(code, {"qty": 0.0, "value": 0.0, "date": _t(tx, "transactionDate/value")})
        side["qty"] += shares
        side["value"] += shares * price
    rows = []
    for code, s in sides.items():
        if not s["qty"]:
            continue
        rows.append({
            "date": s["date"][:10], "kind": "insider", "symbol": symbol, "name": issuer,
            "client": owner.title() if owner.isupper() else owner, "side": "buy" if code == "P" else "sell",
            "qty": s["qty"], "price": s["value"] / s["qty"] if s["qty"] else None, "value": s["value"] or None,
            "remarks": ", ".join(roles) or None,
        })
    return rows


def _us(fetch_text: Optional[Callable[[str], str]] = None, max_filings: int = 120) -> dict:
    from .sec_mdna import user_agent

    ua = user_agent()  # raises SecNotConfigured with the fix
    if fetch_text is None:
        import requests

        session = requests.Session()
        session.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})
        gate = threading.Semaphore(6)  # SEC allows 10 requests/second

        def fetch_text(url: str) -> str:
            with gate:
                r = session.get(url, timeout=20)
                time.sleep(0.15)
            r.raise_for_status()
            return r.text

    filings: list[tuple[str, str]] = []
    for start in (0, 100):
        filings += parse_feed(fetch_text(SEC_FEED.format(start=start)))
    seen, unique = set(), []
    for cik, acc in filings:
        if acc not in seen:
            seen.add(acc)
            unique.append((cik, acc))
    unique = unique[:max_filings]

    def one(item):
        cik, acc = item
        try:
            import json

            index = json.loads(fetch_text(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"))
            names = [f["name"] for f in index.get("directory", {}).get("item", []) if f["name"].endswith(".xml")]
            if not names:
                return []
            return parse_form4(fetch_text(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{names[0]}"))
        except Exception as exc:
            logger.debug("Form 4 %s skipped: %s", acc, exc)
            return []

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = [r for found in pool.map(one, unique) for r in found]
    rows.sort(key=lambda r: -(r["value"] or 0))
    return {
        "title": "Insider buys & sells (SEC Form 4)",
        "subtitle": "Open-market purchases and sales by executives, directors and 10% owners in the latest filings",
        "currency": "$", "deals": rows,
        "note": f"Latest {len(unique)} insider filings (Form 4) with the US regulator; open-market trades only (code P / S), "
                "so grants, option exercises and tax withholding are left out. Insiders sell for many reasons; "
                "buys are the rarer, stronger signal.",
    }


# -------------------------------------------------- China A: block trades


def parse_blocks(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        if str(r.get("SECURITY_TYPE_WEB")) != "1":  # 1 = A-share stock (skip ETFs, bonds)
            continue
        premium = _num(r.get("PREMIUM_RATIO"))
        out.append({
            "date": str(r.get("TRADE_DATE", ""))[:10], "kind": "block", "symbol": r.get("SECURITY_CODE"),
            "name": r.get("SECURITY_NAME_ABBR"),
            "client": f"{r.get('BUYER_NAME') or '?'} ← {r.get('SELLER_NAME') or '?'}",
            "side": "premium" if (premium or 0) > 0 else "discount" if (premium or 0) < 0 else "at market",
            "qty": _num(r.get("DEAL_VOLUME")), "price": _num(r.get("DEAL_PRICE")), "value": _num(r.get("DEAL_AMT")),
            "remarks": f"{premium * 100:+.1f}% vs close" if premium is not None else None,
        })
    return out


def _china(days: int, fetch=_json) -> dict:
    since = (date.today() - timedelta(days=days + 16)).isoformat()  # holidays (Golden Week, CNY) can run 9 days
    data = fetch(EASTMONEY, {
        "reportName": "RPT_DATA_BLOCKTRADE", "columns": "ALL", "sortColumns": "TRADE_DATE,DEAL_AMT", "sortTypes": "-1,-1",
        "pageSize": 500, "pageNumber": 1, "source": "WEB", "client": "WEB", "filter": f"(TRADE_DATE>='{since}')",
    })
    rows = parse_blocks(((data or {}).get("result") or {}).get("data") or [])
    if rows:
        latest = max(r["date"] for r in rows)
        cutoff = (date.fromisoformat(latest) - timedelta(days=days - 1)).isoformat()
        rows = [r for r in rows if r["date"] >= cutoff]
    rows.sort(key=lambda r: -(r["value"] or 0))
    return {
        "title": "Block trades (Shanghai & Shenzhen)",
        "subtitle": "Large negotiated trades between brokerage branches, with the price against the day's close",
        "currency": "¥", "deals": rows,
        "note": "Buyer ← seller are brokerage branches; 机构专用 means an institution's dedicated seat. A deep discount "
                "often means a large holder exiting; a premium, a buyer keen to get size. Source: Eastmoney.",
    }


# ------------------------------------------ Hong Kong: southbound connect


def parse_southbound(rows: list[dict], link: str) -> list[dict]:
    out = []
    for r in rows:
        net = _num(r.get("NET_BUY_AMT"))
        out.append({
            "date": str(r.get("TRADE_DATE", ""))[:10], "kind": f"southbound ({link})", "symbol": r.get("SECURITY_CODE"),
            "name": r.get("SECURITY_NAME"), "client": f"Mainland investors via {link}",
            "side": "net buy" if (net or 0) >= 0 else "net sell", "qty": None, "price": _num(r.get("CLOSE_PRICE")),
            "value": abs(net) if net is not None else _num(r.get("DEAL_AMT")),
            "remarks": (f"bought HK${(_num(r.get('BUY_AMT')) or 0) / 1e6:,.0f}m · sold HK${(_num(r.get('SELL_AMT')) or 0) / 1e6:,.0f}m"
                        if r.get("BUY_AMT") is not None else None),
        })
    return out


def _hk_english(rows: list[dict], names: Optional[dict[str, str]] = None) -> None:
    """Eastmoney sends Chinese names; our HK listing has the English ones."""
    if names is None:
        try:
            from ..data.listings import get_store

            names = {r["symbol"]: r["name"] for r in get_store().rows("hong_kong")}
        except Exception:
            names = {}
    for r in rows:
        en = names.get(str(r.get("symbol")))
        if en:
            r["name_local"], r["name"] = r["name"], en


def _hong_kong(days: int, fetch=_json, names: Optional[dict[str, str]] = None) -> dict:
    since = (date.today() - timedelta(days=days + 16)).isoformat()  # holidays (Golden Week, CNY) can run 9 days
    rows: list[dict] = []
    for code, link in (("002", "Shanghai link"), ("004", "Shenzhen link")):
        data = fetch(EASTMONEY, {
            "reportName": "RPT_MUTUAL_TOP10DEAL", "columns": "ALL", "sortColumns": "TRADE_DATE,RANK", "sortTypes": "-1,1",
            "pageSize": 200, "pageNumber": 1, "source": "WEB", "client": "WEB",
            "filter": f'(MUTUAL_TYPE="{code}")(TRADE_DATE>=\'{since}\')',
        })
        rows += parse_southbound(((data or {}).get("result") or {}).get("data") or [], link)
    if rows:
        latest = max(r["date"] for r in rows)
        cutoff = (date.fromisoformat(latest) - timedelta(days=days - 1)).isoformat()
        rows = [r for r in rows if r["date"] >= cutoff]
    rows.sort(key=lambda r: -(r["value"] or 0))
    _hk_english(rows, names)
    return {
        "title": "Southbound Stock Connect",
        "subtitle": "The Hong Kong stocks mainland investors traded most, and whether they were net buyers or sellers",
        "currency": "HK$", "deals": rows,
        "note": "Daily top-10 traded stocks on each southbound link (Shanghai and Shenzhen), sorted by net amount. "
                "Mainland flows have become a big driver of HK prices. Source: Eastmoney / HKEX.",
    }


# ------------------------------------------------ crypto: big-trader positioning


def _coin_positioning(coin: str, fetch=_json) -> Optional[dict]:
    base = "https://fapi.binance.com/futures/data"
    sym = f"{coin}USDT"
    top = fetch(f"{base}/topLongShortPositionRatio", {"symbol": sym, "period": "1d", "limit": 8})
    oi = fetch(f"{base}/openInterestHist", {"symbol": sym, "period": "1d", "limit": 8})
    taker = fetch(f"{base}/takerlongshortRatio", {"symbol": sym, "period": "1d", "limit": 2})
    if not top or not oi:
        return None
    last_top, prev_top = top[-1], top[-2] if len(top) > 1 else top[-1]
    oi_now = _num(oi[-1]["sumOpenInterestValue"])
    oi_1d = _num(oi[-2]["sumOpenInterestValue"]) if len(oi) > 1 else None
    oi_7d = _num(oi[0]["sumOpenInterestValue"]) if len(oi) > 1 else None
    return {
        "coin": coin,
        "top_long_pct": round(_num(last_top["longAccount"]) * 100, 1),
        "top_ratio": _num(last_top["longShortRatio"]),
        "top_ratio_change": (_num(last_top["longShortRatio"]) or 0) - (_num(prev_top["longShortRatio"]) or 0),
        "open_interest": oi_now,
        "oi_change_1d": (oi_now / oi_1d - 1) * 100 if oi_now and oi_1d else None,
        "oi_change_7d": (oi_now / oi_7d - 1) * 100 if oi_now and oi_7d else None,
        "taker_ratio": _num(taker[-1]["buySellRatio"]) if taker else None,
    }


def _crypto(fetch=_json) -> dict:
    with ThreadPoolExecutor(max_workers=5) as pool:
        rows = [r for r in pool.map(lambda c: _safe(_coin_positioning, c, fetch), POSITION_COINS) if r]
    return {
        "title": "Whale positioning (crypto futures)",
        "subtitle": "How the largest futures accounts are positioned, and whether leverage is building or unwinding",
        "currency": "$", "positions": rows,
        "note": "Top traders = the 20% of accounts with the biggest margin balances; their long % is by position size. "
                "Open interest = total value of open futures; rising OI with rising price = new money, falling OI = "
                "positions closing. Taker ratio > 1 = more aggressive buying than selling yesterday. Source: a major crypto exchange's futures data.",
    }


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as exc:
        logger.info("Positioning %s skipped: %s", args[0], exc)
        return None


def build(market: str, days: int = 1, use_cache: bool = True) -> dict:
    market = market.lower()
    builders: dict[str, Callable[[], dict]] = {
        "us": _us, "china_a": lambda: _china(days), "hong_kong": lambda: _hong_kong(days), "crypto": _crypto,
    }
    if market not in builders:
        raise ValueError("Big trades are available for India, US, China A, Hong Kong and crypto")
    key = (market, days if market in ("china_a", "hong_kong") else 0)
    if use_cache:
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    out = {"market": market, "days": days, "as_of": datetime.now().isoformat(timespec="minutes"), **builders[market]()}
    if use_cache and (out.get("deals") or out.get("positions")):
        with _lock:
            _cache[key] = (time.time(), out)
    return out
