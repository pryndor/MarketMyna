"""Trade section from chat: /alert, /alerts, /risk, /scan.

Symbols take an optional market prefix like the scheduler's STOCK_LIST
(us:AAPL, crypto:BTC-USD); without one, the Risk tab's market is used."""

from __future__ import annotations

from ...storage import DatabaseManager, PriceAlertRecord, SavedScanRecord, get_db_url
from ..models import CommandResult, IncomingMessage
from .base import Command

MARKETS = {"us", "india", "china_a", "hong_kong", "crypto", "global"}
KIND_WORDS = {
    "above": "price_above", ">": "price_above", ">=": "price_above",
    "below": "price_below", "<": "price_below", "<=": "price_below",
    "up": "pct_up", "down": "pct_down",
    "rsi>": "rsi_above", "rsi<": "rsi_below",
    "volume": "volume_spike", "vol": "volume_spike",
    "breakout": "high_breakout", "breakdown": "low_breakdown",
}


def _db(config):
    return DatabaseManager.instance(get_db_url(config=config))


def _default_market(config) -> str:
    from ...trading.risk import load_settings

    return load_settings(config).get("market") or "india"


def _symbol(token: str, config) -> tuple[str, str]:
    if ":" in token:
        market, sym = token.split(":", 1)
        if market.lower() in MARKETS:
            return sym.upper(), market.lower()
    return token.upper(), _default_market(config)


class AlertCommand(Command):
    name = "alert"
    aliases = ["al"]
    usage = "/alert SYMBOL above|below PRICE [note]"
    description = "Create a price alert (also up|down %, rsi>|rsi< N, volume X, breakout|breakdown DAYS)."
    group = "Trading"
    example = "/alert india:RELIANCE below 1210"
    help_text = (
        "/alert SYMBOL above|below PRICE [note] - price alert; also up|down PCT, rsi>|rsi< N, "
        "volume X, breakout|breakdown DAYS. Prefix the market: us:AAPL, crypto:BTC-USD"
    )

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        from ...trading.alerts import describe

        parts = args.split()
        if len(parts) < 3:
            return CommandResult(text=f"Usage: {self.help_text}", success=False)
        symbol, market = _symbol(parts[0], self._config)
        kind = KIND_WORDS.get(parts[1].lower())
        if kind is None:
            return CommandResult(text=f"Unknown condition '{parts[1]}'. Use one of: {', '.join(sorted(KIND_WORDS))}", success=False)
        try:
            value = float(parts[2].rstrip("%x"))
        except ValueError:
            return CommandResult(text=f"'{parts[2]}' is not a number", success=False)
        note = " ".join(parts[3:])
        with _db(self._config).get_session() as s:
            rec = PriceAlertRecord(symbol=symbol, market=market, kind=kind, value=value, note=note, status="active", armed=True)
            s.add(rec)
            s.flush()
            alert_id = rec.id
        return CommandResult(text=f"🔔 Alert #{alert_id} set: {symbol} ({market}) {describe(kind, value)}")


class AlertsCommand(Command):
    name = "alerts"
    aliases = []
    usage = "/alerts [delete|pause|resume ID]"
    description = "List your active alerts, or delete / pause / resume one."
    group = "Trading"
    example = "/alerts"
    help_text = "/alerts - list active alerts · /alerts delete ID · /alerts pause ID · /alerts resume ID"

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        from ...trading.alerts import describe

        parts = args.split()
        if len(parts) == 2 and parts[0] in ("delete", "pause", "resume") and parts[1].lstrip("#").isdigit():
            alert_id = int(parts[1].lstrip("#"))
            with _db(self._config).get_session() as s:
                rec = s.get(PriceAlertRecord, alert_id)
                if rec is None:
                    return CommandResult(text=f"No alert #{alert_id}", success=False)
                if parts[0] == "delete":
                    s.delete(rec)
                else:
                    rec.status = "paused" if parts[0] == "pause" else "active"
                    rec.armed = True
            return CommandResult(text=f"Alert #{alert_id} {parts[0]}d")
        with _db(self._config).get_session() as s:
            recs = s.query(PriceAlertRecord).filter(PriceAlertRecord.status.in_(["active", "paused"])).order_by(PriceAlertRecord.id).all()
            if not recs:
                return CommandResult(text="No active alerts. Create one with /alert RELIANCE below 1210")
            lines = [f"#{r.id} {r.symbol} ({r.market}): {describe(r.kind, r.value)}"
                     + (" [paused]" if r.status == "paused" else "") + (f" · {r.note}" if r.note else "") for r in recs]
        return CommandResult(text="\n".join(lines))


class RiskCommand(Command):
    name = "risk"
    aliases = []
    usage = "/risk"
    description = "Today's P&L against your daily loss limit, open risk and trade count."
    group = "Trading"
    example = "/risk"
    help_text = "/risk - today's P&L against your daily loss limit, open risk and trade count"

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        from ...trading.risk import status

        r = status(self._config)
        icon = {"ok": "✅", "warn": "⚠️", "stop": "🛑"}[r["status"]]
        lines = [
            f"{icon} Risk: {r['status'].upper()} ({r['settings']['market']})",
            f"Net P&L today: {r['day_pnl']:,.2f} (realised {r['realized']:,.2f}, open {r['unrealized']:,.2f})",
            f"Loss limit: {r['loss_limit']:,.2f}" + (f" · {r['limit_used_pct']}% used" if r["limit_used_pct"] else ""),
            f"Open risk to stops: {r['open_risk']:,.2f} ({r['open_risk_pct']}% of capital)",
            f"Trades today: {r['trades_today']} / {r['settings']['max_trades_per_day']}",
        ]
        lines += [f"• {x}" for x in r["reasons"]]
        return CommandResult(text="\n".join(lines))


class ScanCommand(Command):
    name = "scan"
    aliases = []
    usage = "/scan [NAME|ID]"
    description = "List saved scans, or run one now."
    group = "Trading"
    example = "/scan"
    help_text = "/scan - list saved scans · /scan NAME or ID - run one now"

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        from ...trading.scanner import run_saved_scans

        with _db(self._config).get_session() as s:
            saved = [(r.id, r.name) for r in s.query(SavedScanRecord).order_by(SavedScanRecord.id)]
        if not saved:
            return CommandResult(text="No saved scans. Save one in Trade → Scanner.")
        key = args.strip().lstrip("#").lower()
        if not key:
            return CommandResult(text="\n".join(f"#{i} {n}" for i, n in saved) + "\nRun one with /scan NAME")
        match = next((i for i, n in saved if str(i) == key or n.lower() == key), None) or next(
            (i for i, n in saved if key in n.lower()), None)
        if match is None:
            return CommandResult(text=f"No saved scan matches '{args.strip()}'", success=False)
        out = run_saved_scans(self._config, force_id=match)[0]
        if not out["rows"]:
            return CommandResult(text=f"🔎 {out['name']}: no matches in {out['scanned']} stocks")
        lines = [f"🔎 {out['name']}: {len(out['rows'])} matches in {out['scanned']} stocks"]
        for r in out["rows"][:20]:
            lines.append(f"• {r['symbol']} {r['price']:,.2f} ({r['change_percent']:+.1f}%): {', '.join(r['reasons'][:2])}")
        return CommandResult(text="\n".join(lines))
