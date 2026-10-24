"""WhatsApp via CallMeBot - free for personal use: message +34 644 51 95 23
"I allow callmebot to send me messages" on WhatsApp to get an API key."""

from __future__ import annotations

from typing import Optional

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, http_ok, truncate

# CallMeBot passes the text in the URL; keep it well under URL limits.
CALLMEBOT_MAX_LENGTH = 1500


class WhatsAppSender:
    def __init__(self, config):
        self._phone = getattr(config, "whatsapp_phone", None)
        self._api_key = getattr(config, "whatsapp_callmebot_apikey", None)

    def is_configured(self) -> bool:
        return bool(self._phone and self._api_key)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False
        text = truncate(f"*{title or DEFAULT_TITLE}*\n{message}", CALLMEBOT_MAX_LENGTH)
        params = {"phone": self._phone.replace(" ", ""), "text": text, "apikey": self._api_key}
        return http_ok("WhatsApp", "GET", "https://api.callmebot.com/whatsapp.php", params=params, timeout=timeout)
