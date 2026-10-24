"""Feishu/Lark custom bot webhook notification sender."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger, truncate

FEISHU_MAX_LENGTH = 19000


class FeishuSender:
    def __init__(self, config):
        self._webhook_url = getattr(config, "feishu_webhook_url", None)
        self._secret = getattr(config, "feishu_webhook_secret", None)

    def is_configured(self) -> bool:
        return bool(self._webhook_url)

    def _security_fields(self) -> dict:
        if not self._secret:
            return {}
        timestamp = str(int(time.time()))
        string_to_sign = f"{timestamp}\n{self._secret}"
        sign = base64.b64encode(
            hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        return {"timestamp": timestamp, "sign": sign}

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        text = truncate(f"{title or DEFAULT_TITLE}\n\n{message}", FEISHU_MAX_LENGTH)
        payload = {"msg_type": "text", "content": {"text": text}}
        payload.update(self._security_fields())

        try:
            resp = requests.post(self._webhook_url, json=payload, timeout=timeout)
            if resp.status_code != 200:
                logger.error("Feishu send failed: HTTP %s", resp.status_code)
                return False
            result = resp.json()
            code = result.get("code", result.get("StatusCode"))
            if code == 0:
                return True
            logger.error("Feishu send failed: %s", result)
            return False
        except (requests.RequestException, ValueError) as exc:
            logger.error("Feishu send failed: %s", exc)
            return False
