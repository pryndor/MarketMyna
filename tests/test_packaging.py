"""The package version is set in two places; they must match."""

import tomllib
from pathlib import Path

import marketmyna


def test_version_matches_pyproject():
    pyproject = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == marketmyna.__version__
