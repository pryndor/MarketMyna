"""/ask <question> - a single LLM call for a free-form question, not the
full agent pipeline (no tool use, no multi-turn memory in this phase).

"/research" is registered as an alias here rather than a distinct
command: a real deep-research capability (multi-step, tool-using, like
daily_stock_analysis's own research agent) is real extra scope this
phase doesn't build. Aliasing it to /ask is an honest "this exists but
is shallower than the name implies", not a silent stand-in for
something it isn't.
"""

from __future__ import annotations

from ...llm.backend_factory import create_generation_backend
from ...llm.protocol import GenerationConfig
from ..models import CommandResult, IncomingMessage
from .base import Command

SYSTEM_PROMPT = (
    "You are a stock research assistant embedded in a chat bot. Answer the "
    "user's question concisely (a few sentences). You have no live tool "
    "access in this mode - if the question needs a live quote or a full "
    "technical/risk analysis, say so and suggest /analyze SYMBOL instead "
    "of guessing at numbers you don't have."
)


class AskCommand(Command):
    name = "ask"
    aliases = ["research", "r"]
    usage = "/ask QUESTION"
    description = "Free-form question to the AI model (no live data)."
    group = "AI analysis"
    example = "/ask What does a falling RSI mean?"
    help_text = "/ask <question> - ask a free-form question (also: /research, shallower than a full deep-research pass)"

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        question = args.strip()
        if not question:
            return CommandResult(text=f"Usage: {self.help_text}", success=False)

        try:
            backend = create_generation_backend(self._config, tier="fast")
            result = backend.generate(question, GenerationConfig(), system_prompt=SYSTEM_PROMPT)
        except Exception as exc:
            return CommandResult(text=f"Couldn't get an answer: {exc}", success=False)

        return CommandResult(text=result.text.strip())
