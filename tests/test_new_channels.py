"""New notification channels and browser Web Push (network mocked)."""

import json
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from marketmyna.core.config import Config
from marketmyna.notifiers import webpush


class Resp:
    def __init__(self, status=200, text="ok"):
        self.status_code, self.text = status, text


@pytest.fixture
def calls(monkeypatch):
    import requests

    recorded = []

    def fake_request(method, url, timeout=None, **kwargs):
        recorded.append({"method": method, "url": url, **kwargs})
        return Resp()

    monkeypatch.setattr(requests, "request", fake_request)
    return recorded


def test_teams(calls):
    from marketmyna.notifiers.teams import TeamsSender

    assert TeamsSender(Config(teams_webhook_url="https://x.logic.azure.com/w")).send("line1\nline2", title="T")
    card = calls[0]["json"]["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert card["body"][0]["text"] == "T" and card["body"][1]["text"] == "line1\n\nline2"


def test_google_chat(calls):
    from marketmyna.notifiers.googlechat import GoogleChatSender

    assert GoogleChatSender(Config(google_chat_webhook_url="https://chat.googleapis.com/x")).send("hi", title="T")
    assert calls[0]["json"] == {"text": "*T*\nhi"}


def test_matrix(calls):
    from marketmyna.notifiers.matrix import MatrixSender

    cfg = Config(matrix_homeserver="https://matrix.org/", matrix_access_token="tok", matrix_room_id="!r:matrix.org")
    assert MatrixSender(cfg).send("hi", title="T")
    call = calls[0]
    assert call["method"] == "PUT"
    assert call["url"].startswith("https://matrix.org/_matrix/client/v3/rooms/%21r%3Amatrix.org/send/m.room.message/")
    assert call["headers"]["Authorization"] == "Bearer tok"
    assert call["json"] == {"msgtype": "m.text", "body": "T\n\nhi"}


def test_whatsapp_callmebot(calls):
    from marketmyna.notifiers.whatsapp import WhatsAppSender

    assert not WhatsAppSender(Config(whatsapp_phone="+91 98765")).is_configured()
    assert WhatsAppSender(Config(whatsapp_phone="+91 98765 43210", whatsapp_callmebot_apikey="k")).send("x" * 5000)
    params = calls[0]["params"]
    assert params["phone"] == "+919876543210" and params["apikey"] == "k"
    assert len(params["text"]) <= 1500


def test_twilio_sends_to_each_recipient(calls):
    from marketmyna.notifiers.twilio import TwilioSender

    cfg = Config(twilio_account_sid="AC1", twilio_auth_token="t", twilio_from="whatsapp:+1415",
                 twilio_to=["whatsapp:+9111", "whatsapp:+9122"])
    assert TwilioSender(cfg).send("hi", title="T")
    assert [c["data"]["To"] for c in calls] == ["whatsapp:+9111", "whatsapp:+9122"]
    assert calls[0]["auth"] == ("AC1", "t")
    assert calls[0]["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json"


def test_bark_pushbullet_signal(calls):
    from marketmyna.notifiers.bark import BarkSender
    from marketmyna.notifiers.pushbullet import PushbulletSender
    from marketmyna.notifiers.signal_messenger import SignalSender

    assert BarkSender(Config(bark_url="https://api.day.app/key/")).send("b", title="T")
    assert PushbulletSender(Config(pushbullet_token="pb")).send("p", title="T")
    assert SignalSender(Config(signal_api_url="http://sig:8080", signal_number="+1", signal_recipients=["+2"])).send("s")
    assert calls[0]["url"] == "https://api.day.app/key" and calls[0]["json"]["body"] == "b"
    assert calls[1]["headers"] == {"Access-Token": "pb"} and calls[1]["json"]["type"] == "note"
    assert calls[2]["url"] == "http://sig:8080/v2/send" and calls[2]["json"]["recipients"] == ["+2"]


def test_http_failure_returns_false(monkeypatch):
    import requests

    monkeypatch.setattr(requests, "request", lambda *a, **k: Resp(500, "boom"))
    from marketmyna.notifiers.googlechat import GoogleChatSender

    assert GoogleChatSender(Config(google_chat_webhook_url="https://x")).send("hi") is False


def test_apprise_without_package_is_not_configured():
    from marketmyna.notifiers.apprise_sender import AppriseSender

    try:
        import apprise  # noqa: F401
        pytest.skip("apprise installed")
    except ImportError:
        pass
    assert AppriseSender(Config(apprise_urls=["mailto://x"])).is_configured() is False


def test_telegram_topic(monkeypatch):
    import requests

    from marketmyna.notifiers.telegram import TelegramSender

    sent = {}
    monkeypatch.setattr(requests, "post", lambda url, json=None, timeout=None: sent.update(json) or Resp())
    TelegramSender(Config(telegram_bot_token="t", telegram_chat_id="1", telegram_message_thread_id="42")).send("hi")
    assert sent["message_thread_id"] == 42


def test_dispatcher_lists_every_channel():
    from marketmyna.notifiers.dispatcher import NotificationDispatcher

    names = NotificationDispatcher(Config()).channel_names()
    for name in ("webpush", "whatsapp", "twilio", "teams", "googlechat", "matrix", "signal", "bark", "pushbullet",
                 "apprise"):
        assert name in names


# -------------------------------------------------------------- web push


def test_encryption_matches_rfc8291_example():
    server_key = ec.derive_private_key(
        int.from_bytes(webpush.b64url_decode("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"), ec.SECP256R1())
    body = webpush.encrypt(
        b"When I grow up, I want to be a watermelon",
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "BTBZMqHH6r4Tts7J_aSIgg",
        salt=webpush.b64url_decode("DGv6ra1nlYgDCS1FRnbzlw"),
        server_key=server_key,
    )
    assert webpush.b64url(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl"
        "7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )


def test_vapid_jwt_is_valid_es256():
    private = webpush.generate_vapid_private_key()
    header = webpush.vapid_authorization("https://fcm.googleapis.com/fcm/send/abc", private, "me@example.com", now=1000)
    token = header.split("t=")[1].split(",")[0]
    public = header.split("k=")[1]
    assert public == webpush.vapid_public_key(private)
    head_b64, claims_b64, sig_b64 = token.split(".")
    claims = json.loads(webpush.b64url_decode(claims_b64))
    assert claims == {"aud": "https://fcm.googleapis.com", "exp": 1000 + 12 * 3600, "sub": "mailto:me@example.com"}
    sig = webpush.b64url_decode(sig_b64)
    der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.b64url_decode(public))
    key.verify(der, f"{head_b64}.{claims_b64}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if invalid


@pytest.fixture
def push_client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from marketmyna.api.deps import get_config_dep
    from marketmyna.api.v1.endpoints import push

    config = replace(Config(), db_path=tmp_path / "t.db", app_dir=tmp_path)
    app = FastAPI()
    app.include_router(push.router, prefix="/api/v1")
    app.dependency_overrides[get_config_dep] = lambda: config
    return TestClient(app), config


def _subscription():
    ua = ec.generate_private_key(ec.SECP256R1())
    from cryptography.hazmat.primitives import serialization

    p256dh = webpush.b64url(ua.public_key().public_bytes(serialization.Encoding.X962,
                                                          serialization.PublicFormat.UncompressedPoint))
    return {"endpoint": "https://fcm.googleapis.com/fcm/send/dev1",
            "keys": {"p256dh": p256dh, "auth": webpush.b64url(b"0123456789abcdef")}}


def test_push_api_and_sender(push_client, monkeypatch):
    client, config = push_client
    key = client.get("/api/v1/push/vapid-public-key").json()["public_key"]
    assert len(webpush.b64url_decode(key)) == 65
    assert config.web_push_vapid_private_key  # generated and kept

    assert client.post("/api/v1/push/subscriptions", json={**_subscription(), "label": "Chrome on Linux"}).status_code == 201
    assert client.post("/api/v1/push/subscriptions", json=_subscription()).status_code == 201  # upsert, not duplicate
    devices = client.get("/api/v1/push/subscriptions").json()
    assert len(devices) == 1 and devices[0]["service"] == "fcm.googleapis.com"

    import requests

    posted = []
    monkeypatch.setattr(requests, "post", lambda url, data=None, headers=None, timeout=None:
                        posted.append((url, data, headers)) or Resp(201))
    assert client.post("/api/v1/push/test").json()["sent"] is True
    url, body, headers = posted[0]
    assert headers["Content-Encoding"] == "aes128gcm" and headers["Authorization"].startswith("vapid t=")
    assert body[21:86] and len(body) > 86 + 16  # salt+rs+idlen+keyid header, then ciphertext

    # An expired subscription (410) is removed automatically.
    monkeypatch.setattr(requests, "post", lambda *a, **k: Resp(410))
    assert client.post("/api/v1/push/test").json()["sent"] is False
    assert client.get("/api/v1/push/subscriptions").json() == []


def test_push_rejects_non_https(push_client):
    client, _ = push_client
    bad = {**_subscription(), "endpoint": "http://evil.local/x"}
    assert client.post("/api/v1/push/subscriptions", json=bad).status_code == 400
