"""StockTwits stream for a symbol (US stocks and crypto).

The public JSON stream sits behind Cloudflare, which turns away plain HTTP
clients, so it is read through the headless browser. Many messages carry
an author-set Bullish/Bearish tag - the most direct sentiment signal of
any source, used as-is by the scorer.
"""

from __future__ import annotations

import json

from . import browser
from .base import SocialPost, SocialQuery, SourceBlocked, SourceSkipped, utc

STREAM = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"


def stocktwits_symbol(query: SocialQuery) -> str:
    if query.market == "crypto":
        return f"{query.ticker}.X"  # BTC-USD -> BTC.X
    if query.market == "us":
        return query.symbol.upper().replace("-", ".")  # BRK-B -> BRK.B
    raise SourceSkipped("StockTwits covers US stocks and crypto")


def parse_stream(payload: dict) -> list[SocialPost]:
    posts = []
    for m in payload.get("messages") or []:
        if not m.get("id") or not m.get("body"):
            continue
        user = (m.get("user") or {}).get("username") or ""
        basic = ((m.get("entities") or {}).get("sentiment") or {}).get("basic")
        posts.append(
            SocialPost(
                source="stocktwits",
                id=f"stocktwits:{m['id']}",
                title=m["body"][:280],
                body=m["body"][280:2000],
                url=f"https://stocktwits.com/{user}/message/{m['id']}",
                created_at=utc(m["created_at"]),
                author=user,
                community="StockTwits",
                score=int((m.get("likes") or {}).get("total") or 0),
                comments=int((m.get("conversation") or {}).get("replies") or 0),
                label=basic.lower() if basic in ("Bullish", "Bearish") else None,
            )
        )
    return posts


def fetch(query: SocialQuery, config=None) -> list[SocialPost]:
    if not getattr(config, "social_playwright", True):
        raise SourceSkipped("Headless-browser scraping is switched off")
    text = browser.get_text(STREAM.format(symbol=stocktwits_symbol(query)))
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SourceBlocked("StockTwits did not return JSON") from exc
    status = (payload.get("response") or {}).get("status")
    if status == 404:
        raise SourceSkipped("Symbol not on StockTwits")
    return parse_stream(payload)
