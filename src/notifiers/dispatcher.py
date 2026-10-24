"""Fan-out dispatcher that sends a message to every configured channel."""

from __future__ import annotations

from typing import Optional

from .astrbot import AstrbotSender
from .base import logger
from .dingtalk import DingtalkSender
from .discord import DiscordSender
from .email import EmailSender
from .feishu import FeishuSender
from .gotify import GotifySender
from .ntfy import NtfySender
from .pushover import PushoverSender
from .pushplus import PushplusSender
from .serverchan3 import Serverchan3Sender
from .slack import SlackSender
from .telegram import TelegramSender
from .webhook import WebhookSender
from .wechat import WechatSender
from .apprise_sender import AppriseSender
from .bark import BarkSender
from .googlechat import GoogleChatSender
from .matrix import MatrixSender
from .pushbullet import PushbulletSender
from .signal_messenger import SignalSender
from .teams import TeamsSender
from .twilio import TwilioSender
from .webpush import WebPushSender
from .whatsapp import WhatsAppSender


# Message purposes and the Config field that routes each one.
PURPOSES = {
    "report": "notification_report_channels",
    "alert": "notification_alert_channels",
    "system_error": "notification_system_error_channels",
}


class NotificationDispatcher:
    """Owns one instance of every sender and fans a message out to all configured ones."""

    def __init__(self, config):
        self._config = config
        self._senders = {
            "telegram": TelegramSender(config),
            "discord": DiscordSender(config),
            "slack": SlackSender(config),
            "email": EmailSender(config),
            "dingtalk": DingtalkSender(config),
            "feishu": FeishuSender(config),
            "wechat": WechatSender(config),
            "pushover": PushoverSender(config),
            "ntfy": NtfySender(config),
            "gotify": GotifySender(config),
            "pushplus": PushplusSender(config),
            "serverchan3": Serverchan3Sender(config),
            "astrbot": AstrbotSender(config),
            "webhook": WebhookSender(config),
            "webpush": WebPushSender(config),
            "whatsapp": WhatsAppSender(config),
            "twilio": TwilioSender(config),
            "teams": TeamsSender(config),
            "googlechat": GoogleChatSender(config),
            "matrix": MatrixSender(config),
            "signal": SignalSender(config),
            "bark": BarkSender(config),
            "pushbullet": PushbulletSender(config),
            "apprise": AppriseSender(config),
        }

    def channel_names(self) -> list[str]:
        return list(self._senders)

    def configured_channels(self, purpose: Optional[str] = None) -> list[str]:
        """Configured channels, narrowed to the ones routed for `purpose`
        ("report", "alert", "system_error") when a route is set."""
        configured = [name for name, sender in self._senders.items() if sender.is_configured()]
        route = getattr(self._config, PURPOSES[purpose], None) if purpose in PURPOSES else None
        if route:
            wanted = {str(name).strip().lower() for name in route}
            configured = [name for name in configured if name in wanted]
        return configured

    # In accounts mode a normal user's messages may only reach their own
    # devices: web push (subscriptions are user-scoped) and their linked
    # Telegram chats. The owner's channels in config.json are the owner's.
    USER_CHANNELS = ("webpush",)

    def _owner_channels_allowed(self) -> bool:
        from ..services.accounts import is_owner_scope

        try:
            return is_owner_scope(self._config)
        except Exception:
            logger.exception("Could not resolve the platform owner; using user channels only")
            return False

    def _sender_for(self, name: str, purpose: Optional[str]):
        """The channel's sender; reports and alerts by email come from the reports address."""
        from ..services.accounts import report_sender

        from_address = report_sender(self._config, purpose) if name == "email" else None
        return EmailSender(self._config, from_address=from_address) if from_address else self._senders.get(name)

    def send_all(self, message: str, title: Optional[str] = None, purpose: Optional[str] = None) -> dict[str, bool]:
        results: dict[str, bool] = {}
        if purpose == "system_error" or self._owner_channels_allowed():  # system errors are for the owner
            allowed = set(self.configured_channels(purpose))
        else:
            allowed = {n for n in self.USER_CHANNELS if self._senders[n].is_configured()}
        for name, sender in self._senders.items():
            if name not in allowed:
                continue
            sender = self._sender_for(name, purpose)
            try:
                results[name] = bool(sender.send(message, title=title))
            except Exception as exc:  # a channel must never take the others down with it
                logger.error("Notifier %s raised unexpectedly: %s", name, exc)
                results[name] = False
        return results

    def send_each(self, messages: dict[str, tuple], purpose: Optional[str] = None,
                  files: Optional[dict[str, list[tuple[str, bytes]]]] = None) -> dict[str, bool]:
        """Send each channel its own (title, message[, html]) - e.g. the same
        report in the language that channel's reader prefers. The optional
        html body is only used by email. files: "email" / "telegram" ->
        (filename, bytes) pairs, attached to the email and sent as Telegram
        documents. Unknown or unconfigured channels are skipped."""
        files = files or {}
        results: dict[str, bool] = {}
        owner = self._owner_channels_allowed()
        for name, payload in messages.items():
            title, message = payload[0], payload[1]
            html = payload[2] if len(payload) > 2 else None
            sender = self._sender_for(name, purpose)
            if sender is None or not sender.is_configured():
                continue
            if not owner and name not in self.USER_CHANNELS:
                continue
            try:
                if name == "email" and (html or files.get("email")):
                    results[name] = bool(sender.send(message, title=title, html=html, attachments=files.get("email")))
                else:
                    results[name] = bool(sender.send(message, title=title))
                if name == "telegram" and results[name]:
                    for filename, data in files.get("telegram") or []:
                        results[name] = sender.send_document(filename, data) and results[name]
            except Exception as exc:
                logger.error("Notifier %s raised unexpectedly: %s", name, exc)
                results[name] = False
        return results
