"""/help - lists every registered command.

Needs a reference to the dispatcher's registry, which creates an
ordering requirement rather than a real circular-construction problem:
register every other command first, then construct and register
HelpCommand(dispatcher) last - by then the dispatcher already holds
every other command, and HelpCommand just reads from it at call time
(not at construction time), so it also correctly lists itself.
"""

from __future__ import annotations

from ..models import CommandResult, IncomingMessage
from .base import Command


class HelpCommand(Command):
    name = "help"
    aliases = ["h", "?"]
    usage = "/help"
    description = "List every command."
    group = "System"
    example = "/help"
    help_text = "/help - list available commands"

    def __init__(self, dispatcher):
        self._dispatcher = dispatcher

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        want = args.strip().lstrip("/").lower()
        if want:
            command = self._dispatcher.get_command(want)
            if command is None:
                return CommandResult(text=f"No command '{want}'. /help lists them.", success=False)
            d = command.describe()
            aliases = f"\nAlso: {', '.join('/' + a for a in d['aliases'])}" if d["aliases"] else ""
            return CommandResult(text=f"{d['usage']}\n{d['description']}\nExample: {d['example']}{aliases}")
        lines = []
        for group, commands in self._dispatcher.groups().items():
            lines.append(f"\n{group}" if lines else group)
            lines += [f"  {c.usage or '/' + c.name} - {c.description or c.help_line()}" for c in commands]
        lines.append("\n/help COMMAND for details and an example.")
        return CommandResult(text="\n".join(lines))
