"""Works out which AI provider a pasted key belongs to, checks the provider
accepts it, and picks the model to use with it (a free one where the key
only has free access).

Supported: Anthropic, Google Gemini, Groq, Mistral and OpenRouter. The key's
prefix settles the provider (AIza = Gemini, gsk_ = Groq, sk-or- = OpenRouter,
sk-ant- = Anthropic, no prefix = Mistral); the provider is then asked to list
its models with the key, which checks it works. The key is only ever sent to
the provider it is being tested against.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

from ..llm.model_catalog import recommend

logger = logging.getLogger(__name__)

TIMEOUT = 8

PROVIDER_LABELS = {
    "gemini": "Google Gemini",
    "groq": "Groq",
    "openrouter": "OpenRouter",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "mistral": "Mistral",
}

# Providers a pasted key is detected for (OpenAI / DeepSeek keys saved earlier still work).
SUPPORTED_TEXT = "Anthropic, Google Gemini, Groq, Mistral or OpenRouter"

# Used only when the key's model list can't be read (provider unreachable);
# otherwise model_catalog.recommend() picks from the live list, so a new
# release is used and a retired one isn't. litellm prefix added later.
PREFERRED_MODELS = {
    "gemini": ["gemini-flash-latest"],
    "groq": ["openai/gpt-oss-120b"],
    "openrouter": ["openai/gpt-5-mini"],
    "openai": ["gpt-5-mini"],
    "anthropic": ["claude-haiku-4-5"],
    "deepseek": ["deepseek-chat"],
    "mistral": ["mistral-small-latest"],
}
OPENROUTER_FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat-v3-0324:free",
    "google/gemini-2.0-flash-exp:free",
    "mistralai/mistral-small-3.2-24b-instruct:free",
]

# Providers whose keys come with a free tier, and how to describe it.
FREE_TIER_NOTES = {
    "gemini": "Free tier (rate-limited) unless billing is enabled on the Google project.",
    "groq": "Free tier (rate-limited).",
    "mistral": "Free Experiment plan (rate-limited) unless the workspace is on a paid plan.",
}
PAID_NOTE = "Paid per use: calls are billed to your {label} account."


class KeyDetectError(ValueError):
    pass


@dataclass
class Detected:
    provider: str
    model: str  # litellm id, e.g. gemini/gemini-flash-latest
    free: Optional[bool]  # True: free access; False: billed; None: can't tell
    note: str
    verified: bool = True


def candidates(key: str) -> list[str]:
    """Providers a key could belong to, most likely first."""
    if key.startswith("AIza"):
        return ["gemini"]
    if key.startswith("gsk_"):
        return ["groq"]
    if key.startswith("sk-or-"):
        return ["openrouter"]
    if key.startswith("sk-ant-"):
        return ["anthropic"]
    if key.startswith("sk-"):
        return []  # OpenAI / DeepSeek style: not supported
    return ["mistral"]


def _get(url: str, headers: dict) -> requests.Response:
    return requests.get(url, headers=headers, timeout=TIMEOUT)


def _list_models(provider: str, key: str) -> Optional[list[str]]:
    """Model ids the key can see; None if the provider is unreachable.
    Raises PermissionError when the provider rejects the key."""
    bearer = {"Authorization": f"Bearer {key}"}
    if provider == "gemini":
        url, headers = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000", {"x-goog-api-key": key}
    elif provider == "anthropic":
        url, headers = "https://api.anthropic.com/v1/models?limit=1000", {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        url = {
            "groq": "https://api.groq.com/openai/v1/models",
            "openrouter": "https://openrouter.ai/api/v1/key",
            "openai": "https://api.openai.com/v1/models",
            "deepseek": "https://api.deepseek.com/models",
            "mistral": "https://api.mistral.ai/v1/models",
        }[provider]
        headers = bearer
    try:
        resp = _get(url, headers)
    except requests.RequestException as exc:
        logger.info("Key check against %s failed: %s", provider, exc)
        return None
    if resp.status_code in (400, 401, 403):
        raise PermissionError(provider)
    if resp.status_code >= 300:
        logger.info("Key check against %s: HTTP %s", provider, resp.status_code)
        return None
    try:
        body = resp.json()
    except ValueError:
        return None
    if provider == "openrouter":
        return ["__free_tier__"] if (body.get("data") or {}).get("is_free_tier") else []
    if provider == "gemini":
        return [m.get("name", "").removeprefix("models/") for m in body.get("models") or []]
    return [m.get("id", "") for m in body.get("data") or []]


def _openrouter_free_model() -> str:
    try:
        models = _get("https://openrouter.ai/api/v1/models", {}).json().get("data") or []
    except (requests.RequestException, ValueError):
        return OPENROUTER_FREE_MODELS[0]
    free = {
        m.get("id") for m in models
        if str((m.get("pricing") or {}).get("prompt")) == "0" and str((m.get("pricing") or {}).get("completion")) == "0"
    }
    for model in OPENROUTER_FREE_MODELS:
        if model in free:
            return model
    return sorted(m for m in free if m and m.endswith(":free"))[0] if free else OPENROUTER_FREE_MODELS[0]


def _pick(provider: str, seen: Optional[list[str]]) -> Detected:
    label = PROVIDER_LABELS[provider]
    if provider == "openrouter":
        if seen and "__free_tier__" in seen:
            return Detected(provider, f"openrouter/{_openrouter_free_model()}", True,
                            "Free account: using a free model (rate-limited).")
        if seen is None:
            return Detected(provider, f"openrouter/{PREFERRED_MODELS[provider][0]}", None,
                            "Couldn't reach OpenRouter to check the key; it will be tried on first use.", False)
        return Detected(provider, f"openrouter/{PREFERRED_MODELS[provider][0]}", False, PAID_NOTE.format(label=label))
    model = (recommend(provider, seen) if seen else None) or PREFERRED_MODELS[provider][0]
    if seen is None:
        return Detected(provider, f"{provider}/{model}", provider in FREE_TIER_NOTES or None,
                        f"Couldn't reach {label} to check the key; it will be tried on first use.", False)
    if provider in FREE_TIER_NOTES:
        return Detected(provider, f"{provider}/{model}", True, FREE_TIER_NOTES[provider])
    return Detected(provider, f"{provider}/{model}", False, PAID_NOTE.format(label=label))


def detect(key: str) -> Detected:
    """Provider and model for `key`. Raises KeyDetectError when no supported
    provider accepts it."""
    key = (key or "").strip()
    options = candidates(key)
    if not options:
        raise KeyDetectError(f"This looks like an OpenAI or DeepSeek key. Use a key from {SUPPORTED_TEXT}.")
    unreachable: list[str] = []
    for provider in options:
        try:
            seen = _list_models(provider, key)
        except PermissionError:
            continue
        if seen is None:
            unreachable.append(provider)
            continue
        return _pick(provider, seen)
    if unreachable and len(options) == 1:
        return _pick(unreachable[0], None)
    if unreachable:
        raise KeyDetectError(
            f"Couldn't reach {', '.join(PROVIDER_LABELS[p] for p in unreachable)} to check this key. Try again in a minute."
        )
    if options == ["mistral"]:
        raise KeyDetectError(f"This key wasn't accepted. Use a key from {SUPPORTED_TEXT}.")
    raise KeyDetectError(f"{' / '.join(PROVIDER_LABELS[p] for p in options)} rejected this key. Check it was copied in full.")
