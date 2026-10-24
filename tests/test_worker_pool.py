"""The scheduled-report worker pool, with real worker processes: results in
order, workers reused across tasks, and a stuck or crashed worker replaced
without losing the other tasks."""

import multiprocessing
import os
import time

from marketmyna.services.worker_pool import WorkerPool

CTX = multiprocessing.get_context("spawn")


def fake_analysis(symbol, market, mode="", llm_kwargs=None, sections=None, user_id=None, shared=False):
    if symbol == "HANG":
        time.sleep(30)
    if symbol == "CRASH":
        os._exit(1)
    if symbol == "BOOM":
        raise RuntimeError("data source down")
    return {"ok": True, "symbol": symbol, "market": market, "pid": os.getpid()}


def _tasks(*symbols):
    return [(s, "us", "quick", {}, [], None, False) for s in symbols]


def test_results_in_order_on_reused_workers():
    pool = WorkerPool(CTX, fake_analysis, size=2, task_timeout=20)
    try:
        out = pool.run_many(_tasks(*[f"S{i}" for i in range(8)]))
        assert [r["symbol"] for r in out] == [f"S{i}" for i in range(8)]
        assert len({r["pid"] for r in out}) <= 2  # two processes did all eight
        again = pool.run_many(_tasks("A", "B"))
        assert {r["pid"] for r in again} <= {r["pid"] for r in out}  # kept between waves
    finally:
        pool.close()


def test_stuck_crashed_and_failing_tasks_dont_sink_the_rest():
    pool = WorkerPool(CTX, fake_analysis, size=2, task_timeout=3)
    try:
        out = pool.run_many(_tasks("A", "HANG", "B", "CRASH", "BOOM", "C"))
        by = {r["symbol"]: r for r in out}
        assert by["A"]["ok"] and by["B"]["ok"] and by["C"]["ok"]
        assert "watchdog timeout" in by["HANG"]["error"]
        assert "exited without a result" in by["CRASH"]["error"]
        assert by["BOOM"]["error"] == "data source down"
        assert all(r["ok"] for r in pool.run_many(_tasks("D", "E")))  # replacements work
    finally:
        pool.close()


def test_workers_are_recycled_after_max_tasks():
    pool = WorkerPool(CTX, fake_analysis, size=1, task_timeout=20, max_tasks=2)
    try:
        out = pool.run_many(_tasks("A", "B", "C", "D", "E"))
        assert len({r["pid"] for r in out}) == 3  # 2 + 2 + 1
    finally:
        pool.close()
