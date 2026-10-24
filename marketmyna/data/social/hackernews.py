"""Hacker News stories via the free Algolia search API (no key).

Useful mostly for US tech names; story titles only (comments are too
off-topic to score reliably).
"""

from __future__ import annotations

import time

import requests

from .base import TIMEOUT, SocialPost, SocialQuery, SourceBlocked, SourceSkipped, utc

API = "https://hn.algolia.com/api/v1/search_by_date"


def parse_hits(payload: dict) -> list[SocialPost]:
    posts = []
    for h in payload.get("hits") or []:
        if not h.get("objectID") or not h.get("title"):
            continue
        posts.append(
            SocialPost(
                source="hackernews",
                id=f"hackernews:{h['objectID']}",
                title=h["title"],
                body=(h.get("story_text") or "")[:2000],
                url=f"https://news.ycombinator.com/item?id={h['objectID']}",
                created_at=utc(int(h.get("created_at_i") or 0)),
                author=h.get("author") or "",
                community="Hacker News",
                score=int(h.get("points") or 0),
                comments=int(h.get("num_comments") or 0),
            )
        )
    return posts


def fetch(query: SocialQuery, config=None, days: int = 14) -> list[SocialPost]:
    if query.market not in ("us", "crypto"):
        raise SourceSkipped("Hacker News is used for US stocks and crypto")
    params = {
        "query": query.name or query.ticker,
        "tags": "story",
        "numericFilters": f"created_at_i>{int(time.time()) - days * 86400}",
        "hitsPerPage": 50,
    }
    r = requests.get(API, params=params, timeout=TIMEOUT)
    if r.status_code == 429:
        raise SourceBlocked("Hacker News rate limit")
    r.raise_for_status()
    return parse_hits(r.json())
