"""Encryption at rest for the secrets kept in config.json.

API keys, tokens, passwords and webhook URLs (they embed tokens) are written
as "enc:v1:<base64>" (AES-256-GCM, random nonce per value) and decrypted in
memory when the config loads. Older plain-text values still load and are
encrypted on the next save.

The key comes from SECRET_KEY (set it on servers and keep a copy) or, when
unset, from a random secret.key file created once in the app folder with
owner-only permissions. Values set through environment variables are never
written to the file at all (see Config.save).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"

# Every config field holding something that grants access to an account.
SECRET_FIELDS = frozenset({
    # AI providers
    "llm_api_key", "llm_api_keys", "gemini_api_key", "groq_api_key", "openrouter_api_key", "openai_api_key",
    "anthropic_api_key", "deepseek_api_key", "mistral_api_key", "cerebras_api_key", "nvidia_api_key",
    # Market data / brokers
    "alpha_vantage_key", "polygon_key", "twelvedata_api_key", "tiingo_api_key", "coingecko_api_key", "finnhub_api_key", "reddit_client_secret", "angel_api_key", "angel_pin", "angel_totp_secret",
    # Notification channels (tokens, passwords, and webhook URLs that embed tokens)
    "telegram_bot_token", "email_password", "discord_webhook_url", "slack_webhook_url", "dingtalk_webhook_url",
    "dingtalk_secret", "feishu_webhook_url", "feishu_webhook_secret", "wechat_webhook_url", "pushover_user_key",
    "pushover_api_token", "ntfy_token", "gotify_token", "pushplus_token", "serverchan3_sendkey", "astrbot_token",
    "webhook_url", "webhook_headers", "teams_webhook_url", "google_chat_webhook_url", "matrix_access_token",
    "whatsapp_callmebot_apikey", "twilio_auth_token", "bark_url", "pushbullet_token", "apprise_urls",
    "web_push_vapid_private_key",
})


def _key(app_dir: Path, secret_key: Optional[str]) -> bytes:
    secret = secret_key
    if not secret:
        path = Path(app_dir) / "secret.key"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            path.chmod(0o600)
        secret = path.read_text(encoding="utf-8").strip()
    return hashlib.sha256(b"marketmyna-config-v1:" + secret.encode()).digest()


def is_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(value: Any, app_dir: Path, secret_key: Optional[str]) -> Any:
    """Encrypt one value (str or list); None and already-encrypted pass through."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if value is None or value == "" or value == [] or is_encrypted(value):
        return value
    nonce = os.urandom(12)
    blob = AESGCM(_key(app_dir, secret_key)).encrypt(nonce, json.dumps(value).encode(), b"config")
    return PREFIX + base64.urlsafe_b64encode(nonce + blob).decode()


def decrypt(value: Any, app_dir: Path, secret_key: Optional[str]) -> Any:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not is_encrypted(value):
        return value
    raw = base64.urlsafe_b64decode(value[len(PREFIX):].encode())
    return json.loads(AESGCM(_key(app_dir, secret_key)).decrypt(raw[:12], raw[12:], b"config").decode())


def encrypt_fields(data: dict, app_dir: Path, secret_key: Optional[str]) -> dict:
    return {k: encrypt(v, app_dir, secret_key) if k in SECRET_FIELDS else v for k, v in data.items()}


def decrypt_config(config) -> bool:
    """Decrypt secret fields in place. Returns True when a plain-text secret
    was found (the caller saves once to encrypt it)."""
    plain = False
    for name in SECRET_FIELDS:
        value = getattr(config, name, None)
        if value in (None, "", []):
            continue
        if not is_encrypted(value):
            if name not in getattr(config, "_env_fields", set()):
                plain = True
            continue
        try:
            setattr(config, name, decrypt(value, config.app_dir, getattr(config, "secret_key", None)))
        except Exception:
            # Wrong or lost key: drop the value rather than use garbage.
            logger.error("Could not decrypt %s from config.json (SECRET_KEY changed?); it is ignored.", name)
            setattr(config, name, None)
    return plain
