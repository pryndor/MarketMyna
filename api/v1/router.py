"""Aggregates all v1 endpoint routers."""

from fastapi import APIRouter

from api.v1.endpoints import (
    data_sources,
    agent,
    bot,
    calendar,
    health,
    listings,
    macro,
    portfolio,
    push,
    reports,
    scheduler,
    stocks,
    trade,
    system_config,
    thesis,
    watchlists,
)

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(data_sources.router, tags=["data-sources"])
router.include_router(stocks.router, tags=["stocks"])
router.include_router(listings.router, tags=["listings"])
router.include_router(portfolio.router, tags=["portfolio"])
router.include_router(watchlists.router, tags=["watchlists"])
router.include_router(system_config.router, tags=["system-config"])
router.include_router(agent.router, tags=["agent"])
router.include_router(scheduler.router, tags=["scheduler"])
router.include_router(bot.router, tags=["bot"])
router.include_router(push.router, tags=["push"])
router.include_router(reports.router, tags=["reports"])
router.include_router(trade.router, tags=["trade"])
router.include_router(calendar.router, tags=["calendar"])
router.include_router(macro.router, tags=["macro"])
router.include_router(thesis.router, tags=["thesis"])
