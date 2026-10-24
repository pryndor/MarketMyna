"""Shared shapes for the social-sentiment sources (src/data/social/*).

Every source turns its own payload into SocialPost rows; the service
(src/services/social_sentiment.py) scores and aggregates them. A source
raises SourceBlocked when the site refuses us (rate limit, bot wall) so
the circuit breaker can back off instead of hammering it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
TIMEOUT = 15


class SourceBlocked(Exception):
    """The site refused the request (429, bot wall, network-security page)."""


class SourceSkipped(Exception):
    """The source does not cover this market/symbol, or is switched off."""


@dataclass
class SocialPost:
    source: str  # "reddit" | "stocktwits" | "valuepickr" | "hackernews"
    id: str
    title: str
    url: str
    created_at: datetime  # UTC, tz-aware
    body: str = ""
    author: str = ""
    community: str = ""  # subreddit, forum category, ...
    score: int = 0  # upvotes / likes / points
    comments: int = 0
    label: Optional[str] = None  # author-tagged "bullish" / "bearish" (StockTwits)

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}".strip()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


@dataclass
class SocialQuery:
    """What to look for: the ticker, the company name, and the market."""

    symbol: str  # app symbol, e.g. AAPL, RELIANCE, BTC-USD
    market: str  # us | india | crypto | ...
    name: str = ""  # cleaned company name, e.g. "Apple", "Reliance Industries"
    aliases: list[str] = field(default_factory=list)

    @property
    def ticker(self) -> str:
        """Bare ticker as people type it ("BTC" for BTC-USD, "RELIANCE")."""
        return self.symbol.split("-")[0].split(".")[0].upper()


def utc(ts) -> datetime:
    """Epoch seconds or ISO string -> tz-aware UTC datetime."""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    value = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# Tickers that are also everyday words/abbreviations: a bare mention is not
# enough, it needs a $cashtag or the company name.
_AMBIGUOUS = {
    "A", "ALL", "AN", "ANY", "ARE", "AT", "BE", "CAN", "CAR", "DD", "EOD", "FOR", "GO", "HAS", "IT", "KEY",
    "LOW", "MAN", "NOW", "ON", "ONE", "OPEN", "OR", "OUT", "PLAY", "REAL", "RUN", "SEE", "SO", "TV", "TWO",
    "UP", "USA", "WELL", "YOU", "F", "T", "U", "V", "X", "C", "AI", "CEO", "IPO", "ATH", "YOLO", "EV", "GDP",
    "CPI", "FED", "SEC", "ETF", "EPS", "PE", "IV", "OTM", "ITM", "LIFE", "NEXT", "BIG", "GOOD", "FUN", "LOVE",
}


def mentions(post: SocialPost, query: SocialQuery) -> bool:
    """True when the post is about the stock. Bare tickers must be upper case
    in the text so "nvda" in a URL slug or "meta" the word don't match."""
    text = post.text
    ticker = query.ticker
    if re.search(rf"\${re.escape(ticker)}\b", text, re.IGNORECASE):
        return True
    if len(ticker) >= 3 and ticker not in _AMBIGUOUS and re.search(rf"\b{re.escape(ticker)}\b", text):
        return True
    for name in [query.name, *query.aliases]:
        name = (name or "").strip()
        if len(name) >= 3 and re.search(
            r"\b" + r"\s+".join(re.escape(w) for w in name.split()) + r"\b", text, re.IGNORECASE
        ):
            return True
    return False
