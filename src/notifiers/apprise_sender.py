"""Apprise sender: one field that reaches 100+ services (LINE, Viber,
Mastodon, Zulip, Home Assistant, Rocket.Chat, SMS gateways, ...) through
Apprise URLs - see https://github.com/caronc/apprise/wiki.

Optional dependency: `pip install apprise`. Without it the channel is
reported as not configured (and logged) rather than failing.
"""

from __future__ import annotations

from typing import Optional

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger


class AppriseSender:
    def __init__(self, config):
        self._urls = [u for u in (getattr(config, "apprise_urls", None) or []) if u]

    def is_configured(self) -> bool:
        if not self._urls:
            return False
        try:
            import apprise  # noqa: F401
        except ImportError:
            logger.warning("apprise_urls is set but the apprise package isn't installed (pip install apprise)")
            return False
        return True

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False
        import apprise

        client = apprise.Apprise()
        for url in self._urls:
            if not client.add(url):
                logger.error("Apprise rejected URL (check its format): %s", url.split("://")[0] + "://…")
        try:
            return bool(client.notify(body=message, title=title or DEFAULT_TITLE))
        except Exception as exc:
            logger.error("Apprise send failed: %s", exc)
            return False
