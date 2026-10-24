"""New stock ideas for the scheduled report: candidates outside the
watchlist, in the user's focus market and categories, that look
constructive under current conditions.

Pipeline (cheap to expensive):
1. Screen the full market listing (src/data/listings.py): stocks with an
   official industry, in the focus categories, at least small-cap (no illiquid micro caps),
   traded today, trending up but not pinned at the 52-week high.
2. Trend check on the best ~25: one year of daily closes - keep stocks
   in an established uptrend that isn't overheated (see technical_check).
3. Final pick: the LLM chooses and explains `count` of them when one is
   configured; otherwise the rule-based ranking and a plain reason.

These are ideas to research, not advice - the report says so.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Iterable, Optional

from ..core.numbers import finite as _num

logger = logging.getLogger(__name__)

SCREEN_SIZE = 25


def screen(rows: Iterable[dict], categories: list[str], exclude: set[str], limit: int = SCREEN_SIZE) -> list[dict]:
    """Rank listing rows by a quick trend/size score; no network."""
    from ..data.listings import cap_band

    wanted = set(categories or [])
    scored = []
    for row in rows:
        if row.get("type") not in ("stock", "crypto") or row["symbol"].upper() in exclude:
            continue
        if wanted and row.get("category") not in wanted:
            continue
        # Recommend only stocks with an official industry: a category guessed
        # from a company name ("Technocraft" -> Technology) is fine for
        # browsing, not for a buy idea.
        if row.get("type") == "stock" and row.get("category_inferred"):
            continue
        price = _num(row.get("price"))
        if not price or price <= 0:
            continue
        if row.get("type") == "stock" and cap_band(row) not in ("mega", "large", "mid", "small"):
            continue
        if row.get("volume") is not None and not _num(row.get("volume")):
            continue

        score = 0.0
        high, low = _num(row.get("high_52w")), _num(row.get("low_52w"))
        if high and low and high > low:
            position = (price - low) / (high - low)
            if position < 0.35:
                continue  # still in a downtrend
            # Best around 75% of the range: uptrend with room left to the high.
            score += 2.0 * (1 - abs(position - 0.75) / 0.75)
        change = _num(row.get("change_percent"))
        if change is not None:
            if change < -4 or change > 8:
                continue  # skip today's crashes and blow-off spikes
            score += 0.3 if 0 < change <= 4 else 0.0
        cap = _num(row.get("market_cap")) or _num(row.get("volume")) or 0
        score += min(math.log10(cap + 1) / 12, 1.0)  # mild preference for size/liquidity
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[:limit]]


def _rsi(close, period: int = 14) -> Optional[float]:
    """Wilder RSI (same as broker charts and the scanner)."""
    from ..trading.indicators import rsi

    if len(close.dropna()) <= period:
        return None
    value = rsi(close.astype(float), period).iloc[-1]
    return None if value != value else float(value)


def technical_check(row: dict) -> Optional[dict]:
    """Trend-following check on a year of daily closes; None if it fails.

    Deliberately not the analyzer's oscillator vote: RSI/Bollinger/
    Stochastic there are mean-reversion signals that call strong uptrends
    "sell" (overbought), which is the opposite of what a buy idea needs.
    Rules: price > 50-day > 200-day average, positive 3-month return, RSI
    45-72 (momentum without being overheated), at most 15% above the 50-day.
    """
    from ..agent.agents import _resolve_fetcher

    try:
        history = _resolve_fetcher(row["market"]).get_history(row["symbol"], period="1y")
    except Exception as exc:
        logger.info("Idea check skipped for %s: %s", row["symbol"], exc)
        return None
    if history is None or len(history) < 120:
        return None
    close = history["close"].astype(float)
    last = float(close.iloc[-1])
    sma50 = float(close.tail(50).mean())
    sma200 = float(close.tail(200).mean())
    ret_3m = (last / float(close.iloc[-64]) - 1) * 100
    ret_1m = (last / float(close.iloc[-22]) - 1) * 100
    rsi = _rsi(close)
    stretch = (last / sma50 - 1) * 100
    if not (last > sma50 > sma200) or ret_3m <= 0 or rsi is None or not 45 <= rsi <= 72 or stretch > 15:
        return None
    # Higher = stronger, steadier trend: reward 3-month momentum, penalise
    # being stretched far above the 50-day average.
    score = ret_3m - 0.5 * max(0.0, stretch - 5) + (5 if 50 <= rsi <= 65 else 0)
    return {"score": score, "rsi": rsi, "return_1m": ret_1m, "return_3m": ret_3m,
            "above_sma50_pct": stretch, "above_sma200_pct": (last / sma200 - 1) * 100}


def _rule_reason(row: dict, tech: dict) -> str:
    bits = [f"uptrend: {tech['above_sma50_pct']:+.1f}% vs 50-day, {tech['above_sma200_pct']:+.1f}% vs 200-day average",
            f"3-month {tech['return_3m']:+.1f}%", f"RSI {tech['rsi']:.0f}"]
    high = _num(row.get("high_52w"))
    if high and _num(row.get("price")):
        bits.append(f"{(1 - row['price'] / high) * 100:.0f}% below 52-week high")
    return "; ".join(bits)


def _llm_pick(finalists: list[dict], count: int, market: str, categories: list[str], config) -> Optional[list[dict]]:
    from ..llm.backend_factory import create_generation_backend
    from ..llm.channels import llm_configured
    from ..llm.protocol import GenerationConfig

    if config is None or not llm_configured(config):
        return None
    lines = []
    for f in finalists:
        lines.append(
            f"- {f['symbol']} ({f.get('name')}), category {f.get('category')}, price {f.get('price')}, "
            f"day {f.get('change_percent')}%, cap {f.get('market_cap')}, technical: {f['reason']}"
        )
    prompt = (
        f"Market: {market}. Focus categories: {', '.join(categories) or 'any'}.\n"
        f"Candidates:\n" + "\n".join(lines) +
        f"\n\nPick the {count} best new positions to consider buying now."
    )
    system = (
        "You are an equity research assistant. From the candidates only, choose the best ideas for a "
        "retail investor under current conditions, balancing trend strength, valuation risk and "
        "diversification across categories. Reply ONLY with JSON: "
        '[{"symbol": "...", "reason": "one sentence, concrete"}]'
    )
    try:
        text = create_generation_backend(config).generate(prompt, GenerationConfig(max_tokens=500), system_prompt=system).text
        match = re.search(r"\[.*\]", text or "", re.DOTALL)
        picks = json.loads(match.group(0)) if match else []
    except Exception as exc:
        logger.warning("AI idea selection unavailable: %s", exc)
        return None
    by_symbol = {f["symbol"].upper(): f for f in finalists}
    chosen = []
    for pick in picks:
        f = by_symbol.get(str(pick.get("symbol", "")).upper())
        if f and f not in chosen:
            chosen.append({**f, "reason": str(pick.get("reason") or f["reason"]).strip(), "ai": True})
        if len(chosen) >= count:
            break
    return chosen or None


def find_ideas(market: str, categories: list[str], count: int = 3, exclude: Iterable[str] = (),
               config=None, rows: Optional[list[dict]] = None, check=technical_check) -> list[dict]:
    market = "us" if market in ("global", "all") else market
    exclude_set = {s.upper() for s in exclude}
    if rows is None:
        from ..data.listings import get_store

        rows = get_store().rows(market)
    candidates = screen(rows, categories, exclude_set)

    finalists = []
    for row in candidates:
        tech = check(row)
        if tech:
            finalists.append({
                "symbol": row["symbol"], "name": row.get("name"), "market": row["market"],
                "category": row.get("category"), "price": row.get("price"), "currency": row.get("currency"),
                "change_percent": row.get("change_percent"), "market_cap": row.get("market_cap"),
                "technical": tech, "reason": _rule_reason(row, tech),
            })
    if not finalists:
        return []
    finalists.sort(key=lambda f: f["technical"]["score"], reverse=True)
    return _llm_pick(finalists, count, market, categories, config) or finalists[:count]
