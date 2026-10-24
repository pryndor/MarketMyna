"""Updates (Settings), against github.com/pryndor/MarketMyna.

Checking:
- releases: the running version against the latest release (every install);
- the main branch: a git checkout also compares its commit with GitHub's
  latest, so new code shows up before it is released.
A background thread checks on its own every few minutes (5 min, 1 h, 2 h or
off, saved in ~/.marketmyna/updates.json), so the sidebar can say an update
is waiting without anyone pressing a button.

Updating ("Update now"): a git checkout fetches main and moves to it (a
backup branch keeps the old commit; local edits stop it), a pipx / pip install
upgrades the package; both then install the requirements and restart the
app. A release zip is updated by hand (download the new zip).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from marketmyna import __version__
from marketmyna.api.middlewares.auth import require_admin
from marketmyna.core.home import app_home

log = logging.getLogger(__name__)

router = APIRouter(prefix="/system/updates", dependencies=[Depends(require_admin)])

REPO = "pryndor/MarketMyna"
BRANCH = "main"
REPO_GIT = f"https://github.com/{REPO}.git"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
COMMIT_URL = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
REPO_PAGE = f"https://github.com/{REPO}"
# GitHub allows 60 unauthenticated calls an hour; a check is 2 calls, so even
# every 5 minutes uses under half. Answers younger than this are reused.
CACHE_SECONDS = 240
_cache: dict = {"at": 0.0, "release": None, "commit_at": 0.0, "commit": None}

# How often the background thread checks, in minutes (0 = off).
INTERVALS = (0, 5, 60, 120)
DEFAULT_INTERVAL = 5

ROOT = Path(__file__).resolve().parents[4]


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2); anything after the numbers (rc1, -beta) is ignored."""
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    width = max(len(a), len(b))
    return (a + (0,) * (width - len(a))) > (b + (0,) * (width - len(b)))


def install_kind() -> str:
    """'source': a git checkout; 'zip': a release zip run with start.py; 'package': pipx / pip."""
    if not (ROOT / "start.py").exists():
        return "package"
    return "source" if (ROOT / ".git").exists() else "zip"


UPDATE_STEPS = {
    "source": ["git pull", "pip install -r requirements-web.txt", "python start.py --rebuild"],
    "zip": ["Download the new zip from the releases page, unpack it, then run: pip install -r requirements-web.txt && python start.py"],
    "package": ["pipx upgrade marketmyna"],
}


# ------------------------------------------------------------------ settings

def _settings_file() -> Path:
    return app_home() / "updates.json"


def load_settings() -> dict:
    try:
        data = json.loads(_settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    interval = data.get("interval_minutes", DEFAULT_INTERVAL)
    return {"interval_minutes": interval if interval in INTERVALS else DEFAULT_INTERVAL}


def save_settings(settings: dict) -> None:
    path = _settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings), encoding="utf-8")


# ------------------------------------------------------------------ GitHub

def _github(url: str):
    response = httpx.get(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": f"MarketMyna/{__version__}"},
        timeout=10,
        follow_redirects=True,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _latest_release(force: bool = False) -> dict | None:
    """The newest published release, or None when the repo has none yet."""
    now = time.time()
    if not force and _cache["at"] and now - _cache["at"] < CACHE_SECONDS:
        return _cache["release"]
    data = _github(RELEASES_URL)
    release = None
    if data:
        release = {
            "version": str(data.get("tag_name") or "").lstrip("v"),
            "name": data.get("name") or data.get("tag_name") or "",
            "url": data.get("html_url") or RELEASES_PAGE,
            "published_at": data.get("published_at"),
            "notes": (data.get("body") or "")[:4000],
        }
    _cache.update(at=now, release=release)
    return release


def _latest_commit(force: bool = False) -> dict | None:
    """The newest commit on GitHub's main branch."""
    now = time.time()
    if not force and _cache["commit_at"] and now - _cache["commit_at"] < CACHE_SECONDS:
        return _cache["commit"]
    data = _github(COMMIT_URL)
    commit = None
    if data:
        info = data.get("commit") or {}
        commit = {
            "sha": data.get("sha") or "",
            "date": (info.get("committer") or {}).get("date"),
            "message": (info.get("message") or "").split("\n")[0][:200],
            "url": data.get("html_url") or REPO_PAGE,
        }
    _cache.update(commit_at=now, commit=commit)
    return commit


def _git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=timeout)


def local_commit() -> dict | None:
    """This checkout's commit (sha and unix time), or None without git."""
    try:
        out = _git("log", "-1", "--format=%H %ct", timeout=5).stdout.split()
        return {"sha": out[0], "time": int(out[1])}
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return None


def code_status(local: dict | None, remote: dict | None) -> dict | None:
    """Is GitHub's main branch newer than this checkout? Newer by commit time,
    so local work that is not pushed yet never reads as an update."""
    if not local or not remote or not remote.get("sha"):
        return None
    try:
        remote_time = datetime.fromisoformat(str(remote["date"]).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        remote_time = 0
    same = remote["sha"] == local["sha"]
    return {
        "local_sha": local["sha"][:7],
        "remote_sha": remote["sha"][:7],
        "remote_date": remote.get("date"),
        "message": remote.get("message"),
        "url": remote.get("url"),
        "update_available": not same and remote_time > local["time"],
    }


# The last result, from a button press or the background thread.
_last: dict = {}


def check(force: bool = False) -> dict:
    kind = install_kind()
    result = {
        "current": __version__,
        "install": kind,
        "commands": UPDATE_STEPS[kind],
        "can_apply": kind in ("source", "package"),
        "repo_url": REPO_PAGE,
        "releases_url": RELEASES_PAGE,
        "checked_at": int(time.time()),
        "settings": load_settings(),
    }
    try:
        release = _latest_release(force)
        code = code_status(local_commit(), _latest_commit(force)) if kind == "source" else None
    except (httpx.HTTPError, ValueError) as exc:
        result.update(latest=None, release=None, release_available=False, code=None, update_available=False,
                      error=f"Could not reach GitHub: {exc}")
    else:
        release_newer = bool(release and release["version"]) and is_newer(release["version"], __version__)
        result.update(
            latest=release["version"] if release else None,
            release=release,
            release_available=release_newer,
            code=code,
            # A git checkout follows main; a package / zip install follows releases.
            update_available=release_newer or bool(code and code["update_available"]),
            error=None,
        )
    _last.clear()
    _last.update(result)
    return result


def check_loop(first_delay: int = 30) -> None:
    """Background thread: check GitHub at the chosen interval (re-read each round)."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # tests never call GitHub
    time.sleep(first_delay)
    while True:
        minutes = load_settings()["interval_minutes"]
        if minutes:
            try:
                result = check()
                if result.get("update_available"):
                    log.info("MarketMyna update available on GitHub (%s)", result.get("latest") or (result.get("code") or {}).get("remote_sha"))
            except Exception:  # never let the thread die
                log.exception("Update check failed")
        time.sleep(max(minutes, 5) * 60)


# ------------------------------------------------------------------ applying

_apply_lock = threading.Lock()


def _run(cmd: list[str], logs: list[str], cwd: Path | None = None, timeout: int = 900) -> None:
    logs.append("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    output = (proc.stdout + proc.stderr).strip()
    if output:
        logs.append(output[-3000:])
    if proc.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd)}` failed (exit {proc.returncode})")


def apply_source(logs: list[str]) -> None:
    """Move this checkout to GitHub's main. Fast-forward when possible; when the
    history was rewritten, keep the old commit on a backup branch first."""
    if _git("status", "--porcelain", "--untracked-files=no", timeout=10).stdout.strip():
        raise RuntimeError("This copy has local changes to MarketMyna's files. Commit or stash them, then update.")
    _run(["git", "-C", str(ROOT), "fetch", REPO_GIT, BRANCH], logs)
    head = _git("rev-parse", "HEAD", timeout=10).stdout.strip()
    target = _git("rev-parse", "FETCH_HEAD", timeout=10).stdout.strip()
    if head == target:
        logs.append("Already at the latest code.")
    elif _git("merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD", timeout=10).returncode == 0:
        _run(["git", "-C", str(ROOT), "merge", "--ff-only", "FETCH_HEAD"], logs)
    else:
        backup = f"marketmyna-backup-{time.strftime('%Y%m%d-%H%M%S')}"
        _run(["git", "-C", str(ROOT), "branch", backup, "HEAD"], logs)
        logs.append(f"Your previous commit is kept on branch {backup}.")
        _run(["git", "-C", str(ROOT), "reset", "--hard", "FETCH_HEAD"], logs)
    changed = _git("diff", "--name-only", head, "HEAD", timeout=10).stdout.split()
    if "requirements-web.txt" in changed:
        install_requirements(logs)
    else:
        logs.append("Requirements unchanged; nothing to install.")


def install_requirements(logs: list[str]) -> None:
    """pip install the requirements. A Python that refuses pip (a system Python,
    PEP 668 "externally managed") is reported, not treated as a failed update."""
    cmd = [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements-web.txt"]
    logs.append("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode == 0:
        if output:
            logs.append(output[-3000:])
        return
    if "externally-managed-environment" in output:
        logs.append("This Python does not allow pip installs (a system Python). The new requirements were "
                    "not installed: run `pip install -r requirements-web.txt` in your virtual environment.")
        return
    logs.append(output[-3000:])
    raise RuntimeError(f"`{' '.join(cmd)}` failed (exit {proc.returncode})")


def apply_package(logs: list[str]) -> None:
    _run([sys.executable, "-m", "pip", "install", "-q", "--upgrade", "marketmyna"], logs)


def restart_command(kind: str, argv: list[str]) -> list[str]:
    """How to start this app again with the same options (and no new browser tab)."""
    args = [a for a in argv if a != "--rebuild"]
    if "--no-browser" not in args:
        args.append("--no-browser")
    if kind == "source":
        return [sys.executable, str(ROOT / "start.py"), *args]
    return [sys.executable, "-m", "marketmyna.launcher", *args]


def restart(kind: str, delay: float = 1.5) -> None:
    """Start the app again with the same options. Linux / macOS replace this
    process in place (same terminal, Ctrl+C still works; the listening socket is
    closed on exec, so the port is free). Windows starts a fresh copy once this
    one has exited. A source install rebuilds the frontend on that start."""
    cmd = restart_command(kind, sys.argv[1:])
    cwd = str(ROOT) if kind == "source" else os.getcwd()

    def go() -> None:
        time.sleep(delay)  # let the HTTP answer reach the browser
        sys.stdout.flush()
        sys.stderr.flush()
        if os.name != "nt":
            os.chdir(cwd)
            os.execv(cmd[0], cmd)
        helper = f"import subprocess, time; time.sleep(3); subprocess.Popen({cmd!r}, cwd={cwd!r})"
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        subprocess.Popen([sys.executable, "-c", helper], creationflags=flags)
        os._exit(0)

    threading.Thread(target=go, name="update-restart", daemon=True).start()


# ------------------------------------------------------------------ routes

@router.get("")
def get_updates(force: bool = False) -> dict:
    """force=true (the button) asks GitHub now; otherwise a recent answer is reused."""
    return check(force=force)


@router.get("/status")
def last_status() -> dict:
    """What the background thread found last (for the sidebar); never calls GitHub."""
    return dict(_last) if _last else {"current": __version__, "update_available": False, "checked_at": None}


class UpdateSettingsIn(BaseModel):
    interval_minutes: int


@router.put("/settings")
def put_settings(body: UpdateSettingsIn) -> dict:
    if body.interval_minutes not in INTERVALS:
        raise HTTPException(status_code=400, detail=f"interval_minutes must be one of {list(INTERVALS)}")
    settings = {"interval_minutes": body.interval_minutes}
    save_settings(settings)
    return settings


@router.post("/apply")
def apply_update() -> dict:
    kind = install_kind()
    if kind == "zip":
        raise HTTPException(status_code=400, detail="A release-zip copy is updated by downloading the new zip from the releases page.")
    if not _apply_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="An update is already running.")
    logs: list[str] = []
    try:
        status = check(force=True)
        if status.get("error"):
            raise HTTPException(status_code=502, detail=status["error"])
        if not status.get("update_available"):
            return {"updated": False, "restarting": False, "log": ["Already up to date."]}
        try:
            (apply_source if kind == "source" else apply_package)(logs)
        except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
            tail = "\n".join(logs[-6:])
            raise HTTPException(status_code=500, detail=f"{exc}\n\n{tail}".strip()) from exc
        logs.append("Update installed. Restarting MarketMyna...")
        restart(kind)
        return {"updated": True, "restarting": True, "log": logs}
    finally:
        _apply_lock.release()
