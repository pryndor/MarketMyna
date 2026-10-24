"""Scheduled-report content: which sections a user receives, in which
language, on which channel - and the builder that renders it.

Plain text with emoji (no Markdown/HTML) so Telegram, email, ntfy,
Slack, WeChat... all render the same message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from .report_i18n import has_builtin, language_name, normalize_language, t, tv
from ..core.compliance import guard_prompt, outlook

logger = logging.getLogger(__name__)

# (id, English label, description, on by default in its area)
SECTIONS: list[tuple[str, str, str, bool]] = [
    ("market", "Market overview", "Index levels and day change for each market in the report", True),
    ("calls", "Movers & AI outlook", "Biggest gainers and losers, stocks near a 52-week high or low, and each stock's bullish / neutral / bearish AI outlook", True),
    ("portfolio", "Your portfolio", "Portfolio value, today's change, total gain and the holdings that moved it most", True),
    ("alerts", "Your alerts", "Price alerts that fired since the last report, and active ones close to their trigger", True),
    ("hot_trade", "Hot for trading", "Today's biggest moves on heavy trading, unusual activity and breakouts in your markets", True),
    ("hot_invest", "Trending for investors", "Quality stocks on a dip, earnings momentum and what mutual funds added", False),
    ("ideas", "New stock ideas", "Stocks outside your watchlist that look constructive now, in your focus market and categories", True),
    ("funds", "Mutual funds", "NAV, day change and 1-month / 1-year returns for the funds you track", True),
    ("price", "Price & range", "Price, day change and 52-week range", True),
    ("levels", "Trading range", "Normal range (20-day band), expected 1-week range and average daily move (ATR)", True),
    ("ai", "AI summary", "What changed, strengths, weaknesses and risks to watch - no buy/sell call", True),
    ("technical", "Technical readings", "Indicator values such as RSI and MACD, without a verdict", True),
    ("indicators", "Technical indicators", "RSI, MACD, moving averages, Bollinger bands (values)", False),
    ("fundamentals", "Fundamentals", "Score, P/E, ROE, financial health, growth, dividend", False),
    ("risk", "Risk", "Risk level, volatility and maximum drawdown", True),
    ("analysts", "Analyst ratings", "Broker consensus of third-party analysts, as bullish / neutral / bearish", False),
    ("events", "Upcoming events", "Next earnings date and ex-dividend date", False),
    ("news", "News headlines", "Latest headlines for each stock", False),
    ("valuation", "Valuation vs sector", "P/E, price/book and price/sales against the median of the stock's sector", False),
]

# Which side of the app a section is for (absent = both). The Scheduler shows
# each area only its own sections and keeps the other area's choices as saved.
SECTION_AREAS: dict[str, str] = {
    "portfolio": "investor", "hot_invest": "investor", "ideas": "investor", "funds": "investor",
    "fundamentals": "investor", "analysts": "investor", "valuation": "investor",
    "alerts": "trader", "hot_trade": "trader", "levels": "trader", "indicators": "trader",
}

# "ideas" (stock picks of our own) is never shown: no buy / sell calls (src/core/compliance.py).
PUBLIC_HIDDEN = {"ideas"}


def section_catalog() -> list[tuple[str, str, str, bool]]:
    """(id, label, description, default) as the Scheduler should show them."""
    return [s for s in SECTIONS if s[0] not in PUBLIC_HIDDEN]


SECTION_IDS = [s[0] for s in SECTIONS]
DEFAULT_SECTIONS = [s[0] for s in SECTIONS if s[3]]
# Report-wide sections built once per run, not per stock.
REPORT_WIDE = {"market", "calls", "portfolio", "alerts", "hot_trade", "hot_invest", "ideas", "funds"}

MARKET_NAMES = {
    "us": "US", "india": "India", "china_a": "China A", "hong_kong": "Hong Kong", "crypto": "Crypto", "global": "Global",
}
CURRENCY_SYMBOLS = {"india": "₹", "us": "$", "china_a": "¥", "hong_kong": "HK$", "crypto": "$", "global": ""}
OUTLOOK_ICONS = {"bullish": "▲", "neutral": "◆", "bearish": "▼"}


def clean_sections(values: Optional[Iterable[str]]) -> list[str]:
    """Known section ids only, in catalogue order."""
    wanted = {v.strip().lower() for v in (values or []) if v and v.strip()}
    return [s for s in SECTION_IDS if s in wanted]


@dataclass
class ReportPrefs:
    language: str = "en"
    sections: list[str] = field(default_factory=lambda: list(DEFAULT_SECTIONS))
    # symbol -> its own section list, overriding `sections` for that stock
    stock_sections: dict[str, list[str]] = field(default_factory=dict)
    # channel name -> language, overriding `language` for that channel
    channel_languages: dict[str, str] = field(default_factory=dict)
    mode: str = "standard"
    timezone: str = "Asia/Kolkata"
    # AMFI scheme codes for the "funds" section
    funds: list[str] = field(default_factory=list)
    # Portfolio names for the "portfolio" section (empty = all)
    portfolios: list[str] = field(default_factory=list)
    # "ideas" section: market to scan, categories to focus on, how many
    ideas_market: str = "india"
    ideas_categories: list[str] = field(default_factory=list)
    ideas_count: int = 3
    # Smart messaging: short top-N message + link to the full report
    smart: bool = False
    smart_top_n: int = 5
    smart_ai_top: int = 10  # AI analyses only the N most interesting stocks (0 = none)
    smart_email_full: bool = True
    # The report file sent with the short message: "pdf", "xlsx" or "none",
    # built from the ticked sections, to these channels (src/services/smart_file.py).
    smart_file: str = "pdf"
    smart_file_channels: list[str] = field(default_factory=lambda: ["email", "telegram"])
    report_base_url: Optional[str] = None

    def sections_for(self, symbol: str) -> list[str]:
        own = self.stock_sections.get(symbol.upper())
        return own if own is not None else self.sections

    def all_sections(self) -> set[str]:
        out = set(self.sections)
        for secs in self.stock_sections.values():
            out.update(secs)
        return out

    def languages_needed(self, channels: Iterable[str]) -> dict[str, list[str]]:
        """language -> channels that should receive it."""
        by_lang: dict[str, list[str]] = {}
        for ch in channels:
            lang = normalize_language(self.channel_languages.get(ch) or self.language)
            by_lang.setdefault(lang, []).append(ch)
        return by_lang


# ------------------------------------------------------------ formatting


def _num(value) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # NaN -> None


def _fmt(value, digits: int = 2) -> Optional[str]:
    v = _num(value)
    if v is None:
        return None
    return f"{v:,.{digits}f}" if abs(v) >= 1 else f"{v:.4f}"


def _pct(value, signed: bool = True) -> Optional[str]:
    v = _num(value)
    if v is None:
        return None
    return f"{v:+.2f}%" if signed else f"{v:.1f}%"


def _one_line(text: Optional[str], limit: int = 240) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _future(d) -> Optional[str]:
    """Format a date only if it's today or later."""
    if d is None:
        return None
    try:
        day = d if isinstance(d, date) else datetime.fromisoformat(str(d)).date()
    except ValueError:
        return None
    return day.strftime("%d %b %Y") if day >= date.today() else None


def _market_lines(overview: list[dict], lang: str) -> list[str]:
    if not overview:
        return []
    lines = [f"🌐 {t(lang, 'market_overview')}"]
    for idx in overview:
        change = _pct(idx.get("change_percent"))
        arrow = "▲" if (_num(idx.get("change_percent")) or 0) >= 0 else "▼"
        lines.append(f"   {arrow} {idx['name']} {_fmt(idx.get('price')) or '—'}" + (f" ({change})" if change else ""))
    return lines


def _stock_block(r: dict, sections: list[str], lang: str, multi_market: bool) -> list[str]:
    dash = r.get("dashboard") or {}
    quote = r.get("quote") or {}
    extras = r.get("extras") or {}
    cur = CURRENCY_SYMBOLS.get(r["market"], "")
    title = f"{'📌' if r.get('ok') else '⚠️'} {r['symbol']}"
    if r.get("name") and r["name"].upper() != r["symbol"].upper():
        title += f" · {r['name']}"
    if dash.get("outlook"):
        word = tv(lang, dash["outlook"])
        title += f" — {OUTLOOK_ICONS[dash['outlook']]} {word.capitalize() if lang == 'en' else word}"
    if multi_market:
        title += f" [{MARKET_NAMES.get(r['market'], r['market'])}]"
    lines = [title]

    if "price" in sections:
        bits = []
        price = _fmt(quote.get("price"))
        if price:
            change = _pct(quote.get("change_percent"))
            bits.append(f"{t(lang, 'price')} {cur}{price}" + (f" ({change})" if change else ""))
        if bits:
            lines.append("   💰 " + " · ".join(bits))
        lo, hi = _fmt(extras.get("low_52w")), _fmt(extras.get("high_52w"))
        if lo and hi:
            lines.append(f"   📏 {t(lang, 'range_52w')}: {cur}{lo} – {cur}{hi}")

    lv = extras.get("levels") or {}
    if "levels" in sections and lv:
        lines += _level_lines(lv, cur, lang)

    if "ai" in sections:
        if dash.get("analysis_summary"):
            lines.append(f"   🤖 {t(lang, 'ai_summary')}: {_one_line(dash['analysis_summary'])}")
        elif not r.get("ok"):
            lines.append(f"   🤖 {t(lang, 'ai_unavailable')}: {_one_line(r.get('error'), 160)}")

    technical = next((o for o in dash.get("opinions", []) if o.get("agent_name") == "technical"), None)
    if "technical" in sections and technical:
        readings = _readings(technical)
        if readings:
            lines.append(f"   📈 {t(lang, 'readings')}: {readings}")

    if "indicators" in sections and technical:
        indicators = (technical.get("details") or {}).get("indicators") or {}
        bits = []
        for name, info in indicators.items():
            value = _fmt(info.get("value"))
            if value:
                bits.append(f"{name.upper()} {value}")
        if bits:
            lines.append(f"   📐 {t(lang, 'indicators')}: " + " · ".join(bits))

    fund = extras.get("fundamentals")
    if "fundamentals" in sections and fund:
        bits = [f"{t(lang, 'score')} {fund.get('overall_score', '—')}/100"]
        val = (fund.get("valuation") or {})
        if _fmt(val.get("value")):
            bits.append(f"{t(lang, 'pe')} {_fmt(val['value'], 1)}")
        roe = ((fund.get("profitability") or {}).get("roe") or {}).get("value")
        if _num(roe):
            bits.append(f"{t(lang, 'roe')} {_pct(roe, signed=False)}")
        health = (fund.get("financial_health") or {}).get("rating")
        if health:
            bits.append(f"{t(lang, 'health')} {tv(lang, health)}")
        growth = ((fund.get("growth") or {}).get("revenue_growth") or {}).get("value")
        if _num(growth):
            bits.append(f"{t(lang, 'revenue_growth')} {_pct(growth)}")
        dy = (fund.get("dividend") or {}).get("yield")
        if _num(dy):
            bits.append(f"{t(lang, 'dividend_yield')} {_pct(dy, signed=False)}")
        lines.append(f"   🏦 {t(lang, 'fundamentals')}: " + " · ".join(bits))

    if "risk" in sections and dash.get("risk_level"):
        bits = [tv(lang, dash["risk_level"])]
        risk = next((o for o in dash.get("opinions", []) if o.get("agent_name") == "risk"), None)
        details = (risk or {}).get("details") or {}
        if _num(details.get("volatility")) is not None:
            bits.append(f"{t(lang, 'volatility')} {_num(details['volatility']) * 100:.0f}%")
        if _num(details.get("max_drawdown")) is not None:
            bits.append(f"{t(lang, 'drawdown')} {_num(details['max_drawdown']) * 100:.0f}%")
        lines.append(f"   ⚖️ {t(lang, 'risk')}: " + " · ".join(bits))

    analysts = extras.get("analysts")
    if "analysts" in sections and analysts and analysts.get("recommendation"):
        # A direction, without the brokers' price target.
        word = outlook(analysts["recommendation"]) or analysts["recommendation"]
        text = f"   🎯 {t(lang, 'consensus_src')}: {tv(lang, word)}"
        if analysts.get("count"):
            text += f" ({t(lang, 'n_analysts', n=analysts['count'])})"
        lines.append(text)

    events = extras.get("events") or {}
    if "events" in sections:
        bits = []
        if _future(events.get("earnings_date")):
            bits.append(f"{t(lang, 'earnings')} {_future(events['earnings_date'])}")
        if _future(events.get("ex_dividend_date")):
            bits.append(f"{t(lang, 'ex_dividend')} {_future(events['ex_dividend_date'])}")
        if bits:
            lines.append(f"   📅 {t(lang, 'upcoming')}: " + " · ".join(bits))

    news = extras.get("news") or []
    news_view = next((o for o in dash.get("opinions", []) if o.get("agent_name") == "news"), None)
    if "news" in sections and news:
        header = f"   📰 {t(lang, 'news')}"
        summary = (news_view or {}).get("summary")
        lines.append(f"{header}: {_one_line(summary, 220)}" if summary else f"{header}:")
        for item in news:
            source = f" — {item['source']}" if item.get("source") else ""
            lines.append(f"      • {_one_line(item.get('title'), 140)}{source}")

    val = extras.get("valuation") or {}
    if "valuation" in sections and val.get("position"):
        bits = [f"{m['label']} {_fmt(m['value'], 1)} vs {_fmt(m['sector_median'], 1)}"
                for m in val.get("multiples", []) if m.get("ratio")]
        zone = val.get("zone")
        word = t(lang, f"zone_{zone}") if zone else ""
        lines.append(f"   ⚖️ {t(lang, 'valuation_vs_sector')}: {' · '.join(bits)} → {val['position']:.2f}× ({word})")
    return lines


def _level_lines(lv: dict, cur: str, lang: str) -> list[str]:
    """Trading range from daily bars (src/services/smart_report.compute_snapshot):
    ranges only, no support / resistance / stop to act on."""
    price = _num(lv.get("price"))
    atr = _num(lv.get("atr"))
    bits = []
    lo, hi = _fmt(lv.get("normal_low")), _fmt(lv.get("normal_high"))
    if lo and hi:
        bits.append(f"{t(lang, 'normal_range')} {cur}{lo} – {cur}{hi}")
    lines = ["   🎚️ " + " · ".join(bits)] if bits else []
    more = []
    wl, wh = _fmt(lv.get("week_low")), _fmt(lv.get("week_high"))
    if wl and wh:
        more.append(f"{t(lang, 'week_range')} {cur}{wl} – {cur}{wh}")
    if atr and price:
        more.append(f"ATR {cur}{_fmt(atr)} ({atr / price * 100:.1f}%)")
    if lv.get("trend"):
        more.append(tv(lang, lv["trend"]))
    if more:
        lines.append("      " + " · ".join(more))
    return lines


def _portfolio_lines(portfolios: list[dict], lang: str) -> list[str]:
    lines = []
    for p in portfolios:
        cur = p.get("currency_symbol", "")
        head = f"💼 {p['name']}: {cur}{_fmt(p['value'], 0)}"
        if _num(p.get("day_change")) is not None:
            head += f" · {t(lang, 'today')} {'+' if p['day_change'] >= 0 else '-'}{cur}{_fmt(abs(p['day_change']), 0)}"
            if _pct(p.get("day_change_pct")):
                head += f" ({_pct(p['day_change_pct'])})"
        lines.append(head)
        if _num(p.get("gain")) is not None:
            lines.append(f"   {t(lang, 'total_gain')} {'+' if p['gain'] >= 0 else '-'}{cur}{_fmt(abs(p['gain']), 0)}"
                         + (f" ({_pct(p.get('gain_pct'))})" if _pct(p.get("gain_pct")) else ""))
        for m in p.get("movers", []):
            lines.append(f"   {'▲' if m['change'] >= 0 else '▼'} {m['symbol']} {_pct(m['change_pct'])} "
                         f"({'+' if m['change'] >= 0 else '-'}{cur}{_fmt(abs(m['change']), 0)})")
    return lines


def _alert_lines(alerts: dict, lang: str) -> list[str]:
    lines = [f"🔔 {t(lang, 'your_alerts')}"]
    fired = alerts.get("fired") or []
    near = alerts.get("near") or []
    if fired:
        lines.append(f"   {t(lang, 'alerts_fired', n=len(fired))}:")
        for e in fired[:8]:
            lines.append(f"   • {e['symbol']} — {_one_line(e.get('message'), 120)}")
    if near:
        lines.append(f"   {t(lang, 'alerts_near')}:")
        for a in near[:8]:
            lines.append(f"   • {a['symbol']} {a['describe']} · {abs(a['distance_pct']):.1f}% away")
    if not fired and not near:
        lines.append(f"   {t(lang, 'alerts_quiet', n=alerts.get('active', 0))}")
    return lines


def _hot_lines(hot: dict, lang: str) -> list[str]:
    key = "hot_trade" if hot.get("area") == "trader" else "hot_invest"
    lines = [f"🔥 {t(lang, key)}"]
    for market, boards in hot.get("markets", {}).items():
        for b in boards:
            if not b["rows"]:
                continue
            head = b["title"] + (f" [{MARKET_NAMES.get(market, market)}]" if len(hot["markets"]) > 1 else "")
            lines.append(f"   {head}")
            for row in b["rows"]:
                lines.append(f"   • {row['symbol']} {_pct(row.get('change_percent')) or ''} — {_one_line(row.get('why'), 110)}")
    return lines if len(lines) > 1 else []


def _readings(technical: dict) -> str:
    """Indicator values only (no buy/sell verdict)."""
    indicators = (technical.get("details") or {}).get("indicators") or {}
    return " · ".join(f"{name.upper()} {_fmt(info.get('value'))}" for name, info in indicators.items() if _fmt(info.get("value")))


def _outlook_lines(results: list[dict], lang: str) -> list[str]:
    """The AI outlook of each stock, grouped (bullish / neutral / bearish)."""
    groups: dict[str, list[str]] = {"bullish": [], "neutral": [], "bearish": []}
    for r in results:
        direction = (r.get("dashboard") or {}).get("outlook")
        if direction in groups:
            groups[direction].append(r["symbol"])
    if not any(groups.values()):
        return []
    lines = ["", f"🧭 {t(lang, 'outlook')}"]
    for key, symbols in groups.items():
        word = tv(lang, key)
        lines.append(f"   {OUTLOOK_ICONS[key]} {word.capitalize() if lang == 'en' else word}: {', '.join(symbols) or '—'}")
    return lines


def _mover_lines(results: list[dict], lang: str) -> list[str]:
    """Facts about the user's own list: biggest moves and 52-week extremes."""
    moves = [(r["symbol"], _num((r.get("quote") or {}).get("change_percent"))) for r in results]
    moves = [m for m in moves if m[1] is not None]
    up = sorted((m for m in moves if m[1] > 0), key=lambda m: -m[1])[:3]
    down = sorted((m for m in moves if m[1] < 0), key=lambda m: m[1])[:3]
    near_hi, near_lo = [], []
    for r in results:
        price = _num((r.get("quote") or {}).get("price"))
        hi, lo = _num((r.get("extras") or {}).get("high_52w")), _num((r.get("extras") or {}).get("low_52w"))
        if price and hi and price >= hi * 0.97:
            near_hi.append(r["symbol"])
        if price and lo and price <= lo * 1.03:
            near_lo.append(r["symbol"])
    fmt = lambda ms: ", ".join(f"{s} {_pct(c)}" for s, c in ms) or "—"
    lines = [f"📊 {t(lang, 'movers')}", f"   ▲ {t(lang, 'up_most')}: {fmt(up)}", f"   ▼ {t(lang, 'down_most')}: {fmt(down)}"]
    if near_hi:
        lines.append(f"   ⤒ {t(lang, 'near_high')}: {', '.join(near_hi)}")
    if near_lo:
        lines.append(f"   ⤓ {t(lang, 'near_low')}: {', '.join(near_lo)}")
    return lines


def _fund_lines(funds: list[dict], lang: str) -> list[str]:
    lines = [f"💼 {t(lang, 'funds')}"]
    for f in funds:
        change = _pct(f.get("change_percent"))
        bits = [f"{t(lang, 'nav')} ₹{_fmt(f.get('nav'), 4 if (_num(f.get('nav')) or 0) < 100 else 2)}"
                + (f" ({change})" if change else "")]
        if _pct(f.get("return_1m")):
            bits.append(f"1M {_pct(f['return_1m'])}")
        if _pct(f.get("return_1y")):
            bits.append(f"1Y {_pct(f['return_1y'])}")
        lines.append(f"   • {_one_line(f.get('name'), 90)}")
        lines.append(f"     {' · '.join(bits)}")
        dip = f.get("lumpsum") or {}
        if dip.get("status") == "ok" and dip.get("level") in ("watch", "strong"):
            below = f"{-dip['below_high'] * 100:.1f}% below high"
            lines.append(f"     📉 {t(lang, 'dip_check')} {dip['met']}/{dip['total']} · {below}")
    return lines


def build_report(
    results: list[dict],
    prefs: ReportPrefs,
    lang: str = "en",
    overview: Optional[list[dict]] = None,
    now: Optional[datetime] = None,
    funds: Optional[list[dict]] = None,
    market_take: Optional[str] = None,
    ideas: Optional[list[dict]] = None,
    portfolios: Optional[list[dict]] = None,
    alerts: Optional[dict] = None,
    hot: Optional[list[dict]] = None,
) -> tuple[str, str]:
    """(title, body) for one language. Labels come from the built-in
    translations; free text stays as generated (see translate_report)."""
    lang = normalize_language(lang)
    label_lang = lang if has_builtin(lang) else "en"
    now = (now or datetime.now(ZoneInfo(prefs.timezone))).astimezone(ZoneInfo(prefs.timezone))
    markets = list(dict.fromkeys(r["market"] for r in results))
    multi = len(markets) > 1

    mode_label = t(label_lang, f"mode_{prefs.mode}") if prefs.mode in ("quick", "standard", "full", "specialist") else prefs.mode
    lines = [
        f"📊 {' + '.join(MARKET_NAMES.get(m, m) for m in markets)} · {t(label_lang, 'analysis', mode=mode_label)}",
        f"🕘 {now:%d %b %Y, %H:%M} {now.tzname()}",
    ]

    if "market" in prefs.sections and overview:
        lines += [""] + _market_lines(overview, label_lang)
        if market_take:
            lines.append(f"   🤖 {_one_line(market_take, 400)}")

    if "calls" in prefs.sections:
        lines += [""] + _mover_lines(results, label_lang) + _outlook_lines(results, label_lang)

    if "portfolio" in prefs.sections and portfolios:
        lines += [""] + _portfolio_lines(portfolios, label_lang)

    if "alerts" in prefs.sections and alerts:
        lines += [""] + _alert_lines(alerts, label_lang)

    for block in hot or []:
        if block.get("section") in prefs.sections:
            hot_lines = _hot_lines(block, label_lang)
            if hot_lines:
                lines += [""] + hot_lines

    if "funds" in prefs.sections and funds:
        lines += [""] + _fund_lines(funds, label_lang)

    for r in results:
        # Always at least the stock's name line, as Settings promises when no section is ticked.
        lines += [""] + _stock_block(r, prefs.sections_for(r["symbol"]), label_lang, multi)

    lines += ["", t(label_lang, "disclaimer")]
    return t(label_lang, "title"), "\n".join(lines)


# ---------------------------------------------------------- translation

_TRANSLATE_SYSTEM = (
    "You translate stock-market reports for a notification message. Translate every piece of "
    "English text into {language}. Keep unchanged: ticker symbols, company names, numbers, "
    "percentages, currency symbols, dates, emoji and the exact line breaks and indentation. "
    "Text already in {language} stays as is. Output only the translated report, nothing else."
)


def translate_report(text: str, lang: str, config) -> Optional[str]:
    """Translate free text with the configured LLM; None if unavailable.
    Sent in blocks so long reports fit the model's output budget."""
    from ..llm.channels import llm_configured

    if lang == "en" or not llm_configured(config):
        return None
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig

    try:
        backend = create_generation_backend(config, tier="fast")  # translation is a level-1 job
    except Exception as exc:
        logger.warning("Translation backend unavailable: %s", exc)
        return None

    system = _TRANSLATE_SYSTEM.format(language=language_name(lang))
    blocks, current = [], ""
    for para in text.split("\n\n"):
        if current and len(current) + len(para) > 1500:
            blocks.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        blocks.append(current)

    out = []
    for block in blocks:
        try:
            result = backend.generate(block, GenerationConfig(), system_prompt=system)
            translated = (result.text or "").strip()
            out.append(translated or block)
        except Exception as exc:
            logger.warning("Translation to %s failed: %s", lang, exc)
            return None
    return "\n\n".join(out)


def render_reports(
    results: list[dict], prefs: ReportPrefs, languages: Iterable[str], config=None,
    overview: Optional[list[dict]] = None, now: Optional[datetime] = None,
    funds: Optional[list[dict]] = None, market_take: Optional[str] = None,
    ideas: Optional[list[dict]] = None,
    portfolios: Optional[list[dict]] = None,
    alerts: Optional[dict] = None,
    hot: Optional[list[dict]] = None,
) -> dict[str, tuple[str, str]]:
    """language -> (title, body), translating free text when an LLM is set."""
    out = {}
    for lang in dict.fromkeys(normalize_language(x) for x in languages):
        title, body = build_report(results, prefs, lang, overview, now, funds=funds, market_take=market_take,
                                   ideas=ideas, portfolios=portfolios, alerts=alerts, hot=hot)
        if lang != "en":
            translated = translate_report(body, lang, config) if config is not None else None
            if translated:
                body = translated
                if not has_builtin(lang):
                    title = translate_report(title, lang, config) or title
            else:
                body += "\n" + t(lang if has_builtin(lang) else "en", "english_note")
        out[lang] = (title, body)
    return out


def market_review(overview: list[dict], results: list[dict], config) -> Optional[str]:
    """Two-sentence AI read of the day's market backdrop (English; the
    report translation step localizes it). None without an LLM."""
    from ..llm.channels import llm_configured

    if not overview or config is None or not llm_configured(config):
        return None
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig

    indices = "\n".join(
        f"- {i['name']}: {_fmt(i.get('price')) or '?'} ({_pct(i.get('change_percent')) or '?'})" for i in overview
    )
    outlooks = ", ".join(
        f"{r['symbol']}={(r.get('dashboard') or {}).get('outlook') or 'n/a'}" for r in results
    )
    try:
        result = create_generation_backend(config, tier="fast").generate(
            f"Index moves today:\n{indices}\n\nAI outlook on the watchlist: {outlooks}",
            GenerationConfig(max_tokens=200),
            system_prompt=guard_prompt(
                "You are a markets editor. In at most two short sentences, describe today's market "
                "backdrop for a retail investor and what it means for the watchlist, using only the "
                "numbers given. No bullet points, no disclaimers, no predictions stated as fact."
            ),
        )
        return " ".join((result.text or "").split()) or None
    except Exception as exc:
        logger.warning("Market review unavailable: %s", exc)
        return None
