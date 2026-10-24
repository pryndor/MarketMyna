"""Matrix room sender (any homeserver, e.g. matrix.org or Element)."""

from __future__ import annotations

import time
import uuid
from typing import Optional
from urllib.parse import quote

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, http_ok


class MatrixSender:
    def __init__(self, config):
        self._homeserver = (getattr(config, "matrix_homeserver", None) or "").rstrip("/")
        self._token = getattr(config, "matrix_access_token", None)
        self._room = getattr(config, "matrix_room_id", None)

    def is_configured(self) -> bool:
        return bool(self._homeserver and self._token and self._room)

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT) -> bool:
        if not self.is_configured():
            return False
        txn = f"marketmyna-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        url = f"{self._homeserver}/_matrix/client/v3/rooms/{quote(self._room, safe='')}/send/m.room.message/{txn}"
        body = {"msgtype": "m.text", "body": f"{title or DEFAULT_TITLE}\n\n{message}"}
        return http_ok("Matrix", "PUT", url, json=body, headers={"Authorization": f"Bearer {self._token}"}, timeout=timeout)
