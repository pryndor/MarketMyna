"""Which AI the app uses.

The owner's own keys come first (Settings -> AI keys: paste a key, the
provider and model are worked out from it, src/services/byok_detect.py),
each tried in turn. With no saved key, the AI setup in config.json and the
environment (LLM_MODEL, OLLAMA_BASE_URL, ...) is used unchanged; with
neither, AI features say no model is configured.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Model used with a key when none was picked from the provider's list when
# the key was saved (src/services/byok_detect.py). Aliases the provider keeps
# current where they exist; a retired one is replaced at the first failing
# call (src/llm/model_health.py). Override with BYOK_MODEL_<PROVIDER>, e.g.
# BYOK_MODEL_GEMINI=gemini/gemini-pro-latest.
BYOK_DEFAULT_MODELS = {
    "gemini": "gemini/gemini-flash-latest",
    "groq": "groq/openai/gpt-oss-120b",
    "openrouter": "openrouter/openai/gpt-5-mini",
    "openai": "openai/gpt-5-mini",
    "anthropic": "anthropic/claude-haiku-4-5",
    "deepseek": "deepseek/deepseek-chat",
    "mistral": "mistral/mistral-small-latest",
}


def byok_model(provider: str, detected: Optional[str] = None) -> str:
    """Env override, else the model picked when the key was saved, else the default."""
    return os.environ.get(f"BYOK_MODEL_{provider.upper()}") or detected or BYOK_DEFAULT_MODELS[provider]


def _db(config):
    from ..storage import DatabaseManager, get_db_url

    return DatabaseManager.instance(get_db_url(config=config))


def own_keys(config) -> list[tuple[str, str, Optional[str], int]]:
    """Every usable saved key as (provider, key, model, key row id), oldest first."""
    from datetime import datetime

    from ..core import tenant
    from ..storage import UserApiKeyRecord
    from .accounts import BYOK_PROVIDERS, decrypt_secret, owner_user_id

    owner = owner_user_id(config) if tenant.enabled() else None
    out = []
    try:
        with _db(config).get_session() as session:
            rows = session.query(UserApiKeyRecord)
            if owner is not None:
                rows = rows.filter_by(user_id=owner)
            for row in rows.order_by(UserApiKeyRecord.id):
                if row.provider not in BYOK_PROVIDERS:
                    continue
                try:
                    out.append((row.provider, decrypt_secret(config, row.key_ciphertext), row.model, row.id))
                except Exception:
                    logger.warning("Could not decrypt the saved %s key %s", row.provider, row.id)
                    continue
                row.last_used_at = datetime.now()
    except Exception:
        logger.exception("Could not read the saved AI keys")
    return out


def wrap_backend(config, build, tier: str):
    """The saved keys if there are any, else `build(config, tier)` (config.json / env)."""
    keys = own_keys(config)
    if not keys:
        return build(config, tier)
    from ..llm.channels import FailoverGenerationBackend, LLMRoute

    routes = [LLMRoute(byok_model(provider, model), [key], None, source="byok", key_id=key_id)
              for provider, key, model, key_id in keys]
    return FailoverGenerationBackend(config, routes, store=None, tier=tier)


def update_byok_model(config, key_id: int, model: str) -> None:
    """The model saved with a key was retired: keep the one that answered
    instead (src/llm/model_health.py)."""
    from ..storage import UserApiKeyRecord

    with _db(config).get_session() as session:
        row = session.get(UserApiKeyRecord, key_id)
        if row is not None:
            row.model = model
