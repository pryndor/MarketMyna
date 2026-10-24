"""WeChat Work (WeCom) group robot webhook notification sender."""

from __future__ import annotations

from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger, split_message, utf8_len

WECHAT_MAX_LENGTH = 4000  # WeCom counts UTF-8 bytes (limit 4096)


class WechatSender:
    def __init__(self, config):
        self._webhook_url = getattr(config, "wechat_webhook_url", None)

    def is_configured(self) -> bool:
        return bool(self._webhook_url)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        # The limit is in bytes; emoji and Chinese take 3-4 each, so split by bytes.
        chunks = split_message(f"**{title or DEFAULT_TITLE}**\n{message}", WECHAT_MAX_LENGTH, measure=utf8_len)
        return all(self._post(chunk, timeout) for chunk in chunks)

    def _post(self, text: str, timeout: float) -> bool:
        payload = {"msgtype": "markdown", "markdown": {"content": text}}
        try:
            resp = requests.post(self._webhook_url, json=payload, timeout=timeout)
            result = resp.json()
            if result.get("errcode") == 0:
                return True
            logger.error("WeChat Work send failed: %s", result)
            return False
        except (requests.RequestException, ValueError) as exc:
            logger.error("WeChat Work send failed: %s", exc)
            return False
