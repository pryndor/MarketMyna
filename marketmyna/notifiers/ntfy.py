"""ntfy.sh (or self-hosted) topic notification sender."""

from __future__ import annotations

from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger


class NtfySender:
    def __init__(self, config):
        self._url = getattr(config, "ntfy_url", None)
        self._token = getattr(config, "ntfy_token", None)

    def is_configured(self) -> bool:
        return bool(self._url)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        headers = {"X-Title": title or DEFAULT_TITLE}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            resp = requests.post(self._url, data=message.encode("utf-8"), headers=headers, timeout=timeout)
            if 200 <= resp.status_code < 300:
                return True
            logger.error("ntfy send failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            logger.error("ntfy send failed: %s", exc)
            return False
