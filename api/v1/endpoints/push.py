"""Browser push notification endpoints: the server's VAPID public key,
device (subscription) management and a test push."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_

from api.deps import get_config_dep
from src.core import tenant
from src.notifiers.webpush import WebPushSender, ensure_vapid_key, vapid_public_key
from src.storage import DatabaseManager, WebPushSubscriptionRecord, get_db_url

router = APIRouter()


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=10)
    auth: str = Field(min_length=4)


class SubscriptionBody(BaseModel):
    endpoint: str = Field(min_length=10)
    keys: SubscriptionKeys
    label: str = ""


class EndpointBody(BaseModel):
    endpoint: str


def _db(config):
    return DatabaseManager.instance(get_db_url(config=config))


def _device(record: WebPushSubscriptionRecord) -> dict:
    return {
        "id": record.id,
        "label": record.label or "Browser",
        "service": urlsplit(record.endpoint).netloc,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "last_success_at": record.last_success_at.isoformat() if record.last_success_at else None,
    }


@router.get("/push/vapid-public-key")
def get_vapid_public_key(config=Depends(get_config_dep)) -> dict:
    return {"public_key": vapid_public_key(ensure_vapid_key(config))}


@router.get("/push/subscriptions")
def list_subscriptions(config=Depends(get_config_dep)) -> list[dict]:
    with _db(config).get_session() as session:
        records = session.query(WebPushSubscriptionRecord).order_by(WebPushSubscriptionRecord.id).all()
        return [_device(r) for r in records]


@router.post("/push/subscriptions", status_code=201)
def subscribe(body: SubscriptionBody, config=Depends(get_config_dep)) -> dict:
    if not body.endpoint.startswith("https://"):
        raise HTTPException(status_code=400, detail="Push endpoint must be https")
    ensure_vapid_key(config)
    with _db(config).get_session() as session:
        if tenant.current_user_id() is not None:
            # Accounts mode: a browser belongs to whoever subscribed on it last
            # (endpoints are unique across users).
            with tenant.system_scope():
                session.query(WebPushSubscriptionRecord).filter(
                    WebPushSubscriptionRecord.endpoint == body.endpoint,
                    or_(WebPushSubscriptionRecord.user_id.is_(None),
                        WebPushSubscriptionRecord.user_id != tenant.current_user_id()),
                ).delete(synchronize_session=False)
        record = (
            session.query(WebPushSubscriptionRecord)
            .filter(WebPushSubscriptionRecord.endpoint == body.endpoint)
            .first()
        )
        if record is None:
            record = WebPushSubscriptionRecord(endpoint=body.endpoint)
            session.add(record)
        record.p256dh = body.keys.p256dh
        record.auth = body.keys.auth
        record.label = body.label[:80]
        session.flush()
        return _device(record)


@router.post("/push/unsubscribe", status_code=204)
def unsubscribe(body: EndpointBody, config=Depends(get_config_dep)) -> Response:
    with _db(config).get_session() as session:
        session.query(WebPushSubscriptionRecord).filter(
            WebPushSubscriptionRecord.endpoint == body.endpoint
        ).delete(synchronize_session=False)
    return Response(status_code=204)


@router.delete("/push/subscriptions/{sub_id}", status_code=204)
def delete_subscription(sub_id: int, config=Depends(get_config_dep)) -> Response:
    with _db(config).get_session() as session:
        deleted = session.query(WebPushSubscriptionRecord).filter(WebPushSubscriptionRecord.id == sub_id).delete(
            synchronize_session=False
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="Device not found")
    return Response(status_code=204)


@router.post("/push/test")
def test_push(config=Depends(get_config_dep), url: Optional[str] = None) -> dict:
    sender = WebPushSender(config)
    if not sender.is_configured():
        return {"sent": False, "message": "No device has enabled push notifications yet."}
    sent = sender.send("Push notifications are working. Reports and alerts will arrive here.",
                       title="MarketMyna test", url=url or "/")
    return {"sent": sent, "message": "Sent" if sent else "Every device rejected the push - see server logs."}
