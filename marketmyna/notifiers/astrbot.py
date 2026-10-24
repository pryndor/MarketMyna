"""Self-hosted AstrBot webhook notification sender."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, logger


class AstrbotSender:
    def __init__(self, config):
        self._url = getattr(config, "astrbot_url", None)
        self._token = getattr(config, "astrbot_token", None)

    def is_configured(self) -> bool:
        return bool(self._url)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        payload = {"content": f"{title}\n\n{message}" if title else message}
        headers = {"Content-Type": "application/json"}

        if self._token:
            timestamp = str(int(time.time()))
            payload_json = json.dumps(payload, sort_keys=True)
            sign_data = f"{timestamp}.{payload_json}".encode("utf-8")
            signature = hmac.new(self._token.encode("utf-8"), sign_data, hashlib.sha256).hexdigest()
            headers["X-Signature"] = signature
            headers["X-Timestamp"] = timestamp

        try:
            resp = requests.post(self._url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                return True
            logger.error("AstrBot send failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            logger.error("AstrBot send failed: %s", exc)
            return False
