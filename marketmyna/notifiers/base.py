"""Shared helpers for notification channel senders.

Each sender follows the same small contract: ``is_configured()`` and
``send(message, title=None, timeout=10.0) -> bool``. A channel that fails
must return False rather than raise, so one broken channel never blocks
the others (see NotificationDispatcher).
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "MarketMyna Alert"
DEFAULT_TIMEOUT = 10.0


TRUNCATION_NOTE = "\n…\n(Shortened to fit this channel. Open MarketMyna for the full report.)"


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def truncate(text: str, max_length: int, measure: Callable[[str], int] = len) -> str:
    """Cap message length for platforms with a hard limit, saying so when it
    cuts (so a reader knows sections are missing). `measure` = utf8_len for
    platforms that count bytes."""
    if measure(text) <= max_length:
        return text
    note = TRUNCATION_NOTE if max_length >= 400 else "…"
    budget = max_length - measure(note)
    cut = text[:budget]
    while cut and measure(cut) > budget:  # multi-byte characters
        cut = cut[: max(1, len(cut) - max(1, (measure(cut) - budget) // 2))]
    cut = cut.rsplit("\n", 1)[0] if "\n" in cut[-200:] and note != "…" else cut  # end on a whole line
    return cut.rstrip() + note


def split_message(text: str, limit: int, measure: Callable[[str], int] = len) -> list[str]:
    """Split on line boundaries into chunks of at most `limit` (chars, or
    bytes with measure=utf8_len); a single over-long line is hard-cut."""
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while measure(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            piece = line[:limit]
            while measure(piece) > limit:
                piece = piece[:-1]
            chunks.append(piece)
            line = line[len(piece):]
        candidate = f"{current}\n{line}" if current else line
        if measure(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [""]


def http_ok(channel: str, method: str, url: str, *, timeout: float = DEFAULT_TIMEOUT, **kwargs) -> bool:
    """One HTTP call for a sender: True on 2xx, False (logged) otherwise."""
    import requests

    try:
        resp = requests.request(method, url, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        logger.error("%s send failed: %s", channel, exc)
        return False
    if 200 <= resp.status_code < 300:
        return True
    logger.error("%s send failed: HTTP %s %s", channel, resp.status_code, resp.text[:200])
    return False
