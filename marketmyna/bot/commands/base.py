"""Command protocol every bot command implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import CommandResult, IncomingMessage


class Command(ABC):
    name: str = ""
    aliases: List[str] = []
    # Shown by /help, the web console's reference and its "/" menu.
    usage: str = ""  # "/quote SYMBOL [market]"
    description: str = ""  # one line, what it does
    group: str = "Other"  # heading in the reference (Research, Markets, ...)
    example: str = ""  # a runnable example, "/quote RELIANCE india"
    help_text: str = ""  # legacy one-liner; derived from usage + description when empty

    def help_line(self) -> str:
        if self.help_text:
            return self.help_text
        return f"{self.usage or '/' + self.name} - {self.description}".rstrip(" -")

    def describe(self) -> dict:
        return {"name": self.name, "aliases": list(self.aliases), "usage": self.usage or f"/{self.name}",
                "description": self.description or self.help_line(), "group": self.group,
                "example": self.example or self.usage or f"/{self.name}"}

    @abstractmethod
    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        """`args` is the raw text after the command word, unparsed - each
        command splits/validates it however it needs to."""
        ...
