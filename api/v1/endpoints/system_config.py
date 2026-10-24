"""Notification-channel settings over HTTP - an API face on the existing
src/notifiers system. Field list/kinds come from
src/notifiers/settings_schema.py, the single source of truth. AI keys are
under /api/auth/account/api-keys; data-source keys in data_sources.py.
"""

from __future__ import annotations

import dataclasses
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, create_model

from api.deps import get_config_dep
from api.middlewares.auth import require_admin
from src.notifiers.dispatcher import NotificationDispatcher
from src.notifiers.settings_schema import CHANNELS, is_secret_kind, iter_fields

router = APIRouter()

# kind -> the HTTP-facing Python type for that field. List fields are taken
# as a native JSON array here (not a comma-string - HTTP payloads are
# natively structured, so there's no reason to make the client stuff a list
# into one string).
_KIND_TYPES = {
    "text": Optional[str],
    "password": Optional[str],
    "multiline": Optional[str],
    "int": Optional[int],
    "float": Optional[float],
    "bool": Optional[bool],
    "list": Optional[List[str]],
    "secret_list": Optional[List[str]],  # list of secrets, never echoed back
}

# One flat pydantic model covering every channel attr, built from the same
# CHANNELS list the dialog uses, so the two surfaces can't drift apart.
NotificationSettingsUpdate = create_model(
    "NotificationSettingsUpdate",
    **{
        attr: (_KIND_TYPES[kind], Field(default=None))
        for _channel, attr, _label, kind in iter_fields()
    },
)



def _check_telegram_ids(overrides: dict, config) -> None:
    """The commonest Telegram mistake: pasting the bot's own number (the part
    of the token before ':') as the Chat ID. Bots can't message themselves."""
    token = overrides.get("telegram_bot_token") or getattr(config, "telegram_bot_token", None) or ""
    chat_ids = overrides.get("telegram_chat_id", getattr(config, "telegram_chat_id", None)) or ""
    bot_number = str(token).split(":")[0]
    if bot_number and bot_number in [c.strip() for c in str(chat_ids).split(",")]:
        raise HTTPException(
            status_code=400,
            detail=(f"Chat ID {bot_number} is your bot's own number (from the token), not your chat. "
                    "Open your bot in Telegram, send /start, and paste the chat ID it replies with."),
        )


@router.get("/system-config/notifications", dependencies=[Depends(require_admin)])
def get_notification_settings(config=Depends(get_config_dep)) -> dict[str, Any]:
    """Current notification config, grouped by channel. Secret fields are
    reported as {"is_set": bool}, never as their raw value."""
    result: dict[str, dict[str, Any]] = {}
    for channel_name, fields in CHANNELS:
        channel_out: dict[str, Any] = {}
        for attr, _label, kind in fields:
            value = getattr(config, attr, None)
            if is_secret_kind(kind):
                channel_out[attr] = {"is_set": bool(value)}
            else:
                channel_out[attr] = value
        result[channel_name] = channel_out
    return result


@router.put("/system-config/notifications", dependencies=[Depends(require_admin)])
def update_notification_settings(
    body: NotificationSettingsUpdate, config=Depends(get_config_dep)  # type: ignore[valid-type]
) -> dict[str, Any]:
    """Partial update: only fields explicitly present in the request body change."""
    overrides = body.model_dump(exclude_unset=True)
    _check_telegram_ids(overrides, config)
    for attr, value in overrides.items():
        setattr(config, attr, value)
    config.save()
    return get_notification_settings(config=config)


@router.post("/system-config/notifications/test", dependencies=[Depends(require_admin)])
def test_notification_settings(
    body: NotificationSettingsUpdate, config=Depends(get_config_dep)  # type: ignore[valid-type]
) -> dict[str, Any]:
    """Fire a live test message through every channel that would be
    configured once `body`'s overrides are applied - without saving them,
    mirroring SettingsDialog._on_test."""
    overrides = body.model_dump(exclude_unset=True)
    _check_telegram_ids(overrides, config)
    temp_config = dataclasses.replace(config, **overrides)
    dispatcher = NotificationDispatcher(temp_config)

    configured = dispatcher.configured_channels()
    if not configured:
        return {
            "configured_channels": [],
            "results": {},
            "message": "No channel is fully configured yet - fill in a channel's fields first.",
        }

    results = dispatcher.send_all(
        "This is a test notification from MarketMyna settings.",
        title="MarketMyna Test",
    )
    return {"configured_channels": configured, "results": results}


_ROUTING = [
    ("report", "notification_report_channels", "Daily reports", "Scheduled analysis reports"),
    ("alert", "notification_alert_channels", "Alerts", "Price and portfolio alerts"),
    ("system_error", "notification_system_error_channels", "System errors", "A scheduled run that failed completely"),
]


class NotificationRoutingUpdate(BaseModel):
    report: Optional[List[str]] = None
    alert: Optional[List[str]] = None
    system_error: Optional[List[str]] = None


@router.get("/system-config/notification-routing", dependencies=[Depends(require_admin)])
def get_notification_routing(config=Depends(get_config_dep)) -> dict[str, Any]:
    """Which configured channels receive each kind of message. An empty
    list means "every configured channel"."""
    dispatcher = NotificationDispatcher(config)
    return {
        "channels": dispatcher.configured_channels(),
        "purposes": [{"id": pid, "label": label, "description": desc} for pid, _attr, label, desc in _ROUTING],
        "routes": {pid: list(getattr(config, attr, None) or []) for pid, attr, _l, _d in _ROUTING},
    }


@router.put("/system-config/notification-routing", dependencies=[Depends(require_admin)])
def update_notification_routing(body: NotificationRoutingUpdate, config=Depends(get_config_dep)) -> dict[str, Any]:
    known = set(NotificationDispatcher(config).channel_names())
    for pid, attr, _label, _desc in _ROUTING:
        value = getattr(body, pid)
        if value is None:
            continue
        unknown = [c for c in value if c not in known]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown channel '{unknown[0]}'")
        setattr(config, attr, list(dict.fromkeys(value)) or None)
    config.save()
    return get_notification_routing(config=config)
