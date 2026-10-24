"""Per-user data scoping for accounts mode.

When accounts mode is on (`enable()` is called at app start), every ORM
SELECT / UPDATE / DELETE on an owned model gets `user_id = <current user>`
added automatically, and every new owned row gets the current user's id on
flush. The current user lives in a context variable that AuthMiddleware sets
per request, so routers and services don't have to pass user ids around.

Scopes:
- a user id (int): only that user's rows.
- SYSTEM: no filter. Only for code that must see every user's rows
  (admin counts, account deletion, background jobs that loop over users).
- unset: fail closed. Queries match nothing and inserts raise, so code that
  forgot to pick a scope can't read or write another user's data.

With accounts off (CLI runs, one local user) nothing is filtered.
"""

from __future__ import annotations

import contextlib
import logging
from contextvars import ContextVar
from typing import Iterator, Optional, Union

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

logger = logging.getLogger(__name__)


class _System:
    def __repr__(self) -> str:
        return "SYSTEM"


SYSTEM = _System()
Scope = Union[int, _System, None]

_current: ContextVar[Scope] = ContextVar("marketmyna_user_scope", default=None)
_enabled = False
_owned: tuple[type, ...] = ()
# Owned for inserts (user_id is filled in) but readable across users: the
# admin reads all feedback and usage, the platform scheduler / alert config
# rows belong to the platform, not one user.
_insert_only: tuple[type, ...] = ()


def configure(owned: tuple[type, ...], insert_only: tuple[type, ...] = ()) -> None:
    global _owned, _insert_only
    _owned, _insert_only = owned, insert_only


def owned_models() -> tuple[type, ...]:
    """Models scoped to one user (each has a user_id column)."""
    return _owned


def enable(on: bool = True) -> None:
    global _enabled
    _enabled = on


def enabled() -> bool:
    return _enabled


def current() -> Scope:
    return _current.get()


def current_user_id() -> Optional[int]:
    scope = _current.get()
    return scope if isinstance(scope, int) else None


def set_scope(scope: Scope):
    """Sets the scope for the rest of this context; returns a reset token."""
    return _current.set(scope)


def reset_scope(token) -> None:
    _current.reset(token)


@contextlib.contextmanager
def user_scope(scope: Scope) -> Iterator[None]:
    token = _current.set(scope)
    try:
        yield
    finally:
        _current.reset(token)


def system_scope():
    return user_scope(SYSTEM)


@event.listens_for(Session, "do_orm_execute")
def _scope_queries(state: ORMExecuteState) -> None:
    if not _enabled or not _owned:
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    if state.is_column_load or state.is_relationship_load:
        return  # the parent row was already scoped
    scope = _current.get()
    if scope is SYSTEM:
        return
    # No user id is ever -1, so an unset scope matches nothing.
    uid = scope if isinstance(scope, int) else -1
    state.statement = state.statement.options(
        *(with_loader_criteria(model, model.user_id == uid, include_aliases=True) for model in _owned)
    )


@event.listens_for(Session, "before_flush")
def _stamp_owner(session: Session, flush_context, instances) -> None:
    if not _enabled:
        return
    scope = _current.get()
    for obj in session.new:
        if not isinstance(obj, _owned + _insert_only):
            continue
        if getattr(obj, "user_id", None) is not None:
            continue
        if isinstance(scope, int):
            obj.user_id = scope
        elif scope is None and isinstance(obj, _owned):
            raise RuntimeError(f"Refusing to create {type(obj).__name__} with no user scope")
