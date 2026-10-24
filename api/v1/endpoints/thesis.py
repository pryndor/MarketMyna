"""Thesis tracker (src/services/thesis.py): one thesis per stock, its update
log, and a check against live data."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.deps import get_config_dep
from src.utils.deadline import call_with_deadline

router = APIRouter()


class Pillar(BaseModel):
    text: str = Field(max_length=300)
    status: str = "on_track"


class ThesisIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    market: str = Field(min_length=1, max_length=32)
    statement: Optional[str] = Field(default=None, max_length=2000)
    pillars: Optional[list[Pillar]] = Field(default=None, max_length=10)
    risks: Optional[list[str]] = Field(default=None, max_length=10)
    exit_below: Optional[float] = None
    exit_note: Optional[str] = Field(default=None, max_length=500)
    target: Optional[float] = None
    conviction: Optional[str] = None
    clear_exit: bool = False
    clear_target: bool = False


class LogIn(BaseModel):
    note: str = Field(min_length=1, max_length=1000)
    impact: str
    conviction: Optional[str] = None


def _key(symbol: str, market: str) -> tuple[str, str]:
    market = market.lower()
    return (symbol.strip() if market == "mf" else symbol.strip().upper()), market


@router.get("/theses")
def list_theses(check: bool = Query(default=False), config=Depends(get_config_dep)) -> list[dict]:
    """Every thesis; with check=true each also gets its live data check."""
    from src.services import thesis

    rows = thesis.list_all(config)
    if not check:
        return rows
    return call_with_deadline(lambda: [thesis.with_check(t) for t in rows], 120)


@router.get("/theses/{symbol}")
def get_thesis(symbol: str, market: str = Query(default="us"), config=Depends(get_config_dep)) -> dict:
    from src.services import thesis

    t = thesis.get(config, *_key(symbol, market))
    if t is None:
        return {"thesis": None}
    return {"thesis": call_with_deadline(thesis.with_check, 60, t)}


@router.put("/theses")
def save_thesis(body: ThesisIn, config=Depends(get_config_dep)) -> dict:
    from src.services import thesis

    fields = body.model_dump(exclude_none=True, exclude={"symbol", "market", "clear_exit", "clear_target"})
    if body.clear_exit:
        fields["exit_below"] = None
    if body.clear_target:
        fields["target"] = None
    try:
        t = thesis.save(config, *_key(body.symbol, body.market), **fields)
    except thesis.ThesisError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"thesis": call_with_deadline(thesis.with_check, 60, t)}


@router.post("/theses/{thesis_id}/log")
def add_log(thesis_id: int, body: LogIn, config=Depends(get_config_dep)) -> dict:
    from src.services import thesis

    try:
        t = thesis.add_log(config, thesis_id, body.note, body.impact, body.conviction)
    except thesis.ThesisError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if t is None:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return {"thesis": call_with_deadline(thesis.with_check, 60, t)}


@router.post("/theses/{thesis_id}/reviewed")
def reviewed(thesis_id: int, config=Depends(get_config_dep)) -> dict:
    from src.services import thesis

    t = thesis.mark_reviewed(config, thesis_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return {"thesis": call_with_deadline(thesis.with_check, 60, t)}


@router.delete("/theses/{thesis_id}", status_code=204)
def delete_thesis(thesis_id: int, config=Depends(get_config_dep)) -> None:
    from src.services import thesis

    if not thesis.delete(config, thesis_id):
        raise HTTPException(status_code=404, detail="Thesis not found")
