"""Shared field schema for notification-channel settings.

Single source of truth for which Config attributes exist per channel and
what kind of value each one holds. The HTTP system-config endpoint
(marketmyna/api/v1/endpoints/system_config.py) reads CHANNELS from here.
"""

from __future__ import annotations

# (attr on Config, label, field kind) per channel.
# kind: "text" | "password" | "int" | "bool" | "list" | "multiline"
CHANNELS = [
    ("Telegram", [
        ("telegram_bot_token", "Bot token", "password"),
        ("telegram_chat_id", "Chat ID (send /start to your bot to get it; comma-separate several)", "text"),
        ("telegram_message_thread_id", "Topic ID (optional, for forum groups)", "text"),
    ]),
    ("WhatsApp", [
        ("whatsapp_phone", "Your WhatsApp number with country code (e.g. +919876543210)", "text"),
        ("whatsapp_callmebot_apikey", "CallMeBot API key (message +34 644 51 95 23 'I allow callmebot to send me messages')", "password"),
    ]),
    ("Twilio SMS/WhatsApp", [
        ("twilio_account_sid", "Account SID", "text"),
        ("twilio_auth_token", "Auth token", "password"),
        ("twilio_from", "From number (e.g. +15551234567, or whatsapp:+14155238886)", "text"),
        ("twilio_to", "To numbers (comma-separated; prefix whatsapp: for WhatsApp)", "list"),
    ]),
    ("Discord", [
        ("discord_webhook_url", "Webhook URL", "text"),
    ]),
    ("Slack", [
        ("slack_webhook_url", "Webhook URL", "text"),
    ]),
    ("Email", [
        ("email_sender", "Sender address", "text"),
        ("email_reports_sender", "Reports & alerts sender", "text"),
        ("email_username", "SMTP username", "text"),
        ("email_password", "Password / app password", "password"),
        ("email_receivers", "Recipients (comma-separated)", "list"),
        ("email_smtp_server", "SMTP server (blank = auto-detect)", "text"),
        ("email_smtp_port", "SMTP port (blank = auto-detect)", "int"),
        ("email_smtp_ssl", "Force SSL (unchecked = auto-detect)", "bool"),
    ]),
    ("DingTalk", [
        ("dingtalk_webhook_url", "Webhook URL", "text"),
        ("dingtalk_secret", "Secret (optional signing)", "password"),
    ]),
    ("Feishu", [
        ("feishu_webhook_url", "Webhook URL", "text"),
        ("feishu_webhook_secret", "Secret (optional signing)", "password"),
    ]),
    ("WeChat", [
        ("wechat_webhook_url", "Group robot webhook URL", "text"),
    ]),
    ("Pushover", [
        ("pushover_user_key", "User key", "text"),
        ("pushover_api_token", "API token", "password"),
    ]),
    ("ntfy", [
        ("ntfy_url", "Topic URL (e.g. https://ntfy.sh/mytopic)", "text"),
        ("ntfy_token", "Access token (optional)", "password"),
    ]),
    ("Gotify", [
        ("gotify_url", "Server URL", "text"),
        ("gotify_token", "App token", "password"),
    ]),
    ("PushPlus", [
        ("pushplus_token", "Token", "password"),
        ("pushplus_topic", "Topic (optional, for group push)", "text"),
    ]),
    ("ServerChan3", [
        ("serverchan3_sendkey", "SendKey", "password"),
    ]),
    ("AstrBot", [
        ("astrbot_url", "Instance URL", "text"),
        ("astrbot_token", "Token (optional)", "password"),
    ]),
    ("Microsoft Teams", [
        ("teams_webhook_url", "Workflows webhook URL (Teams channel > Workflows > 'Post to a channel when a webhook request is received')", "text"),
    ]),
    ("Google Chat", [
        ("google_chat_webhook_url", "Space webhook URL (Space > Apps & integrations > Webhooks)", "text"),
    ]),
    ("Matrix", [
        ("matrix_homeserver", "Homeserver URL (e.g. https://matrix.org)", "text"),
        ("matrix_access_token", "Access token", "password"),
        ("matrix_room_id", "Room ID (e.g. !abc123:matrix.org)", "text"),
    ]),
    ("Signal", [
        ("signal_api_url", "signal-cli REST API URL (e.g. http://localhost:8080)", "text"),
        ("signal_number", "Sending number linked to signal-cli (e.g. +919876543210)", "text"),
        ("signal_recipients", "Recipients (comma-separated numbers or group IDs)", "list"),
    ]),
    ("Bark (iOS)", [
        ("bark_url", "Device URL from the Bark app (e.g. https://api.day.app/yourkey)", "password"),
    ]),
    ("Pushbullet", [
        ("pushbullet_token", "Access token", "password"),
    ]),
    ("Apprise", [
        ("apprise_urls", "Apprise URLs for 100+ other services (comma-separated; needs 'pip install apprise')", "list"),
    ]),
    ("Webhook", [
        ("webhook_url", "URL", "text"),
        ("webhook_headers", 'Extra headers (JSON, e.g. {"Authorization": "Bearer x"})', "multiline"),
    ]),
]


def iter_fields():
    """Yield (channel_name, attr, label, kind) for every field across all channels."""
    for channel_name, fields in CHANNELS:
        for attr, label, kind in fields:
            yield channel_name, attr, label, kind


def is_secret_kind(kind: str) -> bool:
    """Whether a field's raw value should never be echoed back (e.g. over HTTP)."""
    return kind in ("password", "secret_list")
