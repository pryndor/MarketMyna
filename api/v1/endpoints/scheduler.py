"""Runtime scheduler endpoints: persisted schedule config, status, and a
manual "run now" that shares the exact same run path
(RuntimeSchedulerService.run_now()) the background timer loop uses -
there is only one "do a run" code path in the whole service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.deps import get_config_dep, get_scheduler_service
from src.llm.channels import llm_configured
from src.notifiers.dispatcher import NotificationDispatcher
from src.core.compliance import mode as compliance_mode
from src.services.report import DEFAULT_SECTIONS, SECTION_AREAS, clean_sections, section_catalog
from src.data.categories import CATEGORIES
from src.services.report_i18n import BUILTIN_LANGUAGES, LANGUAGES
from src.services import schedule_time
from src.services.schedule_config import (
    SMART_FILE_CHANNELS, SMART_FILES, SOURCES, ScheduleConfig, ScheduleConfigStore, ideas_market, resolve_targets, source_catalog,
)

router = APIRouter()


class ScheduleConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = None
    time_of_day: Optional[str] = None
    symbols: Optional[List[str]] = None
    market: Optional[str] = None
    mode: Optional[str] = None
    report_language: Optional[str] = None
    report_sections: Optional[List[str]] = None
    stock_sections: Optional[Dict[str, List[str]]] = None
    channel_languages: Optional[Dict[str, str]] = None
    mf_codes: Optional[List[str]] = None
    ideas_market: Optional[str] = None
    ideas_categories: Optional[List[str]] = None
    ideas_count: Optional[int] = None
    smart_enabled: Optional[bool] = None
    smart_top_n: Optional[int] = None
    smart_ai_top: Optional[int] = None
    smart_email_full: Optional[bool] = None
    smart_file: Optional[str] = None
    smart_file_channels: Optional[List[str]] = None
    report_base_url: Optional[str] = None
    sources: Optional[List[str]] = None
    watchlist_ids: Optional[List[int]] = None
    portfolio_names: Optional[List[str]] = None


def _ideas_market(cfg: ScheduleConfig, config) -> str:
    """The market the ideas scan will use (picked, or from the run's stocks)."""
    try:
        return ideas_market(cfg, resolve_targets(cfg, config))
    except Exception:
        return ideas_market(cfg, [])


def _to_dict(cfg: ScheduleConfig, config=None) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "interval_minutes": cfg.interval_minutes,
        "time_of_day": cfg.time_of_day,
        "symbols": cfg.symbols,
        "market": cfg.market,
        "mode": cfg.mode,
        "last_run_at": cfg.last_run_at.isoformat() if cfg.last_run_at else None,
        "last_run_status": cfg.last_run_status,
        "last_run_summary": cfg.last_run_summary,
        "report_language": cfg.report_language or "en",
        "report_sections": cfg.report_sections if cfg.report_sections is not None else list(DEFAULT_SECTIONS),
        "stock_sections": cfg.stock_sections or {},
        "channel_languages": cfg.channel_languages or {},
        "mf_codes": cfg.mf_codes or [],
        "ideas_market": _ideas_market(cfg, config),
        "ideas_categories": cfg.ideas_categories or [],
        "ideas_count": cfg.ideas_count or 3,
        "smart_enabled": bool(cfg.smart_enabled),
        "smart_top_n": cfg.smart_top_n or 5,
        "smart_ai_top": cfg.smart_ai_top if cfg.smart_ai_top is not None else 10,
        "smart_email_full": cfg.smart_email_full if cfg.smart_email_full is not None else True,
        "smart_file": cfg.smart_file if cfg.smart_file in SMART_FILES else "pdf",
        "smart_file_channels": list(cfg.smart_file_channels if cfg.smart_file_channels is not None
                                    else SMART_FILE_CHANNELS),
        "report_base_url": cfg.report_base_url or "",
        "sources": cfg.run_sources(),
        "watchlist_ids": cfg.watchlist_ids or [],
        "portfolio_names": cfg.portfolio_names or [],
        "stock_count": cfg.stock_count,
        "area": cfg.area,
    }


def _stock_count(cfg: ScheduleConfig, config) -> int:
    """Stocks the run will cover."""
    try:
        return len(resolve_targets(cfg, config))
    except Exception:
        return cfg.stock_count or 0


@router.get("/scheduler/config")
def get_schedule_config(config=Depends(get_config_dep)) -> dict:
    return _to_dict(ScheduleConfigStore(config=config).load(), config)


def _session_area(request: Request, config) -> Optional[str]:
    """The area ("trader" / "investor") the owner is working in, or None."""
    if not getattr(config, "accounts_enabled", False):
        return None
    from api.middlewares.auth import accounts_db, current_user_from_request

    with accounts_db(config).get_session() as session:
        user = current_user_from_request(request, session)
        return user.last_area if user is not None else None


@router.put("/scheduler/config")
def update_schedule_config(body: ScheduleConfigUpdate, request: Request, config=Depends(get_config_dep)) -> dict:
    overrides = body.model_dump(exclude_unset=True)
    # The report follows the area it was set up in (its sections only).
    area = _session_area(request, config)
    if area:
        overrides["area"] = area
    if overrides.get("time_of_day"):
        try:
            hour, minute = schedule_time.parse_time(overrides["time_of_day"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Use a 24-hour time such as 08:45 or 18:30.")
        overrides["time_of_day"] = f"{hour:02d}:{minute:02d}"
    if overrides.get("interval_minutes") is not None and overrides["interval_minutes"] < 1:
        raise HTTPException(status_code=400, detail="Repeat every 1 minute or more.")
    if "report_language" in overrides and overrides["report_language"] not in LANGUAGES:
        raise HTTPException(status_code=400, detail=f"Unknown language '{overrides['report_language']}'")
    if overrides.get("report_sections") is not None:
        overrides["report_sections"] = clean_sections(overrides["report_sections"])
    if overrides.get("stock_sections") is not None:
        overrides["stock_sections"] = {
            sym.strip().upper(): clean_sections(secs) for sym, secs in overrides["stock_sections"].items() if sym.strip()
        }
    if overrides.get("channel_languages") is not None:
        bad = [lang for lang in overrides["channel_languages"].values() if lang and lang not in LANGUAGES]
        if bad:
            raise HTTPException(status_code=400, detail=f"Unknown language '{bad[0]}'")
        overrides["channel_languages"] = {ch: lang for ch, lang in overrides["channel_languages"].items() if lang}
    if overrides.get("mf_codes") is not None:
        overrides["mf_codes"] = [c.strip() for c in overrides["mf_codes"] if c.strip().isdigit()]
    if overrides.get("ideas_count") is not None:
        overrides["ideas_count"] = max(1, min(10, overrides["ideas_count"]))
    if overrides.get("ideas_categories") is not None:
        overrides["ideas_categories"] = [c for c in overrides["ideas_categories"] if c in CATEGORIES]
    if overrides.get("smart_top_n") is not None:
        overrides["smart_top_n"] = max(1, min(20, overrides["smart_top_n"]))
    if overrides.get("smart_ai_top") is not None:
        overrides["smart_ai_top"] = max(0, min(50, overrides["smart_ai_top"]))
    if overrides.get("smart_file") is not None and overrides["smart_file"] not in SMART_FILES:
        raise HTTPException(status_code=400, detail="Report file must be pdf, xlsx or none.")
    if overrides.get("smart_file_channels") is not None:
        overrides["smart_file_channels"] = [c for c in SMART_FILE_CHANNELS if c in overrides["smart_file_channels"]]
    if "report_base_url" in overrides:
        url = (overrides["report_base_url"] or "").strip().rstrip("/")
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Public address must start with http:// or https://")
        overrides["report_base_url"] = url or None
    if overrides.get("sources") is not None:
        overrides["sources"] = [s for s in SOURCES if s in overrides["sources"]]
    store = ScheduleConfigStore(config=config)
    after = store.load()
    for key, value in overrides.items():
        setattr(after, key, value)
    after.stock_count = _stock_count(after, config)
    store.save(after)
    return _to_dict(after, config)


@router.get("/scheduler/status")
def get_scheduler_status(scheduler=Depends(get_scheduler_service), config=Depends(get_config_dep)) -> dict:
    cfg = ScheduleConfigStore(config=config).load()
    return {"running": scheduler.is_running(), "schedule": _to_dict(cfg, config)}


@router.post("/scheduler/run-now")
def run_now(request: Request, scheduler=Depends(get_scheduler_service), config=Depends(get_config_dep)) -> dict:
    """Starts an immediate out-of-band run in the background, independent of
    the schedule/timer - same watchdog-guarded child-process path and
    notification push as a normal scheduled run. GET /scheduler/run-now
    tells when it's done."""
    area = _session_area(request, config)
    store = ScheduleConfigStore(config=config)
    if area and store.load().area != area:
        store.update(area=area)  # "Run now" from the investor area gives the investor report
    if not scheduler.start_run_now():
        raise HTTPException(status_code=409, detail="Your report is already running.")
    return {"started": True}


@router.get("/scheduler/run-now")
def run_now_state(scheduler=Depends(get_scheduler_service)) -> dict:
    """{"running": bool, "result": the last Run now's outcome or None}."""
    return scheduler.run_now_state()


@router.get("/scheduler/sources")
def run_sources(config=Depends(get_config_dep)) -> dict:
    """Watchlists and portfolios a run can cover, with their symbols."""
    return source_catalog(config)


@router.get("/scheduler/report-options")
def report_options(config=Depends(get_config_dep)) -> dict:
    """Everything the Scheduler page needs to build the report settings UI."""
    dispatcher = NotificationDispatcher(config)
    return {
        "languages": [
            {"code": code, "native": native, "english": english, "builtin": code in BUILTIN_LANGUAGES}
            for code, (native, english) in LANGUAGES.items()
        ],
        "sections": [
            {"id": sid, "label": label, "description": desc, "default": default,
             # "trader" / "investor": shown only in that area of the app (None = both)
             "area": SECTION_AREAS.get(sid)}
            for sid, label, desc, default in section_catalog()
        ],
        "channels": dispatcher.configured_channels("report"),
        "categories": [c for c in CATEGORIES if c != "Other"],
        "llm_configured": llm_configured(config),
        # Always "analytics": no calls or stock ideas; Smart messaging shows readings
        "compliance": compliance_mode(),
    }
