"""Stale-while-revalidate for the slow-changing caches (macro, earnings,
financials, company info, fund NAVs).

When a cached value has expired but is not too old, the caller serves it at
once and the fresh download runs on a background thread, so a page view never
waits on the outside service just because a timer ran out. Only one refresh
per key runs at a time; a failed refresh leaves the old value in place.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Hashable

logger = logging.getLogger(__name__)

_running: set[Hashable] = set()
_lock = threading.Lock()


def refresh_later(key: Hashable, fn: Callable[[], object]) -> None:
    """Run `fn` on a background thread unless a refresh for `key` is already running."""
    with _lock:
        if key in _running:
            return
        _running.add(key)

    def run() -> None:
        try:
            fn()
        except Exception as exc:
            logger.info("Background refresh %s failed: %s", key, exc)
        finally:
            with _lock:
                _running.discard(key)

    threading.Thread(target=run, name="swr-refresh", daemon=True).start()
