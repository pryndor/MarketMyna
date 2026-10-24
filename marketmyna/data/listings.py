"""Full-market instrument universe (every listed stock, ETF and mutual fund).

Each market has a provider that pulls one or two free bulk files and
normalises them into flat rows:

    {symbol, name, market, type, exchange, sector, price, change,
     change_percent, volume, market_cap, high_52w, low_52w, currency, ...}

Sources
-------
- India stocks/ETFs: NSE daily "PR" bhavcopy zip (prices, 52w range, market
  cap for every NSE security) + EQUITY_L / SME_EQUITY_L for full names +
  the Nifty Total Market list for industry. REITs (series RR) and InvITs
  (series IV) come from the same zip, as units with sector REIT / InvIT.
- India mutual funds: AMFI NAVAll.txt (every scheme, NAV, AMC, category).
- US stocks/ETFs: NASDAQ screener API (NYSE/NASDAQ/AMEX), falling back to
  the nasdaqtrader symbol directories (names only) when it is down.
- China A: Eastmoney quote list API (akshare's own source), falling back
  to Sina Finance's full A-share list.
- Hong Kong: HKEX's official securities list, priced via Eastmoney, then
  Tencent batch quotes, then Sina.
- Crypto: Binance public 24h tickers (USDT pairs).

Rows are cached on disk (~/.marketmyna/listings/<key>.json) and in memory.
Stale caches are served immediately while a background thread refreshes
them, so only the very first load of a market waits on the network.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import random
import re
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

import requests

from marketmyna.core.home import app_home

from .categories import enrich
from .shariah import stamp as stamp_shariah

logger = logging.getLogger(__name__)

_UA = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
}
_TIMEOUT = 40

# Listing types
STOCK = "stock"
ETF = "etf"
MUTUAL_FUND = "mf"
CRYPTO = "crypto"


def _get(url: str, **kwargs) -> requests.Response:
    resp = requests.get(url, headers=_UA, timeout=_TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp


def _float(value) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("$", "").replace("%", "")
    if text in ("", "-", "NA", "N/A", "nan"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _row(symbol: str, name: str, market: str, type_: str, **fields) -> dict:
    row = {
        "symbol": symbol,
        "name": name or symbol,
        "market": market,
        "type": type_,
        "exchange": None,
        "sector": None,
        "price": None,
        "change": None,
        "change_percent": None,
        "volume": None,
        "market_cap": None,
        "high_52w": None,
        "low_52w": None,
        "currency": None,
    }
    row.update(fields)
    return row


def _with_change(row: dict, prev: Optional[float]) -> dict:
    price = row.get("price")
    if price is not None and prev:
        row["change"] = round(price - prev, 4)
        row["change_percent"] = round((price - prev) / prev * 100, 2)
    return row


# ------------------------------------------------------------------ India


def _read_csv(text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [f.strip() for f in reader.fieldnames or []]
    return [{k: (v or "").strip() for k, v in r.items() if k} for r in reader]


def _nse_pr_zip() -> tuple[datetime, zipfile.ZipFile]:
    """Latest NSE PR bhavcopy zip. Walks back from today to skip weekends,
    holidays and the pre-close hours before today's file is published."""
    day = datetime.now()
    last_error: Exception | None = None
    for _ in range(10):
        url = f"https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR{day:%d%m%y}.zip"
        try:
            return day, zipfile.ZipFile(io.BytesIO(_get(url).content))
        except Exception as exc:  # 404 on non-trading days
            last_error = exc
            day -= timedelta(days=1)
    raise RuntimeError(f"No NSE bhavcopy found in the last 10 days: {last_error}")


def _zip_csv(zf: zipfile.ZipFile, prefix: str) -> list[dict]:
    for name in zf.namelist():
        if name.lower().startswith(prefix):
            return _read_csv(zf.read(name).decode("latin-1"))
    return []


# Listed trusts: NSE series -> sector. They trade like shares (units).
TRUST_SERIES = {"RR": "REIT", "IV": "InvIT"}
# NSE abbreviates trust names ("BROOKFIELD INDIA RET"); the well-known ones
# get their full names, the rest are title-cased.
TRUST_NAMES = {
    "EMBASSY": "Embassy Office Parks REIT",
    "MINDSPACE": "Mindspace Business Parks REIT",
    "BIRET": "Brookfield India Real Estate Trust",
    "NXST": "Nexus Select Trust",
    "KRT": "Knowledge Realty Trust",
    "BAGMANE": "Bagmane Prime Office REIT",
    "INDIGRID": "IndiGrid Infrastructure Trust",
    "PGINVIT": "POWERGRID Infrastructure Investment Trust",
    "IRBINVIT": "IRB InvIT Fund",
    "NHIT": "National Highways Infra Trust",
    "ANZEN": "Anzen India Energy Yield Plus Trust",
}


def _trust_name(symbol: str, raw: str) -> str:
    if symbol in TRUST_NAMES:
        return TRUST_NAMES[symbol]
    name = re.sub(r"\s+", " ", raw or symbol).strip().title()
    return re.sub(r"\b(Reit|Invits?)\b", lambda m: "REIT" if m.group(1) == "Reit" else "InvIT", name)


def _india_trusts(zf: zipfile.ZipFile, day: datetime) -> list[dict]:
    """Every listed REIT and InvIT: the market-cap file lists all of them,
    the price file has the day's trades (missing when a unit didn't trade)."""
    traded = {r["SYMBOL"]: r for r in _zip_csv(zf, "pd") if r.get("SERIES") in TRUST_SERIES and r.get("SYMBOL")}
    rows = []
    for m in _zip_csv(zf, "mcap"):
        sym, series = m.get("Symbol", ""), m.get("Series", "")
        if not sym or series not in TRUST_SERIES:
            continue
        t = traded.get(sym, {})
        vol = _float(t.get("NET_TRDQTY"))
        row = _row(
            sym,
            _trust_name(sym, m.get("Security Name", "")),
            "india",
            STOCK,
            exchange="NSE",
            sector=TRUST_SERIES[series],
            price=_float(t.get("CLOSE_PRICE")) or _float(m.get("Close Price/Paid up value(Rs.)")),
            volume=int(vol) if vol is not None else None,
            market_cap=_float(m.get("Market Cap(Rs.)")),
            high_52w=_float(t.get("HI_52_WK")) or None,
            low_52w=_float(t.get("LO_52_WK")) or None,
            currency="INR",
            series=series,
            close_date=day.date().isoformat(),
        )
        rows.append(_with_change(row, _float(t.get("PREV_CL_PR"))))
    return rows


def fetch_india_stocks() -> list[dict]:
    day, zf = _nse_pr_zip()
    mcap = {r["Symbol"]: _float(r.get("Market Cap(Rs.)")) for r in _zip_csv(zf, "mcap") if r.get("Symbol")}
    mcap_names = {r["Symbol"]: r.get("Security Name", "") for r in _zip_csv(zf, "mcap") if r.get("Symbol")}

    names: dict[str, str] = {}
    isins: dict[str, str] = {}  # links fund portfolio files (by ISIN) to symbols
    for url in (
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://nsearchives.nseindia.com/emerge/corporates/content/SME_EQUITY_L.csv",
    ):
        try:
            for r in _read_csv(_get(url).text):
                if r.get("SYMBOL"):
                    names[r["SYMBOL"]] = r.get("NAME OF COMPANY") or r.get("NAME_OF_COMPANY", "")
                    if r.get("ISIN NUMBER"):
                        isins[r["SYMBOL"]] = r["ISIN NUMBER"]
        except Exception as exc:
            logger.warning("NSE name list %s failed: %s", url, exc)

    # NSE only publishes industry for index constituents; together these
    # two lists cover the ~1,000 largest names. The rest get a category
    # inferred from their company name (marketmyna/data/categories.py).
    industry: dict[str, str] = {}
    for index in ("ind_niftytotalmarket_list", "ind_niftymicrocap250_list"):
        try:
            text = _get(f"https://nsearchives.nseindia.com/content/indices/{index}.csv").text
            for r in _read_csv(text):
                if r.get("Symbol") and r.get("Industry"):
                    industry.setdefault(r["Symbol"], r["Industry"])
        except Exception as exc:
            logger.warning("NSE industry list %s failed: %s", index, exc)

    rows: dict[str, dict] = {}
    # Main board (pd = all securities incl. indices; keep equity series).
    for r in _zip_csv(zf, "pd") + _zip_csv(zf, "sme"):
        sym = r.get("SYMBOL", "")
        series = r.get("SERIES", "")
        if not sym or series not in ("EQ", "BE", "BZ", "SM", "ST", "SZ"):
            continue
        sme = series in ("SM", "ST", "SZ")
        vol = _float(r.get("NET_TRDQTY"))
        row = _row(
            sym,
            names.get(sym) or mcap_names.get(sym) or r.get("SECURITY", sym),
            "india",
            STOCK,
            exchange="NSE SME" if sme else "NSE",
            sector=industry.get(sym) or ("SME" if sme else None),
            price=_float(r.get("CLOSE_PRICE")),
            volume=int(vol) if vol is not None else None,
            market_cap=mcap.get(sym),
            high_52w=_float(r.get("HI_52_WK")) or None,
            low_52w=_float(r.get("LO_52_WK")) or None,
            currency="INR",
            series=series,
            isin=isins.get(sym),
            close_date=day.date().isoformat(),  # session of the official close (bhavcopy)
        )
        rows[sym] = _with_change(row, _float(r.get("PREV_CL_PR")))

    for r in _zip_csv(zf, "etf"):
        sym = r.get("SYMBOL", "")
        if not sym:
            continue
        vol = _float(r.get("NET TRADED QTY"))
        row = _row(
            sym,
            f"{r['UNDERLYING'].title()} ETF" if r.get("UNDERLYING") else r.get("SECURITY", sym),
            "india",
            ETF,
            exchange="NSE",
            sector="ETF",
            price=_float(r.get("CLOSE PRICE")),
            volume=int(vol) if vol is not None else None,
            high_52w=_float(r.get("52 WEEK HIGH")) or None,
            low_52w=_float(r.get("52 WEEK LOW")) or None,
            currency="INR",
            underlying=r.get("UNDERLYING") or None,
            close_date=day.date().isoformat(),
        )
        rows[sym] = _with_change(row, _float(r.get("PREVIOUS CLOSE PRICE")))

    for row in _india_trusts(zf, day):
        rows[row["symbol"]] = row

    # Listed names with no trade today still belong in the universe.
    for sym, name in names.items():
        rows.setdefault(sym, _row(sym, name, "india", STOCK, exchange="NSE", sector=industry.get(sym),
                                  market_cap=mcap.get(sym), currency="INR"))

    logger.info("India stocks: %d rows (bhavcopy %s)", len(rows), day.date())
    return list(rows.values())


def _amfi_category(header: str) -> tuple[str, str]:
    """'Open Ended Schemes(Equity Scheme - Large Cap Fund)' ->
    ('Equity', 'Large Cap Fund')."""
    inner = header[header.find("(") + 1 : header.rfind(")")] if "(" in header else header
    structure = header.split("(")[0].replace("Schemes", "").strip()
    if " - " in inner:
        group, sub = inner.split(" - ", 1)
    else:
        group, sub = inner, inner
    group = re.sub(r"\s*Schemes?$", "", group.strip()) or "Other"
    if structure and not structure.lower().startswith("open"):
        sub = f"{sub} ({structure})"
    return group, sub.strip()


def fetch_india_mutual_funds() -> list[dict]:
    text = _get("https://portal.amfiindia.com/spages/NAVAll.txt").content.decode("utf-8", "replace")
    rows: list[dict] = []
    group, category, amc = "Other", "Other", ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("Scheme Code"):
            continue
        if ";" not in line:
            if "Schemes(" in line or line.endswith("Schemes"):
                group, category = _amfi_category(line)
            else:
                amc = line
            continue
        parts = [p.strip() for p in line.split(";")]
        if len(parts) >= 8:
            code, isin, isin_re, name, plan, option, nav, date = parts[:8]
            display = " - ".join(p for p in (name, plan, option) if p and p != "-")
        elif len(parts) >= 6:
            code, isin, isin_re, display, nav, date = parts[:6]
            plan = "Direct" if "direct" in display.lower() else "Regular"
            option = "Growth" if "growth" in display.lower() else ("IDCW" if "idcw" in display.lower() else "")
        else:
            continue
        rows.append(
            _row(
                code,
                display,
                "india",
                MUTUAL_FUND,
                exchange=amc.replace(" Mutual Fund", "").replace(" MUTUAL FUND", "") or None,
                sector=category,
                price=_float(nav),
                currency="INR",
                amc=amc,
                fund_group=group,
                plan="Direct" if "direct" in (plan or "").lower() else "Regular",
                option=option or None,
                isin=isin if isin not in ("-", "") else None,
                nav_date=date,
            )
        )
    logger.info("India mutual funds: %d rows", len(rows))
    return rows


# --------------------------------------------------------------------- US


def _nasdaq_screener(kind: str) -> list[dict]:
    url = f"https://api.nasdaq.com/api/screener/{kind}?tableonly=true&download=true&limit=0"
    data = _get(url).json().get("data") or {}
    table = data.get("data") if kind == "etf" else data
    return (table or {}).get("rows") or []


def _fetch_us_symbol_directory() -> list[dict]:
    """Names-only fallback when the NASDAQ screener API is unavailable."""
    rows: list[dict] = []
    exchanges = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "BATS", "V": "IEX"}
    for url, sym_col, exch in (
        ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "Symbol", None),
        ("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", "ACT Symbol", "Exchange"),
    ):
        lines = _get(url).text.splitlines()
        reader = csv.DictReader(lines[:-1], delimiter="|")  # last line = file timestamp
        for r in reader:
            if r.get("Test Issue") == "Y" or not r.get(sym_col):
                continue
            rows.append(
                _row(
                    r[sym_col].replace(".", "-"),
                    r.get("Security Name", ""),
                    "us",
                    ETF if r.get("ETF") == "Y" else STOCK,
                    exchange=exchanges.get(r.get(exch, ""), "NASDAQ") if exch else "NASDAQ",
                    currency="USD",
                )
            )
    return rows


def fetch_us() -> list[dict]:
    try:
        stocks = _nasdaq_screener("stocks")
        etfs = _nasdaq_screener("etf")
    except Exception as exc:
        logger.warning("NASDAQ screener failed (%s); using symbol directory", exc)
        return _fetch_us_symbol_directory()

    rows: dict[str, dict] = {}
    for r in stocks:
        sym = (r.get("symbol") or "").strip().replace("/", "-").replace("^", "-P")
        if not sym:
            continue
        vol = _float(r.get("volume"))
        rows[sym] = _row(
            sym,
            r.get("name", "").strip(),
            "us",
            STOCK,
            sector=r.get("sector") or None,
            industry=r.get("industry") or None,
            country=r.get("country") or None,
            price=_float(r.get("lastsale")),
            change=_float(r.get("netchange")),
            change_percent=_float(r.get("pctchange")),
            volume=int(vol) if vol is not None else None,
            market_cap=_float(r.get("marketCap")) or None,
            currency="USD",
        )
    for r in etfs:
        sym = (r.get("symbol") or "").strip()
        if not sym:
            continue
        rows[sym] = _row(
            sym,
            r.get("companyName", "").strip(),
            "us",
            ETF,
            sector="ETF",
            price=_float(r.get("lastSalePrice")),
            change=_float(r.get("netChange")),
            change_percent=round(_float(r.get("percentageChange")) or 0, 2)
            if r.get("percentageChange") else None,
            return_1y=_float(r.get("oneYearPercentage")),
            currency="USD",
        )
    logger.info("US: %d rows", len(rows))
    return list(rows.values())


# --------------------------------------------------------- China / HK


# Eastmoney's quote list API (the same source akshare's *_spot_em functions
# wrap) called directly, so China/HK listings need no extra package.
# It caps pages at 100 rows, so pages are fetched in parallel, and its
# mirror hosts are individually flaky (timeouts, redirect loops), so each
# page rotates through several before giving up.
_EASTMONEY_HOSTS = [
    "https://82.push2.eastmoney.com",
    "https://push2delay.eastmoney.com",
    "http://1.push2.eastmoney.com",
    "http://29.push2.eastmoney.com",
    "http://33.push2.eastmoney.com",
    "http://7.push2.eastmoney.com",
    "http://push2delay.eastmoney.com",
]
_EASTMONEY_FIELDS = "f2,f3,f4,f5,f9,f12,f13,f14,f20,f23,f100"
_EASTMONEY_MARKETS = {
    # SSE main + STAR, SZSE main + ChiNext, BSE
    "china_a": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
    "hong_kong": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2",
}


def _eastmoney_page(fs: str, page: int, quick: bool = False) -> dict:
    params = {
        "pn": page, "pz": 100, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "fid": "f20", "fs": fs, "fields": _EASTMONEY_FIELDS,
    }
    last_error: Exception | None = None
    # Start each page on a different host to spread the load; a second
    # pass after a pause rides out short throttling bursts.
    n = len(_EASTMONEY_HOSTS)
    # A first probe tries each host once with a short timeout; later pages
    # (Eastmoney known reachable) get a second, paused pass.
    for i in range(n if quick else 2 * n):
        if i == n:
            time.sleep(2)
        host = _EASTMONEY_HOSTS[(page + i) % n]
        try:
            resp = requests.get(
                f"{host}/api/qt/clist/get", params=params, headers=_UA, timeout=5 if quick else 10,
                allow_redirects=False,
            )
            resp.raise_for_status()
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            return resp.json().get("data") or {}
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"Eastmoney page {page} failed on every host: {last_error}")


# When Eastmoney blocks this IP it stays blocked for a while; after one
# failed first page, go straight to the backups instead of spending minutes
# on timeouts across every mirror.
_EASTMONEY_COOLDOWN = 30 * 60
_eastmoney_blocked_until = 0.0


def _eastmoney_rows(market: str) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor

    global _eastmoney_blocked_until
    if time.monotonic() < _eastmoney_blocked_until:
        raise RuntimeError("Eastmoney skipped: it refused connections recently")
    fs = _EASTMONEY_MARKETS[market]
    try:
        first = _eastmoney_page(fs, 1, quick=True)
    except Exception:
        _eastmoney_blocked_until = time.monotonic() + _EASTMONEY_COOLDOWN
        raise
    items = list(first.get("diff") or [])
    pages = -(-int(first.get("total") or 0) // 100)
    if pages > 1:
        def paced(page: int) -> dict:
            # Eastmoney bans IPs that burst; keep a trickle, not a flood.
            time.sleep(random.uniform(0.1, 0.4))
            return _eastmoney_page(fs, page)

        with ThreadPoolExecutor(max_workers=3) as pool:
            for data in pool.map(paced, range(2, pages + 1)):
                items.extend(data.get("diff") or [])
    if not items:
        raise RuntimeError("Eastmoney returned no rows")
    return items


def _china_exchange(code: str) -> str:
    if code[0] in "569":  # 5xxxxx = Shanghai-listed funds (ETFs / LOFs)
        return "SSE"
    if code[0] in "48":
        return "BSE"
    return "SZSE"


def _eastmoney_listing(market: str, currency: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for r in _eastmoney_rows(market):
        sym = str(r.get("f12") or "")
        name = str(r.get("f14") or sym)
        # HK RMB-traded duplicate counters ("腾讯控股-R") mirror the HKD line.
        if not sym or name.endswith("-R"):
            continue
        vol = _float(r.get("f5"))
        pe = _float(r.get("f9"))
        rows[sym] = _row(
            sym,
            name,
            market,
            STOCK,
            exchange=_china_exchange(sym) if market == "china_a" else "HKEX",
            sector=(r.get("f100") if r.get("f100") not in (None, "-") else None),
            price=_float(r.get("f2")),
            change=_float(r.get("f4")),
            change_percent=_float(r.get("f3")),
            # A-share volume is quoted in lots of 100 shares.
            volume=int(vol * 100 if market == "china_a" else vol) if vol is not None else None,
            market_cap=_float(r.get("f20")) or None,
            pe=pe if pe and pe > 0 else None,
            pb=_float(r.get("f23")),
            currency=currency,
        )
    logger.info("%s (Eastmoney): %d rows", market, len(rows))
    return rows


# Sina Finance and Tencent: the same fallbacks daily_stock_analysis uses
# when Eastmoney is throttling (akshare's stock_zh_a_spot / stock_hk_spot
# read the Sina endpoints below).
_SINA_API = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php"
_SINA_HEADERS = {**_UA, "Referer": "https://finance.sina.com.cn"}
_TENCENT_HEADERS = {**_UA, "Referer": "https://finance.qq.com"}


def _sina_pages(method: str, node: str, max_pages: int = 80) -> list[dict]:
    """All rows of a Sina market-centre list, 100 per page, gently paced."""
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        batch = None
        for attempt in range(3):  # Sina has short slow spells; retry a page before giving up
            try:
                resp = requests.get(
                    f"{_SINA_API}/Market_Center.{method}",
                    params={"page": page, "num": 100, "sort": "symbol", "asc": 1, "node": node, "_s_r_a": "page"},
                    headers=_SINA_HEADERS,
                    timeout=20,
                )
                resp.raise_for_status()
                batch = resp.json() or []
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        time.sleep(random.uniform(0.1, 0.3))
    if not out:
        raise RuntimeError(f"Sina returned no rows for {node}")
    return out


def _sina_china_a() -> list[dict]:
    rows = []
    for r in _sina_pages("getHQNodeData", "hs_a"):
        code = str(r.get("code") or "")
        if not code:
            continue
        mcap = _float(r.get("mktcap"))  # in 10,000 CNY
        pe = _float(r.get("per"))
        rows.append(_row(
            code, str(r.get("name") or code), "china_a", STOCK,
            exchange=_china_exchange(code),
            price=_float(r.get("trade")) or None,  # 0 = suspended
            change=_float(r.get("pricechange")),
            change_percent=_float(r.get("changepercent")),
            volume=int(_float(r.get("volume")) or 0) or None,
            market_cap=mcap * 1e4 if mcap else None,
            pe=pe if pe and pe > 0 else None,
            pb=_float(r.get("pb")),
            currency="CNY",
        ))
    logger.info("china_a (Sina): %d rows", len(rows))
    return rows


def _tencent_quote_lines(symbols: list[str], batch_size: int = 60):
    """Yield the "~"-split fields of each Tencent quote, in batches."""
    for start in range(0, len(symbols), batch_size):
        resp = requests.get("https://qt.gtimg.cn/q=" + ",".join(symbols[start:start + batch_size]),
                            headers=_TENCENT_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        for line in resp.content.decode("gbk", errors="replace").split(";"):
            if '"' in line:
                yield line[line.index('"') + 1:line.rindex('"')].split("~")
        if start + batch_size < len(symbols):
            time.sleep(random.uniform(0.05, 0.2))


def _cached_rows(key: str) -> list[dict]:
    """Rows from the on-disk listing cache (last successful fetch), if any."""
    path = app_home() / "listings" / f"{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("rows") or []
    except (OSError, ValueError):
        return []


def _tencent_china_a(codes: list[str], names: dict[str, str]) -> list[dict]:
    from .extra_sources import tencent_symbol

    rows = []
    for f in _tencent_quote_lines([tencent_symbol(c, "china_a") for c in codes]):
        if len(f) < 47 or not f[2]:
            continue
        mcap, pe, vol = _float(f[45]), _float(f[39]), _float(f[6])  # mcap in 100M CNY, volume in lots
        rows.append(_row(
            f[2], f[1] or names.get(f[2], f[2]), "china_a", STOCK,
            exchange=_china_exchange(f[2]), price=_float(f[3]) or None, change=_float(f[31]),
            change_percent=_float(f[32]), volume=int(vol * 100) if vol else None,
            market_cap=mcap * 1e8 if mcap else None, pe=pe if pe and pe > 0 else None, pb=_float(f[46]),
            currency="CNY",
        ))
    if not rows:
        raise RuntimeError("Tencent returned no China A quotes")
    logger.info("china_a (Tencent, cached code list): %d rows", len(rows))
    return rows


def _sina_china_funds() -> list[dict]:
    """Exchange-traded funds on Shanghai / Shenzhen: ETFs and LOFs (listed
    open-end funds), from Sina's market centre. Both trade like shares, so
    they sit in the ETF tab; `sector` tells them apart."""
    rows = []
    for node, label in (("etf_hq_fund", "ETF"), ("lof_hq_fund", "LOF")):
        for r in _sina_pages("getHQNodeData", node, max_pages=30):
            code = str(r.get("code") or "")
            if not code:
                continue
            mcap = _float(r.get("mktcap"))  # in 10,000 CNY
            rows.append(_row(
                code, str(r.get("name") or code), "china_a", ETF,
                exchange=_china_exchange(code),
                sector=label,
                price=_float(r.get("trade")) or None,
                change=_float(r.get("pricechange")),
                change_percent=_float(r.get("changepercent")),
                volume=int(_float(r.get("volume")) or 0) or None,
                market_cap=mcap * 1e4 if mcap else None,
                currency="CNY",
            ))
    logger.info("china_a funds (Sina): %d rows", len(rows))
    return rows


def fetch_china_a() -> list[dict]:
    """Stocks plus exchange-traded funds (best effort: a fund-list failure
    never costs the stock list)."""
    stocks = _fetch_china_a_stocks()
    try:
        funds = _sina_china_funds()
    except Exception as exc:
        logger.warning("China A funds via Sina failed: %s", exc)
        funds = [r for r in _cached_rows("china_a") if r.get("type") == ETF]
    have = {r["symbol"] for r in stocks}
    return stocks + [f for f in funds if f["symbol"] not in have]


def _fetch_china_a_stocks() -> list[dict]:
    """Eastmoney, then Sina's full A-share list, then fresh Tencent prices
    for the last known code list (new listings appear once a full source
    is back)."""
    try:
        return list(_eastmoney_listing("china_a", "CNY").values())
    except Exception as exc:
        logger.warning("China A via Eastmoney failed (%s); falling back to Sina", exc)
    try:
        return _sina_china_a()
    except Exception as exc:
        logger.warning("China A via Sina failed (%s); refreshing cached codes via Tencent", exc)
    cached = _cached_rows("china_a")
    if not cached:
        raise RuntimeError("Eastmoney and Sina are unavailable and there is no cached China A list yet")
    stocks = [r for r in cached if r.get("type") != ETF]
    return _tencent_china_a([r["symbol"] for r in stocks], {r["symbol"]: r.get("name", "") for r in stocks})


def _tencent_hk_quotes(codes: list[str], batch_size: int = 60) -> dict[str, dict]:
    """Batch HK quotes from Tencent: price, change, volume, market cap,
    P/E and 52-week range for up to `batch_size` codes per request."""
    quotes: dict[str, dict] = {}
    for f in _tencent_quote_lines([f"hk{c}" for c in codes], batch_size):
        if len(f) < 50 or not f[2] or not _float(f[3]):
            continue
        mcap = _float(f[45])  # in 100 million HKD
        pe = _float(f[39])
        quotes[f[2]] = {
            "name": f[1], "price": _float(f[3]), "change": _float(f[31]),
            "change_percent": _float(f[32]), "volume": _float(f[6]),
            "market_cap": mcap * 1e8 if mcap else None, "pe": pe if pe and pe > 0 else None,
            "high_52w": _float(f[48]) or None, "low_52w": _float(f[49]) or None,
        }
    if not quotes:
        raise RuntimeError("Tencent returned no Hong Kong quotes")
    return quotes


def _sina_hk_quotes() -> dict[str, dict]:
    quotes = {}
    for r in _sina_pages("getHKStockData", "qbgg_hk"):
        code = str(r.get("symbol") or "")
        price = _float(r.get("lasttrade"))
        if not code or not price:
            continue
        quotes[code] = {
            "name": r.get("name"), "price": price, "change": _float(r.get("pricechange")),
            "change_percent": _float(r.get("changepercent")), "volume": _float(r.get("volume")),
            "high_52w": _float(r.get("high_52week")) or None, "low_52w": _float(r.get("low_52week")) or None,
        }
    return quotes


def _hong_kong_quotes(codes: list[str]) -> tuple[dict[str, dict], str]:
    """Prices for HK codes: Eastmoney, then Tencent, then Sina."""
    for name, fetch in (
        ("Eastmoney", lambda: _eastmoney_listing("hong_kong", "HKD")),
        ("Tencent", lambda: _tencent_hk_quotes(codes)),
        ("Sina", _sina_hk_quotes),
    ):
        try:
            quotes = fetch()
            if quotes:
                return quotes, name
        except Exception as exc:
            logger.warning("Hong Kong prices via %s failed: %s", name, exc)
    return {}, "none"


def _read_xlsx_rows(data: bytes) -> list[dict[str, str]]:
    """First sheet of an .xlsx as [{column letter: text}] (stdlib only, so
    no openpyxl dependency just for one exchange file)."""
    from xml.etree import ElementTree as ET

    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    zf = zipfile.ZipFile(io.BytesIO(data))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in zf.namelist():
        for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).iter(f"{ns}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))
    out = []
    for row in ET.fromstring(zf.read("xl/worksheets/sheet1.xml")).iter(f"{ns}row"):
        cells: dict[str, str] = {}
        for c in row.iter(f"{ns}c"):
            col = re.match(r"[A-Z]+", c.get("r", "")).group()
            v = c.find(f"{ns}v")
            if v is None:
                t = c.find(f"{ns}is/{ns}t")
                cells[col] = (t.text or "") if t is not None else ""
            else:
                cells[col] = shared[int(v.text)] if c.get("t") == "s" else (v.text or "")
        out.append(cells)
    return out


_HKEX_TYPES = {
    "Equity": STOCK,
    "Real Estate Investment Trusts": STOCK,
    "Exchange Traded Products": ETF,
}


def fetch_hong_kong() -> list[dict]:
    """HKEX's official list (every stock/ETF/REIT, English names) as the
    base, enriched with Eastmoney prices/industry when it is reachable."""
    data = _get(
        "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
    ).content
    rows: dict[str, dict] = {}
    for r in _read_xlsx_rows(data):
        code, name, cat, sub = r.get("A", ""), r.get("B", ""), r.get("C", ""), r.get("D", "")
        if not code.isdigit() or cat not in _HKEX_TYPES or sub == "Trading Only Securities":
            continue
        # RMB counters ("Tencent-R", "Baba-WR" for weighted-voting shares)
        # duplicate the HKD line.
        if re.search(r"-W?R$", name.strip().upper()):
            continue
        rows[code] = _row(
            code,
            name.title(),
            "hong_kong",
            _HKEX_TYPES[cat],
            exchange="HKEX GEM" if "GEM" in sub else "HKEX",
            sector="REIT" if cat.startswith("Real Estate") else ("ETF" if cat.startswith("Exchange") else None),
            currency=r.get("Q") or "HKD",
            isin=r.get("F") or None,
        )
    if not rows:
        raise RuntimeError("HKEX list returned no securities")

    quotes, source = _hong_kong_quotes(list(rows))
    for code, row in rows.items():
        q = quotes.get(code)
        if not q:
            continue
        for key in ("price", "change", "change_percent", "volume", "market_cap", "pe", "pb", "high_52w", "low_52w"):
            if q.get(key) is not None:
                row[key] = q[key]
        if q.get("sector") and not row.get("sector"):
            row["sector"] = q["sector"]
        if q.get("name"):
            row["name_local"] = q["name"]
    priced = sum(1 for r in rows.values() if r.get("price") is not None)
    logger.info("Hong Kong: %d rows (%d priced via %s)", len(rows), priced, source)
    return list(rows.values())


# ---------------------------------------------------------------- Crypto


def fetch_crypto() -> list[dict]:
    # Binance's public 24h ticker endpoint returns every pair in one call,
    # so no ccxt (or API key) is needed just to list the market.
    tickers = _get("https://api.binance.com/api/v3/ticker/24hr").json()
    rows = []
    for t in tickers:
        pair = t.get("symbol", "")
        if not pair.endswith("USDT"):
            continue
        base = pair[: -len("USDT")]
        price = _float(t.get("lastPrice"))
        if not base or base.endswith(("UP", "DOWN", "BULL", "BEAR")) or not price:
            continue
        rows.append(
            _row(
                f"{base}-USD",
                base,
                "crypto",
                CRYPTO,
                exchange="Spot (USDT)",
                price=price,
                change=_float(t.get("priceChange")),
                change_percent=_float(t.get("priceChangePercent")),
                volume=_float(t.get("quoteVolume")),
                currency="USD",
            )
        )
    return rows


# ------------------------------------------------------------- Registry

# key -> (market, fetcher, ttl)
PROVIDERS: dict[str, tuple[str, Callable[[], list[dict]], timedelta]] = {
    "india_stocks": ("india", fetch_india_stocks, timedelta(hours=6)),
    "india_mf": ("india", fetch_india_mutual_funds, timedelta(hours=6)),
    "us": ("us", fetch_us, timedelta(hours=1)),
    # Eastmoney rate-limits hard, so China/HK refresh less often.
    "china_a": ("china_a", fetch_china_a, timedelta(hours=4)),
    "hong_kong": ("hong_kong", fetch_hong_kong, timedelta(hours=4)),
    "crypto": ("crypto", fetch_crypto, timedelta(minutes=10)),
}

MARKET_LABELS = {
    "india": "India",
    "us": "US",
    "china_a": "China A",
    "hong_kong": "Hong Kong",
    "crypto": "Crypto",
}


_RETRY_AFTER = 60.0
# An explicit refresh (any signed-in user can press it) re-fetches a source at
# most this often, so repeated clicks can't hammer NSE / Yahoo.
_FORCE_GAP = 300.0


class _Entry:
    __slots__ = ("rows", "fetched_at", "attempted_at", "error", "lock", "refreshing")

    def __init__(self):
        self.rows: list[dict] = []
        self.fetched_at: Optional[float] = None
        self.attempted_at: float = 0.0
        self.error: Optional[str] = None
        self.lock = threading.Lock()
        self.refreshing = False


class ListingStore:
    """Process-wide cache of provider rows with on-disk persistence."""

    def __init__(self, cache_dir: Optional[Path] = None, providers=None):
        self.cache_dir = cache_dir or app_home() / "listings"
        self.providers = providers or PROVIDERS
        self._entries = {key: _Entry() for key in self.providers}

    # ---- persistence
    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _load_disk(self, key: str, entry: _Entry) -> None:
        path = self._path(key)
        if entry.fetched_at is not None or not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entry.rows = stamp_shariah(enrich(payload["rows"]))
            entry.fetched_at = payload["fetched_at"]
            self._retry_if_unpriced(key, entry)
        except Exception as exc:
            logger.warning("Listing cache %s unreadable: %s", path, exc)

    def _retry_if_unpriced(self, key: str, entry: _Entry) -> None:
        """Names came through but prices didn't (e.g. Hong Kong while
        Eastmoney is throttling): keep the rows but retry in ~10 minutes
        instead of waiting out the full TTL."""
        if not entry.rows or any(r.get("price") is not None for r in entry.rows):
            return
        ttl = self.providers[key][2].total_seconds()
        entry.fetched_at = min(entry.fetched_at or 0.0, time.time() - max(0.0, ttl - 600))
        entry.error = "Prices temporarily unavailable; showing names only"

    def _save_disk(self, key: str, entry: _Entry) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = self._path(key).with_suffix(".tmp")
            tmp.write_text(json.dumps({"fetched_at": entry.fetched_at, "rows": entry.rows}), encoding="utf-8")
            tmp.replace(self._path(key))
        except Exception as exc:
            logger.warning("Listing cache %s not saved: %s", key, exc)

    # ---- fetching
    def _refresh(self, key: str, entry: _Entry) -> None:
        fetcher = self.providers[key][1]
        entry.attempted_at = time.time()
        try:
            rows = fetcher()
            if not rows:
                raise RuntimeError("source returned no rows")
            entry.rows = stamp_shariah(enrich(rows))
            entry.fetched_at = time.time()
            entry.error = None
            self._save_disk(key, entry)
            self._retry_if_unpriced(key, entry)
        except Exception as exc:
            logger.warning("Listing provider %s failed: %s", key, exc)
            entry.error = str(exc)
        finally:
            entry.refreshing = False

    def _is_stale(self, key: str, entry: _Entry) -> bool:
        ttl = self.providers[key][2]
        return entry.fetched_at is None or time.time() - entry.fetched_at > ttl.total_seconds()

    def get(self, key: str, force: bool = False) -> list[dict]:
        entry = self._entries[key]
        with entry.lock:
            self._load_disk(key, entry)
            # Failed sources back off for a minute instead of re-hitting
            # the network (and its timeouts) on every request.
            backing_off = entry.error is not None and time.time() - entry.attempted_at < _RETRY_AFTER
            force = force and not backing_off and time.time() - entry.attempted_at >= _FORCE_GAP
            if force or (entry.fetched_at is None and not backing_off):
                # Nothing to serve yet (or explicit refresh): fetch inline.
                entry.refreshing = True
                self._refresh(key, entry)
            elif self._is_stale(key, entry) and not entry.refreshing and not backing_off:
                entry.refreshing = True
                threading.Thread(target=self._refresh, args=(key, entry), daemon=True).start()
            return entry.rows

    def keys_for(self, market: str) -> list[str]:
        if market in ("all", "global"):
            return list(self.providers)
        return [k for k, (m, _, _) in self.providers.items() if m == market]

    def rows(self, market: str, force: bool = False, wait: float | None = None) -> list[dict]:
        """All rows for a market. With `wait` (seconds), providers still loading
        after that are left out and keep loading in the background: a first
        "all" search on a new install does not wait minutes for China and Hong Kong."""
        keys = self.keys_for(market)
        if len(keys) == 1 and wait is None:
            return self.get(keys[0], force)
        # Several providers: fetch in parallel so "all" costs the slowest one.
        results: dict[str, list[dict]] = {}
        threads = [
            threading.Thread(target=lambda k=k: results.__setitem__(k, self.get(k, force)), daemon=True)
            for k in keys
        ]
        for t in threads:
            t.start()
        deadline = None if wait is None else time.monotonic() + wait
        for t in threads:
            t.join(None if deadline is None else max(0.0, deadline - time.monotonic()))
        return [r for k in keys for r in results.get(k, [])]

    def lookup(self, keys: Iterable[tuple[str, str, str]]) -> dict[tuple[str, str, str], dict]:
        """(market, type, symbol) -> current listing row, for the keys
        that exist. Only loads the providers those markets need."""
        wanted = set(keys)
        found: dict[tuple[str, str, str], dict] = {}
        for market in {m for m, _, _ in wanted}:
            for row in self.rows(market):
                key = (row["market"], row["type"], row["symbol"])
                if key in wanted:
                    found[key] = row
        return found

    def status(self) -> list[dict]:
        out = []
        for key, (market, _, ttl) in self.providers.items():
            entry = self._entries[key]
            self._load_disk(key, entry)
            out.append(
                {
                    "source": key,
                    "market": market,
                    "count": len(entry.rows),
                    "fetched_at": datetime.fromtimestamp(entry.fetched_at).isoformat() if entry.fetched_at else None,
                    "stale": self._is_stale(key, entry),
                    "error": entry.error,
                }
            )
        return out


# --------------------------------------------------------------- Querying

# Rough USD rates, only used to rank market caps across currencies when
# several markets are listed together (never shown to the user).
_USD_PER = {"USD": 1.0, "INR": 1 / 88.0, "CNY": 1 / 7.1, "HKD": 1 / 7.8}

SORTABLE = {"symbol", "name", "price", "change_percent", "volume", "market_cap", "high_52w", "low_52w", "sector", "category"}

# Market-cap size bands in USD (CNY/HKD caps are converted first).
# Mega (≥ $200B) is checked in USD for every currency, so a ₹ company that
# big counts too. India's other bands follow the usual ₹ crore cut-offs:
# large ≥ 20,000 Cr, mid 5,000–20,000 Cr, small 500–5,000 Cr, micro < 500 Cr.
_MEGA_USD = 200e9
_CAP_BANDS_USD = {
    "mega": (_MEGA_USD, None),
    "large": (10e9, _MEGA_USD),
    "mid": (2e9, 10e9),
    "small": (300e6, 2e9),
    "micro": (None, 300e6),
}
_CAP_BANDS_INR = {
    "large": (2e11, None),
    "mid": (5e10, 2e11),
    "small": (5e9, 5e10),
    "micro": (None, 5e9),
}


def cap_band(row: dict) -> Optional[str]:
    cap = row.get("market_cap")
    if cap is None:
        return None
    currency = row.get("currency") or "USD"
    if cap * _USD_PER.get(currency, 1.0) >= _MEGA_USD:
        return "mega"
    if currency == "INR":
        bands = _CAP_BANDS_INR
    else:
        bands = _CAP_BANDS_USD
        cap = cap * _USD_PER.get(currency, 1.0)
    for name, (lo, hi) in bands.items():
        if (lo is None or cap >= lo) and (hi is None or cap < hi):
            return name
    return None


def _pct_from(value: Optional[float], ref: Optional[float]) -> Optional[float]:
    if value is None or not ref:
        return None
    return abs(value - ref) / ref * 100


def _search_rank(row: dict, q: str) -> Optional[int]:
    """Lower is better; None = no match. Symbol hits beat name hits."""
    sym = row["symbol"].lower()
    name = (row.get("name") or "").lower()
    local = row.get("name_local")
    if local and q in local.lower():
        return 2 if local.lower().startswith(q) else 6
    if sym == q:
        return 0
    if sym.startswith(q):
        return 1
    if name.startswith(q):
        return 2
    if f" {q}" in f" {name}":
        return 3
    if q in sym:
        return 4
    # Multi-word: every token must appear ("hdfc flexi direct").
    tokens = q.split()
    if len(tokens) > 1 and all(t in name or t in sym for t in tokens):
        return 5
    if q in name:
        return 6
    return None


def query(
    rows: Iterable[dict],
    q: str = "",
    type_: str = "all",
    sector: str = "",
    exchange: str = "",
    plan: str = "",
    option: str = "",
    min_cap: Optional[float] = None,
    max_cap: Optional[float] = None,
    categories: Iterable[str] = (),
    cap_sizes: Iterable[str] = (),
    shariah: Iterable[str] = (),
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    change_min: Optional[float] = None,
    change_max: Optional[float] = None,
    near_high: Optional[float] = None,
    near_low: Optional[float] = None,
    min_volume: Optional[float] = None,
    max_volume: Optional[float] = None,
    markets: Iterable[str] = (),
    sort: str = "market_cap",
    order: str = "desc",
    offset: int = 0,
    limit: int = 50,
) -> dict:
    """Filter, facet, sort and page listing rows.

    shariah keeps rows whose Shariah screen status (halal / doubtful /
    haram / unknown, see marketmyna/data/shariah.py) is in the set.
    near_high / near_low keep rows within that many percent of their
    52-week high / low. Price bounds are in each row's own currency.
    """
    q = q.strip().lower()
    wanted_categories = {c for c in categories if c}
    wanted_sizes = {c for c in cap_sizes if c}
    wanted_shariah = {c for c in shariah if c}
    wanted_markets = {m for m in markets if m}
    market_counts: dict[str, int] = {}
    matched: list[tuple[int, dict]] = []
    sectors: dict[str, int] = {}
    types: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    shariah_counts: dict[str, int] = {}
    for row in rows:
        if exchange and row.get("exchange") != exchange:
            continue
        if plan and row.get("plan") != plan:
            continue
        if option and option.lower() not in (row.get("option") or "").lower():
            continue
        cap = row.get("market_cap")
        if min_cap is not None and (cap is None or cap < min_cap):
            continue
        if max_cap is not None and (cap is None or cap > max_cap):
            continue
        if wanted_sizes and cap_band(row) not in wanted_sizes:
            continue
        price = row.get("price")
        if price_min is not None and (price is None or price < price_min):
            continue
        if price_max is not None and (price is None or price > price_max):
            continue
        change = row.get("change_percent")
        if change_min is not None and (change is None or change < change_min):
            continue
        if change_max is not None and (change is None or change > change_max):
            continue
        if min_volume is not None and (row.get("volume") or 0) < min_volume:
            continue
        if max_volume is not None and (row.get("volume") is None or row["volume"] > max_volume):
            continue
        if near_high is not None:
            gap = _pct_from(price, row.get("high_52w"))
            if gap is None or gap > near_high:
                continue
        if near_low is not None:
            gap = _pct_from(price, row.get("low_52w"))
            if gap is None or gap > near_low:
                continue
        rank = 0
        if q:
            r = _search_rank(row, q)
            if r is None:
                continue
            rank = r

        # Each facet ignores its own filter so the type tabs, category
        # chips and industry dropdown keep showing every choice + count.
        type_ok = type_ == "all" or row["type"] == type_
        market_ok = not wanted_markets or row.get("market") in wanted_markets
        category_ok = not wanted_categories or row.get("category") in wanted_categories
        sector_ok = not sector or row.get("sector") == sector
        shariah_ok = not wanted_shariah or row.get("shariah") in wanted_shariah
        if market_ok and category_ok and sector_ok and shariah_ok:
            types[row["type"]] = types.get(row["type"], 0) + 1
        if market_ok and type_ok and sector_ok and shariah_ok and row.get("category"):
            category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1
        if market_ok and type_ok and category_ok and shariah_ok and row.get("sector"):
            sectors[row["sector"]] = sectors.get(row["sector"], 0) + 1
        if market_ok and type_ok and category_ok and sector_ok and row.get("shariah"):
            shariah_counts[row["shariah"]] = shariah_counts.get(row["shariah"], 0) + 1
        if type_ok and category_ok and sector_ok and shariah_ok:
            market_counts[row.get("market") or ""] = market_counts.get(row.get("market") or "", 0) + 1
            if market_ok:
                matched.append((rank, row))

    sort = sort if sort in SORTABLE else "market_cap"
    reverse = order != "asc"
    is_text = sort in ("symbol", "name", "sector", "category")

    mixed = sort == "market_cap" and len({m[1].get("currency") for m in matched}) > 1

    def value(item: tuple[int, dict]):
        v = item[1].get(sort)
        if is_text:
            return (v or "").lower()
        if mixed and v is not None:
            return v * _USD_PER.get(item[1].get("currency") or "USD", 1.0)
        return v

    if q and sort == "market_cap" and order == "desc":
        # Default sort while searching: relevance first, then size.
        ordered = sorted(matched, key=lambda m: (m[0], -(value(m) or 0)))
    else:
        present = [m for m in matched if value(m) not in (None, "")]
        missing = [m for m in matched if value(m) in (None, "")]
        present.sort(key=value, reverse=reverse)
        ordered = present + missing  # blanks always last

    page = [m[1] for m in ordered[offset : offset + limit]]
    return {
        "total": len(ordered),
        "offset": offset,
        "limit": limit,
        "rows": page,
        "facets": {
            "sectors": sorted(({"value": k, "count": v} for k, v in sectors.items()), key=lambda x: -x["count"]),
            "types": types,
            "categories": sorted(
                ({"value": k, "count": v} for k, v in category_counts.items()), key=lambda x: -x["count"]
            ),
            "shariah": shariah_counts,
            "markets": market_counts,
        },
    }


_store: Optional[ListingStore] = None
_store_lock = threading.Lock()


def get_store() -> ListingStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = ListingStore()
        return _store
