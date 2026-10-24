"""Treat /api/v1/foo/ the same as /api/v1/foo instead of redirecting.

FastAPI's default answer to a trailing-slash mismatch is a 307 to an
absolute URL built from the Host header and scheme it sees, which behind a
proxy can be the internal address. Stripping the slash before routing
avoids the redirect (and its extra round trip) entirely.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


class StripTrailingSlashMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if len(path) > 1 and path.endswith("/"):
                scope = dict(scope)
                scope["path"] = path.rstrip("/") or "/"
                raw = scope.get("raw_path")
                if raw:
                    scope["raw_path"] = raw.rstrip(b"/") or b"/"
        await self.app(scope, receive, send)
