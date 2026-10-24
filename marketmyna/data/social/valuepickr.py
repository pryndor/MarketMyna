"""ValuePickr (forum.valuepickr.com) - India's main stock-discussion forum.

Runs on Discourse, whose search answers plain JSON, so no browser needed.
Posts are slower and longer than Reddit's, so the window is wider.
"""

from __future__ import annotations

import html
import re

import requests

from .base import TIMEOUT, UA, SocialPost, SocialQuery, SourceBlocked, SourceSkipped, utc

BASE = "https://forum.valuepickr.com"


def parse_search(payload: dict) -> list[SocialPost]:
    topics = {t["id"]: t for t in payload.get("topics") or [] if t.get("id")}
    posts = []
    for p in payload.get("posts") or []:
        topic = topics.get(p.get("topic_id")) or {}
        if not p.get("id") or not topic.get("title"):
            continue
        posts.append(
            SocialPost(
                source="valuepickr",
                id=f"valuepickr:{p['id']}",
                title=html.unescape(topic["title"]),
                body=html.unescape(re.sub(r"\s+", " ", p.get("blurb") or "")).strip("."),
                url=f"{BASE}/t/{topic.get('slug', 'topic')}/{p['topic_id']}/{p.get('post_number', 1)}",
                created_at=utc(p["created_at"]),
                author=p.get("username") or "",
                community="ValuePickr",
                score=int(p.get("like_count") or 0),
                comments=int(topic.get("reply_count") or 0) if p.get("post_number") == 1 else 0,
            )
        )
    return posts


def fetch(query: SocialQuery, config=None) -> list[SocialPost]:
    if query.market != "india":
        raise SourceSkipped("ValuePickr covers Indian stocks")
    term = query.name or query.ticker
    r = requests.get(
        f"{BASE}/search.json", params={"q": f"{term} order:latest"}, headers={"User-Agent": UA}, timeout=TIMEOUT
    )
    if r.status_code in (403, 429):
        raise SourceBlocked(f"ValuePickr HTTP {r.status_code}")
    r.raise_for_status()
    return parse_search(r.json())
