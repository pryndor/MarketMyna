"""Provider catalogue for the Settings page: which AI providers the app
knows, where to get a key, and a live "which models can this key use"
lookup - so model names come from the provider, not from a list in this
code that goes stale.

Returned model ids are already in litellm form ("groq/openai/gpt-oss-120b"),
and the one model_catalog.recommend() would pick is marked "recommended".
"""

from __future__ import annotations

from typing import Iterable, Optional

import requests

_TIMEOUT = 15

# id, label, config key field, where to get a key, free-tier note
PROVIDERS = [
    {"id": "gemini", "label": "Google Gemini", "key_field": "gemini_api_key",
     "key_url": "https://aistudio.google.com/app/apikey",
     "note": "Free tier with per-model rate limits - a good default."},
    {"id": "groq", "label": "Groq", "key_field": "groq_api_key",
     "key_url": "https://console.groq.com/keys",
     "note": "Free tier, very fast - good as the fast model or a fallback."},
    {"id": "openrouter", "label": "OpenRouter", "key_field": "openrouter_api_key",
     "key_url": "https://openrouter.ai/keys",
     "note": "One key for many models; free models are marked but rate-limited."},
    {"id": "openai", "label": "OpenAI", "key_field": "openai_api_key",
     "key_url": "https://platform.openai.com/api-keys", "note": "Paid."},
    {"id": "anthropic", "label": "Anthropic", "key_field": "anthropic_api_key",
     "key_url": "https://console.anthropic.com/settings/keys", "note": "Paid."},
    {"id": "deepseek", "label": "DeepSeek", "key_field": "deepseek_api_key",
     "key_url": "https://platform.deepseek.com/api_keys", "note": "Paid, low cost."},
    {"id": "mistral", "label": "Mistral", "key_field": "mistral_api_key",
     "key_url": "https://console.mistral.ai/api-keys", "note": "Free experiment tier available."},
    {"id": "cerebras", "label": "Cerebras", "key_field": "cerebras_api_key",
     "key_url": "https://cloud.cerebras.ai/platform", "note": "Free tier with a large daily token allowance - a strong fallback."},
    {"id": "nvidia_nim", "label": "NVIDIA NIM", "key_field": "nvidia_api_key",
     "key_url": "https://build.nvidia.com/settings/api-keys", "note": "Free developer credits for hosted open models."},
    {"id": "ollama", "label": "Ollama (local)", "key_field": None,
     "key_url": "https://ollama.com/download", "note": "Runs on your machine: free and private."},
]
PROVIDER_IDS = {p["id"] for p in PROVIDERS}


def list_models(provider: str, api_key: Optional[str] = None, base_url: Optional[str] = None,
                include_old: bool = True, hide: Iterable[str] = ()) -> list[dict]:
    """[{id, label, free, recommended}] for models this key can use to
    generate text; the recommended one first.

    include_old=False leaves out models a newer stable release of the same
    line replaces (model_catalog.superseded), models the provider marks
    inactive, and `hide` (litellm ids found retired by model_health)."""
    from .model_catalog import bare, is_text_model, recommend, superseded

    models = [m for m in _list_models(provider, api_key, base_url) if is_text_model(bare(m["id"]))]
    if not include_old:
        gone = superseded(bare(m["id"]) for m in models)
        hidden = set(hide)
        models = [m for m in models if m.get("active", True) and bare(m["id"]) not in gone and m["id"] not in hidden]
    for m in models:
        m.pop("active", None)
    best = recommend(provider, [bare(m["id"]) for m in models])
    for m in models:
        m["recommended"] = best is not None and bare(m["id"]) == best
    return sorted(models, key=lambda m: not m["recommended"])


def _list_models(provider: str, api_key: Optional[str] = None, base_url: Optional[str] = None) -> list[dict]:
    if provider == "gemini":
        resp = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                            params={"key": api_key, "pageSize": 200}, timeout=_TIMEOUT)
        resp.raise_for_status()
        out = []
        for m in resp.json().get("models", []):
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            name = m["name"].split("/", 1)[-1]
            out.append({"id": f"gemini/{name}", "label": m.get("displayName") or name, "free": None})
        return out

    if provider == "openrouter":
        # Public list; pricing tells which models are free.
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=_TIMEOUT)
        resp.raise_for_status()
        out = []
        for m in resp.json().get("data", []):
            pricing = m.get("pricing") or {}
            free = str(pricing.get("prompt")) in ("0", "0.0") and str(pricing.get("completion")) in ("0", "0.0")
            out.append({"id": f"openrouter/{m['id']}", "label": m.get("name") or m["id"], "free": free})
        return sorted(out, key=lambda m: (not m["free"], m["label"].lower()))

    if provider == "ollama":
        base = (base_url or "http://localhost:11434").rstrip("/")
        resp = requests.get(f"{base}/api/tags", timeout=_TIMEOUT)
        resp.raise_for_status()
        return [{"id": f"ollama/{m['name']}", "label": m["name"], "free": True} for m in resp.json().get("models", [])]

    if provider == "anthropic":
        resp = requests.get("https://api.anthropic.com/v1/models", timeout=_TIMEOUT,
                            headers={"x-api-key": api_key or "", "anthropic-version": "2023-06-01"})
        resp.raise_for_status()
        return [{"id": f"anthropic/{m['id']}", "label": m.get("display_name") or m["id"], "free": False}
                for m in resp.json().get("data", [])]

    # OpenAI-style /models lists.
    urls = {
        "groq": "https://api.groq.com/openai/v1/models",
        "openai": "https://api.openai.com/v1/models",
        "deepseek": "https://api.deepseek.com/models",
        "mistral": "https://api.mistral.ai/v1/models",
        "cerebras": "https://api.cerebras.ai/v1/models",
        "nvidia_nim": "https://integrate.api.nvidia.com/v1/models",
    }
    if provider not in urls:
        raise ValueError(f"Unknown provider '{provider}'")
    resp = requests.get(urls[provider], headers={"Authorization": f"Bearer {api_key or ''}"}, timeout=_TIMEOUT)
    resp.raise_for_status()
    skip = ("whisper", "tts", "embedding", "embed", "moderation", "dall-e", "image", "audio", "transcribe", "guard")
    out = []
    for m in resp.json().get("data", []):
        mid = m.get("id", "")
        if not mid or any(word in mid.lower() for word in skip):
            continue
        out.append({"id": f"{provider}/{mid}", "label": mid, "free": True if provider in ("groq", "cerebras") else None,
                    "active": m.get("active") is not False})
    return sorted(out, key=lambda m: m["label"].lower())


# Free-tier providers for the fallback chain, most generous first, and how
# many of each provider's models to add (a second model has its own limits).
FREE_CHAIN = [("cerebras", 1), ("groq", 2), ("gemini", 2), ("nvidia_nim", 1), ("mistral", 1), ("openrouter", 2)]


def free_chain(config, exclude: Iterable[str] = ()) -> dict:
    """A fallback list built from the free-tier providers that have a saved
    key: {"models": [litellm ids], "skipped": {provider: reason}}.

    Models are picked from each provider's live list (model_catalog), so the
    names don't go stale. `exclude` (the main and fast models) is left out.
    OpenRouter only contributes its ":free" models."""
    from .model_catalog import bare, recommend, tier_of

    picked: list[str] = []
    skipped: dict[str, str] = {}
    taken = {m for m in exclude if m}
    for provider, count in FREE_CHAIN:
        meta = next(p for p in PROVIDERS if p["id"] == provider)
        key = getattr(config, meta["key_field"], None)
        if not key:
            skipped[provider] = "no key saved"
            continue
        try:
            models = list_models(provider, key, include_old=False)
        except Exception as exc:  # noqa: BLE001 - one provider down never blocks the rest
            skipped[provider] = f"model list failed: {str(exc)[:120]}"
            continue
        if provider == "openrouter":
            ids = [bare(m["id"]) for m in models if m.get("free") and m["id"].endswith(":free")]
            chosen = [f"openrouter/{i}" for i in ids if f"openrouter/{i}" not in taken][:count]
        else:
            ids = [bare(m["id"]) for m in models]
            chosen = []
            while len(chosen) < count:
                # A further model must be another tier ("flash-lite" after
                # "flash"): an alias of the same model shares its quota.
                tiers = [tier_of(bare(c)) for c in chosen]
                pool = [i for i in ids if tier_of(i) not in tiers]
                best = recommend(provider, pool, exclude=[*taken, *chosen])
                if not best:
                    break
                chosen.append(f"{provider}/{best}")
        if not chosen:
            skipped[provider] = "no suitable model in its list"
        picked += chosen
        taken.update(chosen)
    return {"models": picked, "skipped": skipped}
