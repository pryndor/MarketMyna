"""PushPlus (pushplus.plus) notification sender."""

from __future__ import annotations

from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger


class PushplusSender:
    def __init__(self, config):
        self._token = getattr(config, "pushplus_token", None)
        self._topic = getattr(config, "pushplus_topic", None)

    def is_configured(self) -> bool:
        return bool(self._token)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        payload = {
            "token": self._token,
            "title": title or DEFAULT_TITLE,
            "content": message,
            "template": "markdown",
        }
        if self._topic:
            payload["topic"] = self._topic

        try:
            resp = requests.post("http://www.pushplus.plus/send", json=payload, timeout=timeout)
            if resp.status_code == 200 and resp.json().get("code") == 200:
                return True
            logger.error("PushPlus send failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        except (requests.RequestException, ValueError) as exc:
            logger.error("PushPlus send failed: %s", exc)
            return False
