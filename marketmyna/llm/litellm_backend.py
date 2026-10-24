"""LiteLLM-backed GenerationBackend.

litellm itself is imported lazily, inside generate(), not at module
scope - this backend's class definition, backend_id and capabilities
must stay importable even when litellm isn't installed (e.g. this
sandbox), so callers that never actually invoke generate() (config
listing, backend_registry resolution, tests) don't crash on import.

litellm reaches every provider - OpenAI, Anthropic, Gemini, and local
Ollama alike - through one model-string convention (e.g. "gpt-4o-mini",
"claude-3-5-sonnet-20241022", "ollama/qwen3:8b"), which is why there is
no separate "Ollama backend" class here, matching daily_stock_analysis's
own design: Ollama is just a litellm model string plus llm_api_base
pointed at the local server.
"""

from __future__ import annotations

from typing import Callable, Optional

from .protocol import (
    GenerationCapabilities,
    GenerationConfig,
    GenerationError,
    GenerationErrorCode,
    GenerationResult,
)

# How providers say a model is gone (retired, renamed, or not offered to this
# key): Gemini "no longer available to new users" / "is not found for API
# version", Groq / OpenAI "model_not_found", "decommissioned", ...
_MODEL_GONE = (
    "no longer available", "model_not_found", "model not found", "does not exist", "decommissioned",
    "has been deprecated", "is deprecated", "is not found for api version", "not supported for generatecontent",
    "unknown model", "invalid model", "no endpoints found", "is not a valid model",
)


def model_unavailable(exception_name: str, message: str) -> bool:
    """True when an error says the model itself is unusable, not the key,
    a quota or the network."""
    name, message = exception_name.lower(), message.lower()
    if any(phrase in message for phrase in _MODEL_GONE):
        return True
    return "notfound" in name and "model" in message


class LiteLLMGenerationBackend:
    backend_id = "litellm"
    capabilities = GenerationCapabilities(
        supports_json=True,
        supports_tools=True,
        supports_stream=False,  # not implemented in this phase, see protocol.py
        supports_vision=False,
        supports_health_check=False,
        supports_smoke_test=False,
    )

    def __init__(self, config):
        self._model = getattr(config, "llm_model", None)
        self._api_base = getattr(config, "llm_api_base", None)
        self._api_key = getattr(config, "llm_api_key", None)
        self._default_timeout = getattr(config, "llm_timeout_seconds", 60.0)
        self._default_max_tokens = getattr(config, "llm_max_tokens", 2048)
        self._default_temperature = getattr(config, "llm_temperature", 0.7)

    def generate(
        self,
        prompt: str,
        generation_config: GenerationConfig,
        *,
        system_prompt: Optional[str] = None,
        stream: bool = False,
        stream_progress_callback: Optional[Callable[[str], None]] = None,
    ) -> GenerationResult:
        if stream:
            raise GenerationError(
                GenerationErrorCode.INVALID_RESPONSE,
                "LiteLLMGenerationBackend does not implement streaming yet",
                stage="generate",
                retryable=False,
                fallbackable=False,
                backend=self.backend_id,
            )

        model = generation_config.model or self._model
        if not model:
            raise GenerationError(
                GenerationErrorCode.BACKEND_NOT_CONFIGURED,
                "No llm_model configured",
                stage="setup",
                retryable=False,
                fallbackable=False,
                backend=self.backend_id,
            )

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            import litellm
        except ImportError as exc:
            raise GenerationError(
                GenerationErrorCode.BACKEND_NOT_CONFIGURED,
                "litellm is not installed",
                stage="setup",
                retryable=False,
                fallbackable=False,
                backend=self.backend_id,
                details={"import_error": str(exc)},
            ) from exc

        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                api_base=self._api_base,
                api_key=self._api_key,
                timeout=generation_config.timeout or self._default_timeout,
                max_tokens=generation_config.max_tokens or self._default_max_tokens,
                temperature=(
                    generation_config.temperature
                    if generation_config.temperature is not None
                    else self._default_temperature
                ),
            )
        except Exception as exc:  # noqa: BLE001 - normalized into GenerationError below
            raise self._wrap_exception(exc, model)

        return self._to_result(response, model)

    def _wrap_exception(self, exc: Exception, model: str) -> GenerationError:
        name = type(exc).__name__.lower()
        message = str(exc).lower()

        if "timeout" in name or "timeout" in message:
            code, retryable = GenerationErrorCode.TIMEOUT, True
        elif "rate" in name or "rate limit" in message or "429" in message:
            code, retryable = GenerationErrorCode.RATE_LIMITED, True
        elif model_unavailable(name, message):
            code, retryable = GenerationErrorCode.MODEL_UNAVAILABLE, False
        elif "auth" in name or "api key" in message or "401" in message or "403" in message:
            code, retryable = GenerationErrorCode.AUTH_FAILED, False
        elif "connection" in name or "connect" in message:
            code, retryable = GenerationErrorCode.UNKNOWN, True
        else:
            code, retryable = GenerationErrorCode.UNKNOWN, False

        return GenerationError(
            code,
            str(exc),
            stage="call",
            retryable=retryable,
            fallbackable=True,
            backend=self.backend_id,
            provider=model.split("/")[0] if "/" in model else None,
            details={"exception_type": type(exc).__name__},
        )

    def _to_result(self, response, model: str) -> GenerationResult:
        try:
            choice = response.choices[0]
            text = choice.message.content or ""
        except (AttributeError, IndexError) as exc:
            raise GenerationError(
                GenerationErrorCode.INVALID_RESPONSE,
                "litellm response missing choices[0].message.content",
                stage="parse",
                retryable=False,
                fallbackable=True,
                backend=self.backend_id,
                details={"raw_type": type(response).__name__},
            ) from exc

        usage = {}
        raw_usage = getattr(response, "usage", None)
        if raw_usage is not None:
            usage = {
                "prompt_tokens": getattr(raw_usage, "prompt_tokens", None),
                "completion_tokens": getattr(raw_usage, "completion_tokens", None),
                "total_tokens": getattr(raw_usage, "total_tokens", None),
            }

        provider = model.split("/")[0] if "/" in model else "unknown"
        response_model = getattr(response, "model", None) or model

        return GenerationResult(
            text=text,
            model=response_model,
            provider=provider,
            backend=self.backend_id,
            usage=usage,
            raw=response,
            diagnostics={},
        )
