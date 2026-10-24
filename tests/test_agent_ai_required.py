"""Run AI needs a model: /agent/status says whether one is set up, and the
analyze endpoints refuse (before any data step runs) when none is."""

from marketmyna.api.v1.endpoints import agent


def test_status_and_refusal_without_ai(app_client, monkeypatch):
    monkeypatch.setattr(agent, "llm_configured", lambda config: False)
    client = app_client()
    assert client.get("/api/v1/agent/status").json() == {"configured": False}
    for path in ("/api/v1/agent/analyze", "/api/v1/agent/analyze/stream"):
        resp = client.post(path, json={"symbol": "AAPL", "market": "us"})
        assert resp.status_code == 400
        assert "AI key" in resp.json()["message"]


def test_status_with_ai(app_client, monkeypatch):
    monkeypatch.setattr(agent, "llm_configured", lambda config: True)
    assert app_client().get("/api/v1/agent/status").json() == {"configured": True}
