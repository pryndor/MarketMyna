"""Application configuration management."""

import json
import os
import typing
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Mapping, Optional

from src.core.home import app_home, db_filename


@dataclass
class Config:
    """Application configuration."""

    # Paths
    app_dir: Path = field(default_factory=lambda: app_home())
    data_dir: Path = field(default_factory=lambda: app_home() / "data")
    cache_dir: Path = field(default_factory=lambda: app_home() / "cache")

    # Database
    db_path: Path = field(default_factory=lambda: app_home() / db_filename(app_home()))
    # Multi-user accounts (src/services/accounts.py). The web API always turns
    # this on (api/middlewares/auth.py check_auth_config); it stays off for
    # CLI runs, which have one local user.
    # ADMIN_EMAIL: the account with this email gets the admin role.
    # APP_BASE_URL: where email links (verify, reset) point.
    # SECRET_KEY: encrypts users' own AI keys; without it a key file is
    # generated under app_dir (fine locally, set it on a server).
    accounts_enabled: bool = False
    admin_email: Optional[str] = None
    app_base_url: Optional[str] = None
    secret_key: Optional[str] = None
    # Shown on public pages and in account emails.
    support_email: Optional[str] = ""
    # Live NSE prices from Angel One SmartAPI (src/services/brokers/angel.py):
    # app API key, client code, login PIN and the TOTP secret (base32).
    angel_api_key: Optional[str] = None
    angel_client_code: Optional[str] = None
    angel_pin: Optional[str] = None
    angel_totp_secret: Optional[str] = None
    # Real-time US prices from Finnhub (src/services/brokers/finnhub.py).
    finnhub_api_key: Optional[str] = None
    # Social sentiment (src/data/social/): Reddit API app keys are optional -
    # without them Reddit is scraped with Playwright. social_reddit_mode:
    # auto (API when keys set, else scraping) | api | playwright.
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None
    reddit_user_agent: Optional[str] = None
    social_reddit_mode: str = "auto"
    social_playwright: bool = True

    # Backup price sources when Yahoo fails (src/data/extra_sources.py);
    # all optional, free tiers. Twelve Data also covers NSE / BSE.
    alpha_vantage_key: Optional[str] = None
    polygon_key: Optional[str] = None
    twelvedata_api_key: Optional[str] = None
    tiingo_api_key: Optional[str] = None
    coingecko_api_key: Optional[str] = None  # optional "demo" key: higher rate limit

    # Notification channels (all optional; a channel is used only when its
    # required fields are set - see src/notifiers/*.py for what each needs)
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    slack_webhook_url: Optional[str] = None
    email_sender: Optional[str] = None
    # SMTP login when it differs from the sender, e.g. Gmail "Send mail as":
    # log in as the Gmail address, send as support@ / reports@ (verified aliases).
    email_username: Optional[str] = None
    # From address of scheduled reports and alerts; blank = email_sender.
    email_reports_sender: Optional[str] = None
    email_password: Optional[str] = None
    email_receivers: Optional[list] = None
    email_smtp_server: Optional[str] = None
    email_smtp_port: Optional[int] = None
    email_smtp_ssl: Optional[bool] = None
    dingtalk_webhook_url: Optional[str] = None
    dingtalk_secret: Optional[str] = None
    feishu_webhook_url: Optional[str] = None
    feishu_webhook_secret: Optional[str] = None
    wechat_webhook_url: Optional[str] = None
    pushover_user_key: Optional[str] = None
    pushover_api_token: Optional[str] = None
    ntfy_url: Optional[str] = None
    ntfy_token: Optional[str] = None
    gotify_url: Optional[str] = None
    gotify_token: Optional[str] = None
    pushplus_token: Optional[str] = None
    pushplus_topic: Optional[str] = None
    serverchan3_sendkey: Optional[str] = None
    astrbot_url: Optional[str] = None
    astrbot_token: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_headers: Optional[str] = None
    telegram_message_thread_id: Optional[str] = None
    teams_webhook_url: Optional[str] = None
    google_chat_webhook_url: Optional[str] = None
    matrix_homeserver: Optional[str] = None
    matrix_access_token: Optional[str] = None
    matrix_room_id: Optional[str] = None
    whatsapp_phone: Optional[str] = None
    whatsapp_callmebot_apikey: Optional[str] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from: Optional[str] = None
    twilio_to: Optional[list] = None
    bark_url: Optional[str] = None
    pushbullet_token: Optional[str] = None
    signal_api_url: Optional[str] = None
    signal_number: Optional[str] = None
    signal_recipients: Optional[list] = None
    apprise_urls: Optional[list] = None
    web_push_vapid_private_key: Optional[str] = None
    web_push_contact: Optional[str] = None
    # Which channels get which kind of message (empty = every configured
    # channel). Env names match daily_stock_analysis.
    notification_report_channels: Optional[list] = None
    notification_alert_channels: Optional[list] = None
    notification_system_error_channels: Optional[list] = None

    # LLM backend (see src/llm/*.py). llm_model uses litellm's own model-
    # string convention so one field covers cloud providers and local
    # Ollama alike, e.g. "gpt-4o-mini", "claude-3-5-sonnet-20241022",
    # "ollama/qwen3:8b" (with llm_api_base pointed at the local server).
    llm_backend: Optional[str] = "litellm"
    llm_model: Optional[str] = None
    llm_api_base: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_timeout_seconds: Optional[float] = 60.0
    llm_max_tokens: Optional[int] = 2048
    llm_temperature: Optional[float] = 0.7
    # Failover (src/llm/channels.py): extra keys rotated for llm_model,
    # models tried when it fails, and named channels whose settings come
    # from LLM_<NAME>_* environment variables.
    llm_api_keys: Optional[list] = None
    llm_fallback_models: Optional[list] = None
    llm_channels: Optional[list] = None
    # Bring-your-own keys per provider (env: GEMINI_API_KEY, GROQ_API_KEY,
    # ...). Any route whose model belongs to that provider uses its key.
    # llm_fast_model: optional cheaper/faster "level 1" model for simple
    # jobs (commentary, news tone, translation); decisions use llm_model.
    # llm_cache_hours: reuse identical AI answers this long (0 = off).
    gemini_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    mistral_api_key: Optional[str] = None
    cerebras_api_key: Optional[str] = None
    nvidia_api_key: Optional[str] = None
    ollama_base_url: Optional[str] = None
    openai_base_url: Optional[str] = None
    llm_fast_model: Optional[str] = None
    llm_cache_hours: Optional[float] = None

    # Scheduled reports: stocks analysed in parallel (None = up to 4 by CPU count).
    scheduler_workers: Optional[int] = None

    # UI Settings
    theme: str = "dark"
    window_width: int = 1400
    window_height: int = 900

    # Data Settings
    cache_expiry_minutes: int = 15
    default_market: str = "US"

    def __post_init__(self):
        """Create necessary directories."""
        self._env_fields: set[str] = set()
        self._plaintext_secrets = False
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "Config":
        """Load configuration from file."""
        if config_path is None:
            config_path = app_home() / "config.json"

        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            # An older file may hold null for a field that now has a default,
            # or settings this build no longer has: skip those.
            known = {f.name for f in fields(cls)}
            data = {k: v for k, v in data.items() if k in known and not (k == "support_email" and v in (None, ""))}
            config = cls(**data).apply_env()
        else:
            config = cls().apply_env()
        # Secrets are stored encrypted (src/core/secret_store.py); decrypt in memory.
        from .secret_store import decrypt_config

        config._plaintext_secrets = decrypt_config(config)
        return config

    def apply_env(self, environ: Optional[Mapping[str, str]] = None) -> "Config":
        """Override fields from environment variables named after them in
        upper case (TELEGRAM_BOT_TOKEN, LLM_MODEL, EMAIL_RECEIVERS, ...).

        This is how headless runs (cron, GitHub Actions) are
        configured: secrets arrive as env vars and no config.json exists.
        Empty values are ignored, so an unset variable passed through as
        "" never blanks a saved setting.
        """
        environ = os.environ if environ is None else environ
        for f in fields(self):
            raw = environ.get(f.name.upper())
            if raw is None or raw.strip() == "":
                continue
            try:
                setattr(self, f.name, _coerce(f.type, raw.strip()))
            except ValueError as exc:
                raise ValueError(f"Environment variable {f.name.upper()}: {exc}") from exc
            self._env_fields.add(f.name)
        return self

    def save(self, config_path: Optional[Path] = None) -> None:
        """Save configuration to file."""
        if config_path is None:
            config_path = self.app_dir / "config.json"

        # Values that came from environment variables (often secrets) are
        # never written to disk; the file keeps whatever it had before.
        previous: dict = {}
        env_fields = getattr(self, "_env_fields", set())
        if env_fields and config_path.exists():
            try:
                previous = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                previous = {}

        data = {
            "theme": self.theme,
            "window_width": self.window_width,
            "window_height": self.window_height,
            "cache_expiry_minutes": self.cache_expiry_minutes,
            "default_market": self.default_market,
            "alpha_vantage_key": self.alpha_vantage_key,
            "polygon_key": self.polygon_key,
            "twelvedata_api_key": self.twelvedata_api_key,
            "tiingo_api_key": self.tiingo_api_key,
            "coingecko_api_key": self.coingecko_api_key,
            "telegram_bot_token": self.telegram_bot_token,
            "telegram_chat_id": self.telegram_chat_id,
            "discord_webhook_url": self.discord_webhook_url,
            "slack_webhook_url": self.slack_webhook_url,
            "email_sender": self.email_sender,
            "email_username": self.email_username,
            "email_reports_sender": self.email_reports_sender,
            "email_password": self.email_password,
            "email_receivers": self.email_receivers,
            "email_smtp_server": self.email_smtp_server,
            "email_smtp_port": self.email_smtp_port,
            "email_smtp_ssl": self.email_smtp_ssl,
            "dingtalk_webhook_url": self.dingtalk_webhook_url,
            "dingtalk_secret": self.dingtalk_secret,
            "feishu_webhook_url": self.feishu_webhook_url,
            "feishu_webhook_secret": self.feishu_webhook_secret,
            "wechat_webhook_url": self.wechat_webhook_url,
            "pushover_user_key": self.pushover_user_key,
            "pushover_api_token": self.pushover_api_token,
            "ntfy_url": self.ntfy_url,
            "ntfy_token": self.ntfy_token,
            "gotify_url": self.gotify_url,
            "gotify_token": self.gotify_token,
            "pushplus_token": self.pushplus_token,
            "pushplus_topic": self.pushplus_topic,
            "serverchan3_sendkey": self.serverchan3_sendkey,
            "astrbot_url": self.astrbot_url,
            "astrbot_token": self.astrbot_token,
            "webhook_url": self.webhook_url,
            "webhook_headers": self.webhook_headers,
            "telegram_message_thread_id": self.telegram_message_thread_id,
            "teams_webhook_url": self.teams_webhook_url,
            "google_chat_webhook_url": self.google_chat_webhook_url,
            "matrix_homeserver": self.matrix_homeserver,
            "matrix_access_token": self.matrix_access_token,
            "matrix_room_id": self.matrix_room_id,
            "whatsapp_phone": self.whatsapp_phone,
            "whatsapp_callmebot_apikey": self.whatsapp_callmebot_apikey,
            "twilio_account_sid": self.twilio_account_sid,
            "twilio_auth_token": self.twilio_auth_token,
            "twilio_from": self.twilio_from,
            "twilio_to": self.twilio_to,
            "bark_url": self.bark_url,
            "pushbullet_token": self.pushbullet_token,
            "signal_api_url": self.signal_api_url,
            "signal_number": self.signal_number,
            "signal_recipients": self.signal_recipients,
            "apprise_urls": self.apprise_urls,
            "web_push_vapid_private_key": self.web_push_vapid_private_key,
            "web_push_contact": self.web_push_contact,
            "notification_report_channels": self.notification_report_channels,
            "notification_alert_channels": self.notification_alert_channels,
            "notification_system_error_channels": self.notification_system_error_channels,
            "llm_backend": self.llm_backend,
            "llm_model": self.llm_model,
            "llm_api_base": self.llm_api_base,
            "llm_api_key": self.llm_api_key,
            "llm_timeout_seconds": self.llm_timeout_seconds,
            "llm_max_tokens": self.llm_max_tokens,
            "llm_temperature": self.llm_temperature,
            "llm_api_keys": self.llm_api_keys,
            "llm_fallback_models": self.llm_fallback_models,
            "llm_channels": self.llm_channels,
            "gemini_api_key": self.gemini_api_key,
            "groq_api_key": self.groq_api_key,
            "openrouter_api_key": self.openrouter_api_key,
            "openai_api_key": self.openai_api_key,
            "anthropic_api_key": self.anthropic_api_key,
            "deepseek_api_key": self.deepseek_api_key,
            "mistral_api_key": self.mistral_api_key,
            "cerebras_api_key": self.cerebras_api_key,
            "nvidia_api_key": self.nvidia_api_key,
            "ollama_base_url": self.ollama_base_url,
            "openai_base_url": self.openai_base_url,
            "llm_fast_model": self.llm_fast_model,
            "llm_cache_hours": self.llm_cache_hours,
            "scheduler_workers": self.scheduler_workers,
            "app_base_url": self.app_base_url,
            "support_email": self.support_email,
            "angel_api_key": self.angel_api_key,
            "angel_client_code": self.angel_client_code,
            "angel_pin": self.angel_pin,
            "angel_totp_secret": self.angel_totp_secret,
            "finnhub_api_key": self.finnhub_api_key,
            "reddit_client_id": self.reddit_client_id,
            "reddit_client_secret": self.reddit_client_secret,
            "reddit_user_agent": self.reddit_user_agent,
            "social_reddit_mode": self.social_reddit_mode,
            "social_playwright": self.social_playwright,
        }
        for name in env_fields:
            if name in data:
                if name in previous:
                    data[name] = previous[name]
                else:
                    data.pop(name)

        # Keys, tokens and passwords go to disk encrypted.
        from .secret_store import encrypt_fields

        data = encrypt_fields(data, self.app_dir, getattr(self, "secret_key", None))
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        try:
            config_path.chmod(0o600)  # owner-only, like the key file
        except OSError:
            pass
        self._plaintext_secrets = False


def _coerce(annotation, raw: str):
    """Env var text -> the field's declared type (Optional[...] unwrapped)."""
    if typing.get_origin(annotation) is typing.Union:
        annotation = next(a for a in typing.get_args(annotation) if a is not type(None))
    if annotation is bool:
        lowered = raw.lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"expected true/false, got {raw!r}")
    if annotation is int:
        return int(raw)
    if annotation is float:
        return float(raw)
    if annotation is list or typing.get_origin(annotation) is list:
        return [part.strip() for part in raw.split(",") if part.strip()]
    if annotation is Path:
        return Path(raw).expanduser()
    return raw
