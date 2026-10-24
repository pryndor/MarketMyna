"""Discord Incoming Webhook notification sender."""

from __future__ import annotations

from typing import Optional

import requests

import time

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger, split_message

DISCORD_MAX_LENGTH = 2000


class DiscordSender:
    def __init__(self, config):
        self._webhook_url = getattr(config, "discord_webhook_url", None)

    def is_configured(self) -> bool:
        return bool(self._webhook_url)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        text = f"**{title or DEFAULT_TITLE}**\n{message}"
        # Long reports go out as several messages instead of being cut off.
        for i, chunk in enumerate(split_message(text, DISCORD_MAX_LENGTH)):
            if i:
                time.sleep(0.5)  # webhook rate limit: 5 requests / 2 s
            try:
                resp = requests.post(self._webhook_url, json={"content": chunk}, timeout=timeout)
            except requests.RequestException as exc:
                logger.error("Discord send failed: %s", exc)
                return False
            if not 200 <= resp.status_code < 300:
                logger.error("Discord send failed: HTTP %s %s", resp.status_code, resp.text[:200])
                return False
        return True
