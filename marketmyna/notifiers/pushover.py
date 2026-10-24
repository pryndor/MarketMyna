"""Pushover notification sender."""

from __future__ import annotations

from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger, truncate

PUSHOVER_MAX_LENGTH = 1024


class PushoverSender:
    def __init__(self, config):
        self._user_key = getattr(config, "pushover_user_key", None)
        self._api_token = getattr(config, "pushover_api_token", None)

    def is_configured(self) -> bool:
        return bool(self._user_key and self._api_token)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        payload = {
            "token": self._api_token,
            "user": self._user_key,
            "message": truncate(message, PUSHOVER_MAX_LENGTH),
            "title": title or DEFAULT_TITLE,
        }

        try:
            resp = requests.post("https://api.pushover.net/1/messages.json", data=payload, timeout=timeout)
            if resp.status_code == 200 and resp.json().get("status") == 1:
                return True
            logger.error("Pushover send failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        except (requests.RequestException, ValueError) as exc:
            logger.error("Pushover send failed: %s", exc)
            return False
