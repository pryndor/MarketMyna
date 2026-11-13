"""Start MarketMyna: the `marketmyna` command (pip / pipx install) and start.py.

    marketmyna                      # the default face (web unless you saved tui)
    marketmyna web                  # web app at http://127.0.0.1:8001, opens your browser
    marketmyna tui                  # terminal app (joins a running server, or starts one)
    marketmyna mode tui             # make the terminal app the default (mode web to undo)
    marketmyna --port 9000 --no-browser

Both faces use the same server and the same data in ~/.marketmyna: run
`marketmyna web` in one window and `marketmyna tui` in another, or press w in
the terminal app to open the same running app in your browser.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import urllib.request
import webbrowser

COMMANDS = ("web", "tui", "mode")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="marketmyna", description="Start MarketMyna in your browser (web) or in this terminal (tui).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n  marketmyna web\n  marketmyna tui\n  marketmyna mode tui    # plain `marketmyna` opens the terminal app")
    p.add_argument("command", nargs="?", choices=COMMANDS, metavar="{web,tui,mode}",
                   help="web: the browser app; tui: the terminal app; mode web|tui: save the default")
    p.add_argument("value", nargs="?", help=argparse.SUPPRESS)
    p.add_argument("--host", default="127.0.0.1",
                   help="address to listen on (default 127.0.0.1: only this computer can reach it)")
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--no-browser", action="store_true", help="don't open the browser (web)")
    p.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    return p


def _version() -> str:
    from marketmyna import __version__
    return __version__


def resolve_mode(args: argparse.Namespace) -> str:
    """'web', 'tui' or 'mode' (save the default) for these arguments."""
    command = getattr(args, "command", None)
    if command:
        return command
    from marketmyna.core.ui_mode import default_mode

    mode = default_mode()
    if mode == "tui" and not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "web"  # no terminal to draw on (a service, CI): the web app is the only choice
    return mode


def open_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(1)


def _exit_now_if_threads_left() -> None:
    # The app has shut down; don't wait minutes at exit for download threads
    # (a first China / Hong Kong listing fetch) that nothing will read.
    if any(t.is_alive() and not t.daemon for t in threading.enumerate() if t is not threading.main_thread()):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


def run_web(args: argparse.Namespace) -> None:
    try:
        import uvicorn
    except ImportError:
        sys.exit("Install the requirements first: pip install -r requirements-web.txt")
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"MarketMyna: {url}  (Ctrl+C to stop; `marketmyna tui` in another terminal uses this same app)")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    # One process: the scheduler, price alerts and the Telegram bot run inside it.
    # Ctrl+C stops within a few seconds even while a slow data download is running.
    try:
        uvicorn.run("marketmyna.api.app:app", host=args.host, port=args.port, timeout_graceful_shutdown=5)
    except KeyboardInterrupt:
        pass
    _exit_now_if_threads_left()


def run_tui(args: argparse.Namespace) -> None:
    try:
        from marketmyna.tui.app import run as run_terminal_app
    except ImportError as exc:
        sys.exit(f"The terminal app needs Textual: pip install 'textual>=0.86' ({exc})")
    message = run_terminal_app(host=args.host, port=args.port)
    if message:
        print(message)
    _exit_now_if_threads_left()


def run_mode(args: argparse.Namespace) -> None:
    from marketmyna.core.ui_mode import MODES, default_mode, save_mode

    if not args.value:
        print(f"Default: {default_mode()}  (change it with: marketmyna mode web | marketmyna mode tui)")
        return
    if args.value not in MODES:
        sys.exit(f"marketmyna mode: choose web or tui, not {args.value!r}")
    save_mode(args.value)
    print(f"`marketmyna` now opens the {'terminal' if args.value == 'tui' else 'web'} app.")


def run(args: argparse.Namespace) -> None:
    mode = resolve_mode(args)
    if mode == "mode":
        run_mode(args)
    elif mode == "tui":
        run_tui(args)
    else:
        if args.value:
            sys.exit(f"marketmyna: unexpected argument {args.value!r}")
        run_web(args)


def main(argv: list[str] | None = None) -> None:
    run(parser().parse_args(argv))


if __name__ == "__main__":
    main()
