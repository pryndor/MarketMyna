"""Real (not stubbed) inbound Telegram listener: long-polls getUpdates,
routes each message through a CommandDispatcher, replies via Telegram's
sendMessage - the one platform with genuine two-way bot support in this
phase. The 13 other notifier channels in marketmyna/notifiers/ remain outbound
(alert-push) only; each would need its own listener (webhook or poll,
depending on the platform) as separate follow-up work.

Reuses config.telegram_bot_token (the same credential marketmyna/notifiers/
telegram.py's outbound TelegramSender uses) rather than a new field.
Does NOT reuse TelegramSender itself for replies: that sender's chat_id
is fixed at construction (one configured alert destination), but a bot
must reply to whichever chat_id sent the incoming message, which can
differ - so this calls Telegram's sendMessage directly with the
per-message chat_id instead of force-fitting the wrong abstraction.

Same start()/stop()/is_running() shape as RuntimeSchedulerService
(marketmyna/services/runtime_scheduler.py) for consistency across the app's
background services.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

import requests

from .dispatcher import CommandDispatcher
from .models import IncomingMessage

logger = logging.getLogger(__name__)

API_ROOT = "https://api.telegram.org"
POLL_TIMEOUT_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = 35  # a bit more than the long-poll timeout itself
ERROR_BACKOFF_SECONDS = 5.0


IDLE_CHECK_SECONDS = 10.0  # how often to look for a newly saved token

SETUP_REPLY = (
    "👋 This is the MarketMyna bot.\n\n"
    "Your chat ID is {chat_id} - paste it into Settings → Notifications → Telegram → Chat ID."
)


def allowed_chats(config) -> set[str]:
    """Chats the bot obeys: Settings → Telegram → Chat ID (comma-separated for
    several, e.g. you and a group)."""
    raw = str(getattr(config, "telegram_chat_id", None) or "")
    return {c.strip() for c in raw.split(",") if c.strip()}


class TelegramListener:
    """Long-polls getUpdates and answers commands - only from the chats in
    Settings' Chat ID. Anyone else (and you, before a Chat ID is saved)
    just gets told their chat ID, so the bot can't be used by strangers
    who find its username.

    Reads the token from the shared Config on every poll, so saving a
    token in Settings takes effect without restarting the server."""

    def __init__(self, config, dispatcher: CommandDispatcher):
        self._config = config
        self._dispatcher = dispatcher
        self._last_update_id: Optional[int] = None
        self._token_in_use: Optional[str] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def _bot_token(self) -> Optional[str]:
        return getattr(self._config, "telegram_bot_token", None)

    def is_configured(self) -> bool:
        return bool(self._bot_token)

    # ---- lifecycle ----

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if not self.is_configured():
            logger.info("TelegramListener waiting: no telegram_bot_token yet (picked up once saved in Settings)")
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="marketmyna-telegram-listener", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- polling loop ----

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._bot_token:
                self._stop_event.wait(IDLE_CHECK_SECONDS)
                continue
            if self._bot_token != self._token_in_use:  # new or changed bot: start from its latest update
                self._token_in_use = self._bot_token
                self._last_update_id = None
                self._publish_commands()
            try:
                self._poll_once()
            except Exception:
                logger.exception("Telegram poll failed, backing off")
                self._stop_event.wait(ERROR_BACKOFF_SECONDS)

    def _poll_once(self) -> None:
        params = {"timeout": POLL_TIMEOUT_SECONDS}
        if self._last_update_id is not None:
            params["offset"] = self._last_update_id + 1

        resp = requests.get(
            f"{API_ROOT}/bot{self._bot_token}/getUpdates",
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            logger.warning("Telegram getUpdates returned ok=false: %s", payload)
            return

        for update in payload.get("result", []):
            update_id = update.get("update_id")
            if update_id is not None:
                self._last_update_id = update_id

            message = update.get("message")
            if not message or "text" not in message:
                continue  # edited_message/channel_post/non-text - skip, not an error

            self._handle_message(message)

    def _handle_message(self, message: dict) -> None:
        from marketmyna.core import tenant

        with tenant.system_scope():
            self._handle_message_scoped(message)

    def _command_scope(self, chat_id: str, is_owner: bool):
        """Commands run as the owner (only the owner's chats get this far)."""
        import contextlib

        from marketmyna.core import tenant
        from marketmyna.services.accounts import owner_scope

        if not tenant.enabled():
            return contextlib.nullcontext()
        return owner_scope(self._config)

    def _handle_message_scoped(self, message: dict) -> None:
        chat_id = str(message["chat"]["id"])
        text = message.get("text", "")
        word = text.strip().split(" ")[0].split("@")[0]

        is_owner = chat_id in allowed_chats(self._config)
        if not is_owner:
            # Not the owner's chat: never run commands, just explain how to connect.
            if word in ("/start", "/id", "/help") or not allowed_chats(self._config):
                self._reply(chat_id, SETUP_REPLY.format(chat_id=chat_id))
            else:
                logger.info("Ignored Telegram message from unauthorised chat %s", chat_id)
            return

        user = message.get("from") or {}
        incoming = IncomingMessage(
            platform="telegram",
            chat_id=chat_id,
            text=text,
            user_id=str(user["id"]) if "id" in user else None,
            raw=message,
        )
        if word in ("/start", "/id"):
            self._reply(chat_id, f"✅ Connected to MarketMyna. Chat ID {chat_id}.\nSend /help for commands.")
            return

        with self._command_scope(chat_id, is_owner):
            result = self._dispatcher.dispatch(incoming)
        if result.text:
            self._reply(chat_id, result.text)

    def _publish_commands(self) -> None:
        """Telegram's own "/" menu: the registered commands with their one-line descriptions."""
        commands = [{"command": c.name, "description": (c.description or c.help_line())[:256]}
                    for c in self._dispatcher.list_commands()][:100]
        try:
            requests.post(f"{API_ROOT}/bot{self._bot_token}/setMyCommands", json={"commands": commands},
                          timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException:
            logger.warning("Could not publish the Telegram command menu")

    def _reply(self, chat_id: str, text: str) -> None:
        for part in split_message(text):
            try:
                requests.post(
                    f"{API_ROOT}/bot{self._bot_token}/sendMessage",
                    json={"chat_id": chat_id, "text": part},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            except requests.RequestException:
                logger.exception("Failed to send Telegram reply to chat %s", chat_id)
                return


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Telegram caps a message at 4096 characters: split on line breaks."""
    parts, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        if current and len(current) + 1 + len(line) > limit:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts
