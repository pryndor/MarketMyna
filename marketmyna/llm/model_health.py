"""Notices when an AI provider retires a configured model, and keeps AI
working until someone fixes the setting.

Runtime healing (FailoverGenerationBackend): a call failing with "model
not found / no longer available" makes the backend ask the provider which
models the key can use, pick the closest current one
(model_catalog.suggest_replacement: Flash -> newer Flash, never Pro) and
retry with it. A working replacement is remembered, so later calls go
straight to it.
- Platform models (Settings -> AI): the saved setting is NOT changed;
  the owner is told once (log + system-error channels) to set it.
- A user's own key (BYOK): the key's saved model is updated directly.

State is kept in <app_dir>/ai_models.json.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from marketmyna.core.home import app_home

from .model_catalog import bare, suggest_replacement
from .store import clean_error, error_kind

logger = logging.getLogger(__name__)

STATE_NAME = "ai_models.json"
LIST_TTL_SECONDS = 3600.0
# Replacements tried for one retired model before giving up.
MAX_TRIES = 3

_lock = threading.Lock()
_cache: dict[str, tuple[float, dict]] = {}
_lists: dict[tuple[str, str, Optional[str]], tuple[float, list[str]]] = {}


# ---------------------------------------------------------------- state
def _state_file(config) -> Path:
    return Path(getattr(config, "app_dir", None) or app_home()) / STATE_NAME


def load(config) -> dict:
    path = _state_file(config)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"checked_at": None, "models": {}}
    hit = _cache.get(str(path))
    if hit and hit[0] == mtime:
        return json.loads(json.dumps(hit[1]))
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    state = {"checked_at": state.get("checked_at"), "models": state.get("models") or {}}
    _cache[str(path)] = (mtime, state)
    return json.loads(json.dumps(state))


def _save(config, state: dict) -> None:
    path = _state_file(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    _cache.pop(str(path), None)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def substitute(config, model: str) -> Optional[str]:
    """The working replacement for a retired platform model, if one was found."""
    entry = load(config)["models"].get(model) or {}
    if entry.get("status") == "unavailable" and entry.get("replacement") and entry.get("replacement_ok"):
        return entry["replacement"]
    return None


# ---------------------------------------------------------------- provider lists
def available_ids(provider: Optional[str], key: Optional[str], api_base: Optional[str] = None,
                  fresh: bool = False) -> Optional[list[str]]:
    """Bare model ids the key can use, or None when the list can't be had."""
    from .providers import PROVIDER_IDS, list_models

    if not provider or provider not in PROVIDER_IDS:
        return None
    if not key and provider not in ("openrouter", "ollama"):
        return None
    cache_key = (provider, key or "", api_base)
    hit = _lists.get(cache_key)
    if hit and not fresh and time.monotonic() - hit[0] < LIST_TTL_SECONDS:
        return hit[1]
    try:
        ids = [bare(m["id"]) for m in list_models(provider, key, api_base)]
    except Exception as exc:
        logger.info("Could not list %s models: %s", provider, clean_error(exc, 200))
        return None
    _lists[cache_key] = (time.monotonic(), ids)
    return ids


def find_replacement(model: str, key: Optional[str], api_base: Optional[str], tried: set[str]) -> Optional[str]:
    from .channels import provider_of

    ids = available_ids(provider_of(model), key, api_base)
    return suggest_replacement(model, ids, exclude=tried) if ids else None


# ---------------------------------------------------------------- runtime healing
def replaced(config, route, new_model: str, error: Exception) -> None:
    """A retired route answered with `new_model`: remember it (platform) or
    save it on the user's key (BYOK)."""
    if getattr(route, "source", "") == "byok":
        key_id = getattr(route, "key_id", None)
        if key_id is not None:
            try:
                from ..services.ai_access import update_byok_model

                update_byok_model(config, key_id, new_model)
            except Exception:
                logger.exception("Could not save the new model for key %s", key_id)
        logger.warning("Own-key model %s retired; switched to %s", route.model, new_model)
        return
    newly = _mark(config, route.model, status="unavailable", kind=error_kind(error), message=clean_error(error),
                  replacement=new_model, replacement_ok=True)
    logger.warning("AI model %s unavailable (%s); using %s until the setting is changed",
                   route.model, clean_error(error, 120), new_model)
    if newly:
        _announce_async(config, route.model, clean_error(error), new_model)


def unavailable(config, route, error: Exception) -> None:
    """A platform route is retired and nothing could replace it."""
    if getattr(route, "source", "") == "byok":
        return
    if _mark(config, route.model, status="unavailable", kind=error_kind(error), message=clean_error(error),
             replacement=None, replacement_ok=False):
        _announce_async(config, route.model, clean_error(error), None)


def _mark(config, model: str, **fields) -> bool:
    """Updates one model's entry; True when it just became unavailable."""
    with _lock:
        state = load(config)
        entry = state["models"].get(model) or {}
        was = entry.get("status")
        if fields.get("status") == "unavailable" and was == "unavailable" and not fields.get("replacement"):
            fields.pop("replacement", None)  # keep a replacement found earlier
            fields.pop("replacement_ok", None)
        entry.update(fields)
        entry["checked_at"] = _now()
        if entry.get("status") == "unavailable":
            entry.setdefault("since", _now())
        state["models"][model] = entry
        _save(config, state)
        newly = entry.get("status") == "unavailable" and not entry.get("notified")
        if newly:
            entry["notified"] = _now()
            _save(config, state)
        return newly


def _announce_async(config, model: str, message: str, replacement: Optional[str]) -> None:
    threading.Thread(target=announce, args=(config, model, message, replacement),
                     name="ai-model-notice", daemon=True).start()


def announce(config, model: str, message: str, replacement: Optional[str]) -> None:
    """Logged and sent to the system-error channels, once per model."""
    if replacement:
        text = (f"The AI model {model} is no longer available ({message[:160]}). MarketMyna is using "
                f"{replacement} instead for now. Set LLM_MODEL to keep it, "
                "or pick another model.")
    else:
        text = (f"The AI model {model} is no longer available ({message[:160]}) and no replacement was found. "
                "AI features may fail until you add an AI key in Settings → AI keys or set another LLM_MODEL.")
    logger.warning("%s", text)
    try:
        from ..notifiers.dispatcher import NotificationDispatcher

        NotificationDispatcher(config).send_all(text, title="⚠️ MarketMyna AI model retired", purpose="system_error")
    except Exception:
        logger.exception("Could not send the retired-model notice")
