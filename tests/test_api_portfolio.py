"""Tests for the portfolio API endpoints (DB-backed, isolated per test via tmp_path)."""

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")


class TestPortfolioApi:
    """Tests for /api/v1/portfolio/*."""

    @pytest.fixture
    def client(self, tmp_path, app_client):
        from dataclasses import replace

        from marketmyna.api.deps import get_config_dep
        from marketmyna.core.config import Config

        config = replace(Config(), db_path=tmp_path / "test_marketmyna.db")

        client = app_client()
        client.app.dependency_overrides[get_config_dep] = lambda: config
        return client

    def test_create_and_list_portfolio(self, client):
        resp = client.post("/api/v1/portfolio", json={"name": "Test", "currency": "USD"})
        assert resp.status_code == 201
        assert resp.json()["name"] == "Test"

        resp = client.get("/api/v1/portfolio")
        assert resp.status_code == 200
        assert resp.json() == ["Test"]

    def test_create_duplicate_portfolio_conflicts(self, client):
        client.post("/api/v1/portfolio", json={"name": "Dup"})
        resp = client.post("/api/v1/portfolio", json={"name": "Dup"})
        assert resp.status_code == 409

    def test_get_missing_portfolio_404(self, client):
        resp = client.get("/api/v1/portfolio/does-not-exist")
        assert resp.status_code == 404

    def test_add_transaction_updates_holdings(self, client):
        client.post("/api/v1/portfolio", json={"name": "Trades"})

        resp = client.post(
            "/api/v1/portfolio/Trades/transactions",
            json={
                "symbol": "AAPL",
                "transaction_type": "buy",
                "quantity": 10,
                "price": 150.0,
                "market": "US",
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "AAPL" in body["holdings"]
        assert body["holdings"]["AAPL"]["quantity"] == 10

    def test_transactions_persist_across_requests(self, client):
        """Each request builds a fresh PortfolioManager - confirms the DB,
        not an in-memory cache, is the source of truth across requests."""
        client.post("/api/v1/portfolio", json={"name": "Persist"})
        client.post(
            "/api/v1/portfolio/Persist/transactions",
            json={"symbol": "MSFT", "transaction_type": "buy", "quantity": 5, "price": 300.0},
        )

        resp = client.get("/api/v1/portfolio/Persist")
        assert resp.status_code == 200
        assert resp.json()["holdings"]["MSFT"]["quantity"] == 5


class TestPortfolioManageApi:
    """Rename / delete portfolios and fix transaction mistakes."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch, app_client):
        from dataclasses import replace

        from marketmyna.api.deps import get_config_dep
        from marketmyna.core.config import Config
        from marketmyna.portfolio.manager import PortfolioManager

        monkeypatch.setattr(PortfolioManager, "update_prices", lambda self, name: None)
        config = replace(Config(), db_path=tmp_path / "test_marketmyna.db")
        client = app_client()
        client.app.dependency_overrides[get_config_dep] = lambda: config
        return client

    def _tx(self, client, name, symbol, kind, qty, price, market="INDIA"):
        return client.post(f"/api/v1/portfolio/{name}/transactions", json={
            "symbol": symbol, "transaction_type": kind, "quantity": qty, "price": price, "market": market})

    def test_rename(self, client):
        client.post("/api/v1/portfolio", json={"name": "Old"})
        client.post("/api/v1/portfolio", json={"name": "Other"})
        self._tx(client, "Old", "TCS", "buy", 2, 3000)
        resp = client.patch("/api/v1/portfolio/Old", json={"name": "  Ravi - Long term "})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Ravi - Long term"
        assert resp.json()["holdings"]["TCS"]["quantity"] == 2
        assert sorted(client.get("/api/v1/portfolio").json()) == ["Other", "Ravi - Long term"]
        assert client.patch("/api/v1/portfolio/Other", json={"name": "Ravi - Long term"}).status_code == 409
        assert client.patch("/api/v1/portfolio/Missing", json={"name": "X"}).status_code == 404

    def test_delete(self, client):
        client.post("/api/v1/portfolio", json={"name": "Gone"})
        self._tx(client, "Gone", "TCS", "buy", 1, 3000)
        assert client.delete("/api/v1/portfolio/Gone").status_code == 204
        assert client.get("/api/v1/portfolio").json() == []
        assert client.delete("/api/v1/portfolio/Gone").status_code == 404

    def test_transactions_listed_with_market(self, client):
        client.post("/api/v1/portfolio", json={"name": "P"})
        body = self._tx(client, "P", "TCS", "buy", 2, 3000).json()
        assert body["transactions"][0]["index"] == 0
        assert body["transactions"][0]["market"] == "INDIA"
        assert body["transactions"][0]["transaction_type"] == "buy"

    def test_delete_transaction_rebuilds_holdings(self, client):
        client.post("/api/v1/portfolio", json={"name": "P"})
        self._tx(client, "P", "TCS", "buy", 10, 100)
        self._tx(client, "P", "TCS", "buy", 10, 200)  # typo we'll remove
        self._tx(client, "P", "TCS", "sell", 5, 150)
        assert client.get("/api/v1/portfolio/P").json()["holdings"]["TCS"]["quantity"] == 15

        resp = client.delete("/api/v1/portfolio/P/transactions/1")
        assert resp.status_code == 200
        h = resp.json()["holdings"]["TCS"]
        assert h["quantity"] == 5 and h["avg_cost"] == 100
        assert h["market"] == "INDIA"
        assert len(resp.json()["transactions"]) == 2
        # Persisted, not just in memory.
        assert client.get("/api/v1/portfolio/P").json()["holdings"]["TCS"]["quantity"] == 5

    def test_delete_buy_needed_by_a_later_sell_is_refused(self, client):
        client.post("/api/v1/portfolio", json={"name": "P"})
        self._tx(client, "P", "TCS", "buy", 10, 100)
        self._tx(client, "P", "TCS", "sell", 5, 150)
        resp = client.delete("/api/v1/portfolio/P/transactions/0")
        assert resp.status_code == 409
        assert "delete that sell first" in resp.json()["message"]
        assert client.get("/api/v1/portfolio/P").json()["holdings"]["TCS"]["quantity"] == 5
        assert client.delete("/api/v1/portfolio/P/transactions/9").status_code == 404

    def test_deleting_last_sell_reopens_position(self, client):
        client.post("/api/v1/portfolio", json={"name": "P"})
        self._tx(client, "P", "TCS", "buy", 4, 100)
        self._tx(client, "P", "TCS", "sell", 4, 120)
        assert client.get("/api/v1/portfolio/P").json()["holdings"] == {}
        h = client.delete("/api/v1/portfolio/P/transactions/1").json()["holdings"]["TCS"]
        assert h["quantity"] == 4 and h["market"] == "INDIA"
