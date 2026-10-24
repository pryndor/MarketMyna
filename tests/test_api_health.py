"""Tests for the health check endpoint."""

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")


class TestHealth:
    """Tests for /health."""

    def test_health_ok(self):
        from api.app import create_app

        client = fastapi_testclient.TestClient(create_app())  # no login needed
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_api_health_ok(self):
        from api.app import create_app

        client = fastapi_testclient.TestClient(create_app())
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_trailing_slash_served_not_redirected(self):
        from api.app import create_app

        client = fastapi_testclient.TestClient(create_app())
        resp = client.get("/api/health/", follow_redirects=False)
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
