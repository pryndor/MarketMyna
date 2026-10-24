"""Tests for the watchlist API (DB-backed, isolated per test via tmp_path)."""

from datetime import timedelta

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")


class TestWatchlistApi:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from dataclasses import replace

        from fastapi import FastAPI

        from marketmyna.api.deps import get_config_dep
        from marketmyna.api.v1.endpoints import watchlists
        from marketmyna.core.config import Config
        from marketmyna.data.listings import ListingStore, _row

        config = replace(Config(), db_path=tmp_path / "test_marketmyna.db")
        store = ListingStore(
            cache_dir=tmp_path / "listings",
            providers={
                "india_stocks": ("india", lambda: [
                    _row("RELIANCE", "Reliance Industries Limited", "india", "stock", price=1400.0, change_percent=1.2),
                ], timedelta(hours=1)),
            },
        )
        monkeypatch.setattr(watchlists, "get_store", lambda: store)

        app = FastAPI()
        app.include_router(watchlists.router, prefix="/api/v1")
        app.dependency_overrides[get_config_dep] = lambda: config
        return fastapi_testclient.TestClient(app)

    def test_default_list_created(self, client):
        resp = client.get("/api/v1/watchlists")
        assert resp.status_code == 200
        assert [w["name"] for w in resp.json()] == ["My watchlist"]

    def test_add_item_is_idempotent_and_enriched(self, client):
        wid = client.get("/api/v1/watchlists").json()[0]["id"]
        body = {"symbol": "reliance", "market": "india", "type": "stock"}
        assert client.post(f"/api/v1/watchlists/{wid}/items", json=body).status_code == 201
        assert client.post(f"/api/v1/watchlists/{wid}/items", json=body).status_code == 201

        detail = client.get(f"/api/v1/watchlists/{wid}").json()
        assert detail["count"] == 1
        item = detail["items"][0]
        assert item["symbol"] == "RELIANCE"
        assert item["listed"] is True
        assert item["price"] == 1400.0
        assert item["name"] == "Reliance Industries Limited"

    def test_unlisted_item_still_saved(self, client):
        wid = client.get("/api/v1/watchlists").json()[0]["id"]
        client.post(f"/api/v1/watchlists/{wid}/items", json={"symbol": "SAP.DE", "market": "global"})
        item = client.get(f"/api/v1/watchlists/{wid}").json()["items"][0]
        assert item["listed"] is False
        assert "price" not in item

    def test_create_rename_delete_lists(self, client):
        client.get("/api/v1/watchlists")
        created = client.post("/api/v1/watchlists", json={"name": "Banks"})
        assert created.status_code == 201
        wid = created.json()["id"]
        assert client.post("/api/v1/watchlists", json={"name": "Banks"}).status_code == 409
        assert client.patch(f"/api/v1/watchlists/{wid}", json={"name": "PSU Banks"}).json()["name"] == "PSU Banks"
        assert client.delete(f"/api/v1/watchlists/{wid}").status_code == 204
        assert [w["name"] for w in client.get("/api/v1/watchlists").json()] == ["My watchlist"]

    def test_remove_item_and_membership(self, client):
        wid = client.get("/api/v1/watchlists").json()[0]["id"]
        item = client.post(
            f"/api/v1/watchlists/{wid}/items", json={"symbol": "119551", "market": "india", "type": "mf"}
        ).json()
        members = client.get("/api/v1/watchlists/items").json()
        assert members == [{"id": item["id"], "watchlist_id": wid, "symbol": "119551", "market": "india", "type": "mf"}]
        assert client.delete(f"/api/v1/watchlists/{wid}/items/{item['id']}").status_code == 204
        assert client.get("/api/v1/watchlists/items").json() == []
        assert client.delete(f"/api/v1/watchlists/{wid}/items/{item['id']}").status_code == 404

    def test_missing_list_404(self, client):
        assert client.get("/api/v1/watchlists/999").status_code == 404
