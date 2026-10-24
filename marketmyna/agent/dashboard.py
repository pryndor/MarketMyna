"""Turns a finished AgentContext into the report shape a frontend renders.

Deliberately smaller than daily_stock_analysis's dashboard payload (no
sentiment_score, no intelligence section, no battle_plan) - this only
includes fields the current agent set can actually populate; adding a
field here that always reads as null/fake would be worse than not
having it.
"""

from __future__ import annotations

from .context import AgentContext


def build_dashboard(ctx: AgentContext) -> dict:
    """No buy / sell call, target, stop or technical verdict (marketmyna/core/compliance.py):
    the decision is shown as an outlook, the opinions as readings."""
    from ..core.compliance import outlook

    decision = ctx.get_opinion("decision")
    risk = ctx.get_opinion("risk")

    return {
        "symbol": ctx.symbol,
        "market": ctx.market,
        "mode": ctx.mode,
        "area": getattr(ctx, "area", None),
        "compliance": "analytics",
        # The decision as a direction (bullish / neutral / bearish), never a call.
        "outlook": outlook(decision.signal) if decision else None,
        "analysis_summary": decision.summary if decision else None,
        "risk_level": (risk.details or {}).get("risk_level") if risk else None,
        "opinions": [_public_opinion(op.to_dict()) for op in ctx.opinions],
        "generated_at": ctx.generated_at.isoformat(),
    }


def _public_opinion(op: dict) -> dict:
    """An agent's opinion without a buy / sell call or confidence: the
    technical agent keeps what its indicators read (bullish / bearish /
    neutral), a news or sentiment opinion keeps its tone as positive /
    negative (about the news or the chatter), the decision agent keeps
    nothing (its outlook is the dashboard's "outlook")."""
    from ..services.overview import reading

    tone = {"bullish": "positive", "bearish": "negative", "neutral": "neutral"}
    name = op.get("agent_name")
    keep = (tone.get(op.get("signal")) if name in ("news", "sentiment")
            else reading(op.get("signal")) if name == "technical" else None)
    details = {k: v for k, v in (op.get("details") or {}).items()
               if k not in ("overall_signal", "buy_signals", "sell_signals", "neutral_signals", "target_price", "stop_loss", "entry", "timeframe")}
    if isinstance(details.get("indicators"), dict):
        details["indicators"] = {key: {"value": info.get("value"), "signal": reading(info.get("signal"))}
                                 for key, info in details["indicators"].items()}
    return {**op, "signal": keep, "confidence": None, "details": details}
