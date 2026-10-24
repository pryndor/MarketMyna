"""Resolves which LLM backend id a Config selects.

Only "litellm" exists in this phase. daily_stock_analysis also has
local-CLI backends (codex_cli/claude_code_cli/opencode_cli - subprocess-
based, with allowlisted env, output caps, redaction) - deliberately not
built here yet: that's real extra scope (subprocess sandboxing is
security-sensitive to get right) rather than a small addition, so it's
cut from Phase 3a rather than half-implemented. backend_factory already
raises a clear, typed error for any backend id other than "litellm" so
adding one later doesn't require reshaping this function's callers.
"""

from __future__ import annotations

LITELLM_BACKEND_ID = "litellm"


def resolve_generation_backend_id(config) -> str:
    return getattr(config, "llm_backend", None) or LITELLM_BACKEND_ID
