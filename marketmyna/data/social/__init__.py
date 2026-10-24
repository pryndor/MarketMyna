"""Social-media / forum posts about a stock, for the sentiment section.

Sources: reddit (API or Playwright), stocktwits (Playwright), valuepickr
(Discourse JSON), hackernews (Algolia). See each module's docstring.
"""

from .base import SocialPost, SocialQuery, SourceBlocked, SourceSkipped, mentions

__all__ = ["SocialPost", "SocialQuery", "SourceBlocked", "SourceSkipped", "mentions"]
