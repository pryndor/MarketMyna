"""Slack Incoming Webhook notification sender."""

from __future__ import annotations

from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger, truncate

SLACK_MAX_LENGTH = 39000


class SlackSender:
    def __init__(self, config):
        self._webhook_url = getattr(config, "slack_webhook_url", None)

    def is_configured(self) -> bool:
        return bool(self._webhook_url)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        text = f"*{title or DEFAULT_TITLE}*\n{message}"
        text = truncate(text, SLACK_MAX_LENGTH)

        try:
            resp = requests.post(self._webhook_url, json={"text": text}, timeout=timeout)
            if resp.status_code == 200 and resp.text == "ok":
                return True
            logger.error("Slack send failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            logger.error("Slack send failed: %s", exc)
            return False
