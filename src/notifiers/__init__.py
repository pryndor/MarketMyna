"""Notification channel senders and dispatcher."""

from .astrbot import AstrbotSender
from .dingtalk import DingtalkSender
from .discord import DiscordSender
from .dispatcher import NotificationDispatcher
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

__all__ = [
    "AstrbotSender",
    "DingtalkSender",
    "DiscordSender",
    "EmailSender",
    "FeishuSender",
    "GotifySender",
    "NotificationDispatcher",
    "NtfySender",
    "PushoverSender",
    "PushplusSender",
    "Serverchan3Sender",
    "SlackSender",
    "TelegramSender",
    "WebhookSender",
    "WechatSender",
]
