"""LLM routes: every model the app may call, in priority order, and the
failover backend that walks them.

Sources, in order:
1. The main model: Config.llm_model with llm_api_key (+ llm_api_keys for
   rotation) and llm_api_base.
2. Named channels, configured the same way as daily_stock_analysis so the
   same environment variables / GitHub secrets work in both projects:

       LLM_CHANNELS=groq,openrouter
       LLM_GROQ_API_KEYS=key1,key2        (or LLM_GROQ_API_KEY=key)
       LLM_GROQ_MODELS=llama-3.3-70b-versatile
       LLM_GROQ_PROTOCOL=openai           (optional; inferred from the name)
       LLM_GROQ_BASE_URL=https://api.groq.com/openai/v1   (optional)
       LLM_GROQ_ENABLED=false             (optional kill switch)

3. Config.llm_fallback_models (env LLM_FALLBACK_MODELS or the
   daily_stock_analysis name LITELLM_FALLBACK_MODELS), which use each
   provider's own key env var (GEMINI_API_KEY, GROQ_API_KEY, ...) via litellm.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Callable, Mapping, Optional

from .litellm_backend import LiteLLMGenerationBackend
from .protocol import (
    GenerationConfig,
    GenerationError,
    GenerationErrorCode,
    GenerationResult,
)
from .store import clean_error

logger = logging.getLogger(__name__)

# Provider prefixes litellm understands that a channel name can imply.
KNOWN_PROVIDERS = {
    "openai", "anthropic", "gemini", "vertex_ai", "deepseek", "ollama", "groq", "openrouter", "mistral",
    "together_ai", "fireworks_ai", "perplexity", "xai", "cohere", "azure", "bedrock", "huggingface",
    "cerebras", "sambanova", "nvidia_nim", "dashscope", "moonshot", "zhipuai", "volcengine",
}
PROTOCOL_ALIASES = {"openai_compatible": "openai", "openai_compat": "openai", "claude": "anthropic", "google": "gemini"}

# Bring-your-own key per provider: Config attribute holding that provider's key.
PROVIDER_KEY_FIELDS = {
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
    "openrouter": "openrouter_api_key",
    "openai": "openai_api_key",
    "anthropic": "anthropic_api_key",
    "deepseek": "deepseek_api_key",
    "mistral": "mistral_api_key",
    "cerebras": "cerebras_api_key",
    "nvidia_nim": "nvidia_api_key",
}


def provider_of(model: str) -> Optional[str]:
    """litellm provider for a model id ("groq/llama..." -> "groq"; bare
    "gpt-4o-mini" -> "openai", "claude-..." -> "anthropic")."""
    model = (model or "").strip()
    if "/" in model:
        prefix = model.split("/", 1)[0].lower()
        return PROTOCOL_ALIASES.get(prefix, prefix)
    lowered = model.lower()
    if lowered.startswith(("gpt-", "o1", "o3", "o4", "chatgpt")):
        return "openai"
    if lowered.startswith("claude"):
        return "anthropic"
    if lowered.startswith("gemini"):
        return "gemini"
    return None


# How long a rate-limited / failing key is skipped before being retried. Each
# failure in a row doubles it (a dead free model stops costing a call a minute),
# up to MAX_COOLDOWN_SECONDS; one success resets it.
COOLDOWN_SECONDS = 60.0
MAX_COOLDOWN_SECONDS = 3600.0


@dataclass
class LLMRoute:
    model: str
    api_keys: list[str] = field(default_factory=list)
    api_base: Optional[str] = None
    source: str = "main"
    # BYOK: the user's saved key row, so a retired model can be updated on it.
    key_id: Optional[int] = None

    def label(self) -> str:
        return f"{self.source}:{self.model}"


def _split(raw: Optional[str]) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def _protocol(name: str, explicit: str, base_url: Optional[str]) -> Optional[str]:
    explicit = PROTOCOL_ALIASES.get(explicit.lower(), explicit.lower()) if explicit else ""
    if explicit:
        return explicit
    lowered = name.lower()
    if lowered in KNOWN_PROVIDERS:
        return lowered
    return "openai" if base_url else None  # any custom endpoint is assumed OpenAI-compatible


def normalize_model(model: str, protocol: Optional[str]) -> str:
    """Give a bare model id the provider prefix litellm routes on."""
    model = model.strip()
    if not model or not protocol:
        return model
    if "/" in model and model.split("/", 1)[0].lower() in KNOWN_PROVIDERS:
        return model
    return f"{protocol}/{model}"


def channel_routes(environ: Mapping[str, str], names: list[str]) -> list[LLMRoute]:
    routes = []
    for name in names:
        up = name.upper()
        enabled = environ.get(f"LLM_{up}_ENABLED", "").strip().lower()
        if enabled in ("0", "false", "no", "off"):
            logger.info("LLM channel %s disabled", name)
            continue
        base_url = environ.get(f"LLM_{up}_BASE_URL", "").strip() or None
        keys = _split(environ.get(f"LLM_{up}_API_KEYS")) or _split(environ.get(f"LLM_{up}_API_KEY"))
        models = _split(environ.get(f"LLM_{up}_MODELS"))
        protocol = _protocol(name, environ.get(f"LLM_{up}_PROTOCOL", "").strip(), base_url)
        if not models:
            logger.warning("LLM channel %s has no LLM_%s_MODELS; skipped", name, up)
            continue
        if not keys and protocol != "ollama":
            logger.warning("LLM channel %s has no API key (LLM_%s_API_KEY[S]); skipped", name, up)
            continue
        for model in models:
            routes.append(LLMRoute(normalize_model(model, protocol), keys, base_url, source=name.lower()))
    return routes


def build_routes(config, environ: Optional[Mapping[str, str]] = None, tier: str = "deep") -> list[LLMRoute]:
    """Every configured model, highest priority first, without duplicates.

    tier="fast" puts Config.llm_fast_model (the cheap/fast "level 1" model)
    in front; the rest of the chain stays behind it as a fallback.
    """
    environ = os.environ if environ is None else environ
    routes: list[LLMRoute] = []

    fast_model = getattr(config, "llm_fast_model", None)
    if tier == "fast" and fast_model:
        routes.append(LLMRoute(fast_model.strip(), source="fast"))

    main_model = getattr(config, "llm_model", None)
    if main_model:
        keys = [k for k in [getattr(config, "llm_api_key", None), *(getattr(config, "llm_api_keys", None) or [])] if k]
        routes.append(LLMRoute(main_model.strip(), list(dict.fromkeys(keys)), getattr(config, "llm_api_base", None)))

    names = list(getattr(config, "llm_channels", None) or []) or _split(environ.get("LLM_CHANNELS"))
    routes += channel_routes(environ, names)

    fallbacks = list(getattr(config, "llm_fallback_models", None) or []) or _split(
        environ.get("LLM_FALLBACK_MODELS") or environ.get("LITELLM_FALLBACK_MODELS")
    )
    routes += [LLMRoute(m, source="fallback") for m in fallbacks]

    # Only a fast model set: the deep tier uses it rather than reporting
    # "no AI model configured". With any main chain it stays fast-only.
    if tier != "fast" and fast_model and not routes:
        routes.append(LLMRoute(fast_model.strip(), source="fast"))

    seen, unique = set(), []
    for route in routes:
        key = (route.model, route.api_base)
        if route.model and key not in seen:
            seen.add(key)
            unique.append(route)

    # Routes without their own key use the provider's saved key (BYOK);
    # litellm still falls back to provider env vars when neither is set.
    for route in unique:
        provider = provider_of(route.model)
        if not route.api_keys and provider in PROVIDER_KEY_FIELDS:
            key = getattr(config, PROVIDER_KEY_FIELDS[provider], None)
            if key:
                route.api_keys = [key]
        if provider == "ollama" and not route.api_base:
            route.api_base = getattr(config, "ollama_base_url", None) or None
        # openai/* models can live on any OpenAI-compatible server (LM Studio,
        # vLLM, a gateway); OPENAI_BASE_URL points them there.
        if provider == "openai" and not route.api_base:
            route.api_base = getattr(config, "openai_base_url", None) or None
    return unique


def llm_configured(config) -> bool:
    """A saved AI key (Settings -> AI keys) or a model set in config.json / env."""
    if build_routes(config):
        return True
    from ..services.ai_access import own_keys

    return bool(own_keys(config))


class _Cooldowns:
    """Process-wide memory of which (model, key) pairs just failed, so a
    batch of calls (one per stock) doesn't hit a rate-limited key again
    and again. Keyed by a key index, never the key itself."""

    def __init__(self):
        self._until: dict[tuple[str, Optional[str], int], float] = {}
        self._strikes: dict[tuple[str, Optional[str], int], int] = {}
        self._lock = threading.Lock()

    def cooling(self, key) -> bool:
        with self._lock:
            return self._until.get(key, 0.0) > time.monotonic()

    def mark(self, key, seconds: float) -> None:
        with self._lock:
            self._until[key] = time.monotonic() + seconds

    def fail(self, key) -> float:
        """Another failure in a row: skip the key twice as long as last time."""
        with self._lock:
            strikes = self._strikes.get(key, 0) + 1
            self._strikes[key] = strikes
            seconds = min(MAX_COOLDOWN_SECONDS, COOLDOWN_SECONDS * 2 ** (strikes - 1))
            self._until[key] = time.monotonic() + seconds
            return seconds

    def ok(self, key) -> None:
        with self._lock:
            self._strikes.pop(key, None)
            self._until.pop(key, None)


_COOLDOWNS = _Cooldowns()


class FailoverGenerationBackend:
    """Tries each route (and each of its keys) until one answers.

    Non-fallbackable errors (e.g. streaming requested) stop immediately;
    everything else - rate limits, timeouts, auth failures, provider
    outages - moves on to the next key, then the next model.
    """

    backend_id = "litellm"
    capabilities = LiteLLMGenerationBackend.capabilities

    def __init__(
        self,
        config,
        routes: list[LLMRoute],
        backend_factory: Callable[[object], object] = LiteLLMGenerationBackend,
        cooldowns: _Cooldowns = _COOLDOWNS,
        store=None,
        tier: str = "deep",
        heal: bool = True,
    ):
        self._config = config
        self._routes = routes
        self._factory = backend_factory
        self._cooldowns = cooldowns
        self._rotation: dict[str, int] = {}
        # Optional LLMStore: response cache + usage counters.
        self._store = store
        self.tier = tier
        # Replace a retired model with the provider's closest current one
        # (src/llm/model_health.py).
        self._heal = heal
        # Level-1 backend for simple jobs; set by create_generation_backend.
        self.fast = self

    def _backend_for(self, route: LLMRoute, api_key: Optional[str]):
        cfg = SimpleNamespace(
            llm_model=route.model,
            llm_api_key=api_key,
            llm_api_base=route.api_base,
            llm_timeout_seconds=getattr(self._config, "llm_timeout_seconds", 60.0),
            llm_max_tokens=getattr(self._config, "llm_max_tokens", 2048),
            llm_temperature=getattr(self._config, "llm_temperature", 0.7),
        )
        return self._factory(cfg)

    def _effective(self, route: LLMRoute) -> LLMRoute:
        """A platform model already known to be retired goes straight to its
        working replacement (until the admin accepts or changes it)."""
        if not self._heal or route.source == "byok":
            return route
        try:
            from . import model_health

            new = model_health.substitute(self._config, route.model)
        except Exception:
            logger.debug("model health state unreadable", exc_info=True)
            return route
        return replace(route, model=new) if new else route

    def _replace_retired(self, route, key, error, attempts, prompt, generation_config, system_prompt, cache_key):
        """The route's model is gone: try the closest current model with the
        same key. Returns the result, or None to carry on down the chain."""
        from . import model_health

        tried = {route.model}
        for _ in range(model_health.MAX_TRIES):
            try:
                new = model_health.find_replacement(route.model, key, route.api_base, tried)
            except Exception:
                logger.exception("Looking for a replacement for %s failed", route.model)
                new = None
            if not new:
                break
            tried.add(new)
            stand_in = replace(route, model=new)
            try:
                result = self._backend_for(stand_in, key).generate(
                    prompt, generation_config, system_prompt=system_prompt)
            except GenerationError as exc:
                attempts.append(f"{stand_in.label()}: {exc.error_code.value}")
                if self._store is not None:
                    self._store.record(f"{self.tier}:{new}", ok=False, error=exc)
                if exc.error_code != GenerationErrorCode.MODEL_UNAVAILABLE:
                    break
                continue
            model_health.replaced(self._config, route, new, error)
            old = route.model
            attempts.append(f"{route.label()}: retired, answered by {new}")
            if route.source == "byok":
                route.model = new  # this backend's later calls too
            result.diagnostics = {**(result.diagnostics or {}), "route": stand_in.label(), "attempts": attempts,
                                  "replaced": {old: new}}
            if self._store is not None:
                self._store.record(f"{self.tier}:{new}", usage=result.usage)
                if cache_key:
                    self._store.put(cache_key, result.text, new)
            return result
        model_health.unavailable(self._config, route, error)
        return None

    def _key_order(self, route: LLMRoute) -> list[tuple[int, Optional[str]]]:
        if not route.api_keys:
            return [(0, None)]
        # Round-robin the starting key so load spreads across keys.
        start = self._rotation.get(route.label(), 0) % len(route.api_keys)
        self._rotation[route.label()] = start + 1
        indexed = list(enumerate(route.api_keys))
        return indexed[start:] + indexed[:start]

    def generate(
        self,
        prompt: str,
        generation_config: GenerationConfig,
        *,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        stream_progress_callback=None,
    ) -> GenerationResult:
        attempts: list[str] = []
        last_error: Optional[GenerationError] = None

        cache_key = None
        if self._store is not None and not stream:
            scope = generation_config.cache_scope
            cache_key = self._store.key(self.tier, system_prompt, f"scope:{scope}" if scope else prompt,
                                        generation_config.max_tokens, generation_config.temperature)
            hit = self._store.get(cache_key)
            if hit:
                text, model = hit
                self._store.record(f"{self.tier}:{model or 'cache'}", cached=True)
                return GenerationResult(text=text, model=model, provider="cache", backend=self.backend_id,
                                        diagnostics={"route": "cache", "cached": True})
        # An explicit per-call model only makes sense for the route that owns it.
        routes = self._routes
        if generation_config.model:
            routes = [r for r in routes if r.model == generation_config.model] or [LLMRoute(generation_config.model)]
        generation_config = GenerationConfig(
            model=None,
            timeout=generation_config.timeout,
            max_tokens=generation_config.max_tokens,
            temperature=generation_config.temperature,
        )

        routes = [self._effective(route) for route in routes]
        candidates = [(route, index, key) for route in routes for index, key in self._key_order(route)]
        # If every candidate is cooling down, try them anyway rather than
        # failing without a single call - a short rate limit may be over.
        respect_cooldown = not all(
            self._cooldowns.cooling((route.model, route.api_base, index)) for route, index, _ in candidates
        )
        for route, index, key in candidates:
            cool_key = (route.model, route.api_base, index)
            if respect_cooldown and self._cooldowns.cooling(cool_key):
                attempts.append(f"{route.label()}#{index}: cooling down")
                continue
            try:
                result = self._backend_for(route, key).generate(
                    prompt, generation_config, system_prompt=system_prompt, stream=stream,
                    stream_progress_callback=stream_progress_callback,
                )
            except GenerationError as exc:
                last_error = exc
                attempts.append(f"{route.label()}#{index}: {exc.error_code.value}")
                if self._store is not None:
                    self._store.record(f"{self.tier}:{route.model}", ok=False, error=exc)
                if not exc.fallbackable:
                    raise
                logger.warning("LLM route %s key #%d failed (%s): %s", route.label(), index,
                               exc.error_code.value, clean_error(exc, 200))
                if exc.error_code == GenerationErrorCode.MODEL_UNAVAILABLE and self._heal:
                    healed = self._replace_retired(route, key, exc, attempts, prompt, generation_config,
                                                   system_prompt, cache_key)
                    if healed is not None:
                        return healed
                    continue
                if exc.error_code in (GenerationErrorCode.RATE_LIMITED, GenerationErrorCode.INVALID_RESPONSE,
                                      GenerationErrorCode.AUTH_FAILED, GenerationErrorCode.TIMEOUT):
                    self._cooldowns.fail(cool_key)
                continue
            self._cooldowns.ok(cool_key)
            result.diagnostics = {**(result.diagnostics or {}), "route": route.label(), "attempts": attempts}
            if self._store is not None:
                self._store.record(f"{self.tier}:{route.model}", usage=result.usage)
                if cache_key:
                    self._store.put(cache_key, result.text, route.model)
            if attempts:
                logger.info("LLM answered via %s after: %s", route.label(), "; ".join(attempts))
            return result

        raise GenerationError(
            last_error.error_code if last_error else GenerationErrorCode.BACKEND_NOT_CONFIGURED,
            f"All LLM routes failed ({'; '.join(attempts) or 'no routes'})",
            stage="failover",
            retryable=bool(last_error and last_error.retryable),
            fallbackable=False,
            backend=self.backend_id,
            details={"attempts": attempts},
        )
