"""Where the app keeps its data: ~/.marketmyna, or MARKETMYNA_HOME if set."""

from __future__ import annotations

import os
from pathlib import Path


def app_home() -> Path:
    raw = os.environ.get("MARKETMYNA_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".marketmyna"


DB_FILENAME = "marketmyna.db"
LEGACY_DB_FILENAME = "stockpulse.db"  # the project's old name


def db_filename(folder: Path) -> str:
    """marketmyna.db, unless only an old stockpulse.db exists in folder."""
    if not (folder / DB_FILENAME).exists() and (folder / LEGACY_DB_FILENAME).exists():
        return LEGACY_DB_FILENAME
    return DB_FILENAME
