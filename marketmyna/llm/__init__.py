"""LLM generation backend layer.

A GenerationBackend Protocol (marketmyna/llm/protocol.py) is the swappable
interface; backend_factory.create_generation_backend(config) builds a
concrete implementation chosen by backend_registry from Config, the
same "small pluggable backend" shape daily_stock_analysis uses for its
own litellm/local-CLI backends.
"""

from __future__ import annotations

from .backend_factory import create_generation_backend
from .backend_registry import LITELLM_BACKEND_ID, resolve_generation_backend_id
from .litellm_backend import LiteLLMGenerationBackend
from .protocol import (
    GenerationBackend,
    GenerationCapabilities,
    GenerationError,
    GenerationErrorCode,
    GenerationResult,
)

__all__ = [
    "GenerationBackend",
    "GenerationCapabilities",
    "GenerationError",
    "GenerationErrorCode",
    "GenerationResult",
    "LiteLLMGenerationBackend",
    "LITELLM_BACKEND_ID",
    "resolve_generation_backend_id",
    "create_generation_backend",
]
