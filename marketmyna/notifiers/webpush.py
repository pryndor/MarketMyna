"""Browser push notifications (Web Push) for the MarketMyna web app.

Any browser that opens the app and allows notifications (Chrome, Edge,
Firefox, Android; Safari/iOS 16.4+ when the app is added to the home
screen) registers a push subscription; reports and alerts then arrive as
system notifications even when the tab is closed.

Implemented directly on `cryptography` (already a dependency) instead of
pywebpush:
- RFC 8291 message encryption ("aes128gcm" content coding),
- RFC 8292 VAPID: an ES256-signed JWT that identifies this server to the
  browser vendor's push service.

The VAPID key pair is generated on first use and kept in the config
(web_push_vapid_private_key); browsers subscribe against its public key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .base import DEFAULT_TIMEOUT, DEFAULT_TITLE, logger, truncate

# Push services accept ~4 KB payloads; leave room for encryption overhead.
BODY_MAX_LENGTH = 2800
RECORD_SIZE = 4096
DEFAULT_CONTACT = "mailto:marketmyna@localhost"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_bytes(key) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


# ------------------------------------------------------------------ VAPID


def generate_vapid_private_key() -> str:
    """New P-256 key as base64url of the 32-byte private scalar."""
    key = ec.generate_private_key(ec.SECP256R1())
    return b64url(key.private_numbers().private_value.to_bytes(32, "big"))


def load_vapid_key(private_b64: str):
    value = int.from_bytes(b64url_decode(private_b64), "big")
    return ec.derive_private_key(value, ec.SECP256R1())


def vapid_public_key(private_b64: str) -> str:
    """The applicationServerKey browsers subscribe with."""
    return b64url(_public_bytes(load_vapid_key(private_b64)))


def vapid_authorization(endpoint: str, private_b64: str, contact: str, now: Optional[float] = None) -> str:
    key = load_vapid_key(private_b64)
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int((now or time.time()) + 12 * 3600),
        "sub": contact if contact.startswith(("mailto:", "https://")) else f"mailto:{contact}",
    }
    signing_input = (
        b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        + "."
        + b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    token = f"{signing_input}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={token}, k={b64url(_public_bytes(key))}"


# ------------------------------------------------------------- encryption


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: Optional[bytes] = None,
            server_key=None) -> bytes:
    """RFC 8291 aes128gcm body for one subscription (salt/server_key are
    injectable only so tests can reproduce the RFC's example vector)."""
    ua_public = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _public_bytes(server_key)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    shared = server_key.exchange(ec.ECDH(), ua_key)

    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)

    # Single record: payload + 0x02 end-of-record delimiter.
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public
    return header + ciphertext


# ----------------------------------------------------------------- sender


def ensure_vapid_key(config) -> str:
    """The server's VAPID private key, generating and saving one if needed."""
    key = getattr(config, "web_push_vapid_private_key", None)
    if not key:
        key = generate_vapid_private_key()
        config.web_push_vapid_private_key = key
        try:
            config.save()
        except Exception as exc:  # the key still works for this process
            logger.warning("Could not persist VAPID key: %s", exc)
    return key


def _db(config):
    from ..storage import DatabaseManager, get_db_url

    return DatabaseManager.instance(get_db_url(config=config))


class WebPushSender:
    def __init__(self, config):
        self._config = config

    def _subscriptions(self) -> list:
        from ..storage import WebPushSubscriptionRecord, has_app_db

        if not getattr(self._config, "web_push_vapid_private_key", None):
            return []
        try:
            if not has_app_db(self._config):
                return []
            with _db(self._config).get_session() as session:
                return [
                    (r.id, r.endpoint, r.p256dh, r.auth)
                    for r in session.query(WebPushSubscriptionRecord).all()
                ]
        except Exception as exc:
            logger.warning("Web push subscriptions unreadable: %s", exc)
            return []

    def is_configured(self) -> bool:
        return bool(self._subscriptions())

    def send(self, message: str, title: Optional[str] = None, *, timeout: float = DEFAULT_TIMEOUT,
             url: str = "/scheduler") -> bool:
        import requests

        from ..storage import WebPushSubscriptionRecord

        subs = self._subscriptions()
        if not subs:
            return False
        key = self._config.web_push_vapid_private_key
        contact = getattr(self._config, "web_push_contact", None) or DEFAULT_CONTACT
        payload = json.dumps({
            "title": title or DEFAULT_TITLE,
            "body": truncate(message, BODY_MAX_LENGTH),
            "url": url,
            "tag": f"marketmyna-{int(time.time())}",
        }).encode()

        delivered, gone = [], []
        for sub_id, endpoint, p256dh, auth in subs:
            try:
                resp = requests.post(
                    endpoint,
                    data=encrypt(payload, p256dh, auth),
                    headers={
                        "Authorization": vapid_authorization(endpoint, key, contact),
                        "Content-Encoding": "aes128gcm",
                        "Content-Type": "application/octet-stream",
                        "TTL": "86400",
                        "Urgency": "normal",
                    },
                    timeout=timeout,
                )
            except Exception as exc:
                logger.error("Web push to %s failed: %s", urlsplit(endpoint).netloc, exc)
                continue
            if resp.status_code in (404, 410):
                gone.append(sub_id)  # browser unsubscribed or expired
            elif 200 <= resp.status_code < 300:
                delivered.append(sub_id)
            else:
                logger.error("Web push to %s failed: HTTP %s %s", urlsplit(endpoint).netloc,
                             resp.status_code, resp.text[:200])

        if delivered or gone:
            with _db(self._config).get_session() as session:
                if gone:
                    session.query(WebPushSubscriptionRecord).filter(WebPushSubscriptionRecord.id.in_(gone)).delete(
                        synchronize_session=False)
                if delivered:
                    session.query(WebPushSubscriptionRecord).filter(
                        WebPushSubscriptionRecord.id.in_(delivered)).update(
                        {"last_success_at": datetime.now()}, synchronize_session=False)
        return bool(delivered)
