"""Platform-agnostic message shapes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class IncomingMessage:
    """One message from any platform, normalized to the same shape
    before it reaches CommandDispatcher."""

    platform: str
    chat_id: str
    text: str
    user_id: Optional[str] = None
    raw: Any = None


@dataclass
class CommandResult:
    """A command's response - plain text, no platform-specific
    formatting (markdown/embeds/etc are each listener's own concern)."""

    text: str
    success: bool = True
