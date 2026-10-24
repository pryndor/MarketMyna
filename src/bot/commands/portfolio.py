"""Your own data from chat: portfolio value and holdings, the portfolio
review (src/portfolio/review.py) and watchlists. In accounts mode the
caller's tenant scope (web request or the linked Telegram chat) limits
every query to that user's rows."""

from __future__ import annotations

from ..models import CommandResult, IncomingMessage
from .base import Command
from .common import big, num, pct

GROUP = "Portfolio"


def _manager(config):
    from ...portfolio.manager import PortfolioManager

    return PortfolioManager(config.data_dir, config=config)


def _pick(manager, args: str) -> tuple[str | None, str]:
    """Portfolio by (case-insensitive, prefix) name; the first one when no name is given."""
    names = manager.get_all_portfolios()
    if not names:
        return None, "No portfolios yet. Create one on the Portfolio page."
    want = args.strip().lower()
    if not want:
        return names[0], ""
    match = next((n for n in names if n.lower() == want), None) or next((n for n in names if n.lower().startswith(want)), None)
    if match is None:
        return None, f"No portfolio '{args.strip()}'. You have: {', '.join(names)}"
    return match, ""


class PortfolioCommand(Command):
    name = "portfolio"
    aliases = ["pf", "holdings"]
    usage = "/portfolio [NAME]"
    description = "Portfolio value, profit / loss and every holding with its weight and return."
    example = "/portfolio"
    group = GROUP

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        manager = _manager(self._config)
        name, error = _pick(manager, args)
        if not name:
            return CommandResult(text=error, success=not args.strip())
        s = manager.get_portfolio_summary(name)
        cur = s.get("currency") or ""
        holdings = sorted(s["holdings"].values(), key=lambda h: -(h.get("market_value") or 0))
        total = s.get("total_market_value") or 0
        lines = [f"{name} · {cur} {num(s.get('total_value'))} "
                 f"(invested {num(s.get('total_cost_basis'))}, P/L {num(s.get('total_unrealized_gain'))} "
                 f"{pct(s.get('total_unrealized_gain_percent'))})"]
        if s.get("cash_balance"):
            lines.append(f"Cash {num(s['cash_balance'])}")
        if not holdings:
            lines.append("No holdings yet.")
        for h in holdings[:25]:
            w = (h.get("market_value") or 0) / total * 100 if total else 0
            lines.append(f"• {h['symbol']} ({h.get('market')}) {num(h.get('quantity'), 4).rstrip('0').rstrip('.')} × "
                         f"{num(h.get('current_price'))} = {big(h.get('market_value'))} · {w:.1f}% · "
                         f"{pct(h.get('unrealized_gain_percent'))}")
        if len(holdings) > 25:
            lines.append(f"… and {len(holdings) - 25} more")
        others = [n for n in manager.get_all_portfolios() if n != name]
        if others:
            lines.append(f"Other portfolios: {', '.join(others)}")
        return CommandResult(text="\n".join(lines))


class ReviewCommand(Command):
    name = "review"
    aliases = ["checkup"]
    usage = "/review [NAME]"
    description = "Portfolio review: what could be changed, why it matters and how, checked against your limits."
    example = "/review"
    group = GROUP

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        from ...portfolio.review import for_portfolio

        manager = _manager(self._config)
        name, error = _pick(manager, args)
        if not name:
            return CommandResult(text=error, success=not args.strip())
        r = for_portfolio(manager, name, self._config)
        if r.get("score") is None:
            return CommandResult(text=f"{name}: {r.get('summary')}")
        lines = [f"{name} review: {r['score']}/100 ({r['grade']}) · {r['summary']}"]
        marks = {"high": "🔴", "medium": "🟠", "low": "⚪"}
        for i, f in enumerate(r["findings"], 1):
            lines.append(f"\n{marks[f['severity']]} {i}. {f['title']}" + (f" ({f['rule']})" if f.get("rule") else ""))
            lines.append(f"   {f['fact']}")
            lines.append(f"   Why: {f['why']}")
            for lever in f["levers"]:
                lines.append(f"   → {lever}")
        if r.get("good"):
            lines.append("\nWorking well:")
            lines += [f"✓ {g}" for g in r["good"]]
        return CommandResult(text="\n".join(lines))


class WatchlistCommand(Command):
    name = "watchlist"
    aliases = ["wl", "watch"]
    usage = "/watchlist [NAME]"
    description = "Your watchlists, or one list's stocks with price and day change."
    example = "/watchlist"
    group = GROUP

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        from ...data.listings import get_store
        from ...storage import DatabaseManager, WatchlistRecord, get_db_url

        with DatabaseManager.instance(get_db_url(config=self._config)).get_session() as session:
            lists = session.query(WatchlistRecord).order_by(WatchlistRecord.id).all()
            if not lists:
                return CommandResult(text="No watchlists yet. Star a stock on Markets or Analyze to start one.")
            want = args.strip().lower()
            record = (next((w for w in lists if w.name.lower() == want), None)
                      or next((w for w in lists if w.name.lower().startswith(want)), None)) if want else (
                lists[0] if len(lists) == 1 else None)
            if record is None:
                if want:
                    return CommandResult(text=f"No watchlist '{args.strip()}'.", success=False)
                return CommandResult(text="Your watchlists:\n" + "\n".join(
                    f"• {w.name} ({len(w.items)} stocks)" for w in lists) + "\nShow one with /watchlist NAME")
            items = [(i.symbol, i.market, i.type) for i in record.items]
            title = record.name
        live = get_store().lookup([(m, t, s) for s, m, t in items]) if items else {}
        lines = [f"{title} ({len(items)})"]
        for s, m, t in items[:40]:
            row = live.get((m, t, s)) or {}
            lines.append(f"• {s} ({m}) {num(row.get('price'))} {pct(row.get('change_percent'))}" if row else f"• {s} ({m})")
        return CommandResult(text="\n".join(lines))
