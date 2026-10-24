"""Server酱³ (ServerChan3, sctapi.ftqq.com) notification sender."""

from __future__ import annotations

import re
from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger


class Serverchan3Sender:
    def __init__(self, config):
        self._sendkey = getattr(config, "serverchan3_sendkey", None)

    def is_configured(self) -> bool:
        return bool(self._sendkey)

    def _endpoint(self) -> str:
        match = re.match(r"sctp(\d+)t", self._sendkey)
        if match:
            return f"https://{match.group(1)}.push.ft07.com/send/{self._sendkey}.send"
        return f"https://sctapi.ftqq.com/{self._sendkey}.send"

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        payload = {"title": title or DEFAULT_TITLE, "desp": message}

        try:
            resp = requests.post(self._endpoint(), json=payload, timeout=timeout)
            if resp.status_code == 200:
                return True
            logger.error("ServerChan3 send failed: HTTP %s %s", resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            logger.error("ServerChan3 send failed: %s", exc)
            return False
