"""Gotify self-hosted push notification sender."""

from __future__ import annotations

from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger


class GotifySender:
    def __init__(self, config):
        self._url = getattr(config, "gotify_url", None)
        self._token = getattr(config, "gotify_token", None)

    def is_configured(self) -> bool:
        return bool(self._url and self._token)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        endpoint = f"{self._url.rstrip('/')}/message"
        headers = {"X-Gotify-Key": self._token}
        payload = {"title": title or DEFAULT_TITLE, "message": message}

        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout)
            if 200 <= resp.status_code < 300:
                return True
            logger.error("Gotify send failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            logger.error("Gotify send failed: %s", exc)
            return False
