"""/batch SYM1,SYM2,SYM3 [market] [mode] - runs the agent pipeline over
several symbols sequentially (same no-concurrency approach as the
runtime scheduler) and replies with one combined summary."""

from __future__ import annotations

from ...agent.dashboard import build_dashboard
from ...agent.orchestrator import AgentOrchestrator
from ..formatting import format_dashboard
from ..models import CommandResult, IncomingMessage
from .base import Command

MAX_SYMBOLS = 10


class BatchCommand(Command):
    name = "batch"
    aliases = ["b"]
    usage = "/batch SYM1,SYM2 [market] [mode]"
    description = "AI analysis of several stocks in one go (max 10)."
    group = "AI analysis"
    example = "/batch TCS,INFY india quick"
    help_text = "/batch SYM1,SYM2,SYM3 [market] [mode] - run the agent pipeline over several symbols (max 10)"

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        parts = args.split()
        if not parts:
            return CommandResult(text=f"Usage: {self.help_text}", success=False)

        symbols = [s.strip() for s in parts[0].split(",") if s.strip()]
        if not symbols:
            return CommandResult(text=f"Usage: {self.help_text}", success=False)
        if len(symbols) > MAX_SYMBOLS:
            return CommandResult(text=f"Too many symbols (max {MAX_SYMBOLS}).", success=False)

        market = parts[1] if len(parts) > 1 else "us"
        mode = parts[2] if len(parts) > 2 else "standard"

        orchestrator = AgentOrchestrator(config=self._config)
        blocks = []
        any_ok = False
        for symbol in symbols:
            try:
                ctx = orchestrator.run(symbol, market, mode=mode)
                blocks.append(format_dashboard(build_dashboard(ctx)))
                any_ok = True
            except Exception as exc:
                blocks.append(f"{symbol}: failed ({exc})")

        return CommandResult(text="\n\n".join(blocks), success=any_ok)
