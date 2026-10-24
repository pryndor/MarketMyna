"""Trading charges per market and product (approximate public schedules;
the broker's contract note is final). One implementation for the position
sizer, the journal's automatic fees and the backtester's presets.

India: discount-broker schedule (brokerage ₹20 or 0.03%, whichever is lower;
0 for delivery) plus statutory STT, exchange transaction charge, SEBI fee,
stamp duty and 18% GST. Rates as of 2025-26.
US: commission (default 0) plus SEC fee and FINRA TAF on sells."""

from __future__ import annotations

from typing import Optional

RATES_AS_OF = "2025-26"

INDIA = {
    # product: (brokerage % per order, brokerage cap ₹, STT buy %, STT sell %, exchange %, stamp buy %)
    "intraday": (0.03, 20.0, 0.0, 0.025, 0.00297, 0.003),
    "delivery": (0.0, 0.0, 0.1, 0.1, 0.00297, 0.015),
    "futures": (0.03, 20.0, 0.0, 0.02, 0.00173, 0.002),
    # options: premium turnover; brokerage is a flat ₹20 per order
    "options": (None, 20.0, 0.0, 0.1, 0.03503, 0.003),
}
SEBI_PCT = 0.0001
GST_PCT = 18.0

US_SEC_PER_MILLION = 27.80
US_TAF_PER_SHARE = 0.000166
US_TAF_CAP = 8.30


def india(buy_value: float, sell_value: float, product: str) -> dict:
    pct_brk, cap, stt_buy, stt_sell, exch, stamp = INDIA[product]
    if pct_brk is None:
        brokerage = (cap if buy_value else 0) + (cap if sell_value else 0)
    else:
        brokerage = sum(min(cap, v * pct_brk / 100) for v in (buy_value, sell_value) if v)
    turnover = buy_value + sell_value
    stt = buy_value * stt_buy / 100 + sell_value * stt_sell / 100
    exchange = turnover * exch / 100
    sebi = turnover * SEBI_PCT / 100
    stamp_duty = buy_value * stamp / 100
    gst = (brokerage + exchange + sebi) * GST_PCT / 100
    return {"Brokerage": brokerage, "STT": stt, "Exchange txn": exchange, "SEBI": sebi,
            "Stamp duty": stamp_duty, "GST": gst}


def us(buy_value: float, sell_value: float, quantity: float, commission_pct: float, flat: float) -> dict:
    orders = (1 if buy_value else 0) + (1 if sell_value else 0)
    return {
        "Commission": (buy_value + sell_value) * commission_pct / 100 + flat * orders,
        "SEC fee": sell_value * US_SEC_PER_MILLION / 1_000_000,
        "FINRA TAF": min(US_TAF_CAP, quantity * US_TAF_PER_SHARE) if sell_value else 0.0,
    }


def custom(buy_value: float, sell_value: float, commission_pct: float, flat: float) -> dict:
    orders = (1 if buy_value else 0) + (1 if sell_value else 0)
    return {"Commission %": (buy_value + sell_value) * commission_pct / 100, "Flat fees": flat * orders}


def estimate(market: str, buy_value: float, sell_value: float, quantity: float = 0, product: Optional[str] = None,
             commission_pct: float = 0.0, flat: float = 0.0) -> dict:
    """Charges for one buy and/or one sell. Pass 0 for a side not traded
    yet (an open position pays only the entry side)."""
    if market == "india":
        parts = india(buy_value, sell_value, product if product in INDIA else "delivery")
    elif market in ("us", "global"):
        parts = us(buy_value, sell_value, quantity, commission_pct, flat)
    else:
        parts = custom(buy_value, sell_value, commission_pct, flat)
    parts = {k: round(v, 2) for k, v in parts.items()}
    return {"total": round(sum(parts.values()), 2), "parts": parts, "rates_as_of": RATES_AS_OF}


def for_trade(t: dict, exit_price: Optional[float] = None) -> float:
    """Charges for a journal trade: entry side, plus exit side once closed."""
    qty = t["quantity"]
    entry_value = t["entry_price"] * qty
    exit_value = (exit_price if exit_price is not None else t.get("exit_price") or 0) * qty
    buy, sell = (entry_value, exit_value) if t.get("side", "long") == "long" else (exit_value, entry_value)
    return estimate(t["market"], buy, sell, qty, t.get("product"))["total"]
