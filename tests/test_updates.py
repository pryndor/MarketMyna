"""Check for updates: version comparison and the endpoint (GitHub mocked)."""

import subprocess

import httpx
import pytest

from marketmyna import __version__
from marketmyna.api.v1.endpoints import updates


@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMYNA_HOME", str(tmp_path / "home"))
    updates._cache.update(at=0.0, release=None, commit_at=0.0, commit=None)
    updates._last.clear()
    yield
    updates._cache.update(at=0.0, release=None, commit_at=0.0, commit=None)
    updates._last.clear()


def test_version_compare():
    assert updates.parse_version("v0.10.2") == (0, 10, 2)
    assert updates.is_newer("0.10.0", "0.9.9")
    assert updates.is_newer("v1.0", "0.9")
    assert not updates.is_newer("0.2.0", "0.2")
    assert not updates.is_newer("0.1.0", "0.2.0")
    assert not updates.is_newer("", "0.2.0")


class _Response:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def test_update_available(app_client, monkeypatch):
    monkeypatch.setattr(
        updates.httpx, "get",
        lambda *a, **k: _Response({"tag_name": "v99.0.0", "name": "v99", "html_url": "https://example.test/r", "body": "notes"}),
    )
    data = app_client().get("/api/v1/system/updates").json()
    assert data["current"] == __version__
    assert data["latest"] == "99.0.0"
    assert data["update_available"] is True
    assert data["release"]["url"] == "https://example.test/r"
    assert data["commands"]


def test_up_to_date(app_client, monkeypatch):
    monkeypatch.setattr(updates.httpx, "get", lambda *a, **k: _Response({"tag_name": f"v{__version__}"}))
    data = app_client().get("/api/v1/system/updates").json()
    assert data["update_available"] is False
    assert data["error"] is None


def test_github_unreachable(app_client, monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(updates.httpx, "get", boom)
    data = app_client().get("/api/v1/system/updates").json()
    assert data["update_available"] is False
    assert data["latest"] is None
    assert "GitHub" in data["error"]


def test_no_release_yet(app_client, monkeypatch):
    monkeypatch.setattr(updates.httpx, "get", lambda *a, **k: _Response({}, status_code=404))
    data = app_client().get("/api/v1/system/updates").json()
    assert data["latest"] is None
    assert data["update_available"] is False
    assert data["error"] is None


def test_code_status_newer_on_github():
    local = {"sha": "a" * 40, "time": 1_700_000_000}
    remote = {"sha": "b" * 40, "date": "2030-01-01T00:00:00Z", "message": "m", "url": "u"}
    status = updates.code_status(local, remote)
    assert status["update_available"] is True
    assert status["remote_sha"] == "bbbbbbb"


def test_code_status_local_is_newer_or_same():
    remote = {"sha": "b" * 40, "date": "2020-01-01T00:00:00Z"}
    assert updates.code_status({"sha": "a" * 40, "time": 1_700_000_000}, remote)["update_available"] is False
    assert updates.code_status({"sha": "b" * 40, "time": 0}, remote)["update_available"] is False
    assert updates.code_status(None, remote) is None


def test_source_install_sees_new_commit(app_client, monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "source")
    monkeypatch.setattr(updates, "local_commit", lambda: {"sha": "a" * 40, "time": 1_700_000_000})

    def fake_get(url, **_):
        if url == updates.COMMIT_URL:
            return _Response({"sha": "c" * 40, "html_url": "https://example.test/c",
                              "commit": {"message": "New feature\n\nbody", "committer": {"date": "2030-01-01T00:00:00Z"}}})
        return _Response({"tag_name": f"v{__version__}"})

    monkeypatch.setattr(updates.httpx, "get", fake_get)
    data = app_client().get("/api/v1/system/updates").json()
    assert data["release_available"] is False
    assert data["code"]["update_available"] is True
    assert data["code"]["message"] == "New feature"
    assert data["update_available"] is True


# ------------------------------------------------------------------ settings

def test_interval_setting_saved_and_validated(app_client):
    client = app_client()
    assert updates.load_settings() == {"interval_minutes": updates.DEFAULT_INTERVAL}
    assert client.put("/api/v1/system/updates/settings", json={"interval_minutes": 120}).status_code == 200
    assert updates.load_settings() == {"interval_minutes": 120}
    assert client.put("/api/v1/system/updates/settings", json={"interval_minutes": 7}).status_code == 400


def test_status_reuses_last_check(app_client, monkeypatch):
    monkeypatch.setattr(updates.httpx, "get", lambda *a, **k: _Response({"tag_name": "v99.0.0"}))
    client = app_client()
    assert client.get("/api/v1/system/updates/status").json()["checked_at"] is None
    client.get("/api/v1/system/updates")
    status = client.get("/api/v1/system/updates/status").json()
    assert status["update_available"] is True and status["latest"] == "99.0.0"


# ------------------------------------------------------------------ applying

def test_apply_refuses_zip_install(app_client, monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "zip")
    assert app_client().post("/api/v1/system/updates/apply").status_code == 400


def test_apply_when_up_to_date_does_nothing(app_client, monkeypatch):
    monkeypatch.setattr(updates, "install_kind", lambda: "package")
    monkeypatch.setattr(updates.httpx, "get", lambda *a, **k: _Response({"tag_name": f"v{__version__}"}))
    restarted = []
    monkeypatch.setattr(updates, "restart", lambda kind: restarted.append(kind))
    data = app_client().post("/api/v1/system/updates/apply").json()
    assert data["updated"] is False and not restarted


def test_restart_command_keeps_options_without_new_tab():
    cmd = updates.restart_command("source", ["--port", "9000", "--rebuild"])
    assert cmd[1].endswith("start.py") and cmd[2:] == ["--port", "9000", "--no-browser"]
    assert updates.restart_command("package", ["--no-browser"])[1:] == ["-m", "marketmyna.launcher", "--no-browser"]


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "HOME": str(cwd), "PATH": __import__("os").environ["PATH"]})


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """An 'upstream' repo standing in for GitHub and a clone of it as this install."""
    upstream, local = tmp_path / "upstream", tmp_path / "local"
    upstream.mkdir()
    _git(upstream, "init", "-q", "-b", "main")
    (upstream / "requirements-web.txt").write_text("")
    (upstream / "app.txt").write_text("v1")
    _git(upstream, "add", ".")
    _git(upstream, "commit", "-q", "-m", "one")
    _git(tmp_path, "clone", "-q", str(upstream), str(local))
    monkeypatch.setattr(updates, "ROOT", local)
    monkeypatch.setattr(updates, "REPO_GIT", str(upstream))
    return upstream, local


def _head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


def test_apply_source_fast_forwards(repos):
    upstream, local = repos
    (upstream / "app.txt").write_text("v2")
    _git(upstream, "commit", "-q", "-am", "two")
    updates.apply_source(logs := [])
    assert _head(local) == _head(upstream)
    assert (local / "app.txt").read_text() == "v2"
    assert not any("backup" in line for line in logs)


def test_apply_source_rewritten_history_keeps_backup(repos):
    upstream, local = repos
    old = _head(local)
    (upstream / "app.txt").write_text("v2")
    _git(upstream, "commit", "-q", "--amend", "-am", "one, amended")  # history rewritten (force-push)
    updates.apply_source(logs := [])
    assert _head(local) == _head(upstream)
    branches = subprocess.run(["git", "branch", "--format=%(refname:short) %(objectname)"], cwd=local,
                              capture_output=True, text=True).stdout
    assert any(line.startswith("marketmyna-backup-") and line.endswith(old) for line in branches.splitlines())


def test_apply_source_stops_on_local_edits(repos):
    upstream, local = repos
    (upstream / "app.txt").write_text("v2")
    _git(upstream, "commit", "-q", "-am", "two")
    (local / "app.txt").write_text("my edit")
    with pytest.raises(RuntimeError, match="local changes"):
        updates.apply_source([])
    assert (local / "app.txt").read_text() == "my edit"


def test_apply_source_installs_requirements_only_when_changed(repos, monkeypatch):
    upstream, local = repos
    installed = []
    monkeypatch.setattr(updates, "install_requirements", lambda logs: installed.append(True))
    (upstream / "requirements-web.txt").write_text("somepkg\n")
    _git(upstream, "commit", "-q", "-am", "new dependency")
    updates.apply_source([])
    assert installed == [True]


def test_externally_managed_python_is_reported_not_failed(monkeypatch):
    class Proc:
        returncode, stdout, stderr = 1, "", "error: externally-managed-environment"

    monkeypatch.setattr(updates.subprocess, "run", lambda *a, **k: Proc())
    updates.install_requirements(logs := [])
    assert "does not allow pip" in logs[-1]
