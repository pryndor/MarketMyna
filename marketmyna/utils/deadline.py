"""Hard deadlines for third-party calls that can hang (Yahoo's `.info`,
option chains, batch downloads have no reliable timeout of their own).

The call runs on a daemon thread: if it overruns, the caller gets
TimeoutError right away and the stuck thread can't delay a reload or
process exit (a ThreadPoolExecutor's threads would)."""

from __future__ import annotations

import contextvars
import threading
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def call_with_deadline(fn: Callable[..., T], seconds: float, *args: Any, **kwargs: Any) -> T:
    box: dict[str, Any] = {}
    done = threading.Event()

    def run() -> None:
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc
        finally:
            done.set()

    # Copy the caller's context so the per-user data scope (marketmyna/core/tenant.py) follows the call.
    ctx = contextvars.copy_context()
    threading.Thread(target=ctx.run, args=(run,), name=f"deadline:{getattr(fn, '__name__', 'call')}", daemon=True).start()
    if not done.wait(seconds):
        raise TimeoutError(f"{getattr(fn, '__name__', 'call')} took longer than {seconds:.0f}s")
    if "error" in box:
        raise box["error"]
    return box["value"]
