"""Thesis tracker: why you own (or watch) a stock, kept honest against data.

Adapted from the thesis-tracker skill in anthropics/financial-services
(Apache-2.0). A thesis should be falsifiable, so it carries:

  statement    1-2 sentences ("margins expand as the mix shifts to software")
  pillars      up to 5 supporting points, each on track / watch / broken
  risks        up to 5 things that would invalidate it
  exit_below   the price at which the thesis is broken; exit_note for the rest
  target       what it is worth if the thesis plays out
  conviction   high / medium / low
  log          dated updates: what happened and whether it strengthened or
               weakened the thesis - disconfirming evidence included

The data check sets the thesis against live numbers: price vs the exit and
target levels, the next results date, estimate revisions, pillars marked
broken and whether the quarterly review is overdue. All of it is the user's
own view measured against arithmetic - nothing here is a recommendation.
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

STATUSES = ("on_track", "watch", "broken")
IMPACTS = ("strengthens", "weakens", "neutral")
CONVICTIONS = ("high", "medium", "low")
MAX_ITEMS = 5
MAX_LOG = 200
REVIEW_DAYS = 90  # review at least quarterly, even when nothing happens
REARM = 0.03  # an exit / target alert re-arms once the price is 3% back on the other side
ALERT_EVERY = 30 * 60  # price checks per user at most this often

_last_run: dict[Optional[int], float] = {}


class ThesisError(ValueError):
    pass


def _db(config):
    from ..storage import DatabaseManager, get_db_url

    return DatabaseManager.instance(get_db_url(config=config))


def to_dict(r) -> dict:
    return {"id": r.id, "symbol": r.symbol, "market": r.market, "statement": r.statement,
            "pillars": r.pillars or [], "risks": r.risks or [], "exit_below": r.exit_below,
            "exit_note": r.exit_note or "", "target": r.target, "conviction": r.conviction or "medium",
            "log": r.log or [], "created_at": r.created_at.date().isoformat() if r.created_at else None,
            "reviewed_at": r.reviewed_at, "alerted": r.alerted or {}}


def _clean(fields: dict) -> dict:
    out = {}
    if "statement" in fields:
        text = (fields["statement"] or "").strip()
        if not text:
            raise ThesisError("Write the thesis in a sentence or two")
        out["statement"] = text[:2000]
    if "pillars" in fields:
        pillars = []
        for p in (fields["pillars"] or [])[:MAX_ITEMS]:
            text = str((p or {}).get("text", "")).strip()[:300]
            if text:
                status = (p or {}).get("status") or "on_track"
                if status not in STATUSES:
                    raise ThesisError(f"Unknown pillar status '{status}'")
                pillars.append({"text": text, "status": status})
        out["pillars"] = pillars
    if "risks" in fields:
        out["risks"] = [str(r).strip()[:300] for r in (fields["risks"] or [])[:MAX_ITEMS] if str(r).strip()]
    for key in ("exit_below", "target"):
        if key in fields:
            v = fields[key]
            if v is not None and (not isinstance(v, (int, float)) or v <= 0):
                raise ThesisError(f"{key.replace('_', ' ').capitalize()} must be a price above 0")
            out[key] = float(v) if v is not None else None
    if out.get("exit_below") and out.get("target") and out["exit_below"] >= out["target"]:
        raise ThesisError("The exit price should be below the target")
    if "exit_note" in fields:
        out["exit_note"] = (fields["exit_note"] or "").strip()[:500]
    if "conviction" in fields:
        if fields["conviction"] not in CONVICTIONS:
            raise ThesisError("Conviction is high, medium or low")
        out["conviction"] = fields["conviction"]
    return out


def get(config, symbol: str, market: str) -> Optional[dict]:
    from ..storage import ThesisRecord

    with _db(config).get_session() as s:
        r = s.query(ThesisRecord).filter(ThesisRecord.symbol == symbol, ThesisRecord.market == market).first()
        return to_dict(r) if r else None


def list_all(config) -> list[dict]:
    from ..storage import ThesisRecord

    with _db(config).get_session() as s:
        return [to_dict(r) for r in s.query(ThesisRecord).order_by(ThesisRecord.symbol)]


def save(config, symbol: str, market: str, **fields) -> dict:
    """Create or update the thesis for one stock."""
    from ..storage import ThesisRecord

    clean = _clean(fields)
    with _db(config).get_session() as s:
        r = s.query(ThesisRecord).filter(ThesisRecord.symbol == symbol, ThesisRecord.market == market).first()
        if r is None:
            if "statement" not in clean:
                raise ThesisError("Write the thesis in a sentence or two")
            r = ThesisRecord(symbol=symbol, market=market, conviction="medium", created_at=datetime.now(),
                             reviewed_at=date.today().isoformat(), log=[])
            s.add(r)
        changed_levels = {"exit_below", "target"} & set(clean)
        for k, v in clean.items():
            setattr(r, k, v)
        if changed_levels:  # new levels: their alerts may fire again
            r.alerted = {k: v for k, v in (r.alerted or {}).items() if k not in ("exit", "target")}
        s.flush()
        return to_dict(r)


def add_log(config, thesis_id: int, note: str, impact: str, conviction: Optional[str] = None,
            day: Optional[str] = None) -> Optional[dict]:
    """A dated update; adding one counts as a review."""
    from ..storage import ThesisRecord

    note = (note or "").strip()[:1000]
    if not note:
        raise ThesisError("Write what happened")
    if impact not in IMPACTS:
        raise ThesisError("Impact is strengthens, weakens or neutral")
    if conviction is not None and conviction not in CONVICTIONS:
        raise ThesisError("Conviction is high, medium or low")
    with _db(config).get_session() as s:
        r = s.query(ThesisRecord).filter(ThesisRecord.id == thesis_id).first()
        if r is None:
            return None
        today = day or date.today().isoformat()
        entry = {"date": today, "note": note, "impact": impact, "conviction": conviction or r.conviction}
        r.log = ([entry] + list(r.log or []))[:MAX_LOG]  # newest first
        if conviction:
            r.conviction = conviction
        r.reviewed_at = today
        r.alerted = {k: v for k, v in (r.alerted or {}).items() if k != "review"}
        s.flush()
        return to_dict(r)


def mark_reviewed(config, thesis_id: int, day: Optional[str] = None) -> Optional[dict]:
    from ..storage import ThesisRecord

    with _db(config).get_session() as s:
        r = s.query(ThesisRecord).filter(ThesisRecord.id == thesis_id).first()
        if r is None:
            return None
        r.reviewed_at = day or date.today().isoformat()
        r.alerted = {k: v for k, v in (r.alerted or {}).items() if k != "review"}
        s.flush()
        return to_dict(r)


def delete(config, thesis_id: int) -> bool:
    from ..storage import ThesisRecord

    with _db(config).get_session() as s:
        return bool(s.query(ThesisRecord).filter(ThesisRecord.id == thesis_id).delete())


# ------------------------------------------------------------------ data check


def review_due(t: dict, today: date) -> Optional[int]:
    """Days since the last review when it is overdue, else None."""
    last = t.get("reviewed_at") or t.get("created_at")
    if not last:
        return None
    days = (today - date.fromisoformat(last)).days
    return days if days >= REVIEW_DAYS else None


def check(t: dict, price: Optional[float], earnings: Optional[dict] = None, today: Optional[date] = None) -> list[dict]:
    """The thesis against live numbers: [{tone: up | down | warn | info, text}]."""
    today = today or date.today()
    out = []
    if price:
        if t.get("exit_below"):
            gap = (price / t["exit_below"] - 1) * 100
            if price <= t["exit_below"]:
                out.append({"tone": "down", "key": "exit",
                            "text": f"Price {price:,.2f} is at or below your exit level {t['exit_below']:,.2f}: "
                                    "by your own rule the thesis is broken."})
            else:
                out.append({"tone": "info", "key": "exit",
                            "text": f"{gap:.1f}% above your exit level {t['exit_below']:,.2f}."})
        if t.get("target"):
            if price >= t["target"]:
                out.append({"tone": "up", "key": "target",
                            "text": f"Price {price:,.2f} has reached your target {t['target']:,.2f}: time to "
                                    "decide whether the thesis still has room to run."})
            else:
                out.append({"tone": "info", "key": "target",
                            "text": f"Your target {t['target']:,.2f} is {(t['target'] / price - 1) * 100:.1f}% above the price."})
    pillars = t.get("pillars") or []
    broken = [p for p in pillars if p["status"] == "broken"]
    watch = [p for p in pillars if p["status"] == "watch"]
    if broken:
        out.append({"tone": "down", "key": "pillars",
                    "text": f"{len(broken)} of {len(pillars)} pillars marked broken: is the thesis still intact?"})
    elif watch:
        out.append({"tone": "warn", "key": "pillars", "text": f"{len(watch)} of {len(pillars)} pillars on watch."})
    weak = [e for e in (t.get("log") or [])[:3] if e.get("impact") == "weakens"]
    if len(weak) >= 2:
        out.append({"tone": "warn", "key": "log",
                    "text": f"{len(weak)} of your last 3 updates weakened the thesis."})
    due = review_due(t, today)
    if due is not None:
        out.append({"tone": "warn", "key": "review",
                    "text": f"Last reviewed {due} days ago: review at least quarterly, even when nothing happened."})
    if earnings:
        nxt, days = earnings.get("next"), earnings.get("days_to_next")
        if nxt and days is not None and 0 <= days <= 21:
            out.append({"tone": "info", "key": "earnings",
                        "text": f"Results on {nxt['date']} ({'today' if days == 0 else f'in {days} days'}): "
                                "a fresh data point for each pillar."})
        latest = earnings.get("latest")
        if latest and latest.get("actual") is not None and latest.get("surprise") is not None:
            word = "beat" if latest["surprise"] > 0 else "missed"
            out.append({"tone": "info", "key": "results",
                        "text": f"Just reported: EPS {word} estimates by {abs(latest['surprise']):.1f}%. "
                                "Log what it means for the thesis."})
        momentum = ((earnings.get("consensus") or {}).get("momentum") or {}).get("label")
        if momentum == "falling":
            out.append({"tone": "warn", "key": "estimates", "text": "Analysts' estimates are falling (90 days)."})
        elif momentum == "rising":
            out.append({"tone": "up", "key": "estimates", "text": "Analysts' estimates are rising (90 days)."})
    return out


def _price(symbol: str, market: str) -> Optional[float]:
    from ..agent.agents import _resolve_fetcher

    try:
        return float((_resolve_fetcher(market).get_quote(symbol) or {}).get("price") or 0) or None
    except Exception as exc:
        logger.info("Thesis price for %s unavailable: %s", symbol, exc)
        return None


def _earnings(symbol: str, market: str) -> Optional[dict]:
    from .earnings import build

    try:
        return build(symbol, market, with_options=False)
    except Exception as exc:
        logger.info("Thesis earnings for %s unavailable: %s", symbol, exc)
        return None


def with_check(t: dict, price: Optional[Callable] = None, earnings: Optional[Callable] = None) -> dict:
    p = (price or _price)(t["symbol"], t["market"])
    e = (earnings or _earnings)(t["symbol"], t["market"]) if t["market"] != "crypto" else None
    return {**t, "price": p, "signals": check(t, p, e)}


# ------------------------------------------------------------------ alerts


def check_alerts(config, dispatcher=None, today: Optional[date] = None, price: Optional[Callable] = None,
                 force: bool = False) -> list[str]:
    """Monitor hook: one message per thesis when the price crosses the exit or
    target level, or the quarterly review falls due. Re-arms after the price
    moves back 3%; a review reminder repeats monthly until reviewed."""
    from ..core import tenant
    from ..storage import ThesisRecord

    uid = tenant.current_user_id()
    clock = time.time()
    if not force and clock - _last_run.get(uid, 0) < ALERT_EVERY:
        return []
    _last_run[uid] = clock
    today = today or date.today()
    price = price or _price
    lines = []
    with _db(config).get_session() as s:
        for r in s.query(ThesisRecord).all():
            t, alerted, changed = to_dict(r), dict(r.alerted or {}), False
            p = price(r.symbol, r.market) if (r.exit_below or r.target) else None
            if p and r.exit_below:
                if p <= r.exit_below and "exit" not in alerted:
                    lines.append(f"• {r.symbol}: price {p:,.2f} is at or below your exit level {r.exit_below:,.2f}")
                    alerted["exit"], changed = today.isoformat(), True
                elif p > r.exit_below * (1 + REARM) and "exit" in alerted:
                    alerted.pop("exit")
                    changed = True
            if p and r.target:
                if p >= r.target and "target" not in alerted:
                    lines.append(f"• {r.symbol}: price {p:,.2f} reached your target {r.target:,.2f}")
                    alerted["target"], changed = today.isoformat(), True
                elif p < r.target * (1 - REARM) and "target" in alerted:
                    alerted.pop("target")
                    changed = True
            due = review_due(t, today)
            last = alerted.get("review")
            if due is not None and (not last or (today - date.fromisoformat(last)).days >= 30):
                lines.append(f"• {r.symbol}: thesis last reviewed {due} days ago - time for a quarterly review")
                alerted["review"], changed = today.isoformat(), True
            if changed:
                r.alerted = alerted
    if lines:
        try:
            from ..notifiers.dispatcher import NotificationDispatcher

            dispatcher = dispatcher or NotificationDispatcher(config)
            dispatcher.send_all("📝 Your theses\n" + "\n".join(lines), title="Thesis check", purpose="alert")
        except Exception as exc:
            logger.error("Thesis alert failed: %s", exc)
    return lines
