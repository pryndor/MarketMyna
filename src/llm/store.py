"""Response cache and usage counters for LLM calls (sqlite, shared by the
API process and the scheduler's child processes).

The cache key covers everything that shapes the answer - model tier,
system prompt, prompt, and generation limits - so a cached reply is only
reused for a byte-identical request. Prompts embed the current price and
indicator values, so a new trading day naturally misses the cache.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from ..utils.log_redact import SECRETS as _SECRETS

logger = logging.getLogger(__name__)

DEFAULT_CACHE_HOURS = 6.0

# GenerationErrorCode value -> the reason shown in Settings -> AI usage.
ERROR_KINDS = {
    "model_unavailable": "retired",
    "rate_limited": "quota",
    "auth_failed": "key",
    "timeout": "timeout",
    "invalid_response": "bad answer",
    "unknown": "outage",
}


def clean_error(exc, limit: int = 300) -> str:
    """One line of an error's text, with anything that looks like an API key
    masked (provider errors can echo the request URL, ?key=... included)."""
    return _SECRETS.sub("***", " ".join(str(exc).split()))[:limit]


def error_kind(exc) -> str:
    code = getattr(getattr(exc, "error_code", None), "value", "")
    return ERROR_KINDS.get(code, "other")


class LLMStore:
    def __init__(self, config):
        from ..storage import DatabaseManager, get_db_url

        self._db = DatabaseManager.instance(get_db_url(config=config))
        hours = getattr(config, "llm_cache_hours", None)
        self.cache_hours = DEFAULT_CACHE_HOURS if hours is None else float(hours)

    @staticmethod
    def key(tier: str, system_prompt: Optional[str], prompt: str, max_tokens, temperature) -> str:
        raw = "\x1f".join([tier, system_prompt or "", prompt, str(max_tokens), str(temperature)])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # ---- cache
    def get(self, key: str) -> Optional[tuple[str, str]]:
        if self.cache_hours <= 0:
            return None
        from ..storage import LLMCacheRecord

        try:
            with self._db.get_session() as session:
                record = session.get(LLMCacheRecord, key)
                if record and record.created_at >= datetime.now() - timedelta(hours=self.cache_hours):
                    return record.text, record.model or ""
        except Exception as exc:
            logger.debug("LLM cache read failed: %s", exc)
        return None

    def put(self, key: str, text: str, model: str) -> None:
        if self.cache_hours <= 0 or not text:
            return
        from ..storage import LLMCacheRecord

        try:
            with self._db.get_session() as session:
                session.merge(LLMCacheRecord(key=key, text=text, model=model, created_at=datetime.now()))
                # Keep the table small: drop answers as soon as they are past the TTL.
                cutoff = datetime.now() - timedelta(hours=self.cache_hours)
                session.query(LLMCacheRecord).filter(LLMCacheRecord.created_at < cutoff).delete(
                    synchronize_session=False)
        except Exception as exc:
            logger.debug("LLM cache write failed: %s", exc)

    # ---- usage
    def record(self, route: str, *, ok: bool = True, cached: bool = False, usage: Optional[dict] = None,
               error: Optional[Exception] = None) -> None:
        from ..storage import LLMUsageRecord

        usage = usage or {}
        try:
            with self._db.get_session() as session:
                today = date.today().isoformat()
                row = session.query(LLMUsageRecord).filter_by(day=today, route=route).first()
                if row is None:
                    row = LLMUsageRecord(day=today, route=route, calls=0, failures=0, cache_hits=0,
                                         prompt_tokens=0, completion_tokens=0)
                    session.add(row)
                if cached:
                    row.cache_hits = (row.cache_hits or 0) + 1
                elif ok:
                    row.calls = (row.calls or 0) + 1
                    row.prompt_tokens = (row.prompt_tokens or 0) + int(usage.get("prompt_tokens") or 0)
                    row.completion_tokens = (row.completion_tokens or 0) + int(usage.get("completion_tokens") or 0)
                else:
                    row.failures = (row.failures or 0) + 1
                    if error is not None:
                        row.last_error_kind = error_kind(error)
                        row.last_error = clean_error(error)
        except Exception as exc:
            logger.debug("LLM usage write failed: %s", exc)

    def usage(self, days: int = 7) -> list[dict]:
        from ..storage import LLMUsageRecord

        since = (date.today() - timedelta(days=days - 1)).isoformat()
        with self._db.get_session() as session:
            rows = session.query(LLMUsageRecord).filter(LLMUsageRecord.day >= since).all()
            return [
                {"day": r.day, "route": r.route, "calls": r.calls or 0, "failures": r.failures or 0,
                 "cache_hits": r.cache_hits or 0, "prompt_tokens": r.prompt_tokens or 0,
                 "completion_tokens": r.completion_tokens or 0, "last_error_kind": r.last_error_kind,
                 "last_error": r.last_error}
                for r in sorted(rows, key=lambda r: (r.day, r.route), reverse=True)
            ]
