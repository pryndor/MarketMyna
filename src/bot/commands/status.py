"""/status - reports the persisted schedule config plus whether the
scheduler thread is currently running.

Unlike an HTTP endpoint, a bot command has no request.app.state to pull
the live RuntimeSchedulerService from - `scheduler_running` is an
optional callable injected by whoever wires the bot into the app (see
api/app.py's lifespan), so this command never reaches into global
state itself.
"""

from __future__ import annotations

from typing import Callable, Optional

from ...services.schedule_config import ScheduleConfigStore
from ..models import CommandResult, IncomingMessage
from .base import Command


class StatusCommand(Command):
    name = "status"
    aliases = ["s"]
    usage = "/status"
    description = "Scheduled-report settings and whether the scheduler is running."
    group = "System"
    example = "/status"
    help_text = "/status - show the scheduled-analysis config and whether it's running"

    def __init__(self, config, scheduler_running: Optional[Callable[[], bool]] = None):
        self._config = config
        self._scheduler_running = scheduler_running

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        cfg = ScheduleConfigStore(config=self._config).load()

        running = self._scheduler_running() if self._scheduler_running else None
        lines = [f"Scheduler thread: {'running' if running else 'not running' if running is not None else 'unknown'}"]
        lines.append(f"Scheduled analysis: {'enabled' if cfg.enabled else 'disabled'}")
        if cfg.symbols:
            lines.append(f"Symbols: {', '.join(cfg.symbols)} ({cfg.market}, {cfg.mode})")
        if cfg.interval_minutes:
            lines.append(f"Every {cfg.interval_minutes} minutes")
        elif cfg.time_of_day:
            lines.append(f"Daily at {cfg.time_of_day}")
        if cfg.last_run_at:
            lines.append(f"Last run: {cfg.last_run_at.isoformat()} ({cfg.last_run_status})")

        return CommandResult(text="\n".join(lines))
