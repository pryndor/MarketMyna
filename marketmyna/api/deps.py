"""FastAPI dependency-injection functions."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from marketmyna.core.config import Config
from marketmyna.storage import DatabaseManager, get_db_url


@lru_cache(maxsize=1)
def get_config_dep() -> Config:
    """Process-wide Config, loaded once per process."""
    return Config.load()


def get_database_manager() -> DatabaseManager:
    config = get_config_dep()
    return DatabaseManager.instance(get_db_url(config=config))


def get_db_session(config: Config = Depends(get_config_dep)) -> Iterator[Session]:
    """A request-scoped session: committed on success, rolled back on error."""
    session = DatabaseManager.instance(get_db_url(config=config)).SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_scheduler_service(request: Request):
    """The RuntimeSchedulerService started in marketmyna/api/app.py's lifespan, off
    app.state - lazily created if somehow missing (e.g. a test app built
    without going through the real lifespan) rather than 500ing."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        from marketmyna.services.runtime_scheduler import RuntimeSchedulerService

        scheduler = RuntimeSchedulerService(get_config_dep())
        scheduler.start()
        request.app.state.scheduler = scheduler
    return scheduler


def get_bot_dispatcher(request: Request):
    """The CommandDispatcher built in marketmyna/api/app.py's lifespan, off
    app.state - lazily created if somehow missing, same fallback shape
    as get_scheduler_service."""
    dispatcher = getattr(request.app.state, "bot_dispatcher", None)
    if dispatcher is None:
        from marketmyna.bot.registry import build_default_dispatcher

        dispatcher = build_default_dispatcher(get_config_dep())
        request.app.state.bot_dispatcher = dispatcher
    return dispatcher
