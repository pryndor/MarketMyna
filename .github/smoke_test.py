"""CI: start MarketMyna, wait for /health, load the page and an API route,
then stop it. Works the same on Linux, Windows and macOS.

    python .github/smoke_test.py               # python start.py in this checkout
    python .github/smoke_test.py marketmyna    # the installed command, run from another folder
"""

import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:8011"


def get(path: str) -> str:
    with urllib.request.urlopen(URL + path, timeout=10) as r:
        return r.read().decode("utf-8")


def main() -> None:
    home = tempfile.mkdtemp()
    env = {**__import__("os").environ, "MARKETMYNA_HOME": home}
    cmd, cwd = (sys.argv[1:], home) if sys.argv[1:] else ([sys.executable, "start.py"], ROOT)
    app = subprocess.Popen([*cmd, "--no-browser", "--port", "8011"], cwd=cwd, env=env)
    try:
        for _ in range(90):
            try:
                get("/health")
                break
            except OSError:
                if app.poll() is not None:
                    sys.exit(f"{cmd[-1]} exited with {app.returncode}")
                time.sleep(1)
        else:
            sys.exit("the app did not answer /health in 90 s")
        assert '<div id="root">' in get("/"), "the page is not served"
        assert '<div id="root">' in get("/markets"), "app routes do not fall back to the page"
        assert get("/api/v1/watchlists").startswith("["), "the API does not answer"
        assert (Path(home) / "marketmyna.db").is_file(), "the SQLite database was not created"
        print("ok: page, routes, API and database")
    finally:
        app.terminate()
        app.wait(timeout=30)


if __name__ == "__main__":
    main()
