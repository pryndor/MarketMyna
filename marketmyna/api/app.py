"""FastAPI application factory.

Auth: single-user build, every request runs as the local owner
(marketmyna/api/middlewares/auth.py).

Phase 5 adds a lifespan: RuntimeSchedulerService is started on app
startup and stopped on shutdown, stashed on app.state.scheduler so
endpoints can reach the one running instance (marketmyna/api/deps.py's
get_scheduler_service pulls it from there, matching the same
"shared services live on app.state" pattern this whole API follows).

Phase 6 adds a second background service to the same lifespan:
TelegramListener (marketmyna/bot/telegram_listener.py), started only if
config.telegram_bot_token is set (a no-op, logged, not an error,
otherwise), stashed on app.state.telegram_listener and app.state.bot_dispatcher.

The lifespan also warms the market listing cache (marketmyna/data/listings.py)
on a daemon thread so the Markets page and symbol search are instant.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from marketmyna import __version__
from marketmyna.api.deps import get_config_dep
from marketmyna.api.middlewares.auth import AuthMiddleware, api_docs_enabled, check_auth_config
from marketmyna.api.middlewares.auth import router as auth_router
from marketmyna.api.middlewares.csrf import CSRFMiddleware
from marketmyna.api.middlewares.error_handler import add_error_handlers
from marketmyna.api.middlewares.slashes import StripTrailingSlashMiddleware
from marketmyna.api.v1.endpoints.account import router as account_router
from marketmyna.api.v1.router import router as api_v1_router
from marketmyna.bot.registry import build_default_dispatcher
from marketmyna.bot.telegram_listener import TelegramListener
from marketmyna.core import tenant
from marketmyna.data.listings import get_store
from marketmyna.services.runtime_scheduler import RuntimeSchedulerService
from marketmyna.trading.alerts import AlertMonitor

# The server keeps times as naive UTC (datetime.now() in the UTC container) and
# the frontend's serverTime() reads them as UTC; pin the zone so a dev machine
# in another zone writes the same times as the server.
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()
else:  # Windows: no time.tzset(); the C runtime re-reads TZ ("UTC0": UTC, no daylight saving) on _tzset()
    os.environ["TZ"] = "UTC0"
    try:
        import ctypes

        ctypes.CDLL("ucrtbase")._tzset()
    except (OSError, AttributeError):
        pass

DEFAULT_CORS_ORIGINS = [
    "http://localhost:5174",
    "http://localhost:3000",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:3000",
]
# Extra allowed origins for a frontend on another domain that calls the API
# directly (comma-separated). Not needed normally: the API serves the built
# frontend itself (serve_frontend below), so both share one origin.
EXTRA_CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

# The built frontend: frontend/dist in a git checkout (cd frontend && npm run build),
# or marketmyna/web inside the installed package.
_PACKAGE = Path(__file__).resolve().parent.parent
FRONTEND_DIST = next((d for d in (_PACKAGE.parent / "frontend" / "dist", _PACKAGE / "web")
                      if (d / "index.html").is_file()), _PACKAGE / "web")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    config = get_config_dep()
    if getattr(config, "_plaintext_secrets", False):
        # One-time upgrade: re-save so older plain-text keys are encrypted on disk.
        config.save()

    scheduler = RuntimeSchedulerService(config)
    scheduler.start()
    app.state.scheduler = scheduler

    dispatcher = build_default_dispatcher(config, scheduler_running=scheduler.is_running)
    app.state.bot_dispatcher = dispatcher

    telegram_listener = TelegramListener(config, dispatcher)
    telegram_listener.start()
    app.state.telegram_listener = telegram_listener

    # Trade section: price alerts, checked every ALERT_POLL_SECONDS while markets are open.
    alert_monitor = AlertMonitor(config, poll_seconds=int(os.environ.get("ALERT_POLL_SECONDS", "60")))
    alert_monitor.start()
    app.state.alert_monitor = alert_monitor

    threading.Thread(target=get_store().rows, args=("all",), name="listings-warmup", daemon=True).start()

    def _warm_funds():
        import time as _t

        _t.sleep(60)  # after the listings warm-up
        from marketmyna.services.fund_rotation import warm

        warm()

    threading.Thread(target=_warm_funds, name="fund-rotation-warmup", daemon=True).start()

    from marketmyna.services.fund_holdings import refresh_loop

    threading.Thread(target=refresh_loop, name="fund-portfolios", daemon=True).start()

    from marketmyna.services.sip_days import refresh_loop as sip_days_loop

    threading.Thread(target=sip_days_loop, name="sip-days", daemon=True).start()

    from marketmyna.services.market_valuation import snapshot_loop as valuation_loop

    threading.Thread(target=valuation_loop, name="market-valuation", daemon=True).start()

    from marketmyna.services.india_flows import snapshot_loop as flows_loop

    threading.Thread(target=flows_loop, name="india-flows", daemon=True).start()

    from marketmyna.services.mf_lumpsum import alert_loop as fund_dip_loop

    threading.Thread(target=fund_dip_loop, args=(config,), name="fund-dip-alerts", daemon=True).start()

    from marketmyna.api.v1.endpoints.updates import check_loop as updates_loop

    # Looks for a new MarketMyna release / newer code on GitHub (Settings -> Updates).
    threading.Thread(target=updates_loop, name="update-check", daemon=True).start()

    try:
        yield
    finally:
        telegram_listener.stop()
        alert_monitor.stop()
        scheduler.stop()


def create_app() -> FastAPI:
    check_auth_config()
    # Every Yahoo Finance request on this server shares one pace and 429 cooldown.
    from marketmyna.utils import yahoo_gate

    yahoo_gate.install()
    # Scope every owned-table query to the signed-in user.
    tenant.enable(bool(get_config_dep().accounts_enabled))
    docs = api_docs_enabled()
    app = FastAPI(title="MarketMyna API", version=__version__, lifespan=app_lifespan, redirect_slashes=False,
                  docs_url="/docs" if docs else None, redoc_url="/redoc" if docs else None,
                  openapi_url="/openapi.json" if docs else None)

    # Added before CORS so CORS ends up outermost and 401s still carry CORS headers.
    app.add_middleware(AuthMiddleware)
    # Cross-site writes are refused before any session lookup (marketmyna/api/middlewares/csrf.py).
    app.add_middleware(CSRFMiddleware, allowed_origins=DEFAULT_CORS_ORIGINS + EXTRA_CORS_ORIGINS)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=DEFAULT_CORS_ORIGINS + EXTRA_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(StripTrailingSlashMiddleware)

    add_error_handlers(app)

    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(account_router, prefix="/api/auth/account", tags=["account"])
    app.include_router(api_v1_router, prefix="/api/v1")

    @app.get("/health")
    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    serve_frontend(app)
    return app


def serve_frontend(app: FastAPI, dist: Path = FRONTEND_DIST) -> None:
    """Serves the built frontend at /, so one uvicorn process is the whole
    app. Paths that are not files get index.html for the React router;
    unknown /api/* paths stay 404s. Does nothing before the first build."""
    dist = dist.resolve()
    if not (dist / "index.html").is_file():
        return

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404)
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        return FileResponse(dist / "index.html")


app = create_app()
