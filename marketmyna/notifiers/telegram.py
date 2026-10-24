"""Telegram Bot API notification sender."""

from __future__ import annotations

import html
import re
from typing import Optional

import requests

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger, split_message  # noqa: F401 (re-exported)

TELEGRAM_MAX_LENGTH = 4096


class TelegramSender:
    def __init__(self, config):
        self._bot_token = getattr(config, "telegram_bot_token", None)
        # One chat ID, or several comma-separated (e.g. you and a group).
        raw = str(getattr(config, "telegram_chat_id", None) or "")
        self._chat_ids = [c.strip() for c in raw.split(",") if c.strip()]
        # Optional: post into one topic of a forum-style group.
        self._thread_id = getattr(config, "telegram_message_thread_id", None)

    def is_configured(self) -> bool:
        return bool(self._bot_token and self._chat_ids)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False

        # HTML mode with everything escaped: the title is bold and the body
        # arrives verbatim (Markdown mode silently ate "_" and "*" in news / AI text).
        text = f"<b>{html.escape(title or DEFAULT_TITLE)}</b>\n\n{html.escape(message, quote=False)}"
        # Long reports go out as several messages instead of being cut off.
        chunks = split_message(text, TELEGRAM_MAX_LENGTH)
        results = [all(self._send_chunk(chat, chunk, timeout) for chunk in chunks) for chat in self._chat_ids]
        return all(results)

    def send_document(self, filename: str, data: bytes, caption: Optional[str] = None, *,
                      timeout: float = 60) -> bool:
        """A file (e.g. the Smart messaging report PDF) to every chat."""
        if not self.is_configured():
            return False
        url = f"https://api.telegram.org/bot{self._bot_token}/sendDocument"
        ok = True
        for chat_id in self._chat_ids:
            payload = {"chat_id": chat_id}
            if caption:
                payload["caption"] = caption[:1024]  # Telegram's caption limit
            if self._thread_id:
                payload["message_thread_id"] = int(self._thread_id)
            try:
                resp = requests.post(url, data=payload, files={"document": (filename, data)}, timeout=timeout)
                if resp.status_code != 200:
                    logger.error("Telegram file to %s failed: HTTP %s %s", chat_id, resp.status_code, resp.text[:200])
                    ok = False
            except requests.RequestException as exc:
                logger.error("Telegram file send failed: %s", exc)
                ok = False
        return ok

    def _send_chunk(self, chat_id: str, text: str, timeout: float) -> bool:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if self._thread_id:
            payload["message_thread_id"] = int(self._thread_id)
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 400 and "parse" in resp.text.lower():
                # A chunk boundary split the bold title tag: resend as plain text.
                payload.pop("parse_mode")
                payload["text"] = html.unescape(re.sub(r"</?b>", "", text))
                resp = requests.post(url, json=payload, timeout=timeout)
            if resp.status_code == 200:
                return True
            logger.error("Telegram send to %s failed: HTTP %s %s", chat_id, resp.status_code, resp.text[:200])
            return False
        except requests.RequestException as exc:
            logger.error("Telegram send failed: %s", exc)
            return False
