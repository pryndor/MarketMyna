"""Twilio sender: SMS, or WhatsApp when the numbers are "whatsapp:+..."."""

from __future__ import annotations

from typing import Optional

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, http_ok, truncate

# One SMS/WhatsApp message body on Twilio is capped at 1600 characters.
TWILIO_MAX_LENGTH = 1600


class TwilioSender:
    def __init__(self, config):
        self._sid = getattr(config, "twilio_account_sid", None)
        self._token = getattr(config, "twilio_auth_token", None)
        self._from = getattr(config, "twilio_from", None)
        self._to = getattr(config, "twilio_to", None) or []

    def is_configured(self) -> bool:
        return bool(self._sid and self._token and self._from and self._to)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False
        body = truncate(f"{title or DEFAULT_TITLE}\n{message}", TWILIO_MAX_LENGTH)
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Messages.json"
        results = [
            http_ok("Twilio", "POST", url, data={"From": self._from, "To": to, "Body": body},
                    auth=(self._sid, self._token), timeout=timeout)
            for to in self._to
        ]
        return all(results)
