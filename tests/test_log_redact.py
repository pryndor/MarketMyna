"""Secrets never reach the logs: Telegram bot tokens in URLs and AI keys, tracebacks included."""

import logging

import marketmyna  # noqa: F401 - installs the redacting record factory

TOKEN = "123456789:AAFAKEfakeFAKEfakeFAKEfakeFAKEfakeX"  # made up; never put a real token here


def test_message_and_traceback_are_masked(caplog):
    log = logging.getLogger("test.redact")
    with caplog.at_level(logging.INFO):
        log.info("GET https://api.telegram.org/bot%s/getUpdates key=%s", TOKEN, "AIzaSyFAKEFAKEFAKE")
        try:
            raise ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/getUpdates")
        except ConnectionError:
            log.exception("Telegram poll failed, backing off")
    text = caplog.text
    assert "AAFAKEfake" not in text and "AIzaSyFAKE" not in text
    assert "/bot***/getUpdates" in text
    assert "Telegram poll failed" in text


def test_plain_lines_untouched(caplog):
    with caplog.at_level(logging.INFO):
        logging.getLogger("test.redact").info("Stock %s at %d", "TCS", 4100)
    assert "Stock TCS at 4100" in caplog.text
