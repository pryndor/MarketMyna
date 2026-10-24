"""Shared parsing and number formatting for the research / market / portfolio commands."""

from __future__ import annotations

import math
from typing import Optional

MARKETS = ("us", "india", "china_a", "hong_kong", "crypto", "global")
MARKET_WORDS = {"in": "india", "nse": "india", "bse": "india", "usa": "us", "hk": "hong_kong", "cn": "china_a",
                "china": "china_a"}


def market_word(token: str) -> Optional[str]:
    t = token.lower()
    return t if t in MARKETS else MARKET_WORDS.get(t)


def default_market(config) -> str:
    """The Trade tab's market, as the trading commands use."""
    try:
        from ...trading.risk import load_settings

        return load_settings(config).get("market") or "india"
    except Exception:
        return "india"


def guess_market(symbol: str, config) -> str:
    """No market given: look the symbol up in the listings, preferring the
    user's default market; fall back to the default."""
    first = default_market(config)
    order = [first] + [m for m in ("india", "us") if m != first]
    if symbol.endswith("-USD"):
        return "crypto"
    try:
        from ...data.listings import get_store

        found = get_store().lookup([(m, kind, symbol) for m in order for kind in ("stock", "etf")])
    except Exception:
        return first
    for m in order:
        if any((m, kind, symbol) in found for kind in ("stock", "etf")):
            return m
    return first


def parse_symbol(args: str, config) -> tuple[Optional[str], str, list[str]]:
    """"AAPL", "AAPL us", "us:AAPL", "RELIANCE india annual" ->
    (symbol, market, remaining words). Symbol None when args are empty."""
    parts = args.split()
    if not parts:
        return None, default_market(config), []
    head, rest = parts[0], parts[1:]
    market = None
    if ":" in head:
        m, _, sym = head.partition(":")
        if market_word(m):
            market, head = market_word(m), sym
    if market is None and rest and market_word(rest[0]):
        market, rest = market_word(rest[0]), rest[1:]
    symbol = head.upper()
    return symbol, market or guess_market(symbol, config), rest


def num(v, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    return f"{v:,.{digits}f}"


def pct(v, digits: int = 1, sign: bool = True) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "n/a"
    return f"{v:+.{digits}f}%" if sign else f"{v:.{digits}f}%"


def big(v) -> str:
    """4.87e12 -> 4.87T"""
    if v is None:
        return "n/a"
    for unit, size in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= size:
            return f"{v / size:,.2f}{unit}"
    return f"{v:,.0f}"
