"""Mask secrets in every log line, tracebacks included.

A failed Telegram call raises an error whose text carries the request URL,
and that URL holds the bot token (api.telegram.org/bot<token>/...); a plain
`logger.exception` then wrote the token to the server logs. The same goes for
AI keys echoed back by a provider. `install()` wraps the log record factory,
so every record from every logger is cleaned before any handler sees it.
"""

from __future__ import annotations

import logging
import re
import traceback

SECRETS = re.compile(
    r"(?<=/bot)\d{5,}:[\w-]{20,}"  # Telegram bot token in an API URL
    r"|\b\d{8,12}:AA[\w-]{30,}"  # Telegram bot token on its own
    r"|AIza[\w-]{10,}|gsk_\w{10,}|sk-[\w-]{10,}"  # AI provider keys
    r"|(?<=key=)[^&\s\"']+|(?<=Bearer )[\w.-]+"
)

_installed = False


def redact(text: str) -> str:
    return SECRETS.sub("***", text)


def install() -> None:
    """Idempotent; safe to call from every entry point."""
    global _installed
    if _installed:
        return
    make = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = make(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string is the handler's problem, not ours
            return record
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        if record.exc_info and record.exc_info[0] is not None:
            # Formatters reuse exc_text when it is set, so the raw traceback is never printed.
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip("\n"))
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
