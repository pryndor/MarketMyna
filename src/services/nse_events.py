"""Exchange-confirmed dates for Indian stocks, from NSE's bulk feeds:

- board meetings (results, dividend, fund raising, split, bonus…), the
  official results date that Yahoo's estimate is replaced with;
- corporate actions by ex-date (dividends with the amount, splits, bonus,
  rights, buybacks).

One fetch covers every stock for the next four months, cached and saved on
disk through econ_calendar's source cache.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Callable, Optional

MEETINGS_URL = "https://www.nseindia.com/api/corporate-board-meetings?index=equities&from_date={a}&to_date={b}"
ACTIONS_URL = "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={a}&to_date={b}"
AHEAD_DAYS = 125
TTL = 6 * 3600

# words in a meeting's purpose / description -> the topic shown
TOPICS = [("financial result", "results"), ("dividend", "dividend"), ("bonus", "bonus"), ("split", "stock split"),
          ("sub-division", "stock split"), ("buy back", "buyback"), ("buyback", "buyback"),
          ("fund raising", "fund raising"), ("rights", "rights issue"), ("merger", "merger"),
          ("amalgamation", "merger"), ("demerger", "demerger")]

# corporate action subject -> label
ACTION_LABELS = [("dividend", "Dividend"), ("bonus", "Bonus issue"), ("split", "Stock split"),
                 ("sub-division", "Stock split"), ("rights", "Rights issue"), ("buy back", "Buyback"),
                 ("buyback", "Buyback"), ("demerger", "Demerger"), ("amalgamation", "Merger"), ("agm", "AGM")]

FetchJson = Callable[[str], object]


def _day(text) -> Optional[date]:
    try:
        return datetime.strptime(str(text).strip(), "%d-%b-%Y").date()
    except ValueError:
        return None


def topics(text: str) -> list[str]:
    low = (text or "").lower()
    out: list[str] = []
    for word, topic in TOPICS:
        if word in low and topic not in out and not (topic == "merger" and "demerger" in low):
            out.append(topic)
    return out


def parse_meetings(rows) -> list[dict]:
    """[{symbol, date, topics}], one per company and meeting day."""
    merged: dict[tuple[str, str], list[str]] = {}
    for r in rows or []:
        d = _day(r.get("bm_date"))
        sym = str(r.get("bm_symbol") or "").upper()
        if not d or not sym:
            continue
        found = topics(f"{r.get('bm_purpose') or ''} {r.get('bm_desc') or ''}")
        have = merged.setdefault((sym, d.isoformat()), [])
        have += [t for t in found if t not in have]
    return [{"symbol": s, "date": d, "topics": t} for (s, d), t in merged.items()]


def action_label(subject: str) -> str:
    low = (subject or "").lower()
    return next((label for word, label in ACTION_LABELS if word in low), "Corporate action")


def parse_actions(rows) -> list[dict]:
    """[{symbol, date (ex-date), label, subject}]."""
    out = []
    for r in rows or []:
        d = _day(r.get("exDate"))
        sym = str(r.get("symbol") or "").upper()
        subject = re.sub(r"\s+", " ", str(r.get("subject") or "")).strip()
        if d and sym and subject:
            out.append({"symbol": sym, "date": d.isoformat(), "label": action_label(subject), "subject": subject})
    return out


def _fetch_json(url: str) -> object:
    from .market_calendar import _get_json

    return _get_json(url)


def india_events(fetch: FetchJson = _fetch_json, today: Optional[date] = None) -> dict:
    """{"meetings": [...], "actions": [...]} from a few days back to four months ahead."""
    from .econ_calendar import _source

    today = today or date.today()
    a, b = (today - timedelta(days=5)).strftime("%d-%m-%Y"), (today + timedelta(days=AHEAD_DAYS)).strftime("%d-%m-%Y")
    meetings, _ = _source("nse_board_meetings", lambda: parse_meetings(fetch(MEETINGS_URL.format(a=a, b=b))), ttl=TTL)
    actions, _ = _source("nse_corporate_actions", lambda: parse_actions(fetch(ACTIONS_URL.format(a=a, b=b))), ttl=TTL)
    return {"meetings": meetings, "actions": actions}
