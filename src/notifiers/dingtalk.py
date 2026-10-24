"""DingTalk custom robot webhook notification sender."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger, truncate, utf8_len

DINGTALK_MAX_LENGTH = 19000


class DingtalkSender:
    def __init__(self, config):
        self._webhook_url = getattr(config, "dingtalk_webhook_url", None)
        self._secret = getattr(config, "dingtalk_secret", None)

    def is_configured(self) -> bool:
        return bool(self._webhook_url)

    def _signed_url(self) -> str:
        if not self._secret:
            return self._webhook_url

        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self._secret}".encode("utf-8")
        hmac_code = hmac.new(self._secret.encode("utf-8"), string_to_sign, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        joiner = "&" if "?" in self._webhook_url else "?"
        return f"{self._webhook_url}{joiner}timestamp={timestamp}&sign={sign}"

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        text = truncate(f"### {title or DEFAULT_TITLE}\n\n{message}", DINGTALK_MAX_LENGTH, measure=utf8_len)  # 20000-byte cap
        payload = {"msgtype": "markdown", "markdown": {"title": title or DEFAULT_TITLE, "text": text}}

        try:
            resp = requests.post(self._signed_url(), json=payload, timeout=timeout)
            result = resp.json()
            if result.get("errcode") == 0:
                return True
            logger.error("DingTalk send failed: %s", result)
            return False
        except (requests.RequestException, ValueError) as exc:
            logger.error("DingTalk send failed: %s", exc)
            return False
