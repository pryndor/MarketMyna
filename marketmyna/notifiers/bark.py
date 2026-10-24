"""Bark iOS push sender (https://github.com/Finb/Bark): the device URL
shown in the Bark app, e.g. https://api.day.app/yourkey."""

from __future__ import annotations

from typing import Optional

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, http_ok, truncate

BARK_MAX_LENGTH = 3500


class BarkSender:
    def __init__(self, config):
        self._url = (getattr(config, "bark_url", None) or "").rstrip("/")

    def is_configured(self) -> bool:
        return bool(self._url)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False
        payload = {"title": title or DEFAULT_TITLE, "body": truncate(message, BARK_MAX_LENGTH), "group": "MarketMyna"}
        return http_ok("Bark", "POST", self._url, json=payload, timeout=timeout)
