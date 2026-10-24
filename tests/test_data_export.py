"""Personal data export: the user's own rows, child rows, and no secrets."""


import pytest

from src.services.data_export import export_user
from src.storage import (
    DatabaseManager, HoldingRecord, PortfolioRecord, UserApiKeyRecord, UserRecord,
    WatchlistItemRecord, WatchlistRecord,
)


@pytest.fixture
def db(tmp_path):
    from src.storage import Base
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path / 'x.db'}"
    Base.metadata.create_all(create_engine(url))
    return DatabaseManager.instance(url)


def _user(session, email):
    u = UserRecord(email=email, display_name=email.split("@")[0])
    session.add(u)
    session.flush()
    return u


def test_export_has_own_rows_children_and_no_secrets(db):
    with db.get_session() as s:
        me, other = _user(s, "me@x.in"), _user(s, "other@x.in")
        p = PortfolioRecord(name="Long term", user_id=me.id)
        s.add(p)
        s.add(PortfolioRecord(name="Not mine", user_id=other.id))
        s.flush()
        s.add(HoldingRecord(portfolio_id=p.id, symbol="GAEL", quantity=62, avg_cost=112.32))
        w = WatchlistRecord(name="Banks", user_id=me.id)
        s.add(w)
        s.flush()
        s.add(WatchlistItemRecord(watchlist_id=w.id, symbol="SBIN", market="india", type="stock"))
        s.add(UserApiKeyRecord(user_id=me.id, provider="gemini", key_ciphertext=b"enc", key_last4="abcd"))
        s.flush()
        out = export_user(s, me.id)

    t = out["tables"]
    assert t["users"][0]["email"] == "me@x.in"
    assert [r["name"] for r in t["portfolios"]] == ["Long term"]
    assert t["holdings"][0]["symbol"] == "GAEL"
    assert t["watchlist_items"][0]["symbol"] == "SBIN"
    assert t["user_api_keys"][0]["key_last4"] == "abcd" and "key_ciphertext" not in t["user_api_keys"][0]
    text = str(out)
    assert "Not mine" not in text
