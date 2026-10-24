"""One scheduled-analysis run: analyze a list of symbols and turn the
results into a human-readable report for notification channels.

Shared by the in-app RuntimeSchedulerService and the headless runner
(marketmyna/cli/scheduled_run.py, for cron or a server), so a scheduled
message looks the same no matter which of them sent it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

MARKET_LABELS = {
    "us": "US",
    "india": "India",
    "china_a": "China A",
    "hong_kong": "Hong Kong",
    "crypto": "Crypto",
    "global": "Global",
}
# Timezone the trading-day check and report timestamp use, per market.
MARKET_TIMEZONES = {
    "india": "Asia/Kolkata",
    "us": "America/New_York",
    "china_a": "Asia/Shanghai",
    "hong_kong": "Asia/Hong_Kong",
}



@dataclass
class Target:
    symbol: str
    market: str


def parse_targets(spec: str, default_market: str) -> list[Target]:
    """"RELIANCE, TCS, us:AAPL" -> targets; a "market:" prefix overrides
    the default market for that one symbol. Duplicates are dropped."""
    seen: set[tuple[str, str]] = set()
    targets: list[Target] = []
    for raw in spec.replace("\n", ",").split(","):
        item = raw.strip()
        if not item:
            continue
        market = default_market
        if ":" in item:
            prefix, rest = item.split(":", 1)
            if prefix.lower() in MARKET_LABELS:
                market, item = prefix.lower(), rest.strip()
        key = (item.upper(), market)
        if item and key not in seen:
            seen.add(key)
            targets.append(Target(item.upper(), market))
    return targets


def is_trading_day(market: str, now: Optional[datetime] = None) -> bool:
    """Weekday check in the market's own timezone. Crypto never closes.
    Exchange holidays aren't known here - a holiday run just reports
    the previous close."""
    if market in ("crypto", "global"):
        return True
    tz = ZoneInfo(MARKET_TIMEZONES.get(market, "UTC"))
    now = now.astimezone(tz) if now else datetime.now(tz)
    return now.weekday() < 5


def _quote(symbol: str, market: str) -> dict:
    """Best-effort price/change for the report header line."""
    try:
        from ..core.constants import Markets
        from ..data.china import ChinaAFetcher, HongKongFetcher
        from ..data.crypto import CryptoDataFetcher
        from ..data.india import IndiaDataFetcher
        from ..data.stocks import StockDataFetcher

        fetcher = {
            Markets.INDIA: IndiaDataFetcher,
            Markets.CRYPTO: CryptoDataFetcher,
            Markets.CHINA_A: ChinaAFetcher,
            Markets.HONG_KONG: HongKongFetcher,
        }.get(Markets(market), StockDataFetcher)()
        return fetcher.get_quote(symbol) or {}
    except Exception as exc:  # the report is still useful without a price
        logger.warning("Quote for %s (%s) unavailable: %s", symbol, market, exc)
        return {}


# Yahoo Finance ticker for markets whose native codes differ.
def yahoo_symbol(symbol: str, market: str) -> str:
    s = symbol.upper()
    if market == "india":
        return s if s.startswith("^") or s.endswith((".NS", ".BO")) else f"{s}.NS"
    if market == "china_a":
        return f"{s}.SS" if s[:1] in "569" else f"{s}.BJ" if s[:1] in "48" else f"{s}.SZ"
    if market == "hong_kong":
        return f"{int(s):04d}.HK" if s.isdigit() else s
    if market == "crypto":
        return s if "-" in s else f"{s}-USD"
    return s


MARKET_INDICES = {
    "india": [("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX"), ("^NSEBANK", "NIFTY Bank")],
    "us": [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones")],
    "china_a": [("000001.SS", "Shanghai Composite"), ("399001.SZ", "Shenzhen Component")],
    "hong_kong": [("^HSI", "Hang Seng")],
    "crypto": [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum")],
}


def market_overview(markets) -> list[dict]:
    """Index level + day change for each market in the run (best effort)."""
    from ..data.stocks import StockDataFetcher

    fetcher = StockDataFetcher()
    out = []
    for market in dict.fromkeys(markets):
        for ticker, name in MARKET_INDICES.get(market, []):
            try:
                q = fetcher.get_quote(ticker)
                out.append({"market": market, "name": name, "price": q.get("price"),
                            "change_percent": q.get("change_percent")})
            except Exception as exc:
                logger.warning("Index %s unavailable: %s", ticker, exc)
    return out


def _to_str_date(value):
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def collect_extras(symbol: str, market: str, sections, ctx=None) -> dict:
    """Per-stock data beyond the agent pipeline, fetched only for the
    sections someone actually asked for. Every piece is best effort."""
    sections = set(sections or [])
    extras: dict = {}
    yf_symbol = yahoo_symbol(symbol, market)
    info: dict = {}

    def load_info() -> dict:
        nonlocal info
        if not info and market != "crypto":
            try:
                import yfinance as yf

                info = yf.Ticker(yf_symbol).info or {}
            except Exception as exc:
                logger.warning("Info for %s unavailable: %s", yf_symbol, exc)
        return info

    # The movers list flags stocks near their 52-week high / low, so it needs the range too.
    if "price" in sections or "calls" in sections:
        data = load_info() if market != "crypto" else {}
        extras["high_52w"] = data.get("fiftyTwoWeekHigh")
        extras["low_52w"] = data.get("fiftyTwoWeekLow")
        extras["name"] = data.get("shortName") or data.get("longName")

    if "fundamentals" in sections and market != "crypto":
        fundamentals = getattr(ctx, "fundamental_summary", None) if ctx else None
        if not fundamentals and load_info():
            try:
                from ..analysis.fundamental import FundamentalAnalyzer, yfinance_fundamentals

                fundamentals = FundamentalAnalyzer(yfinance_fundamentals(info)).get_summary()
            except Exception as exc:
                logger.warning("Fundamentals for %s unavailable: %s", symbol, exc)
        if fundamentals:
            extras["fundamentals"] = {
                k: fundamentals.get(k)
                for k in ("overall_score", "valuation", "profitability", "financial_health", "growth", "dividend")
            }

    if "analysts" in sections and load_info().get("recommendationKey"):
        extras["analysts"] = {
            "recommendation": info.get("recommendationKey"),
            "target_mean": info.get("targetMeanPrice"),
            "count": info.get("numberOfAnalystOpinions"),
        }

    if "events" in sections and market != "crypto":
        try:
            import yfinance as yf

            cal = yf.Ticker(yf_symbol).calendar or {}
            extras["events"] = {
                "earnings_date": _to_str_date(cal.get("Earnings Date")),
                "ex_dividend_date": _to_str_date(cal.get("Ex-Dividend Date")),
            }
        except Exception as exc:
            logger.warning("Calendar for %s unavailable: %s", yf_symbol, exc)

    if "valuation" in sections and market != "crypto":
        try:
            from .valuation import meter

            v = meter(symbol, market)
            if v.get("status") == "ok":
                extras["valuation"] = {k: v.get(k) for k in ("position", "zone", "multiples", "sector")}
        except Exception as exc:
            logger.warning("Valuation for %s unavailable: %s", symbol, exc)

    if "levels" in sections:
        # Daily-bar levels (support, resistance, stop, ATR, ranges) from the
        # history the Technical step already fetched.
        try:
            from .smart_report import compute_snapshot

            history = getattr(ctx, "history", None) if ctx else None
            if history is None:
                from ..agent.agents import _resolve_fetcher

                history = _resolve_fetcher(market).get_history(symbol, period="1y")
            snap = compute_snapshot(history)
            extras["levels"] = {k: snap.get(k) for k in (
                "price", "buy_point", "sell_point", "stop_loss", "atr", "normal_low", "normal_high",
                "week_low", "week_high", "trend")}
        except Exception as exc:
            logger.warning("Trade levels for %s unavailable: %s", symbol, exc)

    if "news" in sections:
        # The pipeline's News step already fetched headlines; reuse them.
        news = getattr(ctx, "news", None) if ctx else None
        if news is None:
            try:
                from ..data.news_search import stock_news

                news = stock_news(symbol, market, limit=3, name=extras.get("name"))
            except Exception as exc:
                logger.warning("News for %s unavailable: %s", symbol, exc)
                news = []
        extras["news"] = news[:3]
    return extras


def analyze_symbol(symbol: str, market: str, mode: str, config, orchestrator=None, sections=None) -> dict:
    """Run the agent pipeline for one symbol, never raising.

    If a critical stage (normally the AI decision) fails, the opinions
    that did finish (technical, risk) are still returned in `dashboard`
    with ok=False, so the report can show the technical read instead of
    only an error. `sections` (report section ids) decides which extra
    data - news, fundamentals, analysts, events - is fetched.
    """
    from ..agent.context import AgentContext
    from ..agent.dashboard import build_dashboard
    from ..agent.orchestrator import AgentOrchestrator

    ctx = AgentContext(symbol=symbol, market=market, mode=mode)
    result: dict = {"symbol": symbol, "market": market, "quote": _quote(symbol, market)}
    try:
        orchestrator = orchestrator or AgentOrchestrator(config=config)
        orchestrator.run(symbol, market, mode=mode, ctx=ctx)
        result.update(ok=True, dashboard=build_dashboard(ctx))
    except Exception as exc:
        result.update(
            ok=False,
            error=str(exc) or type(exc).__name__,
            dashboard=build_dashboard(ctx) if ctx.opinions else None,
        )
    if sections:
        extras = collect_extras(symbol, market, sections, ctx)
        result["name"] = extras.pop("name", None)
        result["extras"] = extras
    return result


def notify_failure(config, summary: str, dispatcher=None) -> dict[str, bool]:
    """Tell the system-error channels a scheduled run failed, so a silent
    morning (no report) never goes unnoticed. Never raises."""
    try:
        from ..notifiers.dispatcher import NotificationDispatcher

        dispatcher = dispatcher or NotificationDispatcher(config)
        return dispatcher.send_all(summary, title="⚠️ MarketMyna scheduled run failed", purpose="system_error")
    except Exception:
        logger.exception("Could not send failure notification")
        return {}


def deliver_report(results: list[dict], prefs, config, dispatcher=None, dry_run: bool = False):
    """Render the report once per language any channel wants, then send
    each configured channel its own language.

    Returns (reports, delivery): reports maps language -> (title, body)
    and always includes prefs.language; delivery maps channel -> sent ok.
    """
    from ..notifiers.dispatcher import NotificationDispatcher
    from .report import market_review, render_reports
    from .report_i18n import normalize_language

    dispatcher = dispatcher or NotificationDispatcher(config)
    channels = dispatcher.configured_channels("report")
    by_lang = prefs.languages_needed(channels)
    languages = [normalize_language(prefs.language), *by_lang]

    overview = market_take = None
    if "market" in prefs.sections:
        overview = market_overview(r["market"] for r in results)
        market_take = market_review(overview, results, config)
    funds = None
    if "funds" in prefs.sections and prefs.funds:
        from .funds import fund_snapshots

        funds = fund_snapshots(prefs.funds)
        try:  # lumpsum window / dip check per fund (cached, equity and hybrid only)
            from .mf_lumpsum import assess_fund

            for f in funds:
                f["lumpsum"] = assess_fund(f["code"], f.get("category") or "", f.get("name") or "")
        except Exception as exc:
            logger.warning("Fund dip check unavailable: %s", exc)

    sections = prefs.all_sections()
    portfolios = portfolio_snapshots(prefs.portfolios, results, config) if "portfolio" in sections else None
    alerts = alert_digest(results, config) if "alerts" in sections else None
    hot = hot_blocks(results, sections)

    reports = render_reports(results, prefs, languages, config=config, overview=overview,
                             funds=funds, market_take=market_take,
                             portfolios=portfolios, alerts=alerts, hot=hot)
    messages = {ch: reports[lang] for lang, chs in by_lang.items() for ch in chs}
    if dry_run or not messages:
        return reports, {}
    return reports, dispatcher.send_each(messages, purpose="report")


def _one_user_scope() -> bool:
    """Personal report data (portfolios, alerts) is only read for one user:
    in accounts mode a SYSTEM or missing scope would mix every user's rows."""
    from ..core import tenant

    return not tenant.enabled() or tenant.current_user_id() is not None


CURRENCY = {"india": "₹", "us": "$", "china_a": "¥", "hong_kong": "HK$", "crypto": "$", "mf": "₹"}


def portfolio_snapshots(names: list[str], results: list[dict], config=None, quote=None) -> list[dict]:
    """Value, today's change and total gain of each portfolio (all of them
    when `names` is empty), priced from the report's own quotes where it has
    them. Mutual funds use their latest NAV. Best effort, never raises."""
    from ..storage import DatabaseManager, HoldingRecord, PortfolioRecord, get_db_url

    if not _one_user_scope():
        return []
    quote = quote or _quote
    known = {(r["symbol"].upper(), r["market"]): r.get("quote") or {} for r in results}
    out = []
    try:
        with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
            rows = []
            for p in session.query(PortfolioRecord).order_by(PortfolioRecord.id):
                if names and p.name not in names:
                    continue
                holdings = [(h.symbol, (h.market or "us").lower(), h.quantity or 0, h.avg_cost or 0, h.current_price or 0)
                            for h in session.query(HoldingRecord).filter(HoldingRecord.portfolio_id == p.id)
                            if (h.quantity or 0) > 0]
                rows.append((p.name, holdings))
    except Exception as exc:
        logger.warning("Portfolios unavailable for the report: %s", exc)
        return []
    for name, holdings in rows:
        if not holdings:
            continue
        value = cost = day = prev_value = 0.0
        movers, markets = [], set()
        for symbol, market, qty, avg, last in holdings:
            markets.add(market)
            price = change = None
            if market == "mf":
                try:
                    from .mf_holdings import latest

                    info = latest(symbol) or {}
                    price, change = info.get("nav"), None
                except Exception:
                    pass
            else:
                q = known.get((symbol.upper(), market))
                if q is None:
                    try:
                        q = quote(symbol, market)
                    except Exception:
                        q = {}
                price, change = q.get("price"), q.get("change")
            price = price or last
            if not price:
                continue
            value += qty * price
            cost += qty * avg
            if change is not None:
                day += qty * change
                prev_value += qty * (price - change)
                movers.append({"symbol": symbol.upper(), "change": qty * change,
                               "change_pct": change / (price - change) * 100 if price - change else None})
            else:
                prev_value += qty * price
        movers.sort(key=lambda m: -abs(m["change"]))
        cur = CURRENCY.get(next(iter(markets)), "") if len(markets - {"mf"}) <= 1 else ""
        out.append({
            "name": name, "value": value, "currency_symbol": cur,
            "day_change": day, "day_change_pct": day / prev_value * 100 if prev_value else None,
            "gain": value - cost if cost else None, "gain_pct": (value - cost) / cost * 100 if cost else None,
            "movers": [m for m in movers[:3] if m["change"]],
        })
    return out


def alert_digest(results: list[dict], config=None, now: Optional[datetime] = None, quote=None,
                 near_pct: float = 3.0) -> dict:
    """The user's price alerts for the report: what fired in the last day, and
    active price alerts within `near_pct` of their level. Never raises."""
    from datetime import timedelta

    from ..storage import DatabaseManager, PriceAlertEventRecord, PriceAlertRecord, get_db_url
    from ..trading.alerts import describe

    if not _one_user_scope():
        return {}
    quote = quote or _quote
    now = now or datetime.now()
    known = {(r["symbol"].upper(), r["market"]): r.get("quote") or {} for r in results}
    try:
        with DatabaseManager.instance(get_db_url(config=config)).get_session() as session:
            fired = [{"symbol": e.symbol, "message": e.message, "at": e.created_at}
                     for e in session.query(PriceAlertEventRecord)
                     .filter(PriceAlertEventRecord.created_at >= now - timedelta(hours=24))
                     .order_by(PriceAlertEventRecord.created_at.desc())]
            active = [(a.symbol, a.market, a.kind, a.value)
                      for a in session.query(PriceAlertRecord).filter(PriceAlertRecord.status == "active")]
    except Exception as exc:
        logger.warning("Alerts unavailable for the report: %s", exc)
        return {}
    near = []
    for symbol, market, kind, level in active:
        if kind not in ("price_above", "price_below") or not level:
            continue
        q = known.get((symbol.upper(), market))
        if q is None:
            try:
                q = quote(symbol, market)
            except Exception:
                continue
            known[(symbol.upper(), market)] = q
        price = q.get("price")
        if not price:
            continue
        distance = (level - price) / price * 100
        if abs(distance) <= near_pct:
            near.append({"symbol": symbol, "describe": describe(kind, level), "distance_pct": distance})
    near.sort(key=lambda a: abs(a["distance_pct"]))
    return {"fired": fired, "near": near, "active": len(active)}


# Boards each hot section shows in a report, three rows each.
HOT_BOARDS = {"hot_trade": ("trader", ("momentum", "activity", "breakouts")),
              "hot_invest": ("investor", ("quality_dip", "earnings", "funds_adding"))}


def hot_blocks(results: list[dict], sections, rows_per_board: int = 3) -> list[dict]:
    """Hot / trending stocks for the report's stock markets (marketmyna/services/hot_stocks.py)."""
    from . import hot_stocks
    from .discovery import DISCOVERY_MARKETS

    markets = [m for m in dict.fromkeys(r["market"] for r in results) if m in DISCOVERY_MARKETS]
    out = []
    for section, (area, keys) in HOT_BOARDS.items():
        if section not in sections or not markets:
            continue
        per_market = {}
        for market in markets:
            try:
                data = hot_stocks.trader(market) if area == "trader" else hot_stocks.investor(market)
            except Exception as exc:
                logger.warning("Hot stocks (%s, %s) unavailable: %s", area, market, exc)
                continue
            boards = [{**b, "rows": b["rows"][:rows_per_board]} for b in data["boards"] if b["key"] in keys]
            per_market[market] = boards
        out.append({"section": section, "area": area, "markets": per_market})
    return out

