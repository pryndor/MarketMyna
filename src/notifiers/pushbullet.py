"""Pushbullet sender: push to your phones and browsers."""

from __future__ import annotations

from typing import Optional

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, http_ok


class PushbulletSender:
    def __init__(self, config):
        self._token = getattr(config, "pushbullet_token", None)

    def is_configured(self) -> bool:
        return bool(self._token)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False
        return http_ok(
            "Pushbullet", "POST", "https://api.pushbullet.com/v2/pushes",
            json={"type": "note", "title": title or DEFAULT_TITLE, "body": message},
            headers={"Access-Token": self._token}, timeout=timeout,
        )
