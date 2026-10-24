"""Single-user build: there is no login. Every request runs as the one
local owner, an admin account made on first use (accounts.ensure_local_owner),
so the per-user data scoping underneath works unchanged. Run it only where
you alone can reach it (localhost, a VPN, or behind your own proxy auth).
"""

from __future__ import annotations

import logging
import os
import threading

import anyio
from fastapi import APIRouter, Request
from starlette.types import ASGIApp, Receive, Scope, Send

from src.core import tenant

logger = logging.getLogger(__name__)

OPEN_PATHS = ("/health", "/api/health", "/api/auth/")


def accounts_config():
    """The app Config the owner lookup uses. Tests patch this."""
    from api.deps import get_config_dep

    return get_config_dep()


def accounts_db(config):
    from src.storage import DatabaseManager, get_db_url

    return DatabaseManager.instance(get_db_url(config=config))


_owner_ids: dict[str, int] = {}
_owner_lock = threading.Lock()


def local_owner_id(config) -> int:
    """Id of the local owner account, made on first use (cached per database)."""
    from src.storage import get_db_url

    url = get_db_url(config=config)
    with _owner_lock:
        if url not in _owner_ids:
            from src.services.accounts import ensure_local_owner

            with accounts_db(config).get_session() as session, tenant.system_scope():
                _owner_ids[url] = ensure_local_owner(session).id
        return _owner_ids[url]


def _session_user(config, raw: str | None):
    """(user_id, role): always the local owner."""
    return local_owner_id(config), "admin"


def current_user_from_request(request: Request, session):
    """The local owner's UserRecord (in the caller's DB session)."""
    from src.storage import UserRecord

    return session.get(UserRecord, local_owner_id(accounts_config()))


def api_docs_enabled() -> bool:
    """/docs, /redoc and /openapi.json exist only with API_DOCS=1."""
    return os.environ.get("API_DOCS", "").strip() == "1"


def check_auth_config() -> None:
    """Turns per-user scoping on (every request runs as the local owner)."""
    from api.deps import get_config_dep

    get_config_dep().accounts_enabled = True


def is_authenticated(scope: Scope) -> bool:
    """Always true: the request runs as the local owner."""
    state = scope.setdefault("state", {})
    state["user_id"], state["user_role"] = _session_user(accounts_config(), None)
    return True


def require_admin(request: Request) -> None:
    """Dependency kept on admin routes (AI configuration, integrations). The
    local owner is the admin, so it always passes."""


class AuthMiddleware:
    """Puts every request in the owner's data scope. Pure ASGI (not
    BaseHTTPMiddleware) so SSE streams pass through untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or scope.get("path", "").startswith(OPEN_PATHS):
            await self.app(scope, receive, send)
            return
        # The owner lookup hits the database on first use: keep it off the event loop.
        await anyio.to_thread.run_sync(is_authenticated, scope)
        token = tenant.set_scope(scope["state"]["user_id"])
        try:
            await self.app(scope, receive, send)
        finally:
            tenant.reset_scope(token)


router = APIRouter()


@router.get("/status")
def auth_status(request: Request) -> dict:
    return {"authenticated": is_authenticated(request.scope)}
