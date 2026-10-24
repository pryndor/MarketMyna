"""Shared test fixtures.

Single-user build: create_app() turns accounts on and every request runs as
the local owner (api/middlewares/auth.py). Tests that drive the full app use
`app_client`, which runs as admin user 1, and every test gets the shared config /
tenant switch put back afterwards so one test's create_app() can't leak
accounts mode into the next."""

import pytest


@pytest.fixture(autouse=True)
def _restore_auth_mode():
    from api.deps import get_config_dep
    from src.core import tenant

    config = get_config_dep()
    accounts, scoped = config.accounts_enabled, tenant._enabled
    yield
    config.accounts_enabled, tenant._enabled = accounts, scoped


@pytest.fixture(autouse=True)
def _home_from_path_home(monkeypatch):
    """app_home() follows Path.home(), so tests that point it at tmp_path
    are not overridden by a MARKETMYNA_HOME set in the shell."""
    monkeypatch.delenv("MARKETMYNA_HOME", raising=False)


@pytest.fixture(autouse=True)
def _isolated_ai_model_state(tmp_path, monkeypatch):
    """Retired-model state (src/llm/model_health.py) in a fresh file per test."""
    from src.llm import model_health

    monkeypatch.setattr(model_health, "_state_file", lambda config: tmp_path / "ai_models.json")
    model_health._lists.clear()


@pytest.fixture
def app_client(monkeypatch):
    """make() -> TestClient for create_app(), running as admin user 1. The
    owner lookup is faked and row scoping is off, so endpoint tests don't need a user table. Override dependencies through
    client.app.dependency_overrides."""

    def make():
        from fastapi.testclient import TestClient

        from api.app import create_app
        from api.middlewares import auth
        from src.core import tenant

        def signed_in(scope) -> bool:
            state = scope.setdefault("state", {})
            state["user_id"], state["user_role"] = 1, "admin"
            return True

        monkeypatch.setattr(auth, "is_authenticated", signed_in)
        client = TestClient(create_app())
        tenant.enable(False)
        return client

    return make


@pytest.fixture
def login_as(monkeypatch):
    """login_as(client) for small test apps that have no user table: every
    request runs as owner 1 (the call itself is kept for older tests)."""
    from api.middlewares import auth

    monkeypatch.setattr(auth, "_session_user", lambda _config, raw: (1, "admin"))
    monkeypatch.setattr(auth, "accounts_config", lambda: None)

    def sign_in(client, role: str = "admin") -> None:
        pass

    return sign_in


@pytest.fixture(autouse=True)
def _no_saved_data_keys(monkeypatch):
    """Backup price sources (src/data/extra_sources.py) see only keys a test
    sets in the environment, never ones saved in the real config.json."""
    from src.data import extra_sources

    monkeypatch.setattr(extra_sources, "_config_key", lambda field: None)
    extra_sources._key_cache.clear()
    yield
    extra_sources._key_cache.clear()


@pytest.fixture
def owner_env(tmp_path, monkeypatch):
    """The full v1 API on a fresh database, every request running as the
    local owner: {"client", "db", "config", "owner_id"}."""
    from dataclasses import replace

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.deps import get_config_dep
    from api.middlewares import auth
    from api.v1.endpoints import account
    from api.v1.router import router as v1
    from src.bot.registry import build_default_dispatcher
    from src.core import tenant
    from src.core.config import Config
    from src.storage import DatabaseManager, get_db_url

    config = replace(Config(), db_path=tmp_path / "owner.db", app_dir=tmp_path, data_dir=tmp_path,
                     accounts_enabled=True, secret_key="test-secret")
    monkeypatch.setattr(auth, "accounts_config", lambda: config)
    monkeypatch.setattr(tenant, "_enabled", True)
    from src.services import accounts

    accounts._owner_cache.clear()
    app = FastAPI()
    app.add_middleware(auth.AuthMiddleware)
    app.include_router(auth.router, prefix="/api/auth")
    app.include_router(account.router, prefix="/api/auth/account")
    app.include_router(v1, prefix="/api/v1")
    app.dependency_overrides[get_config_dep] = lambda: config
    app.state.bot_dispatcher = build_default_dispatcher(config)
    return {"client": TestClient(app), "db": DatabaseManager.instance(get_db_url(config=config)),
            "config": config, "owner_id": auth.local_owner_id(config)}
