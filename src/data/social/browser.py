"""Headless Chromium for sources that refuse plain HTTP clients
(Reddit's pages, StockTwits behind Cloudflare).

One short-lived browser per call, at most two at a time - Chromium costs
300-500 MB each, so this stays bounded on a small server. Playwright is an
optional dependency: without it (or its Chromium download) every browser
source reports itself unavailable and the other sources still run.

    pip install playwright && python -m playwright install chromium
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

from .base import UA, SourceBlocked, SourceSkipped

logger = logging.getLogger(__name__)

_SLOTS = threading.BoundedSemaphore(2)

# Text of the pages sites show instead of content when they block a bot.
_BLOCK_MARKERS = (
    "blocked by network security",
    "just a moment...",
    "too many requests",
    "log in to use old reddit",
    "verify you are human",
)


def available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


@contextmanager
def page(timeout_ms: int = 30_000) -> Iterator["object"]:
    """A fresh Playwright page in its own browser; closed on exit."""
    if not available():
        raise SourceSkipped("Playwright is not installed (pip install playwright)")
    from playwright.sync_api import sync_playwright

    with _SLOTS, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        try:
            context = browser.new_context(user_agent=UA, locale="en-US", viewport={"width": 1280, "height": 900})
            pg = context.new_page()
            pg.set_default_timeout(timeout_ms)
            # Images/fonts/media are never needed - skip them to save time and bandwidth.
            pg.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font")
                else route.continue_(),
            )
            yield pg
        finally:
            browser.close()


def check_blocked(pg, status: int | None = None) -> None:
    """Raise SourceBlocked if the loaded page is a bot wall / rate limit."""
    if status == 429:
        raise SourceBlocked("rate limited (429)")
    try:
        head = (pg.title() + " " + pg.inner_text("body")[:600]).lower()
    except Exception:
        return
    for marker in _BLOCK_MARKERS:
        if marker in head:
            raise SourceBlocked(marker)


def get_text(url: str, timeout_ms: int = 30_000) -> str:
    """Load a URL in the browser and return the body text (for JSON endpoints
    that only answer real browsers)."""
    with page(timeout_ms) as pg:
        response = pg.goto(url, wait_until="domcontentloaded")
        status = response.status if response else None
        body = pg.inner_text("body")
        if status == 429 or (not body.lstrip().startswith(("{", "[")) and status != 200):
            raise SourceBlocked(f"HTTP {status}")
        if not body.lstrip().startswith(("{", "[")):
            check_blocked(pg, status)
        return body
