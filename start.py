"""Start MarketMyna on this computer: Linux, macOS or Windows.

    python start.py                 # http://127.0.0.1:8001, opens your browser
    python start.py --port 9000 --no-browser
    python start.py --rebuild       # rebuild the frontend even if it looks current

Run it with the Python of the virtual environment that has
requirements-web.txt installed. The frontend is built with Node.js 22 (npm)
on the first run and again whenever its source is newer than the last build
(after a git pull); otherwise the app starts straight away.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


def _stale(built: Path) -> bool:
    """True when the build is missing or older than any frontend source file."""
    if not built.is_file():
        return True
    done = built.stat().st_mtime
    sources = [FRONTEND / name for name in ("package.json", "package-lock.json", "index.html", "vite.config.ts")]
    for folder in ("src", "public"):
        sources += [p for p in (FRONTEND / folder).rglob("*") if p.is_file()]
    return any(p.is_file() and p.stat().st_mtime > done for p in sources)


def build_frontend(force: bool) -> None:
    if not force and not _stale(FRONTEND / "dist" / "index.html"):
        return
    npm = shutil.which("npm")  # npm.cmd on Windows
    if npm is None:
        sys.exit("The frontend is built once with Node.js 22 (npm). Install it from https://nodejs.org/ and run again.")
    print("Building the frontend...")
    for args in (["ci"], ["run", "build"]):
        subprocess.run([npm, *args], cwd=FRONTEND, check=True)


def open_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Start MarketMyna.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to listen on (default 127.0.0.1: only this computer can reach it)")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--no-browser", action="store_true", help="don't open the browser")
    parser.add_argument("--rebuild", action="store_true", help="rebuild the frontend first")
    args = parser.parse_args(argv)

    if sys.version_info < (3, 10):
        sys.exit("MarketMyna needs Python 3.10 or newer (3.12 recommended).")
    try:
        import uvicorn
    except ImportError:
        sys.exit("Install the requirements first: pip install -r requirements-web.txt")

    build_frontend(args.rebuild)
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"MarketMyna: {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    # One process: the scheduler, price alerts and the Telegram bot run inside it.
    uvicorn.run("api.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
