"""Stock news search across several providers, for the AI and the report.

Same environment variables as daily_stock_analysis, so one set of
secrets works for both projects:

    TAVILY_API_KEYS    comma-separated, rotated        (tavily.com)
    BRAVE_API_KEYS     comma-separated, rotated        (brave.com/search/api)
    SERPAPI_API_KEYS   comma-separated, rotated        (serpapi.com, Google News)
    BOCHA_API_KEYS     comma-separated, rotated        (bochaai.com, Chinese web)
    SEARXNG_BASE_URLS  your own SearXNG instance(s), no key
    NEWS_MAX_AGE_DAYS  how far back to look (default 3)

With none of those set it still works: Google News RSS (free, no key)
and then Yahoo Finance headlines are always available as fallbacks.
Providers are tried in the order above; the first one that returns
results wins, and a failing key is skipped on the next call.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Callable, Mapping, Optional
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
_TIMEOUT = 15
_CACHE_SECONDS = 30 * 60

# Titles that are quote pages, not news.
_JUNK = re.compile(r"stock price, news, quote|share price today|live share price|stock quote|historical prices", re.I)

# Google News locale per market: (hl, gl, ceid)
_LOCALES = {
    "india": ("en-IN", "IN", "IN:en"),
    "us": ("en-US", "US", "US:en"),
    "hong_kong": ("en-HK", "HK", "HK:en"),
    "china_a": ("en-US", "US", "US:en"),  # English coverage of A-shares is far better via Google News
    "crypto": ("en-US", "US", "US:en"),
}


@dataclass
class NewsItem:
    title: str
    source: str = ""
    url: str = ""
    snippet: str = ""
    published: Optional[str] = None  # ISO 8601
    provider: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _split(raw: Optional[str]) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def _iso(value) -> Optional[str]:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        text = str(value).strip()
        try:
            return parsedate_to_datetime(text).isoformat()
        except (TypeError, ValueError):
            return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _fresh(item: NewsItem, days: int) -> bool:
    if not item.published:
        return True  # unknown age: keep, providers already filter by time
    try:
        published = datetime.fromisoformat(item.published)
    except ValueError:
        return True
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return published >= datetime.now(timezone.utc) - timedelta(days=days + 1)


def _freshness(days: int, day: str, week: str, month: str, year: str) -> str:
    return day if days <= 1 else week if days <= 7 else month if days <= 31 else year


# ------------------------------------------------------------- providers


def _tavily(query: str, key: str, limit: int, days: int, _market: str) -> list[NewsItem]:
    resp = requests.post(
        "https://api.tavily.com/search",
        json={"query": query, "topic": "news", "days": days, "max_results": limit, "api_key": key},
        headers={"Authorization": f"Bearer {key}"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return [
        NewsItem(r.get("title", ""), source=re.sub(r"^www\.", "", (r.get("url") or "").split("/")[2] if r.get("url") else ""),
                 url=r.get("url", ""), snippet=r.get("content", ""), published=_iso(r.get("published_date")))
        for r in resp.json().get("results", [])
    ]


def _brave(query: str, key: str, limit: int, days: int, _market: str) -> list[NewsItem]:
    resp = requests.get(
        "https://api.search.brave.com/res/v1/news/search",
        params={"q": query, "count": limit, "freshness": _freshness(days, "pd", "pw", "pm", "py")},
        headers={"X-Subscription-Token": key, "Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return [
        NewsItem(r.get("title", ""), source=(r.get("meta_url") or {}).get("hostname", ""), url=r.get("url", ""),
                 snippet=r.get("description", ""), published=_iso(r.get("page_age")))
        for r in resp.json().get("results", [])
    ]


def _serpapi(query: str, key: str, limit: int, days: int, market: str) -> list[NewsItem]:
    hl, gl, _ = _LOCALES.get(market, _LOCALES["us"])
    resp = requests.get(
        "https://serpapi.com/search.json",
        params={"engine": "google_news", "q": f"{query} when:{max(1, days)}d", "api_key": key,
                "hl": hl.split("-")[0], "gl": gl.lower()},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    items = []
    for r in resp.json().get("news_results", [])[:limit]:
        source = r.get("source") or {}
        items.append(NewsItem(r.get("title", ""), source=source.get("name", "") if isinstance(source, dict) else str(source),
                              url=r.get("link", ""), snippet=r.get("snippet", ""), published=_iso(r.get("iso_date") or r.get("date"))))
    return items


def _bocha(query: str, key: str, limit: int, days: int, _market: str) -> list[NewsItem]:
    resp = requests.post(
        "https://api.bochaai.com/v1/web-search",
        json={"query": query, "count": limit, "summary": True,
              "freshness": _freshness(days, "oneDay", "oneWeek", "oneMonth", "oneYear")},
        headers={"Authorization": f"Bearer {key}"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    pages = ((resp.json().get("data") or {}).get("webPages") or {}).get("value", [])
    return [
        NewsItem(p.get("name", ""), source=p.get("siteName", ""), url=p.get("url", ""),
                 snippet=p.get("summary") or p.get("snippet", ""), published=_iso(p.get("datePublished")))
        for p in pages
    ]


def _searxng(query: str, base_url: str, limit: int, days: int, _market: str) -> list[NewsItem]:
    resp = requests.get(
        f"{base_url.rstrip('/')}/search",
        params={"q": query, "format": "json", "categories": "news",
                "time_range": _freshness(days, "day", "week", "month", "year")},
        headers=_UA,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return [
        NewsItem(r.get("title", ""), source=r.get("engine", ""), url=r.get("url", ""),
                 snippet=r.get("content", ""), published=_iso(r.get("publishedDate")))
        for r in resp.json().get("results", [])[:limit]
    ]


def _google_news(query: str, _key, limit: int, days: int, market: str) -> list[NewsItem]:
    hl, gl, ceid = _LOCALES.get(market, _LOCALES["us"])
    url = (f"https://news.google.com/rss/search?q={quote_plus(query)}+when:{max(1, days)}d"
           f"&hl={hl}&gl={gl}&ceid={ceid}")
    resp = requests.get(url, headers=_UA, timeout=_TIMEOUT)
    resp.raise_for_status()
    items = []
    for it in ET.fromstring(resp.content).iter("item"):
        title = it.findtext("title") or ""
        source = it.findtext("source") or ""
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        items.append(NewsItem(title, source=source, url=it.findtext("link") or "", published=_iso(it.findtext("pubDate"))))
        if len(items) >= limit * 3:  # headroom for junk filtering
            break
    return items


def _yahoo(symbol_query: str, _key, limit: int, _days: int, _market: str) -> list[NewsItem]:
    from .news import NewsFetcher

    return [
        NewsItem(a.title, source=a.source, url=a.url, snippet=a.summary if a.summary != a.title else "",
                 published=a.published.isoformat() if a.published else None)
        for a in NewsFetcher().get_stock_news(symbol_query, limit=limit)
    ]


@dataclass
class _Provider:
    name: str
    fn: Callable[..., list[NewsItem]]
    credentials: list  # keys or base URLs; [None] for keyless providers
    uses_ticker: bool = False  # Yahoo searches by ticker, the rest by text


class NewsSearchService:
    def __init__(self, environ: Optional[Mapping[str, str]] = None):
        env = os.environ if environ is None else environ
        self.max_age_days = int(env.get("NEWS_MAX_AGE_DAYS") or 3)
        self.providers = [
            p for p in (
                _Provider("tavily", _tavily, _split(env.get("TAVILY_API_KEYS") or env.get("TAVILY_API_KEY"))),
                _Provider("brave", _brave, _split(env.get("BRAVE_API_KEYS") or env.get("BRAVE_API_KEY"))),
                _Provider("serpapi", _serpapi, _split(env.get("SERPAPI_API_KEYS") or env.get("SERPAPI_API_KEY"))),
                _Provider("bocha", _bocha, _split(env.get("BOCHA_API_KEYS") or env.get("BOCHA_API_KEY"))),
                _Provider("searxng", _searxng, _split(env.get("SEARXNG_BASE_URLS"))),
                _Provider("google_news", _google_news, [None]),
                _Provider("yahoo", _yahoo, [None], uses_ticker=True),
            ) if p.credentials
        ]
        self._cache: dict[tuple, tuple[float, list[NewsItem]]] = {}
        self._bad_until: dict[tuple[str, int], float] = {}
        self._rotation: dict[str, int] = {}
        self._lock = threading.Lock()

    def provider_names(self) -> list[str]:
        return [p.name for p in self.providers]

    def search(self, query: str, *, ticker: str = "", market: str = "us", limit: int = 5,
               days: Optional[int] = None) -> list[NewsItem]:
        days = days or self.max_age_days
        cache_key = (query, ticker, market, limit, days)
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
                return hit[1]

        items: list[NewsItem] = []
        for provider in self.providers:
            q = ticker if provider.uses_ticker else query
            if not q:
                continue
            start = self._rotation.get(provider.name, 0)
            self._rotation[provider.name] = start + 1
            creds = list(enumerate(provider.credentials))
            creds = creds[start % len(creds):] + creds[: start % len(creds)]
            for index, cred in creds:
                if self._bad_until.get((provider.name, index), 0) > time.monotonic():
                    continue
                try:
                    found = provider.fn(q, cred, limit, days, market)
                except Exception as exc:
                    logger.warning("News provider %s #%d failed: %s", provider.name, index, str(exc)[:160])
                    self._bad_until[(provider.name, index)] = time.monotonic() + 10 * 60
                    continue
                items = self._clean(found, provider.name, limit, days)
                if items:
                    break
            if items:
                break

        with self._lock:
            self._cache[cache_key] = (time.monotonic(), items)
        return items

    @staticmethod
    def _clean(found: list[NewsItem], provider: str, limit: int, days: int) -> list[NewsItem]:
        seen, out = set(), []
        for item in found:
            title = " ".join((item.title or "").split())
            key = re.sub(r"\W+", "", title.lower())[:80]
            if not title or key in seen or _JUNK.search(title) or not _fresh(item, days):
                continue
            seen.add(key)
            item.title, item.provider = title, provider
            out.append(item)
        out.sort(key=lambda i: i.published or "", reverse=True)
        return out[:limit]


@lru_cache(maxsize=512)
def company_name(symbol: str, market: str) -> str:
    """Best human name for a news query ("Reliance Industries" beats
    "RELIANCE"). One cached Yahoo lookup per symbol."""
    if market != "crypto":
        try:
            import yfinance as yf

            from ..services.analysis_run import yahoo_symbol

            info = yf.Ticker(yahoo_symbol(symbol, market)).info or {}
            name = info.get("shortName") or info.get("longName")
            if name:
                return name
        except Exception:
            pass
    return symbol


_SUFFIXES = re.compile(r"\b(limited|ltd\.?|inc\.?|corp(oration)?\.?|co\.?|plc|holdings?|common stock|class [a-z])\b", re.I)


def news_query(symbol: str, market: str, name: Optional[str] = None) -> str:
    name = _SUFFIXES.sub("", name or company_name(symbol, market))
    name = " ".join(re.sub(r"[.,()&]+", " ", name).split()).title() or symbol
    if market == "crypto":
        return f"{symbol.split('-')[0]} crypto"
    return f"{name} share" if market == "india" else f"{name} stock"


_service: Optional[NewsSearchService] = None
_service_lock = threading.Lock()


def get_news_service() -> NewsSearchService:
    global _service
    with _service_lock:
        if _service is None:
            _service = NewsSearchService()
        return _service


def stock_news(symbol: str, market: str, limit: int = 5, name: Optional[str] = None) -> list[dict]:
    """Recent headlines for one stock, as plain dicts (picklable/JSON-safe)."""
    from ..services.analysis_run import yahoo_symbol

    service = get_news_service()
    items = service.search(news_query(symbol, market, name), ticker=yahoo_symbol(symbol, market),
                           market=market, limit=limit)
    return [i.to_dict() for i in items]
