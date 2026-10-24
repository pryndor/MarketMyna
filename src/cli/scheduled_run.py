"""Headless scheduled analysis: analyze a stock list, then push the report
to every configured notification channel.

Runs anywhere - cron, a server, your laptop:

    python -m src.cli.scheduled_run --symbols "RELIANCE,TCS,us:AAPL" --market india
    python -m src.cli.scheduled_run --watchlist "My watchlist" --dry-run

Everything can also come from environment variables, which is how the
workflow passes GitHub Secrets/Variables in:

    STOCK_LIST       symbols, comma-separated; "market:SYMBOL" overrides the market
    MARKET           default market for unprefixed symbols (default: india)
    ANALYSIS_MODE    quick | standard | full | specialist (default: standard)
    REPORT_TIMEZONE  timestamp timezone in the report (default: Asia/Kolkata)
    TRADING_DAY_CHECK_ENABLED  "false" to also run on weekends
    REPORT_LANGUAGE  default report language code, e.g. en, hi, ta, zh (default: en)
    REPORT_SECTIONS  comma-separated section ids (see src/services/report.py SECTIONS)
    STOCK_SECTIONS   per-stock sections: "RELIANCE=news+fundamentals,TCS=technical"
    CHANNEL_LANGUAGES  per-channel language: "telegram:ta,email:en"
    SMART_MESSAGING  "true": short top-N message + full report (HTML email/file)
    SMART_TOP_N      stocks in the short message (default 5)
    SMART_AI_TOP     stocks that get the AI pipeline (default 10; 0 = none)
    SMART_EMAIL_FULL "false": email gets only the short message
    REPORT_BASE_URL  public MarketMyna address for full-report links
    MF_LIST          AMFI scheme codes for the mutual-fund section: "122639,120503"
    IDEAS_MARKET     market to scan for new ideas (default: MARKET)
    IDEAS_CATEGORIES focus categories, e.g. "Technology,Agriculture" (default: any)
    IDEAS_COUNT      how many new ideas (default 3)
    + LLM_* and every notification channel field (TELEGRAM_BOT_TOKEN, ...),
      read by Config.apply_env().

Exit codes: 0 = report produced (and delivered, if any channel is set),
1 = nothing to analyze or every symbol failed outright,
2 = channels are configured but none accepted the message.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ..core.config import Config
from ..notifiers.dispatcher import NotificationDispatcher
from ..services.analysis_run import (
    MARKET_LABELS,
    analyze_symbol,
    deliver_report,
    is_trading_day,
    notify_failure,
    parse_targets,
)
from ..services.report import ReportPrefs, clean_sections
from ..services.report_i18n import normalize_language

logger = logging.getLogger("marketmyna.scheduled_run")

MODES = ("quick", "standard", "full", "specialist")


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")


def _watchlist_symbols(config: Config, name: str) -> str:
    """Symbols from a saved in-app watchlist, as a STOCK_LIST-style spec."""
    from ..storage import DatabaseManager, WatchlistRecord, get_db_url

    db = DatabaseManager.instance(get_db_url(config=config))
    with db.get_session() as session:
        record = session.query(WatchlistRecord).filter(WatchlistRecord.name == name).first()
        if record is None:
            raise SystemExit(f"No watchlist named {name!r}")
        # Funds have no price-chart analysis; skip them.
        return ",".join(f"{i.market}:{i.symbol}" for i in record.items if i.type != "mf")


def _saved_prefs(config: Config) -> ReportPrefs | None:
    """Report preferences saved on the Scheduler page, if this machine has
    the app database (a server run); a fresh GitHub runner has none."""
    try:
        from ..services.schedule_config import ScheduleConfigStore
        from ..storage import has_app_db

        if not has_app_db(config):
            return None
        return ScheduleConfigStore(config=config).load().report_prefs()
    except Exception as exc:
        logger.warning("Saved report preferences unreadable: %s", exc)
        return None


def parse_pairs(raw: str, sep: str) -> dict[str, str]:
    """"telegram:ta,email:en" -> {"telegram": "ta", "email": "en"}."""
    out = {}
    for part in raw.split(","):
        if sep in part:
            key, value = part.split(sep, 1)
            if key.strip() and value.strip():
                out[key.strip()] = value.strip()
    return out


def parse_list(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def build_prefs(
    config: Config, mode: str, timezone: str, language: str | None = None, market: str = "india"
) -> ReportPrefs:
    """Saved Scheduler preferences, overridden by env vars / flags."""
    prefs = _saved_prefs(config)
    if prefs is None:
        prefs = ReportPrefs(ideas_market=market)
    prefs.mode, prefs.timezone = mode, timezone
    if language or os.environ.get("REPORT_LANGUAGE", "").strip():
        prefs.language = normalize_language(language or os.environ["REPORT_LANGUAGE"])
    if os.environ.get("REPORT_SECTIONS", "").strip():
        prefs.sections = clean_sections(os.environ["REPORT_SECTIONS"].split(","))
    if os.environ.get("STOCK_SECTIONS", "").strip():
        prefs.stock_sections = {
            sym.upper(): clean_sections(secs.replace("|", "+").split("+"))
            for sym, secs in parse_pairs(os.environ["STOCK_SECTIONS"], "=").items()
        }
    if os.environ.get("MF_LIST", "").strip():
        prefs.funds = [c for c in parse_list(os.environ["MF_LIST"]) if c.isdigit()]
    if os.environ.get("IDEAS_MARKET", "").strip():
        prefs.ideas_market = os.environ["IDEAS_MARKET"].strip().lower()
    if os.environ.get("IDEAS_CATEGORIES", "").strip():
        prefs.ideas_categories = parse_list(os.environ["IDEAS_CATEGORIES"])
    if os.environ.get("IDEAS_COUNT", "").strip():
        prefs.ideas_count = max(1, min(10, int(os.environ["IDEAS_COUNT"])))
    if os.environ.get("SMART_MESSAGING", "").strip():
        prefs.smart = os.environ["SMART_MESSAGING"].strip().lower() in ("1", "true", "yes", "on")
    if os.environ.get("SMART_TOP_N", "").strip():
        prefs.smart_top_n = max(1, min(20, int(os.environ["SMART_TOP_N"])))
    if os.environ.get("SMART_AI_TOP", "").strip():
        prefs.smart_ai_top = max(0, int(os.environ["SMART_AI_TOP"]))
    if os.environ.get("SMART_EMAIL_FULL", "").strip():
        prefs.smart_email_full = os.environ["SMART_EMAIL_FULL"].strip().lower() not in ("0", "false", "no", "off")
    if os.environ.get("REPORT_BASE_URL", "").strip():
        prefs.report_base_url = os.environ["REPORT_BASE_URL"].strip()
    if os.environ.get("CHANNEL_LANGUAGES", "").strip():
        prefs.channel_languages = {
            ch.lower(): normalize_language(lang) for ch, lang in parse_pairs(os.environ["CHANNEL_LANGUAGES"], ":").items()
        }
    return prefs


def _run_smart(targets, prefs, config, args) -> int:
    """Smart messaging: top-N message + full report (HTML file here, since
    a GitHub runner has no server to host the link)."""
    from ..services.smart_report import run_smart

    logger.info("Smart messaging: %d stocks, AI for the top %d, message shows top %d",
                len(targets), prefs.smart_ai_top, prefs.smart_top_n)
    dispatcher = NotificationDispatcher(config)
    reports, delivery, rows, token, full_html = run_smart(targets, prefs, config, dispatcher=dispatcher,
                                                          dry_run=args.dry_run)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo(args.timezone)).strftime("%Y%m%d-%H%M")
    from ..services.smart_report import html_report

    (out_dir / f"marketmyna-{stamp}-full.html").write_text(
        full_html or html_report(rows, f"MarketMyna · {len(rows)} stocks", datetime.now(ZoneInfo(args.timezone)), None),
        encoding="utf-8")
    for lang, (title, body) in reports.items():
        print(f"===== {title} [{lang}] =====\n{body}\n")
        (out_dir / f"marketmyna-{stamp}-{lang}.txt").write_text(f"{title}\n\n{body}\n", encoding="utf-8")
    good = [r for r in rows if "error" not in r]
    if not good:
        logger.error("Every symbol failed - check the symbols, market and data sources above.")
        if not args.dry_run:
            notify_failure(config, "No stock could be analyzed.", dispatcher=dispatcher)
        return 1
    for name, ok in delivery.items():
        logger.info("Notification %-12s %s", name, "sent" if ok else "FAILED")
    if delivery and not any(delivery.values()):
        return 2
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli.scheduled_run", description=__doc__.split("\n\n")[0])
    parser.add_argument("--symbols", default=os.environ.get("STOCK_LIST", ""), help="comma-separated; env STOCK_LIST")
    parser.add_argument("--watchlist", help="use a saved in-app watchlist instead of --symbols")
    parser.add_argument(
        "--market", default=os.environ.get("MARKET", "india").strip().lower() or "india", choices=sorted(MARKET_LABELS)
    )
    parser.add_argument(
        "--mode", default=os.environ.get("ANALYSIS_MODE", "standard").strip().lower() or "standard", choices=MODES
    )
    parser.add_argument("--timezone", default=os.environ.get("REPORT_TIMEZONE", "Asia/Kolkata") or "Asia/Kolkata")
    parser.add_argument("--language", help="report language code (env REPORT_LANGUAGE)")
    parser.add_argument("--force-run", action="store_true", help="run even on weekends")
    parser.add_argument("--dry-run", action="store_true", help="print the report, don't send it")
    parser.add_argument("--output-dir", default="reports", help="where to save the report file")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    config = Config.load()
    if config.accounts_enabled:
        # Accounts mode: report on the platform owner's lists, like the in-app scheduler.
        from ..core import tenant
        from ..services.accounts import owner_scope

        tenant.enable()
        with owner_scope(config):
            return _main(args, config)
    return _main(args, config)


def _main(args, config) -> int:

    spec = _watchlist_symbols(config, args.watchlist) if args.watchlist else args.symbols
    targets = parse_targets(spec, args.market)
    if not targets:
        logger.error("No symbols to analyze. Set STOCK_LIST (e.g. RELIANCE,TCS,INFY) or pass --symbols.")
        return 1

    check_days = _env_flag("TRADING_DAY_CHECK_ENABLED", True) and not args.force_run
    if check_days:
        open_targets = [t for t in targets if is_trading_day(t.market)]
        skipped = len(targets) - len(open_targets)
        if skipped:
            logger.info("Skipping %d symbol(s): market closed today (use --force-run to override)", skipped)
        targets = open_targets
        if not targets:
            logger.info("All markets closed today - nothing to do.")
            return 0

    from ..llm.channels import build_routes

    routes = build_routes(config)
    if routes:
        logger.info("AI routes (in order): %s", ", ".join(r.label() for r in routes))
    else:
        logger.warning("No AI model configured (LLM_MODEL / LLM_CHANNELS): reports carry technical/risk signals but no AI decision.")

    prefs = build_prefs(config, args.mode, args.timezone, args.language, market=args.market)
    logger.info("Report: language=%s sections=%s", prefs.language, ",".join(prefs.sections))
    if prefs.smart:
        return _run_smart(targets, prefs, config, args)

    results = []
    for i, target in enumerate(targets, 1):
        logger.info("[%d/%d] Analyzing %s (%s, %s)", i, len(targets), target.symbol, target.market, args.mode)
        result = analyze_symbol(
            target.symbol, target.market, args.mode, config, sections=prefs.sections_for(target.symbol)
        )
        if not result["ok"]:
            logger.warning("%s: %s", target.symbol, result.get("error"))
        results.append(result)

    produced_anything = any(r.get("dashboard") for r in results)
    if not produced_anything:
        logger.error("Every symbol failed - check the symbols, market and data sources above.")

    dispatcher = NotificationDispatcher(config)
    reports, delivery = deliver_report(results, prefs, config, dispatcher=dispatcher, dry_run=args.dry_run)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo(args.timezone)).strftime("%Y%m%d-%H%M")
    for lang, (title, body) in reports.items():
        print(f"===== {title} [{lang}] =====\n{body}\n")
        (out_dir / f"marketmyna-{stamp}-{lang}.txt").write_text(f"{title}\n\n{body}\n", encoding="utf-8")

    if args.dry_run:
        logger.info("Dry run: not sending.")
        return 0 if produced_anything else 1
    if not produced_anything and not args.dry_run:
        errors = "\n".join(f"{r['symbol']}: {r.get('error', 'no data')}" for r in results)
        notify_failure(config, f"No stock could be analyzed.\n{errors}", dispatcher=dispatcher)

    if not dispatcher.configured_channels("report"):
        logger.warning("No notification channel configured (e.g. TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID); report only printed.")
        return 0 if produced_anything else 1

    for name, ok in delivery.items():
        lang = normalize_language(prefs.channel_languages.get(name) or prefs.language)
        logger.info("Notification %-12s [%s] %s", name, lang, "sent" if ok else "FAILED")
    if not any(delivery.values()):
        return 2
    return 0 if produced_anything else 1


if __name__ == "__main__":
    sys.exit(main())
