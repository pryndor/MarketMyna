"""call_with_deadline: returns, re-raises, and gives up on hung calls."""

import threading
import time

import pytest

from marketmyna.utils.deadline import call_with_deadline


def test_returns_and_raises():
    assert call_with_deadline(lambda a, b=0: a + b, 1, 2, b=3) == 5
    with pytest.raises(ValueError):
        call_with_deadline(lambda: (_ for _ in ()).throw(ValueError("boom")), 1)


def test_hung_call_times_out_on_a_daemon_thread():
    gate = threading.Event()
    started = time.time()
    with pytest.raises(TimeoutError):
        call_with_deadline(gate.wait, 0.2)
    assert time.time() - started < 1
    stuck = [t for t in threading.enumerate() if t.name.startswith("deadline:")]
    assert stuck and all(t.daemon for t in stuck)  # can't block interpreter exit
    gate.set()
