"""In-process runtime scheduler.

A background thread wakes up every CHECK_INTERVAL_SECONDS and asks "is a
run due?" against the persisted ScheduleConfig (marketmyna/services/schedule_config.py).
When it is, every configured symbol is analyzed in its own isolated
**child process** (multiprocessing, spawn context - matching
daily_stock_analysis's own RuntimeSchedulerService design) with a
watchdog timeout, so a long-running or crashing analysis can never take
the API server down with it. Results are written back to the persisted
config and delivered per channel/language by analysis_run.deliver_report().

Both the timer loop and the manual "run now" API endpoint call the same
`run_now()` method, so there is exactly one "do a run" code path.

Multiprocessing/pickling note: a spawn-context Process target must be a
plain module-level function, not a bound method or closure, and its
arguments must be picklable. `_run_one_symbol_in_process` below is that
function - it does NOT receive the parent's live Config object (pickling
a whole Config, or an AgentOrchestrator, across the process boundary is
fragile and unnecessary); it receives a small dict of plain LLM-related
values and reconstructs whatever it needs from scratch inside the child.

Deployment caveat worth flagging explicitly: a spawned child process
re-imports this module by its dotted path (`marketmyna.services.runtime_scheduler`).
That only works if `src`/`api` are resolvable as top-level packages in a
FRESH interpreter, i.e. the project root is on that interpreter's
sys.path (or PYTHONPATH) independent of the parent process's own
sys.path tricks. Whatever launches the real API server (uvicorn from the
project root, a proper package install, etc) must ensure that's true;
this was not exercised against a real spawned-from-uvicorn process in
this sandbox (fastapi itself isn't installed here), only against a
directly-invoked python process where cwd is already on sys.path.
"""

from __future__ import annotations

import contextvars
import logging
import multiprocessing
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from ..core import tenant
from .analysis_run import analyze_symbol, deliver_report, notify_failure
from .schedule_config import ScheduleConfig, ScheduleConfigStore, resolve_funds, resolve_targets

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 30.0
DEFAULT_WATCHDOG_SECONDS = 30 * 60.0


def _extract_llm_kwargs(config) -> dict:
    """The only Config fields the child process actually needs (to build
    its own GenerationBackend) - deliberately not the whole Config, so
    the multiprocessing payload stays small and unambiguous."""
    return {
        "llm_backend": getattr(config, "llm_backend", None),
        "llm_model": getattr(config, "llm_model", None),
        "llm_api_base": getattr(config, "llm_api_base", None),
        "llm_api_key": getattr(config, "llm_api_key", None),
        "llm_timeout_seconds": getattr(config, "llm_timeout_seconds", None),
        "llm_max_tokens": getattr(config, "llm_max_tokens", None),
        "llm_temperature": getattr(config, "llm_temperature", None),
        "llm_api_keys": getattr(config, "llm_api_keys", None),
        "llm_fallback_models": getattr(config, "llm_fallback_models", None),
        "llm_channels": getattr(config, "llm_channels", None),
        # Per-provider keys, the fast tier and the shared cache/usage db.
        **{
            name: getattr(config, name, None)
            for name in (
                "gemini_api_key", "groq_api_key", "openrouter_api_key", "openai_api_key", "anthropic_api_key",
                "deepseek_api_key", "mistral_api_key", "cerebras_api_key", "nvidia_api_key", "ollama_base_url", "openai_base_url", "llm_fast_model",
                "llm_cache_hours",
                "db_path",
                # Accounts mode: the child meters AI and reads the user's own key.
                "accounts_enabled", "admin_email", "secret_key", "app_dir",
            )
            if getattr(config, name, None) is not None
        },
    }


def _analyze_in_child(
    symbol: str, market: str, mode: str, llm_kwargs: dict, sections: Optional[list] = None,
    user_id: Optional[int] = None, shared: bool = False,
) -> dict:
    """One analysis inside a child process (a one-off process or a pool
    worker). Module-level so spawn can pickle it; never raises."""
    try:
        import contextlib

        from ..core import tenant
        from ..core.config import Config
        from ..utils import yahoo_gate
        from .analysis_run import analyze_symbol

        # One Yahoo pace for the whole server; a worker waits out a 429 cooldown.
        yahoo_gate.install()
        yahoo_gate.patient()

        config = Config(**llm_kwargs)
        scope = contextlib.nullcontext()
        if config.accounts_enabled:
            # A fresh process: re-apply the owner's data scope.
            tenant.enable()
            scope = tenant.user_scope(user_id)
        with scope:
            return analyze_symbol(symbol, market, mode, config, sections=sections)
    except Exception as exc:  # noqa: BLE001 - reported to parent, not raised in the child
        return {"ok": False, "symbol": symbol, "market": market, "error": str(exc)}


def _run_one_symbol_in_process(
    symbol: str, market: str, mode: str, llm_kwargs: dict, result_queue, sections: Optional[list] = None,
    user_id: Optional[int] = None, shared: bool = False,
) -> None:
    """Module-level, picklable multiprocessing target for a one-off child
    ("Run now"). Every outcome is reported through result_queue so the parent
    always gets a clean answer rather than a silently-dead child."""
    result_queue.put(_analyze_in_child(symbol, market, mode, llm_kwargs, sections, user_id, shared))


# Seconds to wait before retrying the stocks that hit a rate limit.
RETRY_PAUSE = float(os.environ.get("SCHEDULER_RETRY_PAUSE", 60))
_LIMIT_SIGNS = ("rate_limited", "rate limit", "too many requests", "429", "cooling down",
                "all sources exhausted", "quota")


def _hit_limit(result: dict) -> bool:
    """A failure that a later try may not hit: an AI or data source said
    "slow down", not "this stock doesn't exist"."""
    if result.get("ok"):
        return False
    error = str(result.get("error") or "").lower()
    return any(sign in error for sign in _LIMIT_SIGNS)


class RuntimeSchedulerService:
    def __init__(
        self,
        config,
        watchdog_seconds: float = DEFAULT_WATCHDOG_SECONDS,
        orchestrator_factory: Optional[Callable[[], object]] = None,
        mp_start_method: str = "spawn",
    ):
        """`orchestrator_factory`, when given, makes `run_now()` build and
        run an AgentOrchestrator in-process (no multiprocessing) via that
        factory instead - the injection point a test uses to swap in a
        fake orchestrator/backend without touching the real child-process
        path at all."""
        self._config = config
        self._store = ScheduleConfigStore(config=config)
        self._watchdog_seconds = watchdog_seconds
        self._orchestrator_factory = orchestrator_factory
        self._mp_context = multiprocessing.get_context(mp_start_method)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Timer waves run on long-lived workers (marketmyna/services/worker_pool.py);
        # tests with a fake orchestrator run everything in-process instead.
        self.use_pool = orchestrator_factory is None
        self._pool = None
        # "Run now" per account: {"running": bool, "result": dict | None}.
        self._now: dict = {}
        self._now_lock = threading.Lock()

    # ---- lifecycle ----

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="marketmyna-scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- timer loop ----

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_and_maybe_run()
            except Exception:
                logger.exception("Scheduler check-and-run failed")
            self._stop_event.wait(CHECK_INTERVAL_SECONDS)

    def _check_and_maybe_run(self) -> None:
        """One tick: find every account whose report is due, then run them all
        as one wave (shared analyses, parallel workers - see _run_wave)."""
        from .accounts import for_each_user

        due: list[Optional[int]] = []

        def collect() -> None:
            if self.is_due(self._store.load(), datetime.now(timezone.utc), self._user_zone()):
                due.append(tenant.current_user_id())

        # Accounts mode: every user's own schedule in their own scope.
        # Otherwise the one schedule.
        for_each_user(self._config, collect, "Scheduled report check")
        if due:
            self._run_wave(due, use_pool=self.use_pool)

    def _user_zone(self):
        """The current account's time zone (single-user mode: the default)."""
        from .schedule_time import zone

        uid = tenant.current_user_id()
        if not tenant.enabled() or uid is None:
            return zone(None)
        from ..storage import DatabaseManager, UserRecord, get_db_url

        with tenant.system_scope(), DatabaseManager.instance(get_db_url(config=self._config)).get_session() as session:
            user = session.get(UserRecord, uid)
            return zone(user.timezone if user else None)

    @staticmethod
    def is_due(cfg: ScheduleConfig, now: datetime, tz=None) -> bool:
        """Public/static so it can be unit-tested with a synthetic
        ScheduleConfig + timestamp, no threading or DB involved.

        `tz`: the account's time zone. A daily time is that local time
        (24-hour), so 08:45 for a user in New York runs at 08:45 New York
        time. Naive datetimes (now, last_run_at) are the server's local time."""
        if not cfg.enabled or not cfg.has_targets_configured():
            return False

        if cfg.interval_minutes:
            if cfg.last_run_at is None:
                return True
            last = cfg.last_run_at
            if now.tzinfo is not None:
                last = last.astimezone(now.tzinfo) if last.tzinfo else last.astimezone()
            return now - last >= timedelta(minutes=cfg.interval_minutes)

        if cfg.time_of_day:
            try:
                hour, minute = (int(part) for part in cfg.time_of_day.split(":", 1))
            except ValueError:
                logger.warning("Invalid time_of_day %r, ignoring", cfg.time_of_day)
                return False
            if tz is not None:
                now = now.astimezone(tz)
            target_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now < target_today:
                return False
            last = cfg.last_run_at
            if last is not None and now.tzinfo is not None:
                last = last.astimezone(now.tzinfo)  # naive = server local time
            if last is not None and last >= target_today:
                return False  # already ran today's slot
            return True

        return False

    # ---- run execution (shared by the loop and the manual endpoint) ----

    def run_now(self) -> dict:
        """Run the current account's report now (the "Run now" button and
        single-user mode). Same wave path as the timer, with one account."""
        return self._run_wave([tenant.current_user_id()])[tenant.current_user_id()]

    def start_run_now(self) -> bool:
        """run_now() in the background, since a report can outlast a proxy's
        request timeout (Cloudflare: 100 s). False if this account's run is
        already going. The page polls run_now_state()."""
        uid = tenant.current_user_id()
        with self._now_lock:
            if self._now.get(uid, {}).get("running"):
                return False
            self._now[uid] = {"running": True, "result": None}

        def work() -> None:
            try:
                result = self.run_now()
            except Exception as exc:  # reported to the page, not raised in a bare thread
                logger.exception("Run now failed")
                result = {"status": "failed", "results": [], "summary": f"The run failed: {exc}"}
            with self._now_lock:
                self._now[uid] = {"running": False, "result": result}

        # The thread keeps the request's context: the account's scope, AI key and compliance mode.
        threading.Thread(target=contextvars.copy_context().run, args=(work,), name="run-now", daemon=True).start()
        return True

    def run_now_state(self) -> dict:
        with self._now_lock:
            return dict(self._now.get(tenant.current_user_id(), {"running": False, "result": None}))

    def _run_wave(self, user_ids: list, use_pool: bool = False) -> dict:
        """Every due account's report in one go.

        1. Plan, in each account's scope: its stocks, sections, AI access.
        2. Analyse each (stock, market, depth) once per group of accounts that
           can share it - same AI access kind and compliance mode; an account
           on its own AI key never shares - on `schedule_slots.workers()`
           parallel workers.
        3. Build and send each account's report from the shared results, in
           its own scope (its sections, language and channels).
        """
        from concurrent.futures import ThreadPoolExecutor

        plans_by_user: dict = {}
        for uid in user_ids:
            with self._scope(uid):
                try:
                    plans_by_user[uid] = self._plan(uid)
                except Exception as exc:
                    logger.exception("Could not plan the report for user %s", uid)
                    plans_by_user[uid] = {"error": str(exc)}

        # One job per shareable analysis; each remembers the account it runs as.
        jobs: dict = {}
        for uid, plan in plans_by_user.items():
            if plan.get("smart") or plan.get("error"):
                continue
            for t in plan["targets"]:
                key = (t.symbol, t.market, plan["mode"], plan["share"])
                job = jobs.setdefault(key, {"user_id": uid, "sections": set(), "shared": False})
                job["sections"].update(plan["sections"])
                if job["user_id"] != uid:
                    job["shared"] = True

        from .schedule_time import workers

        results: dict = {}
        if jobs and use_pool:
            keys = list(jobs)
            llm_kwargs = _extract_llm_kwargs(self._config)
            tasks = [(k[0], k[1], k[2], llm_kwargs, sorted(jobs[k]["sections"]), jobs[k]["user_id"], jobs[k]["shared"])
                     for k in keys]
            results = dict(zip(keys, self._worker_pool().run_many(tasks)))
        elif jobs:
            with ThreadPoolExecutor(max_workers=min(workers(self._config), len(jobs))) as pool:
                futures = {
                    key: pool.submit(self._run_job, key[0], key[1], key[2], sorted(job["sections"]),
                                     job["user_id"], job["shared"])
                    for key, job in jobs.items()
                }
                for key, future in futures.items():
                    results[key] = future.result()

        # Free AI and data tiers throttle bursts (Gemini / Groq 429, Yahoo "Too
        # Many Requests"). Stocks that hit a limit get one more try, one at a
        # time, once the limits have had a moment to reset.
        retry = [key for key, result in results.items() if _hit_limit(result)]
        if retry:
            logger.info("Retrying %d stock(s) that hit a rate limit in %.0fs: %s",
                        len(retry), RETRY_PAUSE, ", ".join(k[0] for k in retry))
            time.sleep(RETRY_PAUSE)
            for key in retry:
                job = jobs[key]
                again = self._run_job(key[0], key[1], key[2], sorted(job["sections"]), job["user_id"], job["shared"])
                if again.get("ok") or (again.get("dashboard") and not results[key].get("dashboard")):
                    results[key] = again

        def deliver(uid):
            with self._scope(uid):
                return self._finish(uid, plans_by_user[uid], results)

        out: dict = {}
        with ThreadPoolExecutor(max_workers=max(1, min(workers(self._config), len(plans_by_user)))) as pool:
            for uid, outcome in zip(plans_by_user, pool.map(deliver, plans_by_user)):
                out[uid] = outcome
        return out

    def _worker_pool(self):
        """The long-lived workers, created on first use and kept between
        waves; resized when the admin changes the worker count."""
        from .schedule_time import workers
        from .worker_pool import WorkerPool

        if self._pool is None:
            self._pool = WorkerPool(self._mp_context, _analyze_in_child, workers(self._config), self._watchdog_seconds)
        else:
            self._pool.resize(workers(self._config))
        return self._pool

    def _scope(self, uid):
        import contextlib

        return tenant.user_scope(uid) if tenant.enabled() and uid is not None else contextlib.nullcontext()

    def _run_job(self, symbol, market, mode, sections, user_id, shared) -> dict:
        try:
            if user_id is not None and tenant.enabled():
                with tenant.user_scope(user_id):
                    return self._run_one_symbol(symbol, market, mode, sections, user_id=user_id, shared=shared)
            return self._run_one_symbol(symbol, market, mode, sections)
        except Exception as exc:  # one stock never sinks the wave
            return {"ok": False, "symbol": symbol, "market": market, "error": str(exc)}

    def _plan(self, uid) -> dict:
        """What this account's run covers (runs in its scope)."""
        from ..core.compliance import mode as compliance_mode

        cfg = self._store.load()
        prefs = cfg.report_prefs(timezone=self._user_zone().key)
        run_mode = cfg.mode or "standard"
        prefs.mode = run_mode
        try:
            targets = resolve_targets(cfg, self._config)
            prefs.funds = resolve_funds(cfg, self._config)
        except Exception as exc:
            logger.exception("Could not read the run's watchlists/portfolios")
            targets = []
            notify_failure(self._config, f"Could not read the watchlists/portfolios to run: {exc}")
        # Smart messaging strips every call, level and stop (smart_report.without_calls).
        smart = bool(prefs.smart and targets)
        return {"cfg": cfg, "prefs": prefs, "targets": targets, "mode": run_mode,
                "sections": sorted(prefs.all_sections()), "smart": smart,
                "share": compliance_mode()}

    def _finish(self, uid, plan: dict, results: dict) -> dict:
        """Build, send and record one account's report (runs in its scope)."""
        import copy

        if plan.get("error"):
            return {"status": "failed", "results": [], "summary": plan["error"]}
        cfg, prefs, targets = plan["cfg"], plan["prefs"], plan["targets"]
        if plan["smart"]:
            return self._run_smart(cfg, prefs, targets)
        own = [copy.deepcopy(results[(t.symbol, t.market, plan["mode"], plan["share"])]) for t in targets]

        if not own:
            status = "no_symbols_configured"
        elif all(r.get("ok") for r in own):
            status = "ok"
        elif any(r.get("ok") for r in own):
            status = "partial_failure"
        else:
            status = "failed"

        reports: dict = {}
        if own:
            try:
                # Renders one report per language and sends each channel
                # its preferred language.
                reports, _ = deliver_report(own, prefs, self._config)
            except Exception as exc:
                logger.exception("Failed to build or dispatch scheduler report")
                notify_failure(self._config, f"The report could not be built or sent: {exc}")
            # Alert only when nothing at all came back - missing AI decisions
            # (no model configured) still produce a useful report.
            if not any(r.get("dashboard") for r in own):
                notify_failure(
                    self._config,
                    "No stock could be analyzed.\n"
                    + "\n".join(f"{r['symbol']}: {r.get('error', 'no data')}" for r in own),
                )
        default = reports.get(prefs.language) or next(iter(reports.values()), None)
        summary = default[1] if default else (
            "Nothing to run: the chosen watchlists / portfolios / symbols are empty."
        )

        cfg = self._store.load()  # settings may have changed while the wave ran
        cfg.last_run_at = datetime.now()
        cfg.last_run_status = status
        cfg.last_run_summary = summary
        cfg.stock_count = len(targets)
        self._store.save(cfg)

        return {"status": status, "results": own, "summary": summary}

    def _run_smart(self, cfg, prefs, targets) -> dict:
        """Smart messaging: computed metrics for every stock, AI for the top
        few, one short message + a saved full report (see smart_report)."""
        from .smart_report import run_smart

        analyze = None
        if self._orchestrator_factory is not None:  # tests: in-process fake pipeline
            analyze = lambda sym, mkt, mode, config: analyze_symbol(  # noqa: E731
                sym, mkt, mode, config, orchestrator=self._orchestrator_factory())
        try:
            reports, _, rows, token, _ = run_smart(targets, prefs, self._config, analyze=analyze)
        except Exception as exc:
            logger.exception("Smart report failed")
            notify_failure(self._config, f"The smart report could not be built or sent: {exc}")
            reports, rows, token = {}, [], None
        ok = [r for r in rows if "error" not in r]
        status = "ok" if rows and len(ok) == len(rows) else "partial_failure" if ok else "failed"
        if rows and not ok:
            notify_failure(self._config, "No stock could be analyzed.\n" + "\n".join(
                f"{r['symbol']}: {r.get('error')}" for r in rows))
        default = reports.get(prefs.language) or next(iter(reports.values()), None)
        summary = default[1] if default else "No report produced."
        cfg = self._store.load()  # settings may have changed while the run went
        cfg.last_run_at = datetime.now()
        cfg.last_run_status = status
        cfg.last_run_summary = summary
        cfg.stock_count = len(targets)
        self._store.save(cfg)
        results = [{"ok": "error" not in r, "symbol": r["symbol"], "error": r.get("error")} for r in rows]
        return {"status": status, "results": results, "summary": summary, "report_token": token}

    def _run_one_symbol(self, symbol: str, market: str, mode: str, sections: Optional[list] = None,
                        user_id: Optional[int] = None, shared: bool = False) -> dict:
        if self._orchestrator_factory is not None:
            # Test/injection path: in-process, no multiprocessing, so a
            # fake orchestrator/backend can be swapped in cleanly.
            try:
                return analyze_symbol(
                    symbol, market, mode, self._config, orchestrator=self._orchestrator_factory(), sections=sections
                )
            except Exception as exc:
                return {"ok": False, "symbol": symbol, "market": market, "error": str(exc)}

        result_queue = self._mp_context.Queue()
        llm_kwargs = _extract_llm_kwargs(self._config)
        process = self._mp_context.Process(
            target=_run_one_symbol_in_process,
            args=(symbol, market, mode, llm_kwargs, result_queue, sections,
                  user_id if user_id is not None else tenant.current_user_id(), shared),
        )
        process.start()
        process.join(timeout=self._watchdog_seconds)

        if process.is_alive():
            logger.warning(
                "Scheduled run for %s exceeded watchdog (%.0fs), terminating", symbol, self._watchdog_seconds
            )
            process.terminate()
            process.join(timeout=5.0)
            return {
                "ok": False,
                "symbol": symbol,
                "market": market,
                "error": f"watchdog timeout after {self._watchdog_seconds:.0f}s",
            }

        try:
            return result_queue.get_nowait()
        except Exception:
            return {"ok": False, "symbol": symbol, "market": market, "error": "child process exited without a result"}
