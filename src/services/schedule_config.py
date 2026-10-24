"""Persisted runtime-scheduler configuration: a singleton row (id=1) in
ScheduleConfigRecord, loaded/saved through the same DatabaseManager
pattern as PortfolioManager."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..storage import DatabaseManager, ScheduleConfigRecord, get_db_url


@dataclass
class ScheduleConfig:
    enabled: bool = False
    # Exactly one of these two should be set: interval_minutes for "every
    # N minutes", time_of_day ("HH:MM") for "once daily". No cron grammar.
    interval_minutes: Optional[int] = None
    time_of_day: Optional[str] = None
    symbols: list[str] = field(default_factory=list)
    market: str = "us"
    mode: str = "standard"
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_run_summary: Optional[str] = None
    # Report content & delivery (src/services/report.py)
    report_language: str = "en"
    report_sections: Optional[list[str]] = None  # None = default sections
    stock_sections: dict[str, list[str]] = field(default_factory=dict)
    channel_languages: dict[str, str] = field(default_factory=dict)
    mf_codes: list[str] = field(default_factory=list)
    # "New ideas" section: where to look and how many to suggest
    ideas_market: Optional[str] = None  # None = the schedule's market
    ideas_categories: list[str] = field(default_factory=list)  # empty = any category
    ideas_count: int = 3
    # Smart messaging (src/services/smart_report.py)
    smart_enabled: bool = False
    smart_top_n: int = 5
    smart_ai_top: int = 10
    smart_email_full: bool = True
    smart_file: str = "pdf"  # "pdf" | "xlsx" | "none"
    smart_file_channels: Optional[list[str]] = None  # None = email and telegram
    report_base_url: Optional[str] = None
    # What to run: any of SOURCES. None = legacy config, i.e. ["custom"].
    sources: Optional[list[str]] = None
    watchlist_ids: list[int] = field(default_factory=list)  # empty = all
    portfolio_names: list[str] = field(default_factory=list)  # empty = all
    stock_count: Optional[int] = None  # stocks a run covers: its cost in a time slot
    area: Optional[str] = None  # "trader" / "investor": only that area's sections; None = all

    def run_sources(self) -> list[str]:
        return [s for s in (self.sources if self.sources is not None else ["custom"]) if s in SOURCES]

    def has_targets_configured(self) -> bool:
        """Cheap due-check: something to run, without touching the DB."""
        srcs = self.run_sources()
        return bool(("custom" in srcs and self.symbols) or "watchlist" in srcs or "portfolio" in srcs)

    def report_prefs(self, timezone: str = "Asia/Kolkata"):
        from .report import DEFAULT_SECTIONS, SECTION_AREAS, ReportPrefs, clean_sections

        def own_area(sections: list[str]) -> list[str]:
            # The page keeps the other area's choices saved; the report leaves them out.
            if self.area not in ("trader", "investor"):
                return sections
            return [s for s in sections if SECTION_AREAS.get(s, self.area) == self.area]

        return ReportPrefs(
            language=self.report_language or "en",
            sections=own_area(clean_sections(self.report_sections) if self.report_sections is not None
                              else list(DEFAULT_SECTIONS)),
            stock_sections={k.upper(): own_area(clean_sections(v)) for k, v in (self.stock_sections or {}).items()},
            channel_languages=dict(self.channel_languages or {}),
            mode=self.mode,
            timezone=timezone,
            funds=list(self.mf_codes or []),
            portfolios=list(self.portfolio_names or []),
            ideas_market=self.ideas_market or self.market,
            ideas_categories=list(self.ideas_categories or []),
            ideas_count=self.ideas_count or 3,
            smart=bool(self.smart_enabled),
            smart_top_n=self.smart_top_n or 5,
            smart_ai_top=self.smart_ai_top if self.smart_ai_top is not None else 10,
            smart_email_full=self.smart_email_full is not False,
            smart_file=self.smart_file if self.smart_file in SMART_FILES else "pdf",
            smart_file_channels=list(self.smart_file_channels if self.smart_file_channels is not None
                                     else SMART_FILE_CHANNELS),
            report_base_url=self.report_base_url or None,
        )


SOURCES = ("watchlist", "portfolio", "custom")
# Smart messaging report file formats and the channels that can carry a file.
SMART_FILES = ("pdf", "xlsx", "none")
SMART_FILE_CHANNELS = ("email", "telegram")
KNOWN_MARKETS = {"us", "india", "china_a", "hong_kong", "crypto", "global"}


def source_catalog(config=None) -> dict:
    """Every watchlist and portfolio with the symbols a run would take from
    it (funds and closed positions excluded - they have no chart analysis)."""
    from ..storage import HoldingRecord, PortfolioRecord, WatchlistRecord

    db = DatabaseManager.instance(get_db_url(config=config))
    with db.get_session() as session:
        watchlists = [
            {
                "id": w.id,
                "name": w.name,
                "symbols": [{"symbol": i.symbol.upper(), "market": i.market} for i in items if i.type != "mf"],
                "funds": [str(i.symbol) for i in items if i.type == "mf"],
            }
            for w in session.query(WatchlistRecord).order_by(WatchlistRecord.id)
            for items in [list(w.items)]
        ]
        portfolios = []
        for p in session.query(PortfolioRecord).order_by(PortfolioRecord.id):
            holdings = session.query(HoldingRecord).filter(HoldingRecord.portfolio_id == p.id).all()
            symbols, funds = [], []
            for h in holdings:
                if (h.quantity or 0) <= 0:
                    continue
                market = (h.market or "us").lower()
                if market == "mf":  # mutual fund (AMFI code): reported in the funds section, not analysed
                    funds.append(str(h.symbol))
                    continue
                symbols.append({"symbol": h.symbol.upper(), "market": market if market in KNOWN_MARKETS else "us"})
            portfolios.append({"id": p.id, "name": p.name, "symbols": symbols, "funds": funds})
    return {"watchlists": watchlists, "portfolios": portfolios}


def resolve_targets(cfg: ScheduleConfig, config=None, catalog: Optional[dict] = None):
    """The (symbol, market) pairs a run covers, from the chosen sources,
    de-duplicated in source order (portfolio first: what you own matters most)."""
    from .analysis_run import Target

    srcs = cfg.run_sources()
    if srcs != ["custom"] and catalog is None:
        catalog = source_catalog(config)
    pairs: list[tuple[str, str]] = []
    if "portfolio" in srcs:
        for p in catalog["portfolios"]:
            if not cfg.portfolio_names or p["name"] in cfg.portfolio_names:
                pairs += [(s["symbol"], s["market"]) for s in p["symbols"]]
    if "watchlist" in srcs:
        for w in catalog["watchlists"]:
            if not cfg.watchlist_ids or w["id"] in cfg.watchlist_ids:
                pairs += [(s["symbol"], s["market"]) for s in w["symbols"]]
    if "custom" in srcs:
        pairs += [(s.upper(), cfg.market) for s in cfg.symbols]
    return [Target(sym, mkt) for sym, mkt in dict.fromkeys(pairs)]


# Markets the stock-ideas scan can cover (src/services/ideas.py).
IDEAS_MARKETS = ("us", "india", "china_a", "hong_kong", "crypto")


def ideas_market(cfg: ScheduleConfig, targets) -> str:
    """Market the "New stock ideas" section scans: the one picked in the
    Scheduler, else the market most of the run's stocks are in (an Indian
    watchlist gets Indian ideas), else the schedule's market."""
    if cfg.ideas_market in IDEAS_MARKETS:
        return cfg.ideas_market
    counts = Counter(t.market for t in targets if t.market in IDEAS_MARKETS)
    if counts:
        return counts.most_common(1)[0][0]
    return cfg.market if cfg.market in IDEAS_MARKETS else "us"


def resolve_funds(cfg: ScheduleConfig, config=None, catalog: Optional[dict] = None) -> list[str]:
    """AMFI codes for the report's funds section: the ones picked in Settings,
    then funds held in / watched on the run's chosen portfolios and watchlists."""
    codes = [str(c) for c in (cfg.mf_codes or [])]
    srcs = cfg.run_sources()
    if srcs != ["custom"]:
        catalog = catalog or source_catalog(config)
        if "portfolio" in srcs:
            for p in catalog["portfolios"]:
                if not cfg.portfolio_names or p["name"] in cfg.portfolio_names:
                    codes += p.get("funds", [])
        if "watchlist" in srcs:
            for w in catalog["watchlists"]:
                if not cfg.watchlist_ids or w["id"] in cfg.watchlist_ids:
                    codes += w.get("funds", [])
    return list(dict.fromkeys(codes))


class ScheduleConfigStore:
    def __init__(self, config=None):
        self._db = DatabaseManager.instance(get_db_url(config=config))

    @staticmethod
    def _record(session):
        # One row per user in accounts mode (the query is user-scoped), a
        # single row otherwise.
        return session.query(ScheduleConfigRecord).order_by(ScheduleConfigRecord.id).first()

    def load(self) -> ScheduleConfig:
        with self._db.get_session() as session:
            record = self._record(session)
            if record is None:
                return ScheduleConfig()
            return ScheduleConfig(
                enabled=bool(record.enabled),
                interval_minutes=record.interval_minutes,
                time_of_day=record.time_of_day,
                symbols=list(record.symbols or []),
                market=record.market or "us",
                mode=record.mode or "standard",
                last_run_at=record.last_run_at,
                last_run_status=record.last_run_status,
                last_run_summary=record.last_run_summary,
                report_language=record.report_language or "en",
                report_sections=list(record.report_sections) if record.report_sections is not None else None,
                stock_sections=dict(record.stock_sections or {}),
                channel_languages=dict(record.channel_languages or {}),
                mf_codes=list(record.mf_codes or []),
                ideas_market=record.ideas_market,
                ideas_categories=list(record.ideas_categories or []),
                ideas_count=record.ideas_count or 3,
                smart_enabled=bool(record.smart_enabled),
                smart_top_n=record.smart_top_n or 5,
                smart_ai_top=record.smart_ai_top if record.smart_ai_top is not None else 10,
                smart_email_full=record.smart_email_full is not False,
                smart_file=record.smart_file or "pdf",
                smart_file_channels=list(record.smart_file_channels) if record.smart_file_channels is not None else None,
                report_base_url=record.report_base_url,
                sources=list(record.sources) if record.sources is not None else None,
                watchlist_ids=[int(i) for i in (record.watchlist_ids or [])],
                portfolio_names=list(record.portfolio_names or []),
                stock_count=record.stock_count,
                area=record.area,
            )

    def save(self, cfg: ScheduleConfig) -> None:
        with self._db.get_session() as session:
            record = self._record(session)
            if record is None:
                record = ScheduleConfigRecord()
                session.add(record)
            record.enabled = cfg.enabled
            record.interval_minutes = cfg.interval_minutes
            record.time_of_day = cfg.time_of_day
            record.symbols = list(cfg.symbols)
            record.market = cfg.market
            record.mode = cfg.mode
            record.last_run_at = cfg.last_run_at
            record.last_run_status = cfg.last_run_status
            record.last_run_summary = cfg.last_run_summary
            record.report_language = cfg.report_language
            record.report_sections = list(cfg.report_sections) if cfg.report_sections is not None else None
            record.stock_sections = dict(cfg.stock_sections or {})
            record.channel_languages = dict(cfg.channel_languages or {})
            record.mf_codes = list(cfg.mf_codes or [])
            record.ideas_market = cfg.ideas_market
            record.ideas_categories = list(cfg.ideas_categories or [])
            record.ideas_count = cfg.ideas_count
            record.smart_enabled = cfg.smart_enabled
            record.smart_top_n = cfg.smart_top_n
            record.smart_ai_top = cfg.smart_ai_top
            record.smart_email_full = cfg.smart_email_full
            record.smart_file = cfg.smart_file
            record.smart_file_channels = list(cfg.smart_file_channels) if cfg.smart_file_channels is not None else None
            record.report_base_url = cfg.report_base_url
            record.sources = list(cfg.sources) if cfg.sources is not None else None
            record.watchlist_ids = list(cfg.watchlist_ids or [])
            record.portfolio_names = list(cfg.portfolio_names or [])
            record.stock_count = cfg.stock_count
            record.area = cfg.area

    def update(self, **overrides) -> ScheduleConfig:
        """Partial update: load, apply only the given fields, save, return
        the merged result - same semantics as system_config.py's PUT
        endpoints (exclude_unset upstream, full-replace fields here)."""
        cfg = self.load()
        for key, value in overrides.items():
            setattr(cfg, key, value)
        self.save(cfg)
        return cfg
