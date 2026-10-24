"""The owner's profile, mounted at /api/auth/account. Single-user build: no
sign-up, login, plans or billing; every route works on the local owner
(marketmyna/api/middlewares/auth.py)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from marketmyna.api.deps import get_config_dep
from marketmyna.api.middlewares.auth import accounts_db, current_user_from_request
from marketmyna.core.compliance import mode_for as compliance_mode_for
from marketmyna.services import accounts
from marketmyna.services.accounts import AccountError
from marketmyna.storage import UserRecord

router = APIRouter()

# Everything is on for the owner; the frontend reads these shapes.
ALL_FEATURES_PLAN = {
    "id": "all",
    "name": "Self-hosted",
    "description": "",
    "ai_calls_month": None,
    "limits": {"watchlist_symbols": None, "price_alerts": None, "scheduled_runs_day": None, "portfolios": None},
    "features": {},
}


def me_dict(user: UserRecord) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.display_name or "",
        "role": user.role,
        # "trader" | "investor": the area the menus and pages follow; None shows both.
        "area": user.last_area,
        # IANA zone, e.g. Asia/Kolkata: scheduled report times are in this zone.
        "timezone": user.timezone or "Asia/Kolkata",
        "timezone_auto": user.timezone_auto is not False,
        # Always 'analytics': no buy / sell calls, targets or stops (marketmyna/core/compliance.py).
        "compliance": compliance_mode_for(user.id),
        "plan": ALL_FEATURES_PLAN,
    }


def _owner(request: Request, session) -> UserRecord:
    user = current_user_from_request(request, session)
    if user is None:
        raise HTTPException(status_code=500, detail="The local owner account is missing.")
    return user


@router.get("/me")
def me(request: Request, config=Depends(get_config_dep)) -> dict:
    with accounts_db(config).get_session() as session:
        return me_dict(_owner(request, session))


class ProfileRequest(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    # True: the app keeps `timezone` equal to the device's zone (sent on each visit).
    timezone_auto: Optional[bool] = None


@router.patch("/profile")
def update_profile(body: ProfileRequest, request: Request, config=Depends(get_config_dep)) -> dict:
    from marketmyna.services.schedule_time import valid_zone

    name = " ".join((body.name or "").split()) if body.name is not None else None
    if name is not None and len(name) > 80:
        raise HTTPException(status_code=400, detail="Keep the name under 80 characters.")
    if body.timezone is not None and not valid_zone(body.timezone):
        raise HTTPException(status_code=400, detail="Unknown time zone.")
    with accounts_db(config).get_session() as session:
        user = _owner(request, session)
        if name is not None:
            user.display_name = name
        if body.timezone is not None:
            user.timezone = body.timezone
        if body.timezone_auto is not None:
            user.timezone_auto = body.timezone_auto
        session.flush()
        return me_dict(user)


AREAS = ("trader", "investor")


class AreaRequest(BaseModel):
    area: str


@router.post("/area")
def choose_area(body: AreaRequest, request: Request, config=Depends(get_config_dep)) -> dict:
    """Switch between the Trader and Investor areas (kept on the account)."""
    if body.area not in AREAS:
        raise HTTPException(status_code=400, detail="Choose the Trader or the Investor area.")
    with accounts_db(config).get_session() as session:
        user = _owner(request, session)
        user.last_area = body.area
        session.flush()
        return me_dict(user)


@router.get("/export")
def export_my_data(request: Request, config=Depends(get_config_dep)) -> Response:
    """Everything the app stores for you as a JSON download. Credentials are
    left out, see data_export.REDACT."""
    from marketmyna.services.data_export import export_user

    with accounts_db(config).get_session() as session:
        user = _owner(request, session)
        data = export_user(session, user.id)
    name = f"marketmyna-data-{datetime.now():%Y-%m-%d}.json"
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


# ---- AI keys: paste a key, the provider and model are worked out from it


class ApiKeyRequest(BaseModel):
    provider: Optional[str] = None  # omitted: detected from the key
    key: str  # one key, or several separated by new lines, spaces or commas


def _keys(session, user: UserRecord, errors: Optional[list] = None) -> dict:
    out = {"providers": list(accounts.BYOK_PROVIDERS), "keys": accounts.api_keys(session, user)}
    if errors is not None:
        out["errors"] = errors
    return out


@router.get("/api-keys")
def list_api_keys(request: Request, config=Depends(get_config_dep)) -> dict:
    with accounts_db(config).get_session() as session:
        return _keys(session, _owner(request, session))


@router.put("/api-keys")
def put_api_key(body: ApiKeyRequest, request: Request, config=Depends(get_config_dep)) -> dict:
    with accounts_db(config).get_session() as session:
        user = _owner(request, session)
        try:
            errors = accounts.set_api_keys(session, config, user, body.provider, body.key)
        except AccountError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message)
        return _keys(session, user, errors)


@router.delete("/api-keys/{key_id}")
def remove_api_key(key_id: str, request: Request, config=Depends(get_config_dep)) -> dict:
    """key_id: a key's id, or a provider name (removes all its keys)."""
    with accounts_db(config).get_session() as session:
        user = _owner(request, session)
        accounts.delete_api_key(session, user, key_id)
        return _keys(session, user)
