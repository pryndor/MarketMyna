"""Google Chat space incoming-webhook sender."""

from __future__ import annotations

from typing import Optional

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, http_ok, split_message

GOOGLE_CHAT_MAX_LENGTH = 4000


class GoogleChatSender:
    def __init__(self, config):
        self._url = getattr(config, "google_chat_webhook_url", None)

    def is_configured(self) -> bool:
        return bool(self._url)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False
        # Long reports go out as several messages instead of being cut off.
        chunks = split_message(f"*{title or DEFAULT_TITLE}*\n{message}", GOOGLE_CHAT_MAX_LENGTH)
        return all(http_ok("Google Chat", "POST", self._url, json={"text": c}, timeout=timeout) for c in chunks)
