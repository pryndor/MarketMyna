"""Smart messaging for big watchlists (100+ stocks).

Instead of a paragraph per stock, a run produces:
- a full table of every monitored stock (saved, opened through a link and
  emailed as HTML), and
- a short message with only the day's top N "hot" stocks.

Every stock gets cheap, computed metrics (no AI):
  normal range   20-day Bollinger band (where price usually trades)
  buy point      support: the higher of the lower band and the 20-day low
  sell point     resistance: the lower of the upper band and the 60-day high
                 (upper band if price is already above it)
  stop loss      buy point minus one average true range
  1-week range   price +/- one weekly standard deviation (~68% of weeks)
  valuation      P/E vs its industry average (fundamental analyzer)
  action         a score from trend, RSI, levels and valuation

The points, stop and action are working values only: without_calls()
turns the action into a bullish / neutral / bearish reading and drops the
rest before anything is saved, sent or shown (src/core/compliance.py).

Only the `ai_top` most "attention-worthy" stocks also get the full AI
pipeline, so a 100-stock list doesn't burn 400 LLM calls a day.
"""

from __future__ import annotations

import html as html_lib
import logging
import math
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from ..core.numbers import finite as _num

logger = logging.getLogger(__name__)

WORKERS = 6


def compute_snapshot(history, info: Optional[dict] = None) -> dict:
    """Levels, forecast range and rule-based action from price history
    (and optional yfinance info for valuation). Pure: no network."""
    close = history["close"].astype(float)
    high = history["high"].astype(float) if "high" in history else close
    low = history["low"].astype(float) if "low" in history else close
    if len(close) < 30:
        raise ValueError("not enough history")

    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    change_pct = (price / prev - 1) * 100 if prev else None

    mid = float(close.tail(20).mean())
    sd = float(close.tail(20).std())
    band_low, band_high = mid - 2 * sd, mid + 2 * sd
    low20 = float(low.tail(20).min())
    high60 = float(high.tail(60).max())

    prev_close = close.shift(1)
    true_range = (high - low).combine((high - prev_close).abs(), max).combine((low - prev_close).abs(), max)
    atr = float(true_range.tail(14).mean())

    buy_point = max(band_low, low20)
    sell_point = min(band_high, high60) if min(band_high, high60) > price else band_high
    stop_loss = buy_point - atr

    daily = close.pct_change().dropna()
    week_sd = float(daily.tail(60).std()) * math.sqrt(5)
    # Risk over the history given (a year): annualised volatility and the deepest fall from a high.
    volatility = float(daily.std()) * math.sqrt(252) if len(daily) > 1 else None
    max_drawdown = float((close / close.cummax() - 1).min())
    week_low, week_high = price * (1 - week_sd), price * (1 + week_sd)

    delta = close.diff()
    gain = delta.clip(lower=0).tail(14).mean()
    loss = (-delta.clip(upper=0)).tail(14).mean()
    rsi = 100.0 if loss == 0 else float(100 - 100 / (1 + gain / loss))

    sma50 = float(close.tail(50).mean())
    sma200 = float(close.tail(200).mean()) if len(close) >= 200 else None
    if sma200 and price > sma50 > sma200:
        trend = "uptrend"
    elif sma200 and price < sma50 < sma200:
        trend = "downtrend"
    else:
        trend = "sideways"

    valuation, pe = None, None
    if info:
        try:
            from ..analysis.fundamental import FundamentalAnalyzer, yfinance_fundamentals

            summary = FundamentalAnalyzer(yfinance_fundamentals(info)).get_summary()
            status = (summary.get("valuation") or {}).get("status")
            valuation = status if status and status != "N/A" else None
            pe = _num((summary.get("valuation") or {}).get("value")) or None
        except Exception:
            pass

    score = {"uptrend": 1, "downtrend": -1}.get(trend, 0)
    score += 1 if rsi < 35 else -1 if rsi > 70 else 0
    near_buy = price <= buy_point * 1.02
    near_sell = price >= sell_point * 0.98
    score += 1 if near_buy else 0
    score -= 1 if near_sell else 0
    score += {"undervalued": 1, "overvalued": -1}.get(valuation or "", 0)
    action = "buy" if score >= 2 else "sell" if score <= -2 else "hold"

    volume = history["volume"].astype(float) if "volume" in history else None
    vol_ratio = None
    if volume is not None and len(volume) > 21 and float(volume.tail(21).head(20).mean()) > 0:
        vol_ratio = float(volume.iloc[-1] / volume.tail(21).head(20).mean())

    # Why this stock deserves attention today (ranking for the top N).
    reasons, attention = [], 0.0
    if change_pct is not None and abs(change_pct) >= 2:
        reasons.append(f"moved {change_pct:+.1f}% today")
    attention += abs(change_pct or 0)
    if action != "hold":
        attention += 2
    if near_buy:
        attention += 1.5
        reasons.append("at its buy point")
    elif near_sell:
        attention += 1.5
        reasons.append("at its sell point")
    if rsi < 30 or rsi > 70:
        attention += 1
        reasons.append("oversold" if rsi < 30 else "overbought")
    if vol_ratio and vol_ratio >= 1.5:
        attention += 1
        reasons.append(f"volume {vol_ratio:.1f}x normal")

    return {
        "price": price, "change_percent": change_pct,
        "normal_low": band_low, "normal_high": band_high,
        "buy_point": buy_point, "sell_point": sell_point, "stop_loss": stop_loss,
        "week_low": week_low, "week_high": week_high,
        "rsi": rsi, "trend": trend, "valuation": valuation, "pe": pe,
        "atr": atr, "volume_ratio": vol_ratio,
        "volatility": volatility, "max_drawdown": max_drawdown,
        "high_52w": float(high.max()), "low_52w": float(low.min()),
        "action": action, "attention": round(attention, 2), "reasons": reasons,
    }


def snapshot(symbol: str, market: str) -> dict:
    """Network wrapper: history (fallback chains) + yfinance info."""
    from ..agent.agents import _resolve_fetcher
    from .analysis_run import yahoo_symbol

    row = {"symbol": symbol, "market": market}
    try:
        history = _resolve_fetcher(market).get_history(symbol, period="1y")
        info = {}
        if market != "crypto":
            try:
                import yfinance as yf

                from ..utils.deadline import call_with_deadline

                info = call_with_deadline(lambda: yf.Ticker(yahoo_symbol(symbol, market)).info, 15) or {}
            except Exception:
                info = {}
        row.update(compute_snapshot(history, info))
        row["name"] = info.get("shortName") or info.get("longName")
    except Exception as exc:
        row["error"] = str(exc) or type(exc).__name__
    return row


def build_rows(targets, config, ai_top: int, analyze=None, snap=snapshot, mode: str = "standard") -> list[dict]:
    """Snapshot every stock (parallel), rank by attention, then run the AI
    pipeline (at the schedule's analysis depth) on the top `ai_top` only."""
    from .analysis_run import analyze_symbol

    analyze = analyze or analyze_symbol
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        rows = list(pool.map(lambda t: snap(t.symbol, t.market), targets))
    rows.sort(key=lambda r: r.get("attention", -1), reverse=True)

    for row in [r for r in rows if "error" not in r][: max(0, ai_top)]:
        result = analyze(row["symbol"], row["market"], mode, config)
        dash = result.get("dashboard") or {}
        # The AI's outlook replaces the computed reading; none, and the computed one stands.
        if dash.get("outlook"):
            row["action"] = {"bullish": "buy", "bearish": "sell"}.get(dash["outlook"], "hold")
            row["ai"] = True
            row["ai_summary"] = dash.get("analysis_summary")
    return rows


# A report shows what the indicators read, never a call (src/core/compliance.py).
READINGS = {"strong_buy": "positive", "buy": "positive", "hold": "mixed", "sell": "negative", "strong_sell": "negative"}
READING_LABELS = {"positive": "Bullish", "mixed": "Neutral", "negative": "Bearish"}
READING_ICONS = {"positive": "▲", "mixed": "◆", "negative": "▼"}
_NEUTRAL_REASONS = {"at its buy point": "near its support level", "at its sell point": "near its resistance level",
                    "oversold": "RSI below 30", "overbought": "RSI above 70"}


def without_calls(row: dict) -> dict:
    """The row with every call, level and stop removed and the computed
    action turned into a reading of the indicators (positive / mixed /
    negative). Verdict words (undervalued, at its buy point) go too."""
    from ..core.compliance import CALL_FIELDS

    if "error" in row:
        return row
    out = {k: v for k, v in row.items() if k not in CALL_FIELDS}
    out["reading"] = READINGS.get(str(row.get("action") or "hold").lower(), "mixed")
    out["reasons"] = [_NEUTRAL_REASONS.get(r, r) for r in row.get("reasons") or []]
    out["valuation"] = None  # "undervalued" / "overvalued" is a verdict; the P/E stays
    return out


def reading_label(row: dict) -> str:
    reading = row.get("reading") or "mixed"
    return f"{READING_ICONS[reading]} {READING_LABELS[reading]}"


def save_report(config, rows: list[dict], title: str, meta: dict) -> str:
    from ..storage import DatabaseManager, ReportRunRecord, get_db_url

    token = secrets.token_urlsafe(16)
    db = DatabaseManager.instance(get_db_url(config=config))
    with db.get_session() as session:
        session.add(ReportRunRecord(token=token, title=title, stock_count=len(rows), rows=rows, meta=meta))
    return token


# ------------------------------------------------------------- rendering

def _f(value, digits: int = 2) -> str:
    v = _num(value)
    if v is None:
        return "—"
    return f"{v:,.{digits}f}" if abs(v) >= 1 else f"{v:.4f}"


def smart_message(rows: list[dict], prefs, lang: str, link: Optional[str], now: datetime) -> tuple[str, str]:
    """(title, body): only the top N, one line each, then the link."""
    from .report import CURRENCY_SYMBOLS
    from .report_i18n import has_builtin, t

    lang_labels = lang if has_builtin(lang) else "en"
    good = [r for r in rows if "error" not in r]
    top = good[: prefs.smart_top_n]
    lines = [
        f"📊 {t(lang_labels, 'smart_top', n=len(top))} · {now:%d %b %Y}",
        "",
    ]
    for r in top:
        cur = CURRENCY_SYMBOLS.get(r["market"], "")
        reading = r.get("reading") or "mixed"
        change = f" ({r['change_percent']:+.1f}%)" if _num(r.get("change_percent")) is not None else ""
        lines.append(f"{READING_ICONS[reading]} {r['symbol']} {cur}{_f(r['price'])}{change} · "
                     f"{t(lang_labels, 'indicators')}: {t(lang_labels, 'reading_' + reading)}")
        lines.append(f"   {t(lang_labels, 'normal')} {cur}{_f(r['normal_low'])}–{_f(r['normal_high'])} · "
                     f"{t(lang_labels, 'week')} {cur}{_f(r['week_low'])}–{_f(r['week_high'])}")
        why = r.get("ai_summary") or ", ".join(r.get("reasons") or [])
        if why:
            lines.append(f"   {why[:140]}{'…' if len(why) > 140 else ''}")
    lines.append("")
    lines.append(f"📄 {t(lang_labels, 'full_report', n=len(rows))}" + (f": {link}" if link else ""))
    lines.append(t(lang_labels, "reading_note"))
    lines.append(t(lang_labels, "disclaimer"))
    return t(lang_labels, "title"), "\n".join(lines)


def html_report(rows: list[dict], title: str, now: datetime, link: Optional[str]) -> str:
    """Self-contained HTML table of every stock (for email and the artifact):
    the indicators' reading and the ranges, no call, level or stop, with a
    note on how to read it."""
    from .report import CURRENCY_SYMBOLS

    esc = html_lib.escape
    colors = {"positive": "#0b7a52", "mixed": "#8f5b00", "negative": "#c02f2f"}
    head = ["Stock", "Price", "Day", "Indicators", "Normal range", "1-week range", "Trend", "RSI", "P/E", "What stands out"]
    body = []
    for r in rows:
        if "error" in r:
            body.append(f"<tr><td>{esc(r['symbol'])}</td><td colspan='9' style='color:#888'>no data: {esc(r['error'][:80])}</td></tr>")
            continue
        cur = CURRENCY_SYMBOLS.get(r["market"], "")
        chg = _num(r.get("change_percent"))
        cells = [
            f"<b>{esc(r['symbol'])}</b><br><span style='color:#666;font-size:11px'>{esc(r.get('name') or '')}</span>",
            f"{cur}{_f(r['price'])}",
            f"<span style='color:{'#0b7a52' if (chg or 0) >= 0 else '#c02f2f'}'>{'' if chg is None else f'{chg:+.1f}%'}</span>",
            f"<b style='color:{colors[r.get('reading') or 'mixed']}'>{esc(reading_label(r))}</b>",
            f"{_f(r['normal_low'])}–{_f(r['normal_high'])}",
            f"{_f(r['week_low'])}–{_f(r['week_high'])}",
            esc(r["trend"]), f"{r['rsi']:.0f}", _f(r.get("pe"), 1),
            esc((r.get("ai_summary") or ", ".join(r.get("reasons") or []))[:200]),
        ]
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    link_html = f"<p><a href='{esc(link)}'>Open the interactive report</a></p>" if link else ""
    return f"""<!doctype html><html><body style="font-family:Segoe UI,Arial,sans-serif;color:#0f1522">
<h2 style="margin:0">{esc(title)}</h2>
<p style="color:#555;margin:4px 0 12px">{now:%d %b %Y, %H:%M %Z} · {len(rows)} stocks</p>
<p style="background:#eef3fb;border-left:4px solid #1f3a8a;padding:8px 12px;font-size:12px">{esc(READING_NOTE)}</p>
{link_html}
<table cellpadding="6" style="border-collapse:collapse;font-size:12px">
<thead><tr style="background:#eceff4">{''.join(f'<th align="left">{h}</th>' for h in head)}</tr></thead>
<tbody>{''.join(body)}</tbody></table>
<p style="color:#777;font-size:11px">Indicators = how trend, momentum (RSI), where the price sits in its range and
valuation lean today: bullish, neutral or bearish. Normal range = 20-day Bollinger band. 1-week range ≈
where ~2 of 3 weeks end, from recent volatility. Computed from market data.</p></body></html>"""


# Shown on every general user's report: what the reading is and is not.
READING_NOTE = ("This report describes what the market data shows. It is not a recommendation to buy, sell or "
                "hold any stock. \"Bullish\" or \"bearish\" means most of the indicators we "
                "track lean that way today; they can change quickly and are often wrong. Do your own research or "
                "speak to a SEBI-registered adviser before you invest.")


def run_smart(targets, prefs, config, dispatcher=None, dry_run: bool = False, analyze=None, snap=snapshot):
    """Full smart run: rows -> saved report -> short messages (+ full HTML
    email). Returns (reports by language, delivery, rows, token)."""
    from ..notifiers.dispatcher import NotificationDispatcher
    from .report import translate_report
    from .report_i18n import normalize_language

    rows = build_rows(targets, config, prefs.smart_ai_top, analyze=analyze, snap=snap,
                      mode=getattr(prefs, "mode", None) or "standard")
    rows = [without_calls(r) for r in rows]
    now = datetime.now(ZoneInfo(prefs.timezone))
    title = f"MarketMyna · {len(rows)} stocks · {now:%d %b %Y}"
    token = None
    try:
        token = save_report(config, rows, title, {"markets": sorted({t.market for t in targets}),
                                                  "compliance": "analytics"})
    except Exception as exc:
        logger.warning("Could not save full report: %s", exc)
    link = f"{prefs.report_base_url.rstrip('/')}/r/{token}" if prefs.report_base_url and token else None

    dispatcher = dispatcher or NotificationDispatcher(config)
    channels = dispatcher.configured_channels("report")
    by_lang = prefs.languages_needed(channels)
    languages = list(dict.fromkeys([normalize_language(prefs.language), *by_lang]))

    reports = {}
    for lang in languages:
        msg_title, body = smart_message(rows, prefs, lang, link, now)
        if lang != "en":
            body = translate_report(body, lang, config) or body
        reports[lang] = (msg_title, body)

    full_html = html_report(rows, title, now, link) if prefs.smart_email_full else None
    if dry_run or not channels:
        return reports, {}, rows, token, full_html

    # The report file (PDF or Excel, from the ticked sections) to the channels the user picked.
    from .smart_file import report_file

    wanted = [c for c in (getattr(prefs, "smart_file_channels", None) or []) if c in ("email", "telegram")]
    report = report_file(rows, prefs, config, now, title) if wanted else None
    files = {c: [report] for c in wanted} if report else {}

    messages = {}
    for lang, chs in by_lang.items():
        for ch in chs:
            msg_title, body = reports[lang]
            messages[ch] = (msg_title, body, full_html) if ch == "email" and full_html else (msg_title, body)
    return reports, dispatcher.send_each(messages, purpose="report", files=files), rows, token, full_html
