"""SQLAlchemy persistence layer for MarketMyna.

Single-file models + a small DatabaseManager. Everything lives in one
SQLite file under ~/.marketmyna/: create_all() makes the tables and
_add_missing_columns() adds columns that newer models bring.
"""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from marketmyna.core.home import app_home, db_filename

from .core import tenant

Base = declarative_base()

# Column sizes shared by several tables.
SYMBOL = 64
MARKET = 32
SHORT = 32  # status / kind / type / mode / currency style values
NAME = 200
DAY = 10  # YYYY-MM-DD
TOKEN = 64


def _owner(ondelete: str = "CASCADE") -> Column:
    """The owning account. Nullable while local single-user mode (no
    accounts) shares these tables; becomes NOT NULL in the multi-user
    migration once every query is scoped to the current user."""
    return Column(Integer, ForeignKey("users.id", ondelete=ondelete), nullable=True, index=True)


# ==================== Accounts ====================


class UserRecord(Base):
    """The local owner (single-user build: one row, made on first use)."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(320), unique=True, nullable=False, index=True)
    email_verified_at = Column(DateTime, nullable=True)
    display_name = Column(String(NAME), default="")
    role = Column(String(16), default="admin", nullable=False)
    status = Column(String(16), default="active", nullable=False, index=True)
    timezone = Column(String(64), default="Asia/Kolkata")
    # Follow the time zone of the device the app is opened on (None = on);
    # False keeps the zone picked by hand.
    timezone_auto = Column(Boolean, nullable=True)
    locale = Column(String(16), default="en")
    created_at = Column(DateTime, default=datetime.now)
    # The area ("trader" | "investor") the menus and pages follow (None = both).
    last_area = Column(String(16), nullable=True)


class UserApiKeyRecord(Base):
    """An AI provider key (Settings -> AI keys), AES-GCM encrypted with the
    master key. Only the last 4 characters are shown. Several may be kept (any
    providers, also two of one); AI tries them oldest first and falls back to
    the next on any failure (ai_access)."""

    __tablename__ = "user_api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(SHORT), nullable=False)  # gemini | groq | openai | anthropic | ...
    key_ciphertext = Column(LargeBinary, nullable=False)
    key_last4 = Column(String(8), default="")
    model = Column(String(128), nullable=True)  # litellm id picked for the key; null = provider default
    free = Column(Boolean, nullable=True)  # key has only free access (None = unknown)
    note = Column(String(255), nullable=True)  # what was detected, shown to the user
    created_at = Column(DateTime, default=datetime.now)
    last_used_at = Column(DateTime, nullable=True)


# ==================== Portfolio domain ====================


class PortfolioRecord(Base):
    __tablename__ = "portfolios"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_portfolio_user_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    name = Column(String(NAME), nullable=False, index=True)
    cash_balance = Column(Float, default=0.0)
    currency = Column(String(8), default="USD")
    # "stocks" | "funds" (mutual funds); None on old rows = inferred from the holdings.
    # Free has one of each (marketmyna/services/free_picks.py).
    kind = Column(String(16), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    holdings = relationship(
        "HoldingRecord", back_populates="portfolio", cascade="all, delete-orphan"
    )
    transactions = relationship(
        "TransactionRecord",
        back_populates="portfolio",
        cascade="all, delete-orphan",
        order_by="TransactionRecord.id",
    )


class FundDipRuleRecord(Base):
    """A user's own dip-alert levels for mutual funds (marketmyna/services/mf_lumpsum.py):
    % below the 52-week high, e.g. [5, 7.5, 10]. fund_code None = the
    portfolio's default for all its funds; a code = an override for that fund."""

    __tablename__ = "fund_dip_rules"
    __table_args__ = (UniqueConstraint("portfolio_id", "fund_code", name="uq_dip_rule_portfolio_fund"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    fund_code = Column(String(SYMBOL), nullable=True)
    levels = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class PortfolioReviewRuleRecord(Base):
    """A user's own limits for the portfolio review (marketmyna/portfolio/review.py):
    max % per holding / sector / cash, loss level to flag, minimum holdings."""

    __tablename__ = "portfolio_review_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, unique=True)
    limits = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class HoldingRecord(Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("portfolio_id", "symbol", name="uq_holding_portfolio_symbol"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(SYMBOL), nullable=False)
    quantity = Column(Float, default=0.0)
    avg_cost = Column(Float, default=0.0)
    current_price = Column(Float, default=0.0)
    market = Column(String(MARKET), default="US")

    portfolio = relationship("PortfolioRecord", back_populates="holdings")


class TransactionRecord(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(SYMBOL), nullable=False)
    transaction_type = Column(String(SHORT), nullable=False)
    quantity = Column(Float)
    price = Column(Float)
    date = Column(DateTime)
    fees = Column(Float, default=0.0)
    notes = Column(Text, default="")
    market = Column(String(MARKET), nullable=True)

    portfolio = relationship("PortfolioRecord", back_populates="transactions")


# ==================== Alerts domain ====================


# ==================== Scheduler domain ====================


class ScheduleConfigRecord(Base):
    """The runtime scheduler's persisted config - one row per user in
    accounts mode, a single row otherwise - which symbols to analyze, how often, and the outcome of the
    last run. No cron-expression parser: either "every N minutes" or
    "once daily at HH:MM", which covers the realistic personal-tool cases
    without the complexity of a real cron grammar."""

    __tablename__ = "schedule_config"

    id = Column(Integer, primary_key=True)
    user_id = _owner()
    enabled = Column(Boolean, default=False)
    interval_minutes = Column(Integer, nullable=True)  # e.g. 60 -> every hour
    time_of_day = Column(String(16), nullable=True)  # e.g. "09:30" -> once daily
    symbols = Column(JSON, default=list)
    market = Column(String(MARKET), default="us")
    mode = Column(String(SHORT), default="standard")
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(SHORT), nullable=True)
    last_run_summary = Column(Text, nullable=True)
    # Report content/delivery preferences (see marketmyna/services/report.py)
    report_language = Column(String(16), nullable=True)
    report_sections = Column(JSON, nullable=True)
    stock_sections = Column(JSON, nullable=True)
    channel_languages = Column(JSON, nullable=True)
    mf_codes = Column(JSON, nullable=True)
    # Smart messaging: short "top N" message + link to the full report
    smart_enabled = Column(Boolean, nullable=True)
    smart_top_n = Column(Integer, nullable=True)
    smart_ai_top = Column(Integer, nullable=True)
    smart_email_full = Column(Boolean, nullable=True)
    # Smart messaging's report file: "pdf" | "xlsx" | "none" (None = pdf), and the
    # channels it goes to (None = email and telegram). marketmyna/services/smart_file.py.
    smart_file = Column(String(8), nullable=True)
    smart_file_channels = Column(JSON, nullable=True)
    report_base_url = Column(Text, nullable=True)
    # What a run covers: "watchlist", "portfolio", "custom" (the symbols list)
    sources = Column(JSON, nullable=True)
    watchlist_ids = Column(JSON, nullable=True)  # empty = every watchlist
    portfolio_names = Column(JSON, nullable=True)  # empty = every portfolio
    # Stocks a run covers (worked out when saved and after each run): what the
    # schedule costs in its time slot (marketmyna/services/schedule_slots.py).
    stock_count = Column(Integer, nullable=True)
    # "trader" / "investor": the login area the report was set up in. A run
    # includes only that area's sections (report.SECTION_AREAS).
    area = Column(String(16), nullable=True)


# ==================== Watchlist domain ====================


class WatchlistRecord(Base):
    """A named list of instruments to track - no quantities or money, just
    what to keep an eye on (holdings live in the portfolio domain)."""

    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    name = Column(String(NAME), nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    items = relationship(
        "WatchlistItemRecord",
        back_populates="watchlist",
        cascade="all, delete-orphan",
        order_by="WatchlistItemRecord.id",
    )


class WatchlistItemRecord(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "market", "type", "symbol", name="uq_watchlist_item"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    watchlist_id = Column(Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(SYMBOL), nullable=False)
    market = Column(String(MARKET), nullable=False)
    type = Column(String(16), nullable=False, default="stock")  # stock | etf | mf | crypto
    name = Column(String(500), default="")
    note = Column(Text, default="")
    added_at = Column(DateTime, default=datetime.now)

    watchlist = relationship("WatchlistRecord", back_populates="items")


# ==================== Web push domain ====================


class WebPushSubscriptionRecord(Base):
    """A browser/device that allowed MarketMyna push notifications (the
    PushSubscription a service worker returns)."""

    __tablename__ = "web_push_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    endpoint = Column(String(700), unique=True, nullable=False)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(255), nullable=False)
    label = Column(String(NAME), default="")
    created_at = Column(DateTime, default=datetime.now)
    last_success_at = Column(DateTime, nullable=True)


# ==================== LLM cache / usage ====================


class LLMCacheRecord(Base):
    """A recent AI answer, reused for an identical request so free-tier
    quotas aren't spent twice on the same prompt."""

    __tablename__ = "llm_cache"

    key = Column(String(TOKEN), primary_key=True)  # sha256 of the request
    text = Column(Text, nullable=False)
    model = Column(String(255), default="")
    created_at = Column(DateTime, default=datetime.now, index=True)


class LLMUsageRecord(Base):
    """Per-day, per-model counters for the Settings usage panel."""

    __tablename__ = "llm_usage"
    __table_args__ = (UniqueConstraint("day", "route", name="uq_llm_usage_day_route"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    day = Column(String(DAY), nullable=False, index=True)  # YYYY-MM-DD
    route = Column(String(255), nullable=False)  # e.g. "fast:groq/llama-3.3-70b-versatile"
    calls = Column(Integer, default=0)
    failures = Column(Integer, default=0)
    cache_hits = Column(Integer, default=0)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    # The latest failure that day: retired / quota / key / timeout / outage / other.
    last_error_kind = Column(String(32), nullable=True)
    last_error = Column(String(300), nullable=True)


# ==================== Social sentiment ====================


class SocialSentimentRecord(Base):
    """One day's social-sentiment reading per stock (latest fetch of the
    day wins) - the history behind the Analyze page's trend line. Shared
    market data, so no owner."""

    __tablename__ = "social_sentiment"
    __table_args__ = (UniqueConstraint("symbol", "market", "day", name="uq_social_sentiment_symbol_day"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(SYMBOL), nullable=False, index=True)
    market = Column(String(MARKET), nullable=False)
    day = Column(String(DAY), nullable=False, index=True)  # YYYY-MM-DD
    score = Column(Float, nullable=False)  # -100 (bearish) .. +100 (bullish)
    posts = Column(Integer, default=0)
    bullish = Column(Integer, default=0)
    bearish = Column(Integer, default=0)
    neutral = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.now)


# ==================== Saved reports ====================


class ReportRunRecord(Base):
    """One scheduled run's full per-stock table, opened through the link in
    a smart message. The token is the unguessable part of that link."""

    __tablename__ = "report_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    token = Column(String(TOKEN), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    title = Column(String(500), default="")
    stock_count = Column(Integer, default=0)
    rows = Column(JSON, default=list)
    meta = Column(JSON, default=dict)


# ==================== Trade section ====================


class PriceAlertRecord(Base):
    """A trader's price / indicator alert, checked by marketmyna/trading/alerts.py's
    AlertMonitor during market hours."""

    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    symbol = Column(String(SYMBOL), nullable=False, index=True)
    market = Column(String(MARKET), nullable=False)
    kind = Column(String(SHORT), nullable=False)  # see marketmyna/trading/alerts.py KINDS
    value = Column(Float, nullable=False)
    note = Column(Text, default="")
    status = Column(String(16), default="active", index=True)  # active | paused | triggered | expired
    repeat = Column(Boolean, default=False)  # re-arm once the condition clears
    armed = Column(Boolean, default=True)
    cooldown_minutes = Column(Integer, default=30)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    last_checked_at = Column(DateTime, nullable=True)
    last_value = Column(Float, nullable=True)  # what the condition last measured
    last_triggered_at = Column(DateTime, nullable=True)
    trigger_count = Column(Integer, default=0)


class PriceAlertEventRecord(Base):
    """One firing of a price alert (the Alerts tab's history)."""

    __tablename__ = "price_alert_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    alert_id = Column(Integer, index=True)
    symbol = Column(String(SYMBOL), nullable=False)
    market = Column(String(MARKET), nullable=False)
    kind = Column(String(SHORT), nullable=False)
    message = Column(Text, default="")
    price = Column(Float, nullable=True)
    delivery = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now, index=True)


class SavedScanRecord(Base):
    """A scanner setup the trader re-runs; with notify on, AlertMonitor runs
    it every interval while its market is open and sends new matches."""

    __tablename__ = "saved_scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    name = Column(String(NAME), nullable=False)
    universe = Column(JSON, default=dict)  # see marketmyna/trading/scanner.py resolve_universe
    scans = Column(JSON, default=list)
    params = Column(JSON, default=dict)
    match = Column(String(8), default="any")  # any | all
    notify = Column(Boolean, default=False)
    interval_minutes = Column(Integer, default=15)
    created_at = Column(DateTime, default=datetime.now)
    last_run_at = Column(DateTime, nullable=True)
    last_count = Column(Integer, nullable=True)
    notified_day = Column(String(DAY), nullable=True)  # YYYY-MM-DD the list below belongs to
    notified_symbols = Column(JSON, default=list)  # already sent today, so only new matches go out


class TradeRiskSettingsRecord(Base):
    """Singleton (id=1): the trader's daily risk rules (marketmyna/trading/risk.py)."""

    __tablename__ = "trade_risk_settings"

    id = Column(Integer, primary_key=True)
    user_id = _owner()
    market = Column(String(MARKET), default="india")  # whose trades / currency the rules cover
    capital = Column(Float, default=100000.0)
    daily_loss_limit_pct = Column(Float, default=2.0)
    max_open_risk_pct = Column(Float, default=5.0)
    max_trades_per_day = Column(Integer, default=5)
    notify = Column(Boolean, default=True)
    notified_day = Column(String(DAY), nullable=True)


class CalendarSettingsRecord(Base):
    """Singleton (id=1): event-calendar reminder settings (marketmyna/services/calendar.py)."""

    __tablename__ = "calendar_settings"

    id = Column(Integer, primary_key=True)
    user_id = _owner()
    notify = Column(Boolean, default=True)
    days_before = Column(Integer, default=1)  # remind about events within this many days
    notify_hour = Column(Integer, default=8)  # local hour (in `timezone`) the daily digest goes out
    timezone = Column(String(64), default="Asia/Kolkata")
    notified_day = Column(String(DAY), nullable=True)  # YYYY-MM-DD the digest was last handled
    hidden_events = Column(Text, nullable=True)  # comma-separated event type keys the user turned off
    results_sent = Column(Text, nullable=True)  # "YYYY-MM-DD:key,key" release results already sent that day
    # "My events list": which lists feed the calendar ("w:<id>" / "p:<id>"; null = every list)
    sources = Column(JSON, nullable=True)
    extra_symbols = Column(JSON, nullable=True)  # [{symbol, market}] followed just for events


class EventAlertRecord(Base):
    """A named event alert: its own stocks, event types and send time; one message per run."""

    __tablename__ = "event_alerts"

    id = Column(Integer, primary_key=True)
    user_id = _owner()
    name = Column(String(NAME), nullable=False)
    enabled = Column(Boolean, default=True)
    sources = Column(JSON, nullable=True)  # like CalendarSettingsRecord.sources; [] = only `symbols`
    symbols = Column(JSON, nullable=True)  # [{symbol, market}] added to this alert
    event_types = Column(JSON, nullable=True)  # event type keys (marketmyna/services/calendar.py); null = all
    days_before = Column(Integer, default=1)
    notify_hour = Column(Integer, default=8)
    notified_day = Column(String(DAY), nullable=True)


class CustomEventRecord(Base):
    """A user's own dated item (SIP date, IPO listing, AGM...), optionally repeating."""

    __tablename__ = "custom_events"

    id = Column(Integer, primary_key=True)
    user_id = _owner()
    title = Column(String(NAME), nullable=False)
    date = Column(String(DAY), nullable=False)  # first (or only) occurrence, YYYY-MM-DD
    repeat = Column(String(SHORT), default="none")  # none | monthly | yearly
    note = Column(Text, nullable=True)


class ThesisRecord(Base):
    """Why the user owns (or watches) a stock: falsifiable statement, pillars,
    risks, exit / target levels and a dated log (marketmyna/services/thesis.py)."""

    __tablename__ = "theses"
    __table_args__ = (UniqueConstraint("user_id", "symbol", "market", name="uq_thesis_user_symbol"),)

    id = Column(Integer, primary_key=True)
    user_id = _owner()
    symbol = Column(String(SYMBOL), nullable=False)
    market = Column(String(MARKET), nullable=False)
    statement = Column(Text, nullable=False)
    pillars = Column(JSON, nullable=True)  # [{text, status: on_track | watch | broken}]
    risks = Column(JSON, nullable=True)  # [text]
    exit_below = Column(Float, nullable=True)  # price that would break the thesis
    exit_note = Column(Text, nullable=True)  # what else would make you exit
    target = Column(Float, nullable=True)  # what it is worth if the thesis plays out
    conviction = Column(String(SHORT), default="medium")  # high | medium | low
    log = Column(JSON, nullable=True)  # [{date, note, impact: strengthens | weakens | neutral, conviction}]
    created_at = Column(DateTime, default=datetime.now)
    reviewed_at = Column(String(DAY), nullable=True)  # YYYY-MM-DD of the last review
    alerted = Column(JSON, nullable=True)  # {"exit": day, "target": day, "review": day} messages sent


class TradeRecord(Base):
    """A trade journal entry. Open while exit_price is empty."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = _owner()
    symbol = Column(String(SYMBOL), nullable=False, index=True)
    market = Column(String(MARKET), nullable=False)
    side = Column(String(8), default="long")  # long | short
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    entry_at = Column(DateTime, default=datetime.now)
    exit_price = Column(Float, nullable=True)
    exit_at = Column(DateTime, nullable=True)
    stop = Column(Float, nullable=True)
    target = Column(Float, nullable=True)
    fees = Column(Float, default=0.0)
    fees_auto = Column(Boolean, nullable=True)  # fees computed by marketmyna/trading/charges.py
    product = Column(String(16), nullable=True)  # india: intraday | delivery | futures | options
    setup = Column(String(NAME), default="")  # e.g. "breakout", "pullback"
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)


# ==================== Feedback ====================


# ==================== Usage analytics ====================


# ==================== Telegram subscribers ====================


# ==================== Security monitoring ====================


# ==================== Maintenance notices ====================


# ==================== Engine / session management ====================


# Accounts mode: these tables are filtered to the signed-in user on every
# query (marketmyna/core/tenant.py). Feedback and usage only get the author's id;
# the admin reads them across users. Each user has their own scheduled
# report (schedule_config).
tenant.configure(
    owned=(
        PortfolioRecord, WatchlistRecord, WebPushSubscriptionRecord, ReportRunRecord,
        PriceAlertRecord, PriceAlertEventRecord, SavedScanRecord, TradeRiskSettingsRecord,
        CalendarSettingsRecord, TradeRecord, ScheduleConfigRecord,
        FundDipRuleRecord, PortfolioReviewRuleRecord, EventAlertRecord, CustomEventRecord, ThesisRecord,
    ),
)

# Every table, by whose rows it holds. tests/test_tenant_isolation.py checks
# that each table is listed exactly once (here or in tenant.configure above),
# so a new table can't skip the decision.
#
# One user's rows, filtered by an explicit `user_id == ...` in the one service
# that reads them (accounts, AI access) - not by the automatic scope,
# because some code works before or across a user scope.
SELF_FILTERED_TABLES = frozenset({
    "users", "user_api_keys",
})
# No user_id of their own: reached only through their owned parent row.
CHILD_TABLES = {"holdings": "portfolios", "transactions": "portfolios", "watchlist_items": "watchlists"}
# Not tied to a user: AI usage counters and the shared market-data and
# AI answer caches.
PLATFORM_TABLES = frozenset({"llm_cache", "llm_usage", "social_sentiment"})


def resolve_db_path(
    config=None, override_dir: Optional[Path] = None, filename: Optional[str] = None
) -> Path:
    """Pick the db file: an explicit Config.db_path wins, then an override
    directory (e.g. a manager's legacy data_dir, or a test's tmp_path), then
    the shared default under ~/.marketmyna/."""
    if config is not None and getattr(config, "db_path", None):
        return Path(config.db_path)
    folder = Path(override_dir) if override_dir is not None else app_home()
    return folder / (filename or db_filename(folder))


def has_app_db(config=None) -> bool:
    """Whether this machine has the app's SQLite file (a fresh GitHub runner
    does not)."""
    return resolve_db_path(config=config).exists()


def get_db_url(config=None, override_dir: Optional[Path] = None, filename: Optional[str] = None) -> str:
    path = resolve_db_path(config=config, override_dir=override_dir, filename=filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.absolute()}"


def _make_private(db_url: str) -> None:
    """The SQLite file holds sessions and encrypted keys: owner-only access."""
    import os

    path = Path(db_url.split("///", 1)[-1])
    for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            if p.exists():
                os.chmod(p, 0o600)
        except OSError:
            pass


# Called with every new engine (marketmyna/security/dbwatch.py counts queries and
# notes slow / failing ones for the admin's Security page).
ENGINE_HOOKS: list = []


def _finite(value):
    """NaN / infinity -> None, all the way down (a stock without a price
    carries NaN, which is not valid JSON)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_finite(v) for v in value]
    return value


def json_dumps(value) -> str:
    """Serializer for every JSON column: always valid JSON."""
    return json.dumps(_finite(value))


class DatabaseManager:
    """One instance per distinct db_url, cached so callers sharing a db file
    share an engine/connection pool instead of each opening their own."""

    _instances: dict[str, "DatabaseManager"] = {}

    def __init__(self, db_url: str):
        self.db_url = db_url
        if not db_url.startswith("sqlite"):
            raise ValueError(f"MarketMyna stores its data in SQLite; got {db_url!r}")
        self.engine = create_engine(
            db_url, pool_pre_ping=True, connect_args={"check_same_thread": False}, json_serializer=json_dumps
        )
        with self.engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
        _make_private(db_url)
        for hook in ENGINE_HOOKS:
            hook(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        """create_all() never alters existing tables, so columns added to a
        model later are appended here (nullable, no data rewrite) - enough
        for this app's additive schema changes without a migration tool."""
        inspector = inspect(self.engine)
        with self.engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if not inspector.has_table(table.name):
                    continue
                existing = {c["name"] for c in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in existing:
                        continue
                    col_type = column.type.compile(dialect=self.engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))

    @classmethod
    def instance(cls, db_url: str) -> "DatabaseManager":
        if db_url not in cls._instances:
            cls._instances[db_url] = cls(db_url)
        return cls._instances[db_url]

    @contextmanager
    def get_session(self):
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
