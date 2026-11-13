"""Find a running MarketMyna server, or start one inside this process.

The web app and the terminal app share one engine: the FastAPI server that
owns the database, the scheduler, price alerts and the Telegram bot. The
terminal app first looks for a server that is already running (say, one
started with `marketmyna web`); without one it runs the server on a
background thread, logging to a file so nothing is written over the screen.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx


def is_marketmyna(url: str, timeout: float = 2.0) -> bool:
    """True when a MarketMyna server answers at url (not some other program on that port)."""
    try:
        with httpx.Client(base_url=url, timeout=timeout) as http:
            if http.get("/health").json().get("status") != "ok":
                return False
            return "configured" in http.get("/api/v1/agent/status").json()
    except (httpx.HTTPError, ValueError, AttributeError):
        return False


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def free_port(host: str, start: int) -> int:
    for port in range(start + 1, start + 50):
        if port_free(host, port):
            return port
    with socket.socket() as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def log_to_file(path: Path) -> None:
    """Send every log line to path instead of the terminal."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    logging.captureWarnings(True)


class LocalServer:
    """The MarketMyna server on a background thread of this process."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.server = None
        self.thread: threading.Thread | None = None
        self.error: BaseException | None = None

    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
        return f"http://{host}:{self.port}"

    def start(self, timeout: float = 180.0) -> None:
        import uvicorn

        config = uvicorn.Config("marketmyna.api.app:app", host=self.host, port=self.port,
                                log_config=None, timeout_graceful_shutdown=5)
        self.server = uvicorn.Server(config)

        def run() -> None:
            try:
                self.server.run()
            except BaseException as exc:  # noqa: BLE001 - reported to the caller below
                self.error = exc

        self.thread = threading.Thread(target=run, name="marketmyna-server", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.server.started:
                return
            if not self.thread.is_alive():
                raise RuntimeError(f"The MarketMyna server stopped while starting: {self.error or 'see the log file'}")
            time.sleep(0.2)
        raise RuntimeError("The MarketMyna server did not start in time (see the log file).")

    def stop(self, timeout: float = 10.0) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout)


def connect(host: str, port: int, log_file: Path) -> tuple[str, LocalServer | None]:
    """(server url, the server this process started or None when it joined a running one)."""
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    if is_marketmyna(url):
        return url, None
    if not port_free(host, port):
        port = free_port(host, port)  # something else is on the port: use the next free one
    log_to_file(log_file)
    server = LocalServer(host, port)
    server.start()
    return server.url, server
