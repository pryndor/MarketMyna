"""The local owner account and helpers around it. Single-user build: no
sign-up or login; every request runs as the owner (marketmyna/api/middlewares/auth.py),
an admin account made on first use. Saved secrets (channel webhooks, AI keys)
are encrypted with AES-GCM using SECRET_KEY or a generated key file.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from marketmyna.core.home import app_home

from ..core import tenant
from ..storage import UserApiKeyRecord, UserRecord

logger = logging.getLogger(__name__)


class AccountError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


BYOK_PROVIDERS = ("gemini", "groq", "openrouter", "openai", "anthropic", "deepseek", "mistral")


LOCAL_OWNER_EMAIL = "owner@localhost"


def ensure_local_owner(session: Session) -> UserRecord:
    """Single-user build: the one account every request runs as. The first
    active admin if there is one, otherwise a fresh admin with no password
    (nobody logs in; the app is reachable only by whoever runs it)."""
    user = (session.query(UserRecord).filter_by(role="admin", status="active")
            .order_by(UserRecord.id).first())
    if user is not None:
        return user
    user = UserRecord(email=LOCAL_OWNER_EMAIL, display_name="Owner", role="admin", status="active",
                      email_verified_at=datetime.now())
    session.add(user)
    session.flush()
    adopt_unowned(session, user.id)
    logger.info("Created the local owner account")
    return user


def adopt_unowned(session: Session, user_id: int) -> int:
    """Gives rows saved before accounts existed (user_id NULL: portfolios,
    watchlists, alerts, ...) to the first admin, so switching a local
    install to log-in keeps its data. Returns the number of rows moved."""
    moved = 0
    with tenant.system_scope():
        for model in tenant.owned_models():
            moved += session.query(model).filter(model.user_id.is_(None)).update(
                {model.user_id: user_id}, synchronize_session=False)
    return moved


# ---------- email ----------


def report_sender(config, purpose: Optional[str]) -> Optional[str]:
    """From address for `purpose`: the reports address for scheduled reports
    and alerts, else None (the main sender)."""
    return (getattr(config, "email_reports_sender", None) or None) if purpose in ("report", "alert") else None


# ---------- saved secrets ----------


def _aes_key(config) -> bytes:
    secret = getattr(config, "secret_key", None)
    if not secret:
        path = Path(getattr(config, "app_dir", app_home())) / "secret.key"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
            path.chmod(0o600)
        secret = path.read_text(encoding="utf-8").strip()
    return hashlib.sha256(b"marketmyna-byok-v1:" + secret.encode()).digest()


def encrypt_secret(config, plaintext: str) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(_aes_key(config)).encrypt(nonce, plaintext.encode(), b"byok")


def decrypt_secret(config, blob: bytes) -> str:
    return AESGCM(_aes_key(config)).decrypt(blob[:12], blob[12:], b"byok").decode()


# ---------- AI keys ----------


MAX_API_KEYS = 10


def set_api_key(session: Session, config, user: UserRecord, provider: Optional[str], key: str) -> UserApiKeyRecord:
    """Saves a key. With no provider, works out the provider and model from the
    key itself (byok_detect), checking the provider accepts it. The same key
    saved again only refreshes what was detected."""
    provider = (provider or "").strip().lower()
    key = (key or "").strip()
    if len(key) < 8 or len(key) > 512 or any(c.isspace() for c in key):
        raise AccountError("That doesn't look like an API key.")
    if provider and provider not in BYOK_PROVIDERS:
        raise AccountError(f"Unsupported provider. Choose one of: {', '.join(BYOK_PROVIDERS)}.")
    rows = session.query(UserApiKeyRecord).filter_by(user_id=user.id).all()
    row = next((r for r in rows if r.key_last4 == key[-4:] and _same_secret(config, r, key)), None)
    if row is None and len(rows) >= MAX_API_KEYS:
        raise AccountError(f"You can keep up to {MAX_API_KEYS} keys. Remove one first.")
    detected = None
    if not provider:
        from .byok_detect import KeyDetectError, detect

        try:
            detected = detect(key)
        except KeyDetectError as exc:
            raise AccountError(str(exc)) from None
        provider = detected.provider
    if row is None:
        row = UserApiKeyRecord(user_id=user.id, key_ciphertext=encrypt_secret(config, key), key_last4=key[-4:],
                               created_at=datetime.now())
    row.provider = provider
    row.model = detected.model if detected else None
    row.free = detected.free if detected else None
    row.note = detected.note if detected else None
    try:
        with session.begin_nested():
            session.add(row)
    except IntegrityError:
        raise AccountError(f"This database keeps one {provider} key. Remove the old one first.", status=409) from None
    return row


def _same_secret(config, row: UserApiKeyRecord, key: str) -> bool:
    try:
        return decrypt_secret(config, row.key_ciphertext) == key
    except Exception:
        return False


def split_keys(raw: str) -> list[str]:
    """Several keys pasted at once: one per line, or separated by spaces or commas."""
    seen: list[str] = []
    for part in re.split(r"[\s,;]+", raw or ""):
        if part and part not in seen:
            seen.append(part)
    return seen


def set_api_keys(session: Session, config, user: UserRecord, provider: Optional[str], raw: str) -> list[str]:
    """Saves every key in `raw` (split_keys). Returns one message per key that
    failed; raises when none could be saved."""
    keys = split_keys(raw)
    if not keys:
        raise AccountError("Paste an API key.")
    errors = []
    for key in keys:
        try:
            set_api_key(session, config, user, provider, key)
        except AccountError as exc:
            if len(keys) == 1:
                raise
            errors.append(f"Key ending {key[-4:]}: {exc.message}")
    if len(errors) == len(keys):
        raise AccountError(" ".join(errors))
    return errors


def delete_api_key(session: Session, user: UserRecord, key_id: str) -> bool:
    """key_id: the key's id, or a provider name to remove all of its keys."""
    query = session.query(UserApiKeyRecord).filter_by(user_id=user.id)
    ref = (key_id or "").strip().lower()
    rows = query.filter_by(id=int(ref)).all() if ref.isdigit() else query.filter_by(provider=ref).all()
    for row in rows:
        session.delete(row)
    session.flush()
    return bool(rows)


def api_keys(session: Session, user: UserRecord) -> list[dict]:
    """In the order AI tries them (oldest first)."""
    return [
        {
            "id": r.id,
            "provider": r.provider,
            "last4": r.key_last4,
            "model": r.model,
            "free": r.free,
            "note": r.note,
            "added_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in session.query(UserApiKeyRecord).filter_by(user_id=user.id).order_by(UserApiKeyRecord.id)
    ]


# ---------- background work in accounts mode ----------

_owner_cache: dict[str, tuple[float, Optional[int]]] = {}
OWNER_CACHE_SECONDS = 60


def owner_user_id(config) -> Optional[int]:
    """The platform owner: the first admin account. Its scope gets the
    owner's channels (config.json) and the platform's scheduled report."""
    import time

    from ..storage import DatabaseManager, get_db_url

    url = get_db_url(config=config)
    hit = _owner_cache.get(url)
    if hit and time.time() - hit[0] < OWNER_CACHE_SECONDS:
        return hit[1]
    with DatabaseManager.instance(url).get_session() as session:
        row = (session.query(UserRecord.id).filter_by(role="admin", status="active")
               .order_by(UserRecord.id).first())
    owner = row[0] if row else None
    _owner_cache[url] = (time.time(), owner)
    return owner


def is_owner_scope(config) -> bool:
    """Whether the current data scope may use the owner's channels: always
    outside accounts mode; the system scope (errors) or the owner otherwise."""
    if not tenant.enabled():
        return True
    scope = tenant.current()
    if scope is tenant.SYSTEM:
        return True
    return scope is not None and scope == owner_user_id(config)


def owner_scope(config):
    """Runs the block as the platform owner in accounts mode (fails closed
    when there is no admin yet); a no-op otherwise."""
    import contextlib

    if not tenant.enabled():
        return contextlib.nullcontext()
    return tenant.user_scope(owner_user_id(config))


def active_user_ids(config) -> list[int]:
    from ..storage import DatabaseManager, get_db_url

    with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
        rows = (session.query(UserRecord.id)
                .filter(UserRecord.status == "active", UserRecord.email_verified_at.isnot(None))
                .order_by(UserRecord.id).all())
    return [r[0] for r in rows]


def for_each_user(config, fn, label: str) -> None:
    """Runs fn() once per active user in that user's scope (accounts mode),
    or once unscoped otherwise. One user's failure doesn't stop the rest."""
    if not tenant.enabled():
        fn()
        return
    for user_id in active_user_ids(config):
        try:
            with tenant.user_scope(user_id):
                fn()
        except Exception:
            logger.exception("%s failed for user %s", label, user_id)
