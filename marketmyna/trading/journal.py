"""Trade journal statistics (pure; computed from TradeRecord dicts)."""

from __future__ import annotations

from collections import defaultdict
from typing import Optional


def trade_pnl(t: dict) -> Optional[float]:
    if t.get("exit_price") is None:
        return None
    sign = -1 if t.get("side") == "short" else 1
    return (t["exit_price"] - t["entry_price"]) * t["quantity"] * sign - (t.get("fees") or 0)


def r_multiple(t: dict) -> Optional[float]:
    """Profit in units of the risk taken (entry-to-stop distance)."""
    pnl = trade_pnl(t)
    stop = t.get("stop")
    if pnl is None or stop is None or stop == t["entry_price"]:
        return None
    risk = abs(t["entry_price"] - stop) * t["quantity"]
    return pnl / risk if risk else None


def stats(trades: list[dict]) -> dict:
    closed = sorted((t for t in trades if t.get("exit_price") is not None),
                    key=lambda t: t.get("exit_at") or t.get("entry_at"))
    pnls = [trade_pnl(t) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    rs = [r for r in (r_multiple(t) for t in closed) if r is not None]

    streak = worst_streak = 0
    for p in pnls:
        streak = streak + 1 if p <= 0 else 0
        worst_streak = max(worst_streak, streak)

    equity, running = [], 0.0
    for t, p in zip(closed, pnls):
        running += p
        when = t.get("exit_at") or t.get("entry_at")
        equity.append({"date": when.isoformat() if hasattr(when, "isoformat") else when, "pnl": round(running, 2)})

    by_setup: dict[str, list[float]] = defaultdict(list)
    for t, p in zip(closed, pnls):
        by_setup[(t.get("setup") or "").strip() or "(none)"].append(p)

    gross_loss = -sum(losses)
    return {
        "closed": len(closed),
        "open": sum(1 for t in trades if t.get("exit_price") is None),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else None,
        "total_pnl": round(sum(pnls), 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else None,
        "profit_factor": round(sum(wins) / gross_loss, 2) if gross_loss > 0 else None,
        "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "avg_r": round(sum(rs) / len(rs), 2) if rs else None,
        "best": round(max(pnls), 2) if pnls else None,
        "worst": round(min(pnls), 2) if pnls else None,
        "max_losing_streak": worst_streak,
        "by_setup": sorted(
            (
                {"setup": s, "trades": len(v), "win_rate": round(sum(1 for p in v if p > 0) / len(v) * 100, 1),
                 "pnl": round(sum(v), 2)}
                for s, v in by_setup.items()
            ),
            key=lambda r: -r["pnl"],
        ),
        "equity": equity,
    }
