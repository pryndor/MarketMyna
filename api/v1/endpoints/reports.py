"""Saved smart reports: the full table behind a smart message's link.

A report is addressed only by its random token (unguessable, like a share
link), so the /r/<token> page works for anyone the link was sent to."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_config_dep
from src.storage import DatabaseManager, ReportRunRecord, get_db_url

router = APIRouter()


def _summary(rec: ReportRunRecord) -> dict:
    return {
        "token": rec.token,
        "title": rec.title,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "stock_count": rec.stock_count,
    }


@router.get("/reports")
def list_reports(limit: int = 20, config=Depends(get_config_dep)) -> list[dict]:
    db = DatabaseManager.instance(get_db_url(config=config))
    with db.get_session() as session:
        recs = (
            session.query(ReportRunRecord)
            .order_by(ReportRunRecord.created_at.desc(), ReportRunRecord.id.desc())
            .limit(max(1, min(100, limit)))
            .all()
        )
        return [_summary(r) for r in recs]


@router.get("/reports/{token}")
def get_report(token: str, config=Depends(get_config_dep)) -> dict:
    db = DatabaseManager.instance(get_db_url(config=config))
    with db.get_session() as session:
        rec = session.query(ReportRunRecord).filter_by(token=token).first()
        if rec is None:
            raise HTTPException(status_code=404, detail="Report not found")
        from src.services.smart_report import without_calls

        # Reports saved before calls were removed still hold them: strip on the way out.
        rows = [r if "reading" in r or "error" in r else without_calls(r) for r in rec.rows or []]
        return {**_summary(rec), "rows": rows, "meta": {**(rec.meta or {}), "compliance": "analytics"}}
