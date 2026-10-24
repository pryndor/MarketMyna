"""Generic JSON webhook notification sender (fallback for any POST-JSON endpoint)."""

from __future__ import annotations

import json
from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger


class WebhookSender:
    def __init__(self, config):
        self._url = getattr(config, "webhook_url", None)
        self._headers_json = getattr(config, "webhook_headers", None)

    def is_configured(self) -> bool:
        return bool(self._url)

    def _headers(self) -> dict:
        if not self._headers_json:
            return {}
        try:
            return json.loads(self._headers_json)
        except ValueError:
            logger.error("Webhook headers config is not valid JSON, ignoring")
            return {}

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        payload = {"title": title or DEFAULT_TITLE, "message": message}

        try:
            resp = requests.post(self._url, json=payload, headers=self._headers(), timeout=timeout)
            if 200 <= resp.status_code < 300:
                return True
            logger.error("Webhook send failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            logger.error("Webhook send failed: %s", exc)
            return False
