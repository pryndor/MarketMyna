"""Which face `marketmyna` opens by default: the web app or the terminal app.

Saved in ~/.marketmyna/ui.json. `marketmyna web` and `marketmyna tui` always
open the one they name; plain `marketmyna` opens the saved default (web
when nothing is saved, or MARKETMYNA_UI=web|tui to override).
"""

from __future__ import annotations

import json
import os

from marketmyna.core.home import app_home

MODES = ("web", "tui")
DEFAULT = "web"


def _path():
    return app_home() / "ui.json"


def saved_mode() -> str:
    try:
        mode = json.loads(_path().read_text(encoding="utf-8")).get("default")
    except (OSError, ValueError, AttributeError):
        return DEFAULT
    return mode if mode in MODES else DEFAULT


def default_mode() -> str:
    env = os.environ.get("MARKETMYNA_UI", "").strip().lower()
    return env if env in MODES else saved_mode()


def save_mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"Choose one of: {', '.join(MODES)}")
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"default": mode}) + "\n", encoding="utf-8")
    return mode
