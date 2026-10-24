"""Notices when an AI provider retires a configured model, and keeps AI
working until someone fixes the setting.

Three parts:

1. Runtime healing (FailoverGenerationBackend): a call failing with "model
   not found / no longer available" makes the backend ask the provider which
   models the key can use, pick the closest current one
   (model_catalog.suggest_replacement: Flash -> newer Flash, never Pro) and
   retry with it. A working replacement is remembered, so later calls go
   straight to it.
   - Platform models (Settings -> AI): the saved setting is NOT changed.
     The admin is told once (Security log + system-error channels) and
     clicks "Accept" in Settings -> AI to make it permanent.
   - A user's own key (BYOK): the key's saved model is updated directly;
     the user has nothing to fix and no admin to ask.
2. A daily check (run_check, started by the Security "AI models" check):
   each configured model is looked up in the provider's model list and sent
   one tiny request, which also catches models a list still shows but a key
   can't use (Gemini lists 2.5 Flash, yet refuses it to new keys).
3. State in <app_dir>/ai_models.json, shown in Settings -> AI and Security.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from src.core.home import app_home

from .model_catalog import bare, suggest_replacement
from .protocol import GenerationConfig, GenerationError, GenerationErrorCode
from .store import clean_error, error_kind

logger = logging.getLogger(__name__)

STATE_NAME = "ai_models.json"
CHECK_HOURS = float(os.environ.get("AI_MODEL_CHECK_HOURS", "24"))
LIST_TTL_SECONDS = 3600.0
# Replacements tried for one retired model before giving up.
MAX_TRIES = 3
# Config fields an "Accept" may rewrite.
MODEL_FIELDS = ("llm_model", "llm_fast_model", "llm_fallback_models")

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


# ---------------------------------------------------------------- daily check
def _probe(model: str, key: Optional[str], api_base: Optional[str]) -> Optional[GenerationError]:
    """One tiny request; None when the model answered."""
    from .litellm_backend import LiteLLMGenerationBackend

    cfg = SimpleNamespace(llm_model=model, llm_api_key=key, llm_api_base=api_base, llm_timeout_seconds=30.0,
                          llm_max_tokens=8, llm_temperature=0)
    try:
        LiteLLMGenerationBackend(cfg).generate("Reply with the single word OK.", GenerationConfig(max_tokens=8, temperature=0))
    except GenerationError as exc:
        return exc
    return None


def _platform_routes(config) -> list:
    from .channels import build_routes

    seen, out = set(), []
    for tier in ("deep", "fast"):
        for route in build_routes(config, tier=tier):
            if route.model not in seen:
                seen.add(route.model)
                out.append(route)
    return out


def check_route(route, probe=_probe) -> dict:
    """Status of one configured model: ok / unavailable / error (key, quota...)."""
    from .channels import provider_of

    key = route.api_keys[0] if route.api_keys else None
    ids = available_ids(provider_of(route.model), key, route.api_base, fresh=True)
    entry = {"status": "ok", "kind": None, "message": "", "replacement": None, "replacement_ok": False,
             "listed": None if ids is None else bare(route.model) in ids}
    err: Optional[Exception] = None
    if entry["listed"] is False:
        err = GenerationError(GenerationErrorCode.MODEL_UNAVAILABLE,
                              f"{route.model} is not in the provider's model list for this key any more")
    else:
        err = probe(route.model, key, route.api_base)
    if err is None:
        return entry
    entry["kind"], entry["message"] = error_kind(err), clean_error(err)
    if getattr(err, "error_code", None) != GenerationErrorCode.MODEL_UNAVAILABLE:
        entry["status"] = "error"
        return entry
    entry["status"] = "unavailable"
    tried = {route.model}
    for _ in range(MAX_TRIES):
        candidate = suggest_replacement(route.model, ids or [], exclude=tried) if ids else None
        if not candidate:
            break
        if probe(candidate, key, route.api_base) is None:
            entry["replacement"], entry["replacement_ok"] = candidate, True
            break
        tried.add(candidate)
    return entry


def run_check(config, probe=_probe, notify: bool = True) -> dict:
    """Checks every platform model now and saves the result."""
    results = {route.model: check_route(route, probe) for route in _platform_routes(config)}
    newly = []
    with _lock:
        state = load(config)
        for model, entry in results.items():
            old = state["models"].get(model) or {}
            entry["checked_at"] = _now()
            if entry["status"] == "unavailable":
                entry["since"] = old.get("since") or _now()
                if old.get("notified"):
                    entry["notified"] = old["notified"]
                else:
                    entry["notified"] = _now()
                    newly.append((model, entry["message"], entry.get("replacement")))
        state = {"checked_at": _now(), "models": results}
        _save(config, state)
    if notify:
        for model, message, replacement in newly:
            announce(config, model, message, replacement)
    return state


# ---------------------------------------------------------------- admin
def overview(config) -> dict:
    """Configured models with their last known status, for Settings -> AI."""
    state = load(config)
    models = []
    for route in _platform_routes(config):
        entry = state["models"].get(route.model) or {}
        models.append({"model": route.model, "source": route.source, "status": entry.get("status", "unchecked"),
                       "kind": entry.get("kind"), "message": entry.get("message") or "",
                       "replacement": entry.get("replacement"), "replacement_ok": bool(entry.get("replacement_ok")),
                       "since": entry.get("since"), "checked_at": entry.get("checked_at"),
                       "can_accept": bool(entry.get("replacement")) and _fields_using(config, route.model) != []})
    return {"checked_at": state.get("checked_at"), "check_hours": CHECK_HOURS, "models": models}


def _fields_using(config, model: str) -> list[str]:
    out = []
    for field in MODEL_FIELDS:
        value = getattr(config, field, None)
        if (isinstance(value, list) and model in value) or value == model:
            out.append(field)
    return out


class AcceptError(ValueError):
    pass


def accept(config, model: str, replacement: Optional[str] = None) -> str:
    """Saves the replacement in place of `model` in Settings -> AI."""
    entry = load(config)["models"].get(model) or {}
    new = (replacement or entry.get("replacement") or "").strip()
    if not new:
        raise AcceptError(f"No replacement is known for {model}. Set another LLM_MODEL.")
    fields = _fields_using(config, model)
    if not fields:
        raise AcceptError(f"{model} is set on the server (an LLM_* variable in .env), not in Settings. "
                          "Change it there and restart.")
    env_fields = set(getattr(config, "_env_fields", set()) or ())
    blocked = [f for f in fields if f in env_fields]
    if blocked:
        raise AcceptError(f"{blocked[0].upper()} is set on the server (.env); change it there to {new} and restart.")
    for field in fields:
        value = getattr(config, field)
        if isinstance(value, list):
            setattr(config, field, list(dict.fromkeys(new if v == model else v for v in value)))
        else:
            setattr(config, field, new)
    config.save()
    with _lock:
        state = load(config)
        state["models"].pop(model, None)
        _save(config, state)
    logger.info("AI model %s replaced by %s in Settings", model, new)
    return new


def health(config) -> tuple[str, str]:
    """(OK / WARNING / CRITICAL / UNKNOWN, message) for the Security page."""
    view = overview(config)
    if not view["models"]:
        return "UNKNOWN", "No AI model configured"
    if not view["checked_at"]:
        return "UNKNOWN", "Not checked yet"
    gone = [m for m in view["models"] if m["status"] == "unavailable"]
    broken = [m for m in gone if not m["replacement_ok"]]
    errors = [m for m in view["models"] if m["status"] == "error"]
    if broken:
        return "CRITICAL", "Retired, no replacement: " + ", ".join(m["model"] for m in broken)
    if gone:
        return "WARNING", "Retired, using a replacement until accepted: " + ", ".join(
            f"{m['model']} -> {m['replacement']}" for m in gone)
    if errors:
        return "WARNING", "; ".join(f"{m['model']}: {m['kind']}" for m in errors)
    return "OK", f"{len(view['models'])} model(s) answering"
