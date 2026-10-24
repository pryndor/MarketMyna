"""Signal sender through a signal-cli REST API instance
(https://github.com/bbernhard/signal-cli-rest-api) linked to your number."""

from __future__ import annotations

from typing import Optional

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, http_ok


class SignalSender:
    def __init__(self, config):
        self._url = (getattr(config, "signal_api_url", None) or "").rstrip("/")
        self._number = getattr(config, "signal_number", None)
        self._recipients = getattr(config, "signal_recipients", None) or []

    def is_configured(self) -> bool:
        return bool(self._url and self._number and self._recipients)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False
        body = {"message": f"{title or DEFAULT_TITLE}\n\n{message}", "number": self._number,
                "recipients": list(self._recipients)}
        return http_ok("Signal", "POST", f"{self._url}/v2/send", json=body, timeout=timeout)
