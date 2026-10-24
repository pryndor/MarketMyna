"""Builds a concrete GenerationBackend from Config."""

from __future__ import annotations

from .backend_registry import LITELLM_BACKEND_ID, resolve_generation_backend_id
from .litellm_backend import LiteLLMGenerationBackend
from .protocol import GenerationBackend, GenerationError, GenerationErrorCode


def create_generation_backend(config, tier: str = "deep") -> GenerationBackend:
    """tier="deep": the main model chain, for decisions and idea picks.
    tier="fast": the cheaper level-1 model first (commentary, news tone,
    translation), falling back to the main chain. The deep backend also
    exposes `.fast`, so agents can pick the right level per job.

    Saved AI keys come first, then the config.json / env setup
    (src/services/ai_access.py)."""
    from ..services.ai_access import wrap_backend

    return wrap_backend(config, _create_platform_backend, tier)


def _create_platform_backend(config, tier: str = "deep") -> GenerationBackend:
    backend_id = resolve_generation_backend_id(config)

    if backend_id == LITELLM_BACKEND_ID:
        from .channels import FailoverGenerationBackend, build_routes
        from .store import LLMStore

        routes = build_routes(config, tier=tier)
        if not routes:
            # Raises a clear "No llm_model configured" on first use.
            return LiteLLMGenerationBackend(config)
        try:
            store = LLMStore(config)
        except Exception:  # cache/usage are optional extras
            store = None
        backend = FailoverGenerationBackend(config, routes, store=store, tier=tier)
        if tier == "deep" and getattr(config, "llm_fast_model", None):
            backend.fast = FailoverGenerationBackend(config, build_routes(config, tier="fast"), store=store,
                                                     tier="fast")
        return backend

    raise GenerationError(
        GenerationErrorCode.BACKEND_NOT_CONFIGURED,
        f"Unknown or unsupported llm_backend '{backend_id}'",
        stage="setup",
        retryable=False,
        fallbackable=False,
        backend=backend_id,
    )
