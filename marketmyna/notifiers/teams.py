"""Microsoft Teams sender (Workflows / Power Automate "post to a channel
when a webhook request is received" URL, which takes an Adaptive Card)."""

from __future__ import annotations

from typing import Optional

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, http_ok, truncate

TEAMS_MAX_LENGTH = 20000


class TeamsSender:
    def __init__(self, config):
        self._url = getattr(config, "teams_webhook_url", None)

    def is_configured(self) -> bool:
        return bool(self._url)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False
        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard",
            "version": "1.4",
            "body": [
                {"type": "TextBlock", "text": title or DEFAULT_TITLE, "weight": "Bolder", "size": "Medium", "wrap": True},
                # Adaptive Cards treat single newlines as spaces; double them.
                {"type": "TextBlock", "text": truncate(message, TEAMS_MAX_LENGTH).replace("\n", "\n\n"), "wrap": True},
            ],
        }
        payload = {
            "type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}],
        }
        return http_ok("Teams", "POST", self._url, json=payload, timeout=timeout)
