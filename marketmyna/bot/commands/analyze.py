"""/analyze SYMBOL [market] [mode] - runs the full agent pipeline and
replies with a short readable summary."""

from __future__ import annotations

from ...agent.dashboard import build_dashboard
from ...agent.orchestrator import AgentOrchestrator
from ..formatting import format_dashboard
from ..models import CommandResult, IncomingMessage
from .base import Command


class AnalyzeCommand(Command):
    name = "analyze"
    aliases = ["a"]
    usage = "/analyze SYMBOL [market] [mode]"
    description = "Full multi-agent AI analysis of one stock (technical, risk, news, decision)."
    group = "AI analysis"
    example = "/analyze AAPL us standard"
    help_text = "/analyze SYMBOL [market] [mode] - run the agent pipeline on one symbol (default market=us, mode=standard)"

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        parts = args.split()
        if not parts:
            return CommandResult(text=f"Usage: {self.help_text}", success=False)

        symbol = parts[0]
        market = parts[1] if len(parts) > 1 else "us"
        mode = parts[2] if len(parts) > 2 else "standard"

        orchestrator = AgentOrchestrator(config=self._config)
        try:
            ctx = orchestrator.run(symbol, market, mode=mode)
        except Exception as exc:
            return CommandResult(text=f"Analysis failed for {symbol}: {exc}", success=False)

        return CommandResult(text=format_dashboard(build_dashboard(ctx)))
