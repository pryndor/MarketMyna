"""Start MarketMyna: the `marketmyna` command (pip / pipx install) and start.py.

    marketmyna                      # http://127.0.0.1:8001, opens your browser
    marketmyna --port 9000 --no-browser
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import urllib.request
import webbrowser


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="marketmyna", description="Start MarketMyna.")
    p.add_argument("--host", default="127.0.0.1",
                   help="address to listen on (default 127.0.0.1: only this computer can reach it)")
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--no-browser", action="store_true", help="don't open the browser")
    p.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    return p


def _version() -> str:
    from marketmyna import __version__
    return __version__


def open_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(1)


def run(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ImportError:
        sys.exit("Install the requirements first: pip install -r requirements-web.txt")
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"MarketMyna: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    # One process: the scheduler, price alerts and the Telegram bot run inside it.
    # Ctrl+C stops within a few seconds even while a slow data download is running.
    try:
        uvicorn.run("marketmyna.api.app:app", host=args.host, port=args.port, timeout_graceful_shutdown=5)
    except KeyboardInterrupt:
        pass
    # The app has shut down; don't wait minutes at exit for download threads
    # (a first China / Hong Kong listing fetch) that nothing will read.
    if any(t.is_alive() and not t.daemon for t in threading.enumerate() if t is not threading.main_thread()):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


def main(argv: list[str] | None = None) -> None:
    run(parser().parse_args(argv))


if __name__ == "__main__":
    main()
