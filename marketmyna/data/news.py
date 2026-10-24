"""News data fetcher for stocks."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class NewsArticle:
    """Represents a news article."""
    title: str
    summary: str
    source: str
    url: str
    published: datetime
    sentiment: Optional[str] = None  # positive, negative, neutral
    symbols: list[str] = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "summary": self.summary,
            "source": self.source,
            "url": self.url,
            "published": self.published.isoformat() if self.published else None,
            "sentiment": self.sentiment,
            "symbols": self.symbols or [],
        }


class NewsFetcher:
    """Fetches a stock's news from Yahoo Finance."""

    def get_stock_news(self, symbol: str, limit: int = 10) -> list[NewsArticle]:
        """Get news for a specific stock using yfinance."""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            news = ticker.news

            articles = []
            for item in news[:limit]:
                # Handle both old and new yfinance API formats
                content = item.get("content", item)  # New API nests data in 'content'

                # Extract title
                title = content.get("title", item.get("title", ""))

                # Extract summary
                summary = content.get("summary", item.get("summary", title))

                # Extract source/publisher - try multiple locations
                source = "Unknown"
                if "provider" in content and isinstance(content["provider"], dict):
                    source = content["provider"].get("displayName", "Unknown")
                elif "publisher" in item:
                    source = item["publisher"]
                elif "publisher" in content:
                    source = content["publisher"]

                # Extract URL - try multiple locations
                url = ""
                if "canonicalUrl" in content and isinstance(content["canonicalUrl"], dict):
                    url = content["canonicalUrl"].get("url", "")
                elif "clickThroughUrl" in content and isinstance(content["clickThroughUrl"], dict):
                    url = content["clickThroughUrl"].get("url", "")
                elif "link" in item:
                    url = item["link"]

                # Extract published date
                try:
                    if "pubDate" in content:
                        # ISO format: "2026-01-05T12:55:00Z"
                        pub_str = content["pubDate"]
                        published = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    elif "providerPublishTime" in item:
                        published = datetime.fromtimestamp(item["providerPublishTime"])
                    else:
                        published = datetime.now()
                except:
                    published = datetime.now()

                article = NewsArticle(
                    title=title,
                    summary=summary,
                    source=source,
                    url=url,
                    published=published,
                    symbols=[symbol],
                )
                articles.append(article)

            return articles
        except Exception as e:
            print(f"Error fetching news for {symbol}: {e}")
            return []

