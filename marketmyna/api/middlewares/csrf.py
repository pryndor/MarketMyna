"""Refuse cross-site writes to the API (CSRF defence in depth).

The session is an HttpOnly cookie (marketmyna/api/middlewares/auth.py) with
SameSite=Lax, which already stops other sites' forms and fetches from
sending it on POST. This adds a second, header-based check so a cookie
policy change, an old browser or a sibling subdomain can't be used to make
a signed-in user's browser change their account, alerts or keys.

For POST / PUT / PATCH / DELETE under /api/:
- Sec-Fetch-Site (sent by every current browser) must be "same-origin" or
  "none"; anything else needs an Origin on the allowed list.
- Without Sec-Fetch-Site, an Origin header, if present, must match the
  request's own host or the allowed list.
- No browser headers at all (server-to-server, tests, curl) passes: that
  caller has no victim's cookie to ride on.
"""

from __future__ import annotations

import json
import logging
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SKIP_PREFIXES: tuple[str, ...] = ()


class CSRFMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: list[str] | None = None) -> None:
        self.app = app
        self.allowed = {o.rstrip("/").lower() for o in (allowed_origins or [])}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self._allowed(scope):
            logger.warning("CSRF: refused %s %s", scope.get("method"), scope.get("path"))
            body = json.dumps({"detail": "Cross-site request refused"}).encode()
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)

    def _allowed(self, scope: Scope) -> bool:
        path = scope.get("path", "")
        if scope.get("method") not in UNSAFE_METHODS or not path.startswith("/api/"):
            return True
        if path.startswith(SKIP_PREFIXES):
            return True
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        origin = (headers.get("origin") or "").rstrip("/").lower()
        fetch_site = (headers.get("sec-fetch-site") or "").lower()
        if fetch_site:
            return fetch_site in ("same-origin", "none") or (origin != "" and origin in self.allowed)
        if not origin or origin == "null":
            # Some privacy setups send "Origin: null"; without Sec-Fetch-Site
            # there's nothing better to go on, and SameSite=Lax still applies.
            return True
        if origin in self.allowed:
            return True
        host = (headers.get("x-forwarded-host") or headers.get("host") or "").split(",")[0].strip().lower()
        return urlsplit(origin).netloc == host
