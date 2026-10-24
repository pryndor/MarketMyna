"""GenerationBackend protocol: the swappable interface every LLM backend
implements, and the result/error shapes they exchange with callers.

Simplified from daily_stock_analysis's own src/llm/generation_backend.py:
`response_validator` (schema-validation-with-retry) and `audit_context`
(HMAC-hashed prompt audit telemetry) are dropped here - both are real
features but belong to a later hardening pass, not a first LLM backend
for MarketMyna. `stream`/`stream_progress_callback` are kept in the
signature (Phase 3b's agent chat endpoint will want streaming) but no
backend in this phase actually implements streaming yet - passing
stream=True raises before any call is made, rather than silently
falling back to non-streaming and surprising a caller expecting chunks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Protocol


class GenerationErrorCode(Enum):
    BACKEND_NOT_CONFIGURED = "backend_not_configured"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    INVALID_RESPONSE = "invalid_response"
    AUTH_FAILED = "auth_failed"  # the provider rejected the key
    MODEL_UNAVAILABLE = "model_unavailable"  # retired, renamed, or closed to this key
    UNKNOWN = "unknown"


class GenerationError(Exception):
    """Structured error every backend raises on failure, so callers (the
    future agent orchestrator) can decide retryable/fallbackable behavior
    without parsing exception messages."""

    def __init__(
        self,
        error_code: GenerationErrorCode,
        message: str = "",
        *,
        stage: str = "generate",
        retryable: bool = False,
        fallbackable: bool = True,
        backend: Optional[str] = None,
        provider: Optional[str] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message or error_code.value)
        self.error_code = error_code
        self.stage = stage
        self.retryable = retryable
        self.fallbackable = fallbackable
        self.backend = backend
        self.provider = provider
        self.details = details or {}


@dataclass
class GenerationCapabilities:
    supports_json: bool = False
    supports_tools: bool = False
    supports_stream: bool = False
    supports_vision: bool = False
    supports_health_check: bool = False
    supports_smoke_test: bool = False


@dataclass
class GenerationResult:
    text: str
    model: str
    provider: str
    backend: str
    usage: dict = field(default_factory=dict)
    raw: Any = None
    diagnostics: dict = field(default_factory=dict)


@dataclass
class GenerationConfig:
    """Per-call generation parameters. A backend applies its own Config-
    derived defaults (model/timeout/max_tokens/temperature) for any field
    left None here."""

    model: Optional[str] = None
    timeout: Optional[float] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    # Reuse key in place of the prompt text: answers for the same scope (e.g. one
    # stock's stage) are shared for the cache's lifetime even as live prices move.
    cache_scope: Optional[str] = None


class GenerationBackend(Protocol):
    """Every concrete backend (LiteLLM today; a local-CLI subprocess
    backend later) implements this."""

    backend_id: str
    capabilities: GenerationCapabilities

    def generate(
        self,
        prompt: str,
        generation_config: GenerationConfig,
        *,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        stream_progress_callback: Optional[Callable[[str], None]] = None,
    ) -> GenerationResult:
        ...
