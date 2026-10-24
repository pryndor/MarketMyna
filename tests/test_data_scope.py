"""Per-user data scoping still guards the owner's rows: code that forgot to
pick a scope reads nothing and can't write, and every table says whose rows
it holds."""

from __future__ import annotations

import pytest

from src.core import tenant
from src.storage import WatchlistRecord


def test_every_request_runs_as_the_owner(owner_env):
    c = owner_env["client"]
    assert c.get("/api/auth/status").json() == {"authenticated": True}
    me = c.get("/api/auth/account/me").json()
    assert me["role"] == "admin" and me["id"] == owner_env["owner_id"]
    assert c.post("/api/v1/portfolio", json={"name": "Mine", "currency": "INR"}).status_code in (200, 201)
    assert c.get("/api/v1/portfolio").json() == ["Mine"]


def test_trader_investor_switch_is_kept(owner_env):
    c = owner_env["client"]
    assert c.get("/api/auth/account/me").json()["area"] is None
    assert c.post("/api/auth/account/area", json={"area": "trader"}).json()["area"] == "trader"
    assert c.get("/api/auth/account/me").json()["area"] == "trader"
    assert c.post("/api/auth/account/area", json={"area": "nope"}).status_code == 400


def test_unscoped_code_fails_closed(owner_env):
    owner_env["client"].post("/api/v1/watchlists", json={"name": "Pharma"})
    with owner_env["db"].get_session() as s:  # no scope: background code that forgot to pick one
        assert s.query(WatchlistRecord).count() == 0
        s.add(WatchlistRecord(name="orphan"))
        with pytest.raises(RuntimeError):
            s.flush()
        s.rollback()
    with tenant.system_scope(), owner_env["db"].get_session() as s:
        assert s.query(WatchlistRecord).filter_by(name="Pharma").count() == 1


def test_every_table_is_classified_once():
    """A new table must say whose rows it holds (src/storage.py), so it can't
    silently skip the per-user filter."""
    import src.storage as st

    owned = {m.__tablename__ for m in tenant.owned_models()}
    insert_only = {m.__tablename__ for m in tenant._insert_only}
    groups = [owned, insert_only, set(st.SELF_FILTERED_TABLES), set(st.CHILD_TABLES), set(st.PLATFORM_TABLES)]
    listed = [t for g in groups for t in g]
    assert len(listed) == len(set(listed)), "a table is in two groups"
    assert set(listed) == set(st.Base.metadata.tables), "unclassified or stale tables"
    for table, parent in st.CHILD_TABLES.items():
        assert parent in owned and "user_id" not in st.Base.metadata.tables[table].c
    for table in owned | insert_only | (set(st.SELF_FILTERED_TABLES) - {"users"}):
        assert "user_id" in st.Base.metadata.tables[table].c, table
