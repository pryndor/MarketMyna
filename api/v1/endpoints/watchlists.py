"""Watchlists: named lists of instruments to track (no quantities or cost -
that's what portfolios are for). Items are enriched with live price data
from the market listing cache (src/data/listings.py)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.deps import get_config_dep, get_db_session
from src.data.listings import MARKET_LABELS, get_store
from src.storage import WatchlistItemRecord, WatchlistRecord

router = APIRouter()

DEFAULT_WATCHLIST = "My watchlist"

# Listing fields copied onto each item so the page can render a full row.
_LIVE_FIELDS = (
    "name", "exchange", "sector", "category", "category_inferred", "price", "change",
    "change_percent", "volume", "market_cap", "high_52w", "low_52w", "currency",
    "name_local", "amc", "fund_group", "plan", "option", "isin", "nav_date",
)


class WatchlistBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ItemBody(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    market: str = "us"
    type: str = "stock"
    name: str = ""
    note: str = ""


def _summary(record: WatchlistRecord) -> dict:
    return {"id": record.id, "name": record.name, "count": len(record.items)}


def _all(db: Session) -> list[WatchlistRecord]:
    records = db.query(WatchlistRecord).order_by(WatchlistRecord.id).all()
    if not records:
        # Everyone starts with one list, so "add to watchlist" always has a target.
        # A savepoint, so a parallel first request creating the same list
        # (unique per user) only loses its insert, not the whole request.
        try:
            with db.begin_nested():
                db.add(WatchlistRecord(name=DEFAULT_WATCHLIST))
        except IntegrityError:
            pass
        records = db.query(WatchlistRecord).order_by(WatchlistRecord.id).all()
    return records


def _get(db: Session, watchlist_id: int) -> WatchlistRecord:
    record = db.get(WatchlistRecord, watchlist_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Watchlist {watchlist_id} not found")
    return record


def _item_dict(item: WatchlistItemRecord, live: Optional[dict]) -> dict:
    out = {
        "id": item.id,
        "watchlist_id": item.watchlist_id,
        "symbol": item.symbol,
        "market": item.market,
        "type": item.type,
        "name": item.name or item.symbol,
        "note": item.note or "",
        "added_at": item.added_at.isoformat() if item.added_at else None,
        "listed": live is not None,
    }
    if live:
        out.update({k: live.get(k) for k in _LIVE_FIELDS if k in live})
    return out


def _unique_name(db: Session, name: str, exclude_id: Optional[int] = None) -> str:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    clash = db.query(WatchlistRecord).filter(WatchlistRecord.name == name).first()
    if clash and clash.id != exclude_id:
        raise HTTPException(status_code=409, detail=f"A watchlist named '{name}' already exists")
    return name


@router.get("/watchlists")
def list_watchlists(db: Session = Depends(get_db_session), config=Depends(get_config_dep)) -> list[dict]:
    return [_summary(r) for r in _all(db)]


@router.post("/watchlists", status_code=201)
def create_watchlist(body: WatchlistBody, db: Session = Depends(get_db_session),
                     config=Depends(get_config_dep)) -> dict:
    record = WatchlistRecord(name=_unique_name(db, body.name))
    db.add(record)
    db.flush()
    return _summary(record)


@router.patch("/watchlists/{watchlist_id}")
def rename_watchlist(watchlist_id: int, body: WatchlistBody, db: Session = Depends(get_db_session)) -> dict:
    record = _get(db, watchlist_id)
    record.name = _unique_name(db, body.name, exclude_id=record.id)
    return _summary(record)


@router.delete("/watchlists/{watchlist_id}", status_code=204)
def delete_watchlist(watchlist_id: int, db: Session = Depends(get_db_session)) -> Response:
    db.delete(_get(db, watchlist_id))
    return Response(status_code=204)


@router.get("/watchlists/items")
def all_items(db: Session = Depends(get_db_session)) -> list[dict]:
    """Every item across lists (no live data) - lets the UI mark stars."""
    _all(db)
    # The join keeps items to the caller's own lists (watchlists are user-scoped).
    items = (
        db.query(WatchlistItemRecord)
        .join(WatchlistRecord, WatchlistItemRecord.watchlist_id == WatchlistRecord.id)
        .order_by(WatchlistItemRecord.id)
        .all()
    )
    return [
        {"id": i.id, "watchlist_id": i.watchlist_id, "symbol": i.symbol, "market": i.market, "type": i.type}
        for i in items
    ]


@router.get("/watchlists/{watchlist_id}")
def get_watchlist(watchlist_id: int, db: Session = Depends(get_db_session), config=Depends(get_config_dep)) -> dict:
    record = _get(db, watchlist_id)
    keys = [(i.market, i.type, i.symbol) for i in record.items if i.market in MARKET_LABELS]
    live = get_store().lookup(keys) if keys else {}
    return {
        **_summary(record),
        "items": [_item_dict(i, live.get((i.market, i.type, i.symbol))) for i in record.items],
    }


@router.post("/watchlists/{watchlist_id}/items", status_code=201)
def add_item(watchlist_id: int, body: ItemBody, db: Session = Depends(get_db_session),
             config=Depends(get_config_dep)) -> dict:
    record = _get(db, watchlist_id)
    symbol = body.symbol.strip().upper() if body.type != "mf" else body.symbol.strip()
    market = body.market.strip().lower()
    existing = next(
        (i for i in record.items if i.symbol == symbol and i.market == market and i.type == body.type), None
    )
    if existing:
        return _item_dict(existing, None)
    item = WatchlistItemRecord(
        watchlist_id=record.id, symbol=symbol, market=market, type=body.type, name=body.name, note=body.note
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"{symbol} is already in this watchlist")
    return _item_dict(item, None)


@router.delete("/watchlists/{watchlist_id}/items/{item_id}", status_code=204)
def remove_item(watchlist_id: int, item_id: int, db: Session = Depends(get_db_session)) -> Response:
    record = _get(db, watchlist_id)  # 404s for someone else's list
    item = db.get(WatchlistItemRecord, item_id)
    if item is None or item.watchlist_id != record.id:
        raise HTTPException(status_code=404, detail="Item not found")
    db.delete(item)
    return Response(status_code=204)
