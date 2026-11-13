"""A small HTTP client for the MarketMyna API.

The terminal app is a client of the same server the web app uses, so both
always show the same data and every feature behaves the same way.
"""

from __future__ import annotations

from typing import Any

import httpx


class ApiError(Exception):
    """A request failed: the message is fit to show to the user."""


def _message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return f"{resp.status_code} {resp.reason_phrase}"
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                where = ".".join(str(p) for p in first.get("loc", [])[1:])
                return f"{where}: {first.get('msg', 'invalid')}" if where else str(first.get("msg", "invalid"))
        if body.get("message"):
            return str(body["message"])
    return f"{resp.status_code} {resp.reason_phrase}"


class Api:
    """Sync client (the terminal app calls it from worker threads)."""

    def __init__(self, base_url: str, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        # No Origin / Sec-Fetch-Site headers: the CSRF check lets a non-browser caller through.
        self.http = httpx.Client(base_url=self.base_url, timeout=timeout, headers={"user-agent": "marketmyna-tui"})

    def close(self) -> None:
        self.http.close()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not path.startswith("/api/") and path not in ("/health",):
            path = "/api/v1" + (path if path.startswith("/") else "/" + path)
        try:
            resp = self.http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ApiError("The request took too long. Try again in a moment.") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Can't reach MarketMyna at {self.base_url}: {exc}") from exc
        if resp.status_code >= 400:
            raise ApiError(_message(resp))
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        return self.request("GET", path, params=clean)

    def post(self, path: str, body: Any = None) -> Any:
        return self.request("POST", path, json=body)

    def put(self, path: str, body: Any = None) -> Any:
        return self.request("PUT", path, json=body)

    def patch(self, path: str, body: Any = None) -> Any:
        return self.request("PATCH", path, json=body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def command(self, text: str) -> tuple[str, bool]:
        """Run a chat command (the same ones the Telegram bot and the web console take)."""
        out = self.post("/bot/command", {"text": text})
        return str(out.get("text", "")), bool(out.get("success", False))
