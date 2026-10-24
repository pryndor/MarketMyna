"""Reddit posts about a stock.

Four ways in, tried in order until one returns posts:

1. Official API (OAuth app-only) - only when REDDIT_CLIENT_ID/SECRET are set.
2. Playwright on reddit.com's global search, one page load per stock.
3. Playwright on the finance subreddits' /new feeds - fetched once and
   shared by every stock for FEED_TTL seconds, then filtered by mention.
4. The same feeds' public RSS (no scores/comment counts).

SOCIAL_REDDIT_MODE picks the order: "auto" (API first when keys exist,
else scraping), "api" (API only), "playwright" (scraping only).

Reddit rate-limits scrapers hard (a few page loads, then "blocked by network
security" for a while, sooner from cloud IPs). Each method sits behind its
own circuit breaker, so once blocked it is skipped for COOLDOWN seconds
rather than retried on every page view.
"""

from __future__ import annotations

import html
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Callable
from urllib.parse import urlencode

import requests

from ..resilience import CircuitBreaker
from . import browser
from .base import TIMEOUT, UA, SocialPost, SocialQuery, SourceBlocked, SourceSkipped, mentions, utc

logger = logging.getLogger(__name__)

BASE = "https://www.reddit.com"
COOLDOWN = 15 * 60
FEED_TTL = 10 * 60

SUBREDDITS = {
    "us": ["wallstreetbets", "stocks", "investing", "StockMarket", "options", "ValueInvesting"],
    "india": ["IndianStreetBets", "IndiaInvestments", "IndianStockMarket", "DalalStreetTalks"],
    "crypto": ["CryptoCurrency", "CryptoMarkets", "Bitcoin", "ethtrader"],
}
SUBREDDITS["hong_kong"] = SUBREDDITS["china_a"] = ["stocks", "investing", "StockMarket", "ChinaStocks"]

# Global search returns every corner of Reddit; keep subreddits that are
# plausibly about markets.
_FINANCE_SUB = re.compile(r"stock|invest|trad|bets|market|financ|crypto|option|dividend|bogle|bull|bear|money|econom", re.I)

_breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=COOLDOWN)


def subreddits(market: str) -> list[str]:
    return SUBREDDITS.get(market, SUBREDDITS["us"])


def _relevant_sub(community: str, market: str) -> bool:
    name = community.removeprefix("r/")
    return name.lower() in {s.lower() for s in subreddits(market)} or bool(_FINANCE_SUB.search(name))


def search_terms(query: SocialQuery) -> str:
    terms = [query.ticker]
    if query.name and query.name.upper() != query.ticker:
        terms.append(f'"{query.name}"')
    return " OR ".join(terms)


def _count(text: str) -> int:
    """'1.2k' -> 1200, '35' -> 35."""
    text = (text or "").strip().lower().replace(",", "")
    match = re.match(r"([\d.]+)\s*([km]?)", text)
    if not match:
        return 0
    value = float(match.group(1))
    return int(value * {"k": 1_000, "m": 1_000_000}.get(match.group(2), 1))


# ---------------------------------------------------------------- 1. API

_token: dict = {"value": None, "expires": 0.0}
_token_lock = threading.Lock()


def _api_token(client_id: str, client_secret: str, user_agent: str) -> str:
    with _token_lock:
        if _token["value"] and _token["expires"] > time.time() + 60:
            return _token["value"]
        r = requests.post(
            f"{BASE}/api/v1/access_token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": user_agent},
            timeout=TIMEOUT,
        )
        if r.status_code in (401, 403):
            raise SourceSkipped("Reddit rejected the API keys")
        r.raise_for_status()
        data = r.json()
        _token.update(value=data["access_token"], expires=time.time() + float(data.get("expires_in", 3600)))
        return _token["value"]


def parse_listing(payload: dict) -> list[SocialPost]:
    """Reddit JSON listing (API or .json) -> posts."""
    posts = []
    for child in (payload.get("data") or {}).get("children") or []:
        d = child.get("data") or {}
        if not d.get("id") or not d.get("title"):
            continue
        posts.append(
            SocialPost(
                source="reddit",
                id=f"reddit:{d['id']}",
                title=html.unescape(d["title"]),
                body=html.unescape(d.get("selftext") or "")[:2000],
                url=BASE + d.get("permalink", ""),
                created_at=utc(float(d.get("created_utc") or 0)),
                author=d.get("author") or "",
                community=f"r/{d.get('subreddit', '')}",
                score=int(d.get("score") or 0),
                comments=int(d.get("num_comments") or 0),
            )
        )
    return posts


def fetch_api(query: SocialQuery, client_id: str, client_secret: str, user_agent: str = "") -> list[SocialPost]:
    user_agent = user_agent or "MarketMyna/1.0 (social sentiment)"
    token = _api_token(client_id, client_secret, user_agent)
    subs = "+".join(subreddits(query.market))
    params = {"q": search_terms(query), "restrict_sr": 1, "sort": "new", "t": "week", "limit": 100}
    r = requests.get(
        f"https://oauth.reddit.com/r/{subs}/search",
        params=params,
        headers={"Authorization": f"bearer {token}", "User-Agent": user_agent},
        timeout=TIMEOUT,
    )
    if r.status_code == 429:
        raise SourceBlocked("Reddit API rate limit")
    r.raise_for_status()
    return parse_listing(r.json())


# ------------------------------------------------------ 2. browser search

_SEARCH_JS = r"""
() => [...document.querySelectorAll('[data-testid="search-post-unit"]')].map(u => {
  const a = u.querySelector('a[data-testid="post-title"]');
  const sub = [...u.querySelectorAll('a[href^="/r/"]')].find(x => !x.dataset.testid);
  const t = u.querySelector('faceplate-timeago');
  return {title: a && (a.getAttribute('aria-label') || a.innerText), href: a && a.getAttribute('href'),
          sub: sub ? sub.innerText.trim() : '', ts: t ? t.getAttribute('ts') : null, text: u.innerText};
})
"""


def parse_search_units(rows: list[dict]) -> list[SocialPost]:
    posts = []
    for row in rows:
        href, title = row.get("href") or "", (row.get("title") or "").strip()
        match = re.search(r"/comments/([a-z0-9]+)/", href)
        if not match or not title or not row.get("ts"):
            continue
        text = row.get("text") or ""
        votes = re.search(r"([\d.,]+[kKmM]?)\s+votes?", text)
        comments = re.search(r"([\d.,]+[kKmM]?)\s+comments?", text)
        community = (row.get("sub") or "").strip()
        if not community:
            sub = re.match(r"/r/([^/]+)/", href)
            community = f"r/{sub.group(1)}" if sub else ""
        posts.append(
            SocialPost(
                source="reddit",
                id=f"reddit:{match.group(1)}",
                title=title,
                url=BASE + href,
                created_at=utc(row["ts"]),
                community=community,
                score=_count(votes.group(1)) if votes else 0,
                comments=_count(comments.group(1)) if comments else 0,
            )
        )
    return posts


def fetch_browser_search(query: SocialQuery) -> list[SocialPost]:
    url = f"{BASE}/search/?" + urlencode({"q": search_terms(query), "type": "posts", "sort": "new", "t": "week"})
    with browser.page() as pg:
        response = pg.goto(url, wait_until="domcontentloaded")
        browser.check_blocked(pg, response.status if response else None)
        try:
            pg.wait_for_selector('[data-testid="search-post-unit"]', timeout=6000)
        except Exception:
            browser.check_blocked(pg)
            return []  # genuinely no results
        pg.mouse.wheel(0, 6000)
        pg.wait_for_timeout(1200)
        rows = pg.evaluate(_SEARCH_JS)
    return [p for p in parse_search_units(rows) if _relevant_sub(p.community, query.market)]


# ------------------------------------------------- 3/4. shared feed pool

_FEED_JS = r"""
() => [...document.querySelectorAll('shreddit-post')].map(p => {
  const body = p.querySelector('[slot="text-body"]');
  return {id: p.getAttribute('id'), title: p.getAttribute('post-title'), permalink: p.getAttribute('permalink'),
          score: p.getAttribute('score'), comments: p.getAttribute('comment-count'),
          ts: p.getAttribute('created-timestamp'), author: p.getAttribute('author'),
          sub: p.getAttribute('subreddit-prefixed-name'), body: body ? body.innerText : ''};
})
"""


def parse_feed_posts(rows: list[dict]) -> list[SocialPost]:
    posts = []
    for row in rows:
        if not row.get("id") or not row.get("title") or not row.get("ts"):
            continue
        posts.append(
            SocialPost(
                source="reddit",
                id=f"reddit:{row['id'].removeprefix('t3_')}",
                title=row["title"],
                body=(row.get("body") or "")[:2000],
                url=BASE + (row.get("permalink") or ""),
                created_at=utc(row["ts"]),
                author=row.get("author") or "",
                community=row.get("sub") or "",
                score=_count(row.get("score") or "0"),
                comments=_count(row.get("comments") or "0"),
            )
        )
    return posts


_ATOM = {"a": "http://www.w3.org/2005/Atom"}


def parse_rss(xml_text: str, subreddit: str) -> list[SocialPost]:
    posts = []
    root = ET.fromstring(xml_text)
    for entry in root.findall("a:entry", _ATOM):
        title = entry.findtext("a:title", default="", namespaces=_ATOM)
        link = entry.find("a:link", _ATOM)
        url = link.get("href") if link is not None else ""
        match = re.search(r"/comments/([a-z0-9]+)/", url or "")
        stamp = entry.findtext("a:published", namespaces=_ATOM) or entry.findtext("a:updated", namespaces=_ATOM)
        if not match or not title or not stamp:
            continue
        content = entry.findtext("a:content", default="", namespaces=_ATOM)
        body = html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(content)))
        body = re.sub(r"submitted by\s+/u/\S+.*$", "", " ".join(body.split())).strip()
        posts.append(
            SocialPost(
                source="reddit",
                id=f"reddit:{match.group(1)}",
                title=html.unescape(title),
                body=body[:2000],
                url=url,
                created_at=utc(stamp),
                author=(entry.findtext("a:author/a:name", default="", namespaces=_ATOM) or "").removeprefix("/u/"),
                community=f"r/{subreddit}",
            )
        )
    return posts


class _FeedPool:
    """Recent posts of the market's subreddits, shared across stocks."""

    def __init__(self):
        self._data: dict[str, tuple[float, list[SocialPost]]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, loader: Callable[[], list[SocialPost]]) -> list[SocialPost]:
        with self._lock:
            hit = self._data.get(key)
            if hit and time.time() - hit[0] < FEED_TTL:
                return hit[1]
            posts = loader()
            self._data[key] = (time.time(), posts)
            return posts


_pool = _FeedPool()


def _load_feeds_browser(market: str) -> list[SocialPost]:
    posts: list[SocialPost] = []
    with browser.page() as pg:
        for sub in subreddits(market):
            response = pg.goto(f"{BASE}/r/{sub}/new/", wait_until="domcontentloaded")
            browser.check_blocked(pg, response.status if response else None)
            pg.mouse.wheel(0, 8000)
            pg.wait_for_timeout(1000)
            posts.extend(parse_feed_posts(pg.evaluate(_FEED_JS)))
            pg.wait_for_timeout(800)  # pace: one subreddit at a time
    return posts


def _load_feeds_rss(market: str) -> list[SocialPost]:
    posts: list[SocialPost] = []
    for sub in subreddits(market):
        r = requests.get(f"{BASE}/r/{sub}/new/.rss", params={"limit": 100}, headers={"User-Agent": UA}, timeout=TIMEOUT)
        if r.status_code in (403, 429):
            if posts:
                break  # keep what we have
            raise SourceBlocked(f"Reddit RSS HTTP {r.status_code}")
        r.raise_for_status()
        posts.extend(parse_rss(r.text, sub))
        time.sleep(0.5)
    return posts


def fetch_browser_feeds(query: SocialQuery) -> list[SocialPost]:
    posts = _pool.get(f"browser:{query.market}", lambda: _load_feeds_browser(query.market))
    return [p for p in posts if mentions(p, query)]


def fetch_rss_feeds(query: SocialQuery) -> list[SocialPost]:
    posts = _pool.get(f"rss:{query.market}", lambda: _load_feeds_rss(query.market))
    return [p for p in posts if mentions(p, query)]


# ------------------------------------------------------------- dispatcher


def methods(config) -> list[tuple[str, Callable[[SocialQuery], list[SocialPost]]]]:
    """(name, fetcher) in the order SOCIAL_REDDIT_MODE asks for."""
    mode = (getattr(config, "social_reddit_mode", None) or "auto").lower()
    client_id = getattr(config, "reddit_client_id", None)
    secret = getattr(config, "reddit_client_secret", None)
    api: list = []
    if client_id and secret:
        ua = getattr(config, "reddit_user_agent", None) or ""
        api = [("api", lambda q: fetch_api(q, client_id, secret, ua))]
    scrape = [("search", fetch_browser_search), ("feeds", fetch_browser_feeds), ("rss", fetch_rss_feeds)]
    if not getattr(config, "social_playwright", True):
        scrape = [("rss", fetch_rss_feeds)]  # headless browser switched off
    if mode == "api":
        return api
    if mode == "playwright":
        return scrape
    return api + scrape


def fetch(query: SocialQuery, config=None) -> tuple[list[SocialPost], str]:
    """Posts plus a note on how they were fetched ("search", "feeds", ...).

    Raises SourceBlocked/SourceSkipped when no method produced anything."""
    chain = methods(config)
    if not chain:
        raise SourceSkipped("Reddit API mode is selected but no API keys are set")
    errors: list[str] = []
    answered = None  # first method that worked but found nothing
    for name, fetcher in chain:
        key = f"reddit:{name}"
        if not _breaker.is_available(key):
            errors.append(f"{name}: backing off after a block")
            continue
        try:
            posts = [p for p in fetcher(query) if mentions(p, query)]
        except SourceSkipped as exc:
            errors.append(f"{name}: {exc}")
            continue
        except SourceBlocked as exc:
            _breaker.record_failure(key, str(exc))
            errors.append(f"{name}: blocked ({exc})")
            logger.info("Reddit %s blocked: %s", name, exc)
            continue
        except Exception as exc:  # network, layout change, ...
            _breaker.record_failure(key, str(exc))
            errors.append(f"{name}: {exc}")
            logger.warning("Reddit %s failed: %s", name, exc)
            continue
        _breaker.record_success(key)
        if posts:
            return posts, name
        answered = answered or name
    if answered:
        return [], answered
    raise SourceBlocked("; ".join(errors))



def reset() -> None:
    """Tests: forget caches, tokens and breaker state."""
    global _breaker, _pool
    _breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=COOLDOWN)
    _pool = _FeedPool()
    _token.update(value=None, expires=0.0)
