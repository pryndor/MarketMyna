"""One shared pace for every Yahoo Finance request on this server.

Yahoo throttles by IP, not by process. The web app, every scheduled-report
worker and the background jobs each run their own yfinance, so before this
gate a report wave of 4 workers fired requests in bursts and one 429 in one
worker said nothing to the others, which kept hammering and extended the ban.

- Pacing (scheduled-report workers only; web requests are never delayed):
  a token bucket shared by all worker processes (a small state file under
  a file lock). Up to `BURST` requests go straight through, so a page that
  fetches dozens of tickers at once is not slowed; beyond that, requests
  are released at `RATE` per second. (A strict gap between every request
  queued page loads behind each other: 80 tickers took 16 s.)
- Shared cooldown: a 429 anywhere pauses Yahoo for every process for
  `COOLDOWN` seconds. Scheduled workers (`patient()`) wait it out, up to
  `MAX_WAIT`; web requests fail fast with yfinance's own YFRateLimitError, so
  pages fall back to caches instead of hanging.

`install()` wraps yfinance's single request method (YfData._make_request), so
every Ticker / download / search call goes through the gate without touching
the call sites. Without fcntl (Windows) the gate works per process only.
"""

from __future__ import annotations

import functools
import logging
import os
import threading
import time
from pathlib import Path

from marketmyna.core.home import app_home

logger = logging.getLogger(__name__)

RATE = float(os.environ.get("YAHOO_RATE", 10))  # sustained requests per second
BURST = float(os.environ.get("YAHOO_BURST", 60))
COOLDOWN = float(os.environ.get("YAHOO_COOLDOWN", 30))
MAX_WAIT = float(os.environ.get("YAHOO_MAX_WAIT", 90))

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
try:
    import msvcrt  # Windows file locks
except ImportError:
    msvcrt = None

_local_lock = threading.Lock()
_local_state = [0.0, 0.0]  # bucket clock (see reserve), cooldown until (no-fcntl fallback)
_patient = False
_installed = False


def state_path() -> Path:
    return Path(os.environ.get("YAHOO_GATE_FILE") or app_home() / "yahoo_gate")


def patient(on: bool = True) -> None:
    """This process waits out a shared cooldown instead of failing fast
    (scheduled-report workers: a late report beats a failed one)."""
    global _patient
    _patient = on


def _lock(f) -> None:
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_EX)
    else:  # Windows: lock the first byte (LK_LOCK retries for about 10 s, then raises OSError)
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)


def _unlock(f) -> None:
    if fcntl is not None:
        fcntl.flock(f, fcntl.LOCK_UN)
    else:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def _update(change):
    """Run change(clock, cooldown_until) -> (clock, cooldown_until, result)
    under the cross-process lock and return result."""
    if fcntl is not None or msvcrt is not None:
        try:
            path = state_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a+", encoding="utf-8") as f:
                _lock(f)
                try:
                    f.seek(0)
                    parts = f.read().split()
                    try:
                        nxt, cool = float(parts[0]), float(parts[1])
                    except (IndexError, ValueError):
                        nxt, cool = 0.0, 0.0
                    nxt, cool, result = change(nxt, cool)
                    f.seek(0)
                    f.truncate()
                    f.write(f"{nxt:.3f} {cool:.3f}")
                    f.flush()
                    return result
                finally:
                    _unlock(f)
        except OSError as exc:
            logger.debug("Yahoo gate file unavailable, pacing this process only: %s", exc)
    with _local_lock:
        nxt, cool, result = change(*_local_state)
        _local_state[:] = [nxt, cool]
        return result


def reserve() -> float:
    """Book the next request slot; returns seconds to sleep before sending.
    Raises YFRateLimitError while Yahoo is cooling down (unless patient)."""
    now = time.time()

    # The bucket is kept as one number, `clock`: the moment it would be full
    # again. Each request pushes it 1/RATE later; a request may go once the
    # clock is no more than BURST/RATE ahead of now.
    def change(clock, cool):
        if cool > now and (not _patient or cool - now > MAX_WAIT):
            return clock, cool, -(cool - now)
        if not _patient:
            # Web requests are never paced (a page waits on them); only the
            # scheduled-report workers, which burst for minutes, use the bucket.
            return clock, cool, 0.0
        start = max(now, cool)
        clock = max(clock, start) + 1.0 / RATE
        return clock, cool, max(0.0, clock - start - BURST / RATE) + (start - now)

    wait = _update(change)
    if wait < 0:
        from yfinance.exceptions import YFRateLimitError

        logger.info("Yahoo cooling down for another %.0fs after a 429; not sending", -wait)
        raise YFRateLimitError()
    return wait


def record_limit() -> None:
    """Yahoo said 429: every process on this server pauses for COOLDOWN."""
    until = time.time() + COOLDOWN

    def change(clock, cool):
        return clock, max(cool, until), None

    _update(change)
    logger.warning("Yahoo rate limit hit; pausing Yahoo requests for %.0fs on this server", COOLDOWN)


def install() -> None:
    """Route every yfinance HTTP request through the gate (idempotent)."""
    global _installed
    if _installed:
        return
    try:
        from yfinance.data import YfData
        from yfinance.exceptions import YFRateLimitError
    except Exception as exc:  # noqa: BLE001 - yfinance missing or reshaped: run ungated
        logger.warning("Yahoo gate not installed: %s", exc)
        return
    original = YfData._make_request

    @functools.wraps(original)
    def paced(self, *args, **kwargs):
        wait = reserve()
        if wait > 0:
            time.sleep(wait)
        try:
            response = original(self, *args, **kwargs)
        except YFRateLimitError:
            record_limit()
            raise
        if getattr(response, "status_code", None) == 429:
            record_limit()
        return response

    YfData._make_request = paced
    _installed = True
