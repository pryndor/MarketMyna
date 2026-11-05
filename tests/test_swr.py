"""Stale-while-revalidate: an expired cache entry is served at once and
refreshed in the background, one refresh per key at a time."""

import threading
import time

from marketmyna.utils import swr


def test_refresh_later_runs_once_per_key():
    started, release = threading.Event(), threading.Event()
    calls = []

    def slow():
        calls.append(1)
        started.set()
        release.wait(5)

    swr.refresh_later("k", slow)
    assert started.wait(5)
    swr.refresh_later("k", slow)  # still running: skipped
    release.set()
    for _ in range(100):
        if "k" not in swr._running:
            break
        time.sleep(0.01)
    assert calls == [1] and "k" not in swr._running


def test_refresh_failure_keeps_key_free():
    done = threading.Event()

    def boom():
        done.set()
        raise RuntimeError("down")

    swr.refresh_later("bad", boom)
    assert done.wait(5)
    for _ in range(100):
        if "bad" not in swr._running:
            break
        time.sleep(0.01)
    assert "bad" not in swr._running
