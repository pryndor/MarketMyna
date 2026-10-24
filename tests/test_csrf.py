"""CSRF guard (api/middlewares/csrf.py): cross-site writes to /api/ are refused."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.middlewares.csrf import CSRFMiddleware


def _client() -> TestClient:
    app = FastAPI()

    @app.post("/api/v1/thing")
    def write() -> dict:
        return {"ok": True}

    @app.get("/api/v1/thing")
    def read() -> dict:
        return {"ok": True}

    app.add_middleware(CSRFMiddleware, allowed_origins=["https://app.example.org"])
    return TestClient(app, base_url="https://marketmyna.com")


def test_same_origin_browser_write_allowed():
    r = _client().post("/api/v1/thing", headers={"Sec-Fetch-Site": "same-origin", "Origin": "https://marketmyna.com"})
    assert r.status_code == 200


def test_cross_site_browser_write_refused():
    r = _client().post("/api/v1/thing", headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_site_subdomain_refused():
    r = _client().post("/api/v1/thing", headers={"Sec-Fetch-Site": "same-site", "Origin": "https://blog.marketmyna.com"})
    assert r.status_code == 403


def test_allowed_origin_cross_site_ok():
    r = _client().post("/api/v1/thing", headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://app.example.org"})
    assert r.status_code == 200


def test_old_browser_origin_mismatch_refused():
    assert _client().post("/api/v1/thing", headers={"Origin": "https://evil.example"}).status_code == 403
    assert _client().post("/api/v1/thing", headers={"Origin": "https://marketmyna.com"}).status_code == 200


def test_reads_and_server_calls_pass():
    c = _client()
    assert c.get("/api/v1/thing", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200
    assert c.post("/api/v1/thing").status_code == 200
