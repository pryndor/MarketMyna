"""A pool of long-lived worker processes for scheduled-report analyses.

Starting a fresh Python process per stock costs ~5 s of imports (pandas,
yfinance, litellm...) before any work; a report wave of hundreds of stocks
would spend a fifth of its time just starting up. These workers import once
and then take one stock after another.

Safety, as with one process per stock:
- every task has a deadline; a worker past it (or one that died) is killed
  and replaced, and only that task fails;
- each worker talks to the parent over its own pipe, so killing one never
  corrupts the others' results;
- a worker is replaced after `max_tasks` tasks, so leaks can't build up.

One batch runs at a time (the scheduler's timer waves); the interactive
"Run now" keeps its own short-lived processes, so it never waits on a wave.
"""

from __future__ import annotations

import logging
import threading
import time
from multiprocessing.connection import wait
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# (symbol, market, mode, llm_kwargs, sections, user_id, shared)
Task = tuple


def _worker_main(conn, run: Callable) -> None:
    """Child process: run tasks until told to stop (None) or the pipe closes."""
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        task_id, task = msg
        try:
            result = run(*task)
        except Exception as exc:  # noqa: BLE001 - always answer the parent
            result = {"ok": False, "symbol": task[0], "market": task[1], "error": str(exc) or type(exc).__name__}
        try:
            conn.send((task_id, result))
        except (EOFError, OSError):
            return


class _Worker:
    def __init__(self, ctx, run: Callable):
        parent, child = ctx.Pipe()
        self.conn = parent
        self.process = ctx.Process(target=_worker_main, args=(child, run), daemon=True)
        self.process.start()
        child.close()
        self.tasks = 0
        self.busy: Optional[tuple[int, float]] = None  # (task index, deadline)

    def stop(self, kill: bool = False) -> None:
        try:
            if kill:
                self.process.kill()
            else:
                self.conn.send(None)
        except Exception:
            pass
        self.process.join(timeout=5)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=5)
        try:
            self.conn.close()
        except Exception:
            pass


class WorkerPool:
    def __init__(self, ctx, run: Callable, size: int, task_timeout: float, max_tasks: int = 200):
        self._ctx, self._run = ctx, run
        self.size = max(1, size)
        self.task_timeout = task_timeout
        self.max_tasks = max_tasks
        self._workers: list[_Worker] = []
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        self._workers = [w for w in self._workers if w.process.is_alive()]
        while len(self._workers) < self.size:
            self._workers.append(_Worker(self._ctx, self._run))
        while len(self._workers) > self.size:  # size lowered by the admin
            self._workers.pop().stop()

    def resize(self, size: int) -> None:
        self.size = max(1, size)

    def run_many(self, tasks: list[Task]) -> list[dict]:
        """Runs every task on the pool; results in task order, never raises."""
        with self._lock:
            self._ensure()
            results: list[Optional[dict]] = [None] * len(tasks)
            pending = list(range(len(tasks)))
            pending.reverse()
            while pending or any(w.busy for w in self._workers):
                for w in self._workers:
                    if w.busy is None and pending:
                        i = pending.pop()
                        try:
                            w.conn.send((i, tasks[i]))
                            w.busy = (i, time.monotonic() + self.task_timeout)
                        except Exception as exc:
                            results[i] = self._failed(tasks[i], f"worker unavailable: {exc}")
                busy = {w.conn: w for w in self._workers if w.busy}
                for conn in wait(list(busy), timeout=0.5) if busy else []:
                    w = busy[conn]
                    try:
                        i, result = conn.recv()
                    except (EOFError, OSError):
                        continue  # died: handled below
                    results[i] = result
                    w.busy = None
                    w.tasks += 1
                now = time.monotonic()
                for idx, w in enumerate(self._workers):
                    if w.busy and (now > w.busy[1] or not w.process.is_alive()):
                        i = w.busy[0]
                        reason = (f"watchdog timeout after {self.task_timeout:.0f}s" if w.process.is_alive()
                                  else "worker process exited without a result")
                        logger.warning("Scheduled analysis of %s: %s; replacing the worker", tasks[i][0], reason)
                        results[i] = self._failed(tasks[i], reason)
                        w.stop(kill=True)
                        self._workers[idx] = _Worker(self._ctx, self._run)
                    elif not w.busy and w.tasks >= self.max_tasks:
                        w.stop()
                        self._workers[idx] = _Worker(self._ctx, self._run)
            return [r if r is not None else self._failed(t, "no result") for r, t in zip(results, tasks)]

    @staticmethod
    def _failed(task: Task, error: str) -> dict:
        return {"ok": False, "symbol": task[0], "market": task[1], "error": error}

    def close(self) -> None:
        with self._lock:
            for w in self._workers:
                w.stop()
            self._workers = []
