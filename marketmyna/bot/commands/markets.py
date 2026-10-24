"""Market-wide views from chat: the Markets page's pulse and sector
rotation, the ready-made screens and the events calendar."""

from __future__ import annotations

from ...utils.deadline import call_with_deadline
from ..models import CommandResult, IncomingMessage
from .base import Command
from .common import default_market, market_word, num, pct

GROUP = "Markets"


class _MarketCommand(Command):
    group = GROUP

    def __init__(self, config):
        self._config = config

    def _market(self, parts: list[str]) -> str:
        return next((market_word(p) for p in parts if market_word(p)), None) or default_market(self._config)

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        try:
            return CommandResult(text=self.run(args.split()))
        except (ValueError, TimeoutError) as exc:
            return CommandResult(text=str(exc), success=False)

    def run(self, parts: list[str]) -> str:
        raise NotImplementedError


class MarketCommand(_MarketCommand):
    name = "market"
    aliases = ["pulse", "m"]
    usage = "/market [market]"
    description = "Market pulse: index levels, breadth, top gainers and losers, sector moves today."
    example = "/market india"

    def run(self, parts):
        from ...services.discovery import DISCOVERY_MARKETS, build

        market = self._market(parts)
        if market not in DISCOVERY_MARKETS:
            raise ValueError(f"Market pulse covers: {', '.join(DISCOVERY_MARKETS)}")
        d = build(market, 500)
        lines = [f"Market pulse · {market} (largest {d['universe']})"]
        for i in d.get("indices") or []:
            lines.append(f"{i['name']} {num(i.get('price'))} ({pct(i.get('change_percent'), 2)})")
        b = d.get("breadth") or {}
        if b.get("total"):
            lines.append(f"Breadth: {b['advancers']} up / {b['decliners']} down of {b['total']}")
        for key, title in (("gainers", "Top gainers"), ("losers", "Top losers")):
            rows = (d.get(key) or [])[:5]
            if rows:
                lines.append(f"{title}: " + ", ".join(f"{r['symbol']} {pct(r.get('change_percent'))}" for r in rows))
        secs = d.get("sectors") or []
        if secs:
            lines.append("Sectors: " + ", ".join(f"{s['sector']} {pct(s.get('change_percent'), 2)}" for s in secs[:4])
                         + " … " + ", ".join(f"{s['sector']} {pct(s.get('change_percent'), 2)}" for s in secs[-3:]))
        return "\n".join(lines)


class SectorsCommand(_MarketCommand):
    name = "sectors"
    aliases = ["rotation", "rrg"]
    usage = "/sectors [market]"
    description = "Sector rotation: which sectors are leading, weakening, lagging or improving vs the index."
    example = "/sectors india"

    def run(self, parts):
        from ...services.rotation import ROTATION_MARKETS, build

        market = self._market(parts)
        if market not in ROTATION_MARKETS:
            raise ValueError(f"Sector rotation covers: {', '.join(ROTATION_MARKETS)}")
        d = call_with_deadline(build, 90, market)
        lines = [f"Sector rotation vs {d['benchmark']['name']}, weekly to {d.get('as_of')}"]
        for q, title in (("leading", "Leading"), ("improving", "Improving"), ("weakening", "Weakening"), ("lagging", "Lagging")):
            rows = [s for s in d.get("sectors") or [] if s.get("quadrant") == q]
            if rows:
                lines.append(f"{title}: " + ", ".join(f"{s['sector']} ({pct(s.get('return_4w'))} 4w)" for s in rows))
        lines.append("Cycle: improving → leading → weakening → lagging.")
        return "\n".join(lines)


class ScreenCommand(_MarketCommand):
    name = "screen"
    aliases = ["screens"]
    usage = "/screen [KEY] [india|us]"
    description = "List the ready-made fundamental screens, or run one over the largest stocks."
    example = "/screen undervalued_large india"

    def run(self, parts):
        from ...services.screens import PRESETS, list_presets, run

        keys = [p for p in parts if not market_word(p)]
        if not keys:
            lines = ["Screens (run one with /screen KEY [india|us]):"]
            lines += [f"• {p['key']}: {p['title']} - {p['description']}" for p in list_presets()]
            return "\n".join(lines)
        key = keys[0].lower()
        if key not in PRESETS:
            match = [k for k in PRESETS if key in k]
            if len(match) != 1:
                raise ValueError(f"Unknown screen '{key}'. /screen lists them.")
            key = match[0]
        market = self._market(parts)
        if market not in ("india", "us"):
            raise ValueError("Screens cover the India and US markets.")
        d = call_with_deadline(run, 90, key, market)
        rows = d.get("results") or []
        lines = [f"{d['title']} ({market}): {len(rows)} of {d.get('scanned')} stocks pass",
                 "Rules: " + "; ".join(d.get("rules") or [])]
        for r in rows[:15]:
            lines.append(f"• {r['symbol']} {num(r.get('price'))} · P/E {num(r.get('pe'), 1)} · "
                         f"ROE {pct(r.get('roe'), 1, False)}")
        return "\n".join(lines)


class CalendarCommand(_MarketCommand):
    name = "calendar"
    aliases = ["events", "cal"]
    usage = "/calendar [DAYS]"
    description = "Upcoming results and dividends for stocks you follow, plus central bank and economic events and market holidays."
    example = "/calendar 14"

    def run(self, parts):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from ...services import econ_calendar, market_calendar
        from ...services.calendar import collect, followed_symbols, load_settings

        days = next((int(p) for p in parts if p.isdigit()), 14)
        days = max(1, min(days, 120))
        settings = load_settings(self._config)
        tz = settings.get("timezone") or "Asia/Kolkata"
        today = datetime.now(ZoneInfo(tz)).date()
        events = collect(followed_symbols(self._config), today, days)
        econ = econ_calendar.collect(today, days)["events"]
        markets = [e for e in market_calendar.collect(today, days)["events"]
                   if e["key"] in ("market_holiday", "short_day", "special_session")]
        lines = [f"Next {days} days"]
        for e in econ[:10]:
            lines.append(f"• {e['date']} {econ_calendar.local_time(e, tz) or ''} {e['title']} ({e.get('region')})".replace("  ", " "))
        for e in markets[:10]:
            lines.append(f"• {e['date']} {e['title']}")
        for e in events[:15]:
            lines.append(f"• {e['date']} {e['symbol']} ({e['market']}): {e['label']}")
        if len(lines) == 1:
            lines.append("Nothing scheduled. Add stocks to a watchlist or portfolio to track their results.")
        return "\n".join(lines)
