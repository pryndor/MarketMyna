"""Turns a dashboard dict (src/agent/dashboard.py's build_dashboard output)
into a short human-readable chat message - not a raw JSON dump."""

from __future__ import annotations


def format_dashboard(dashboard: dict) -> str:
    outlook = dashboard.get("outlook")
    lines = [f"{dashboard['symbol']} ({dashboard['market']}) - {f'{outlook} outlook' if outlook else 'AI analysis'}"]

    summary = dashboard.get("analysis_summary")
    if summary:
        lines.append(summary)

    target = dashboard.get("target_price")
    stop = dashboard.get("stop_loss")
    if target is not None or stop is not None:
        lines.append(f"Target: {target if target is not None else 'n/a'}  Stop: {stop if stop is not None else 'n/a'}")

    if dashboard.get("technical_signal"):
        lines.append(f"Technical: {dashboard['technical_signal']}")
    if dashboard.get("risk_level"):
        lines.append(f"Risk: {dashboard['risk_level']}")

    return "\n".join(lines)
