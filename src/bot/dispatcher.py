"""Routes an IncomingMessage to a registered Command.

Parsing is forgiving: "/analyze AAPL" is the normal form, but a bare
"analyze AAPL" (first word matching a registered command name/alias,
no leading slash) also routes correctly. Anything else with no
recognized command word falls through to the "ask" command if one is
registered (so a plain question like "should I buy AAPL?" gets a
useful answer instead of an "unknown command" reply) - the same
graceful-fallback shape as daily_stock_analysis's own dispatcher, kept
much smaller here (no rate limiting, no admin users, no NL-intent LLM
routing - none of that is in scope for this phase).
"""

from __future__ import annotations

import logging

from .commands.base import Command
from .models import CommandResult, IncomingMessage

logger = logging.getLogger(__name__)


class CommandDispatcher:
    def __init__(self, command_prefix: str = "/"):
        self.command_prefix = command_prefix
        self._commands: dict[str, Command] = {}
        self._aliases: dict[str, str] = {}

    def register(self, command: Command) -> None:
        name = command.name.lower()
        if name in self._commands:
            logger.warning("Command '%s' already registered, overwriting", name)
        self._commands[name] = command
        for alias in command.aliases:
            self._aliases[alias.lower()] = name

    def get_command(self, name: str) -> "Command | None":
        name = name.lower()
        if name in self._commands:
            return self._commands[name]
        if name in self._aliases:
            return self._commands.get(self._aliases[name])
        return None

    def list_commands(self) -> list[Command]:
        return sorted(self._commands.values(), key=lambda c: c.name)

    # Reference order of the groups; anything else goes after, then "System".
    GROUP_ORDER = ("Stock research", "AI analysis", "Markets", "Portfolio", "Trading")

    def groups(self) -> dict[str, list[Command]]:
        """Commands by group, in registration order within a group."""
        out: dict[str, list[Command]] = {}
        for command in self._commands.values():
            out.setdefault(command.group, []).append(command)
        rank = {g: i for i, g in enumerate(self.GROUP_ORDER)}
        return dict(sorted(out.items(), key=lambda kv: (kv[0] == "System", rank.get(kv[0], len(rank)))))

    def _split(self, text: str) -> tuple[str, str]:
        stripped = text.strip()
        if not stripped:
            return "", ""
        parts = stripped.split(maxsplit=1)
        return parts[0], (parts[1] if len(parts) > 1 else "")

    def dispatch(self, message: IncomingMessage) -> CommandResult:
        text = (message.text or "").strip()
        if not text:
            return CommandResult(text="", success=True)

        if text.startswith(self.command_prefix):
            head, args = self._split(text[len(self.command_prefix) :])
        else:
            head, args = self._split(text)

        command = self.get_command(head) if head else None

        if command is None:
            # No recognized command word - if the message started with the
            # prefix, that's a genuine unknown-command; otherwise treat the
            # whole message as a free-form question for "ask", if present.
            if text.startswith(self.command_prefix) or "ask" not in self._commands:
                return CommandResult(
                    text=f"Unknown command. Try {self.command_prefix}help for a list of commands.",
                    success=False,
                )
            command = self._commands["ask"]
            args = text

        try:
            return command.handle(message, args)
        except Exception as exc:  # noqa: BLE001 - a command must never crash the listener
            logger.exception("Command '%s' failed", command.name)
            return CommandResult(text=f"Command failed: {exc}", success=False)
