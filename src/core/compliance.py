"""What the app may say about a single stock: facts, explanations and
comparisons, never a call.

MarketMyna never gives a buy / hold / sell call, price target, entry, exit
or stop loss. Where a direction helps, it is shown as an outlook: bullish,
neutral or bearish (outlook() below). The frontend reads mode() ("analytics")
to pick its wording.
"""

from __future__ import annotations

MODE = "analytics"


def mode() -> str:
    return MODE


def mode_for(user_id) -> str:
    """mode() for the /me endpoint (the frontend reads it to pick the wording)."""
    return MODE


# A buy / hold / sell style rating (an analyst consensus, an AI reply) as a direction.
OUTLOOKS = {"strong_buy": "bullish", "buy": "bullish", "hold": "neutral", "sell": "bearish", "strong_sell": "bearish"}


def outlook(rating) -> "str | None":
    """bullish / neutral / bearish for a rating (or an outlook already),
    None when there is none."""
    value = str(rating or "").lower()
    return value if value in ("bullish", "neutral", "bearish") else OUTLOOKS.get(value)


# Appended to every AI prompt that writes about a single security, so no
# agent slips a call into its prose.
NO_CALLS_RULE = (
    "This is an analytics tool that is not registered with SEBI as an investment adviser or research "
    "analyst. Describe what the data shows as observations. Never recommend buying, holding, selling, "
    "accumulating, booking profit or exiting, and never give a price target, entry, exit or stop loss. A "
    "direction may be described only as a bullish, neutral or bearish outlook, never as an instruction. Do "
    "not use words like attractive, cheap, expensive, undervalued or overvalued as a verdict."
)


def guard_prompt(system_prompt: str) -> str:
    """The system prompt, plus NO_CALLS_RULE."""
    return f"{system_prompt}\n\n{NO_CALLS_RULE}"


# Response fields that carry a call, target or stop; always stripped.
CALL_FIELDS = ("decision_type", "target_price", "stop_loss", "buy_point", "sell_point", "action",
               "ai_target", "ai_stop", "technical_signal")
