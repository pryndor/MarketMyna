"""Platform-agnostic bot-command endpoint: exercises the same
CommandDispatcher a real chat platform listener uses, without needing
any chat platform at all - the web app's Bot console, or curl.

Open to every signed-in user: the auth middleware scopes each request to
its user, so /portfolio, /alerts and the rest see only their own rows, and
the AI commands go through the same plan quota as the Analyze page - the
same as a linked Telegram chat."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from marketmyna.api.deps import get_bot_dispatcher
from marketmyna.bot.models import IncomingMessage

router = APIRouter()


class BotCommandRequest(BaseModel):
    text: str
    platform: str = "http"
    chat_id: str = "http"


@router.post("/bot/command")
def run_bot_command(body: BotCommandRequest, dispatcher=Depends(get_bot_dispatcher)) -> dict:
    message = IncomingMessage(platform=body.platform, chat_id=body.chat_id, text=body.text)
    result = dispatcher.dispatch(message)
    return {"text": result.text, "success": result.success}


@router.get("/bot/commands")
def list_bot_commands(dispatcher=Depends(get_bot_dispatcher)) -> list[dict]:
    """Every registered command with usage, description, group and an example
    (the console's reference panel and "/" menu)."""
    return [{**c.describe(), "group": group} for group, commands in dispatcher.groups().items() for c in commands]
