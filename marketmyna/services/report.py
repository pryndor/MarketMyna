"""Scheduled-report content: which sections a user receives, in which
language, on which channel - and the builder that renders it.

Plain text with emoji (no Markdown/HTML) so Telegram, email, ntfy,
Slack, WeChat... all render the same message.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

from ..core.compliance import guard_prompt, outlook
from ..core.numbers import finite as _num
from .report_i18n import has_builtin, label_overrides, language_name, normalize_language, t, tv

logger = logging.getLogger(__name__)

# (id, English label, description, on by default in its area)
SECTIONS: list[tuple[str, str, str, bool]] = [
    ("market", "Market overview", "Is the market up or down today, which sectors are gaining or losing strength, and what it means for the sectors you hold", True),
    ("calls", "Bullish / Neutral / Bearish list", "One-glance view of each stock from its fundamentals and price "
     "trend, with the figures behind it - no buy/sell call", True),
    ("portfolio", "Your portfolio", "Portfolio value, today's change, total gain, the holdings that moved it most, "
     "and each mutual fund's NAV and 1-month / 1-year returns (plus funds you watch)", True),
    ("alerts", "Your alerts", "Price alerts that fired since the last report, and active ones close to their trigger", True),
    ("hot_trade", "Hot for trading", "Today's biggest moves on heavy trading, unusual activity and breakouts in your markets", True),
    ("hot_invest", "Trending for investors", "Quality stocks on a dip, earnings momentum and what mutual funds added", False),
    ("ideas", "Stocks matching your screen", "Stocks outside your watchlist in an uptrend with sound figures, in your "
     "markets and categories, with an AI note on what stands out and what to watch - no buy call", True),
    ("price", "Price & range", "Price, day change, 52-week range and where the price sits in it", True),
    ("levels", "Trading range", "Normal range (20-day band), expected 1-week range and average daily move (ATR)", True),
    ("ai", "AI summary", "The AI's read of news, momentum and risks behind each stock's Bullish / Neutral / "
     "Bearish view, and where they point the other way - no buy/sell call", True),
    ("technical", "Technical readings", "Indicator values such as RSI and MACD, without a verdict", True),
    ("indicators", "Technical indicators", "RSI, MACD, moving averages, Bollinger bands (values)", False),
    ("fundamentals", "Fundamentals", "Company quality: score, ROE, financial health, revenue growth, dividend, "
     "and the P/E (how it compares with peers is in Valuation vs sector)", False),
    ("risk", "Risk", "Each stock's risk level, how much it swings in a year and its worst fall from a high", True),
    ("analysts", "Analyst ratings", "Broker consensus of third-party analysts, as bullish / neutral / bearish", False),
    ("events", "Upcoming events", "Next earnings date and ex-dividend date", False),
    ("news", "News headlines", "Latest headlines for each stock", False),
    ("valuation", "Valuation vs sector", "P/E, price/book and price/sales against the median of the stock's sector", False),
]

# Which side of the app a section is for (absent = both). The Scheduler shows
# each area only its own sections and keeps the other area's choices as saved.
SECTION_AREAS: dict[str, str] = {
    "portfolio": "investor", "hot_invest": "investor", "ideas": "investor",
    "fundamentals": "investor", "analysts": "investor", "valuation": "investor",
    "alerts": "trader", "hot_trade": "trader", "levels": "trader", "indicators": "trader",
}


def section_catalog() -> list[tuple[str, str, str, bool]]:
    """(id, label, description, default) as the Scheduler should show them."""
    return list(SECTIONS)


SECTION_IDS = [s[0] for s in SECTIONS]
DEFAULT_SECTIONS = [s[0] for s in SECTIONS if s[3]]
# Report-wide sections built once per run, not per stock.
REPORT_WIDE = {"market", "calls", "portfolio", "alerts", "hot_trade", "hot_invest", "ideas"}
# Retired section ids -> the one that took them over. "funds" (Mutual funds)
# merged into "portfolio" on 2026-10-27; saved schedules keep working.
RENAMED_SECTIONS = {"funds": "portfolio"}

MARKET_NAMES = {
    "us": "US", "india": "India", "china_a": "China A", "hong_kong": "Hong Kong", "crypto": "Crypto", "global": "Global",
}
CURRENCY_SYMBOLS = {"india": "₹", "us": "$", "china_a": "¥", "hong_kong": "HK$", "crypto": "$", "global": ""}


def clean_sections(values: Optional[Iterable[str]]) -> list[str]:
    """Known section ids only, in catalogue order."""
    wanted = {v.strip().lower() for v in (values or []) if v and v.strip()}
    wanted = {RENAMED_SECTIONS.get(v, v) for v in wanted}
    return [s for s in SECTION_IDS if s in wanted]


# Smart messaging: stocks the AI looks at per report (most interesting first);
# the rest get data and rules only. 5 (was 10) halves the AI calls per report.
SMART_AI_TOP = 5


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
    # AMFI scheme codes for the "portfolio" section's funds (held, picked or watched)
    funds: list[str] = field(default_factory=list)
    # Portfolio names for the "portfolio" section (empty = all)
    portfolios: list[str] = field(default_factory=list)
    # "ideas" section: market to scan, categories to focus on, how many
    ideas_market: str = "india"
    ideas_markets: list[str] = field(default_factory=list)  # several (Pro); empty = ideas_market
    ideas_categories: list[str] = field(default_factory=list)
    ideas_count: int = 3
    # "hot_invest" section: markets to scan (empty = the markets of the run's stocks)
    hot_invest_markets: list[str] = field(default_factory=list)
    # Smart messaging: short top-N message + link to the full report
    smart: bool = False
    smart_top_n: int = 5
    smart_ai_top: int = SMART_AI_TOP  # AI analyses only the N most interesting stocks (0 = none)
    smart_email_full: bool = True
    # The report file sent with the short message: "pdf", "xlsx" or "none",
    # built from the ticked sections, to these channels (marketmyna/services/smart_file.py).
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


def _crisp(text: Optional[str], limit: int = 280) -> str:
    """Whole sentences up to `limit` characters (never cut mid-sentence
    unless the first sentence alone is longer)."""
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(out) + len(sentence) + 1 > limit:
            break
        out = f"{out} {sentence}".strip()
    return out or _one_line(text, limit)


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


# Average index move (%) inside which a market reads as flat.
FLAT_BAND = 0.3
MOOD_ICONS = {"up": "▲", "down": "▼", "flat": "◆", "mixed": "◆"}


def market_mood(indices: list[dict]) -> Optional[str]:
    """One market's mood from its indices, by rule: an average move beyond
    +/-FLAT_BAND is up/down, else flat (mixed when the indices disagree).
    None when no index has a day change."""
    moves = [v for i in indices if (v := _num(i.get("change_percent"))) is not None]
    if not moves:
        return None
    avg = sum(moves) / len(moves)
    if avg > FLAT_BAND:
        return "up"
    if avg < -FLAT_BAND:
        return "down"
    return "mixed" if any(v > 0 for v in moves) and any(v < 0 for v in moves) else "flat"


GAINING = ("leading", "improving")  # rotation quadrants with momentum building
SECTORS_SHOWN = 3


def _sector_lines(view: dict, lang: str) -> list[str]:
    """Sectors gaining / losing strength against the index, and how the
    sectors the report's stocks belong to stand."""
    ranked = view.get("sectors") or []  # strongest first (services/rotation)
    gaining = [n for n, q in ranked if q in GAINING][:SECTORS_SHOWN]
    losing = [n for n, q in reversed(ranked) if q not in GAINING][:SECTORS_SHOWN]
    lines = []
    if gaining:
        lines.append(f"   {t(lang, 'sectors_gaining')}: {', '.join(gaining)}")
    if losing:
        lines.append(f"   {t(lang, 'sectors_losing')}: {', '.join(losing)}")
    yours = view.get("yours") or []
    if yours:
        lines.append(f"   {t(lang, 'your_sectors')}: "
                     + " · ".join(f"{n} {'▲' if q in GAINING else '▼'}" for n, q, _ in yours))
    return lines


def _market_lines(overview: list[dict], lang: str, sectors: Optional[dict] = None) -> list[str]:
    """Per market: its mood and index day changes on one line, then the
    sector read (when there is one)."""
    if not overview:
        return []
    lines = [f"{t(lang, 'market_overview')}"]
    by_market: dict[str, list[dict]] = {}
    for idx in overview:
        by_market.setdefault(idx.get("market") or "", []).append(idx)
    for market, indices in by_market.items():
        mood = market_mood(indices)
        head = " · ".join(f"{i['name']} {_pct(i.get('change_percent')) or '—'}" for i in indices)
        if mood:
            verdict = t(lang, f"mood_{mood}")
            verdict = f"{MARKET_NAMES.get(market, market)} {verdict}" if market else verdict.capitalize()
            head = f"{MOOD_ICONS[mood]} {verdict} · {head}"
        lines.append(f"   {head}")
        lines += _sector_lines((sectors or {}).get(market) or {}, lang)
    return lines


def _stock_block(r: dict, sections: list[str], lang: str, multi_market: bool) -> list[str]:
    dash = r.get("dashboard") or {}
    quote = r.get("quote") or {}
    extras = r.get("extras") or {}
    cur = CURRENCY_SYMBOLS.get(r["market"], "")
    from .outlook import EMOJI
    from .outlook import outlook as figures_view

    # The stock's Bullish / Neutral / Bearish view: from its fundamentals and trend,
    # else the AI's outlook; never a call, target or stop.
    view = figures_view(extras["facts"])["view"] if extras.get("facts") else dash.get("outlook")
    icon = EMOJI.get(view, "") if view else ""

    title = f"{icon} {r['symbol']}" if icon else r["symbol"]
    if r.get("name") and r["name"].upper() != r["symbol"].upper():
        title += f" · {r['name']}"
    if view:
        word = tv(lang, view)
        title += f" — {word.upper() if lang == 'en' else word}"
    if multi_market:
        title += f" [{MARKET_NAMES.get(r['market'], r['market'])}]"
    lines = [title]

    if "price" in sections:  # the same for investors and traders; targets and stops live in Trade levels
        price = _fmt(quote.get("price"))
        if price:
            change = _pct(quote.get("change_percent"))
            lines.append(f"   {t(lang, 'price')} {cur}{price}" + (f" ({change})" if change else ""))
        lo, hi = _fmt(extras.get("low_52w")), _fmt(extras.get("high_52w"))
        if lo and hi:
            where = ""
            p, l, h = _num(quote.get("price")), _num(extras.get("low_52w")), _num(extras.get("high_52w"))
            if p and l is not None and h and h > l:
                where = f" · {t(lang, 'range_position', pct=f'{min(max((p - l) / (h - l), 0), 1) * 100:.0f}')}"
            lines.append(f"   {t(lang, 'range_52w')}: {cur}{lo} – {cur}{hi}{where}")

    lv = extras.get("levels") or {}
    if "levels" in sections and lv:
        lines += _level_lines(lv, cur, lang)

    if "ai" in sections:
        if dash.get("analysis_summary"):
            lines.append(f"   {t(lang, 'ai_summary')}: {_crisp(dash['analysis_summary'])}")
        elif r.get("no_ai"):
            lines.append(f"   {t(lang, 'ai_with_pro')}")
        elif not r.get("ok"):
            lines.append(f"   {t(lang, 'ai_unavailable')}: {_one_line(r.get('error'), 160)}")

    technical = next((o for o in dash.get("opinions", []) if o.get("agent_name") == "technical"), None)
    if "technical" in sections and technical:
        # The commentary is written under the no-calls rule here (agents.TechnicalAgent); one
        # that slips a verdict word in anyway gives way to the plain indicator values.
        summary = technical.get("summary") or ""
        text = (_crisp(summary, 200) if summary and not _VERDICT_WORDS.search(summary) else "") or _readings(technical)
        if text:
            lines.append(f"   {t(lang, 'technical')}: {text}")

    if "indicators" in sections and technical:
        indicators = (technical.get("details") or {}).get("indicators") or {}
        bits = []
        for name, info in indicators.items():
            value = _fmt(info.get("value"))
            if value:
                bits.append(f"{name.upper()} {value}")
        if bits:
            lines.append(f"   {t(lang, 'indicators')}: " + " · ".join(bits))

    fund = extras.get("fundamentals")
    if "fundamentals" in sections and fund:
        # Company quality only: whether the price is high or low against peers is
        # Valuation vs sector's job (real sector medians), so no verdict here.
        bits = [f"{t(lang, 'score')} {fund.get('quality_score', fund.get('overall_score', '—'))}/100"]
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
        lines.append(f"   {t(lang, 'fundamentals')}: " + " · ".join(bits))

    if "risk" in sections and dash.get("risk_level"):
        # One line in plain words: level, yearly swing (volatility), worst fall from a high (max drawdown).
        level = tv(lang, dash["risk_level"])
        bits = [level.capitalize() if lang == "en" else level]
        risk = next((o for o in dash.get("opinions", []) if o.get("agent_name") == "risk"), None)
        details = (risk or {}).get("details") or {}
        if _num(details.get("volatility")) is not None:
            bits.append(t(lang, "swings_year", pct=f"{_num(details['volatility']) * 100:.0f}"))
        if _num(details.get("max_drawdown")) is not None:
            bits.append(t(lang, "fell_from_high", pct=f"{abs(_num(details['max_drawdown'])) * 100:.0f}"))
        lines.append(f"   {t(lang, 'risk')}: " + " · ".join(bits))

    analysts = extras.get("analysts")
    if "analysts" in sections and analysts and analysts.get("recommendation"):
        # A direction, without the brokers' price target.
        word = outlook(analysts["recommendation"]) or analysts["recommendation"]
        text = f"   {t(lang, 'consensus_src')}: {tv(lang, word)}"
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
            lines.append(f"   {t(lang, 'upcoming')}: " + " · ".join(bits))

    news = extras.get("news") or []
    news_view = next((o for o in dash.get("opinions", []) if o.get("agent_name") == "news"), None)
    if "news" in sections and news:
        header = f"   {t(lang, 'news')}"
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
        lines.append(f"   {t(lang, 'valuation_vs_sector')}: {' · '.join(bits)} → {val['position']:.2f}× ({word})")
    return lines


def _level_lines(lv: dict, cur: str, lang: str) -> list[str]:
    """Trading range from daily bars (marketmyna/services/smart_report.compute_snapshot):
    ranges only, no support / resistance / target / stop to act on."""
    price = _num(lv.get("price"))
    atr = _num(lv.get("atr"))
    bits = []
    lo, hi = _fmt(lv.get("normal_low")), _fmt(lv.get("normal_high"))
    if lo and hi:
        bits.append(f"{t(lang, 'normal_range')} {cur}{lo} – {cur}{hi}")
    lines = ["   " + " · ".join(bits)] if bits else []
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


def _portfolio_lines(portfolios: list[dict], lang: str, funds: Optional[list[dict]] = None) -> list[str]:
    """Each portfolio's value, today's change, total gain and top movers, then
    the NAV and returns of every fund it holds; funds picked or watched but not
    held come last under "Funds you watch"."""
    by_code = {str(f.get("code") or f.get("name")): f for f in funds or []}
    held: set[str] = set()
    lines = []
    for p in portfolios:
        cur = p.get("currency_symbol", "")
        head = f"{p['name']}: {cur}{_fmt(p['value'], 0)}"
        if _num(p.get("day_change")) is not None:
            head += f" · {t(lang, 'today')} {'+' if p['day_change'] >= 0 else '-'}{cur}{_fmt(abs(p['day_change']), 0)}"
            if _pct(p.get("day_change_pct")):
                head += f" ({_pct(p['day_change_pct'])})"
        lines.append(head)
        if _num(p.get("gain")) is not None:
            lines.append(f"   {t(lang, 'total_gain')} {'+' if p['gain'] >= 0 else '-'}{cur}{_fmt(abs(p['gain']), 0)}"
                         + (f" ({_pct(p.get('gain_pct'))})" if _pct(p.get("gain_pct")) else ""))
        for m in p.get("movers", []):
            lines.append(f"   {'▲' if m['change'] >= 0 else '▼'} {m.get('name') or m['symbol']} {_pct(m['change_pct'])} "
                         f"({'+' if m['change'] >= 0 else '-'}{cur}{_fmt(abs(m['change']), 0)})")
        own = [by_code[c] for c in p.get("fund_codes", []) if c in by_code]
        held.update(p.get("fund_codes", []))
        lines += _fund_lines(own, lang)
    watched = [f for code, f in by_code.items() if code not in held]
    if watched:
        if lines:
            lines.append("")
        lines.append(f"{t(lang, 'funds_watched')}")
        lines += _fund_lines(watched, lang)
    return lines


def _alert_lines(alerts: dict, lang: str) -> list[str]:
    lines = [f"{t(lang, 'your_alerts')}"]
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


# "Trending for investors" for a general user: what each list holds, in
# plain facts (admins and the owner keep the names in marketmyna/services/hot_stocks.py).
INVEST_TITLES = {
    "quality_dip": ("Strong fundamentals, 10-30% below the high", "ROE over 15%, debt below equity, earnings growing"),
    "earnings": ("Fast-growing earnings and sales", "EPS growth 20-300%, sales growth over 10%, within 15% of the high"),
    "value_turning": ("P/E below its sector, rising off the low", "P/E under 85% of the sector median, profitable and growing"),
    "compounders": ("High returns, low debt, near the high", "ROE over 18%, operating margin over 15%, within 10% of the high"),
    "income": ("Dividend payers below their high", "Yield over 2.5%, payout under 80%, 10% or more below the high"),
    "funds_adding": ("Most bought by mutual funds last month", "Fund schemes that newly bought or added to the stock"),
    "crypto_dips": ("Large coins 30% or more below the high", "The most-traded coins, furthest from their 52-week high"),
    "crypto_strong": ("Large coins within 10% of the high", "The most-traded coins, closest to their 52-week high"),
}


def _invest_figures(row: dict) -> str:
    """Pro: the stock's figures on one line, for a quick first check."""
    def p(key, label, signed=False):
        v = _num(row.get(key))
        return f"{label} {v:+.0f}%" if v is not None and signed else f"{label} {v:.0f}%" if v is not None else None

    bits = [p("roe", "ROE"),
            f"Debt/Eq {row['debt_equity']:.1f}" if _num(row.get("debt_equity")) is not None else None,
            p("earnings_growth", "EPS", True), p("revenue_growth", "Sales", True),
            p("operating_margin", "Margin")]
    pe, rel = _num(row.get("pe")), _num(row.get("pe_vs_sector"))
    if pe and pe > 0:
        bits.append(f"P/E {pe:.0f}" + (f" ({rel:.1f}× sector)" if rel else ""))
    if _num(row.get("dividend_yield")):
        bits.append(f"Yield {row['dividend_yield']:.1f}%")
    hi, lo = _num(row.get("from_high")), _num(row.get("from_low"))
    if hi is not None:
        bits.append(f"{abs(hi):.0f}% below high" if hi < -0.5 else "at the high")
    if lo is not None:
        bits.append(f"{lo:.0f}% above low")
    return " · ".join(b for b in bits if b)


def _hot_lines(hot: dict, lang: str) -> list[str]:
    key = "hot_trade" if hot.get("area") == "trader" else "hot_invest"
    invest = key == "hot_invest"
    detail = invest and hot.get("detail")
    lines = [f"{t(lang, key)}"]
    for market, boards in hot.get("markets", {}).items():
        cur = CURRENCY_SYMBOLS.get(market, "")
        for b in boards:
            if not b["rows"]:
                continue
            title, rule = INVEST_TITLES.get(b["key"], (b["title"], b.get("description") or "")) if invest else (b["title"], "")
            head = title + (f" [{MARKET_NAMES.get(market, market)}]" if len(hot["markets"]) > 1 else "")
            lines.append(f"   {head}")
            if rule:
                lines.append(f"     ({_one_line(rule, 120)})")
            for row in b["rows"]:
                name = f" · {_one_line(row['name'], 32)}" if invest and row.get("name") else ""
                if detail:
                    price = _fmt(row.get("price"))
                    sector = f" · {row['sector']}" if row.get("sector") else ""
                    lines.append(f"   • {row['symbol']}{name}{sector} — {cur}{price or '—'} "
                                 f"{_pct(row.get('change_percent')) or ''}".rstrip())
                    figures = _invest_figures(row) if b["key"] not in ("crypto_dips", "crypto_strong") else ""
                    lines.append(f"     {figures or _one_line(row.get('why'), 140)}")
                    if b["key"] == "funds_adding":
                        lines.append(f"     {_one_line(row.get('why'), 140)}")
                else:
                    lines.append(f"   • {row['symbol']}{name} {_pct(row.get('change_percent')) or ''} — "
                                 f"{_one_line(row.get('why'), 110)}")
    if len(lines) == 1:
        return []
    if invest:
        lines.append(f"   {t(lang, 'invest_note_detail' if detail else 'invest_note')}")
    return lines


_VERDICT_WORDS = re.compile(r"\b(bullish|bearish|buy|sell|accumulate|undervalued|overvalued|target|stop loss)\b", re.I)


def _readings(technical: dict) -> str:
    """Indicator values only (no buy/sell verdict)."""
    indicators = (technical.get("details") or {}).get("indicators") or {}
    return " · ".join(f"{name.upper()} {_fmt(info.get('value'))}" for name, info in indicators.items() if _fmt(info.get("value")))


def _outlook_lines(results: list[dict], lang: str) -> list[str]:
    """The Bullish / Neutral / Bearish list: from each stock's fundamentals and
    trend, with the figures behind it (marketmyna/services/outlook.py); a stock
    without those figures uses the AI's outlook. Never a buy / hold / sell call."""
    from .outlook import EMOJI, why
    from .outlook import outlook as figures_view

    groups: dict[str, list[tuple[str, str]]] = {"bullish": [], "neutral": [], "bearish": []}
    missing = []
    for r in results:
        f = (r.get("extras") or {}).get("facts")
        if f:
            o = figures_view(f)
            groups[o["view"]].append((r["symbol"], why(o)))
            continue
        ai_view = (r.get("dashboard") or {}).get("outlook")
        if ai_view in groups:
            groups[ai_view].append((r["symbol"], ""))
        else:
            missing.append(r["symbol"])
    lines = [f"{t(lang, 'outlook')}"]
    for view, items in groups.items():
        word = tv(lang, view)
        lines.append(f"   {EMOJI[view]} {word.capitalize() if lang == 'en' else word}: "
                     f"{', '.join(s for s, _ in items) or '—'}")
        for symbol, reason in items:
            if reason:
                lines.append(f"      • {symbol}: {_one_line(reason, 200)}")
    if missing:
        lines.append(f"   {t(lang, 'incomplete')}: {', '.join(missing)}")
    lines.append(f"   {t(lang, 'outlook_note')}")
    return lines


def _fund_lines(funds: list[dict], lang: str) -> list[str]:
    """One fund per bullet: NAV, day change, 1M / 1Y returns and the dip check."""
    lines = []
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
            lines.append(f"     {t(lang, 'dip_check')} {dip['met']}/{dip['total']} · {below}")
    return lines


def _idea_lines(ideas: list[dict], prefs: ReportPrefs, lang: str) -> list[str]:
    """Each idea: price, its figures, why it was chosen and what to watch. A
    general user's header and note say it is a screen, not a recommendation."""
    markets = list(dict.fromkeys(i.get("market") for i in ideas if i.get("market"))) or [prefs.ideas_market]
    scope = ", ".join(MARKET_NAMES.get(m, m) for m in markets)
    if prefs.ideas_categories:
        scope += " · " + ", ".join(prefs.ideas_categories)
    lines = [f"{t(lang, 'ideas_public')} ({scope})"]
    for idea in ideas:
        cur = CURRENCY_SYMBOLS.get(idea.get("market"), "")
        change = _pct(idea.get("change_percent"))
        head = f"   • {idea['symbol']}"
        if idea.get("name") and idea["name"].upper() != idea["symbol"].upper():
            head += f" · {_one_line(idea['name'], 50)}"
        price = _fmt(idea.get("price"))
        if price:
            head += f" — {cur}{price}" + (f" ({change})" if change else "")
        lines.append(head)
        high, low, price_v = (_num(idea.get(k)) for k in ("high_52w", "low_52w", "price"))
        figures = _invest_figures({**(idea.get("figures") or {}),
                                   "from_high": (price_v / high - 1) * 100 if price_v and high else None,
                                   "from_low": (price_v / low - 1) * 100 if price_v and low else None})
        if figures:
            lines.append(f"     {figures}")
        if idea.get("reason"):
            lines.append(f"     {'AI: ' if idea.get('ai') else ''}{_one_line(idea['reason'], 220)}")
        if idea.get("watch"):
            lines.append(f"     {t(lang, 'watch')}: {_one_line(idea['watch'], 200)}")
        if idea.get("invalidator"):
            lines.append(f"     {t(lang, 'rethink')}: {_one_line(idea['invalidator'], 200)}")
        flags = [f["label"] for f in (idea.get("risk") or {}).get("flags", [])[:2]]
        if flags:
            lines.append(f"     {t(lang, 'flags')}: {'; '.join(flags)}")
    lines.append(f"   {t(lang, 'ideas_note')}")
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
    sectors: Optional[dict] = None,
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
        f"{' + '.join(MARKET_NAMES.get(m, m) for m in markets)} · {t(label_lang, 'analysis', mode=mode_label)}",
        f"{now:%d %b %Y, %H:%M} {now.tzname()}",
    ]

    if "market" in prefs.sections and overview:
        lines += [""] + _market_lines(overview, label_lang, sectors)
        if market_take:
            lines.append(f"   AI: {_one_line(market_take, 320)}")

    if "calls" in prefs.sections:
        lines += [""] + _outlook_lines(results, label_lang)

    if "portfolio" in prefs.sections and (portfolios or funds):
        lines += [""] + _portfolio_lines(portfolios or [], label_lang, funds)

    if "alerts" in prefs.sections and alerts:
        lines += [""] + _alert_lines(alerts, label_lang)

    for block in hot or []:
        if block.get("section") in prefs.sections:
            hot_lines = _hot_lines(block, label_lang)
            if hot_lines:
                lines += [""] + hot_lines

    if "ideas" in prefs.sections and ideas:
        lines += [""] + _idea_lines(ideas, prefs, label_lang)

    for r in results:
        # A stock gets its own block only when a per-stock section is ticked for it.
        own = prefs.sections_for(r["symbol"])
        if any(sec not in REPORT_WIDE for sec in own):
            lines += [""] + _stock_block(r, own, label_lang, multi)

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


# Built-in languages already have their labels; only the English free text
# (AI commentary, headlines, rule-based sentences) is translated, one sentence
# at a time with each sentence cached, so the same sentence in another
# account's report costs nothing. AI-only languages still go whole.

# English words that the Latin-script built-in languages (es, fr, de, pt, id)
# don't use themselves: two of them mark a sentence as English.
_EN_WORDS = frozenset(
    "the and of to is for with from are its has this that were by at after over into than be it "
    "their which while about below above more less has have been".split())
_LATIN_RUN = re.compile(r"[A-Za-z0-9\"'(][A-Za-z0-9 ,;:'’\"()%$₹€£&+/.!?-]*")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_TRANSLATE_LIST_SYSTEM = (
    "You translate short pieces of a stock-market report into {language}. You get a JSON list of "
    "strings; reply ONLY with a JSON list of the same length, each item translated. Keep unchanged: "
    "ticker symbols, company names, numbers, percentages, currency symbols, dates and anything in "
    "{{curly braces}}."
)


def _json_list(text: str) -> Optional[list]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    try:
        value = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, list) else None


def _english_sentences(text: str) -> list[str]:
    found = []
    for line in text.split("\n"):
        for run in _LATIN_RUN.findall(line):
            for sentence in _SENTENCE_END.split(run.strip()):
                words = re.findall(r"[a-z]+", sentence.lower())
                if len(words) >= 4 and sum(w in _EN_WORDS for w in words) >= 2 \
                        or len(words) >= 5 and sum(w in _EN_WORDS for w in words) >= 1:
                    found.append(sentence.strip())
    return list(dict.fromkeys(found))


def translate_sentences(sentences: list[str], lang: str, config) -> Optional[dict[str, str]]:
    """sentence -> translation, from the shared cache where it can; the rest
    in one AI call per 40. None when the AI is unavailable or answers badly."""
    from ..llm.backend_factory import create_generation_backend
    from ..llm.channels import llm_configured
    from ..llm.protocol import GenerationConfig
    from ..llm.store import LLMStore

    if not sentences:
        return {}
    if not llm_configured(config):
        return None
    system = _TRANSLATE_LIST_SYSTEM.format(language=language_name(lang))
    store = LLMStore(config)
    out, todo = {}, []
    for sentence in sentences:
        hit = store.get(store.key(f"translate:{lang}", system, sentence, None, None))
        if hit:
            out[sentence] = hit[0]
        else:
            todo.append(sentence)
    try:
        backend = create_generation_backend(config, tier="fast")
        for i in range(0, len(todo), 40):
            batch = todo[i:i + 40]
            reply = backend.generate(json.dumps(batch, ensure_ascii=False), GenerationConfig(), system_prompt=system)
            items = _json_list(reply.text or "")
            if not isinstance(items, list) or len(items) != len(batch):
                logger.warning("Translation to %s: %s items back for %d", lang,
                               len(items) if isinstance(items, list) else "no list", len(batch))
                return None
            for sentence, done in zip(batch, items):
                done = str(done or "").strip() or sentence
                out[sentence] = done
                store.put(store.key(f"translate:{lang}", system, sentence, None, None), done, reply.model or "")
    except Exception as exc:
        logger.warning("Translation to %s failed: %s", lang, exc)
        return None
    return out


def _pending_labels(lang: str, config) -> dict[str, str]:
    """AI translations of the labels with no built-in one yet (cached, so a
    language's labels cost one call per cache period)."""
    from .report_i18n import _EN, PENDING_TRANSLATION

    keys = [k for k in sorted(PENDING_TRANSLATION) if k in _EN]
    done = translate_sentences([_EN[k] for k in keys], lang, config) or {}
    labels = {}
    for k in keys:
        text = done.get(_EN[k])
        # A label whose {placeholders} did not survive stays English.
        if text and set(re.findall(r"{\w+}", text)) == set(re.findall(r"{\w+}", _EN[k])):
            labels[k] = text
    return labels


def translate_free_text(body: str, lang: str, config) -> Optional[str]:
    """The report with its English sentences translated; None on failure."""
    done = translate_sentences(_english_sentences(body), lang, config)
    if done is None:
        return None
    for sentence in sorted(done, key=len, reverse=True):  # longer first: no partial overlaps
        body = body.replace(sentence, done[sentence])
    return body


def render_reports(
    results: list[dict], prefs: ReportPrefs, languages: Iterable[str], config=None,
    overview: Optional[list[dict]] = None, now: Optional[datetime] = None,
    funds: Optional[list[dict]] = None, market_take: Optional[str] = None,
    ideas: Optional[list[dict]] = None,
    portfolios: Optional[list[dict]] = None,
    alerts: Optional[dict] = None,
    hot: Optional[list[dict]] = None,
    sectors: Optional[dict] = None,
) -> dict[str, tuple[str, str]]:
    """language -> (title, body), translating free text when an LLM is set."""
    out = {}
    for lang in dict.fromkeys(normalize_language(x) for x in languages):
        sentence_wise = lang != "en" and has_builtin(lang) and config is not None
        labels = _pending_labels(lang, config) if sentence_wise else {}
        with label_overrides(labels):
            title, body = build_report(results, prefs, lang, overview, now, funds=funds, market_take=market_take,
                                       sectors=sectors, ideas=ideas, portfolios=portfolios, alerts=alerts, hot=hot)
        if sentence_wise:
            translated = translate_free_text(body, lang, config)
            if translated is not None:
                out[lang] = (title, translated)
                continue
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


def market_review(overview: list[dict], results: list[dict], config, sectors: Optional[dict] = None) -> Optional[str]:
    """Two short sentences on the market's tone and what it means for the
    sectors the report's stocks are in - no single stocks (English; the report
    translation step localizes it). None without an LLM."""
    from ..llm.channels import llm_configured

    if not overview or config is None or not llm_configured(config):
        return None
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig

    facts = ["Index moves today:"] + [
        f"- {i['name']}: {_pct(i.get('change_percent')) or '?'}" for i in overview
    ]
    for market, view in (sectors or {}).items():
        name = MARKET_NAMES.get(market, market)
        facts.append(f"{name} sectors, 4-week momentum against the index (strongest first): "
                     + ", ".join(f"{n} ({q})" for n, q in view.get("sectors") or []))
        if view.get("yours"):
            facts.append(f"Sectors this investor holds in {name}: "
                         + ", ".join(f"{n} ({k} stocks)" for n, _, k in view["yours"]))
    # One comment per markets + the investor's sectors + hour, shared by every
    # report with the same view: index numbers move within the hour, the tone holds.
    yours = sorted(n for view in (sectors or {}).values() for n, _, _ in view.get("yours") or [])
    scope = "|".join(["market_review", ",".join(sorted(sectors or {})), ",".join(i["name"] for i in overview),
                      ",".join(yours), datetime.now().strftime("%Y-%m-%d %H")])
    try:
        result = create_generation_backend(config, tier="fast").generate(
            "\n".join(facts),
            # Room for a reasoning model's thinking; the prompt keeps the answer short.
            GenerationConfig(max_tokens=1000, cache_scope=scope),
            system_prompt=guard_prompt(
                "You are a markets editor writing for a retail investor. In two short sentences "
                "(at most 45 words in all): first, the overall tone today (bullish, bearish or mixed) "
                "and which sectors are carrying or dragging it; second, what that means for the "
                "sectors this investor holds. Do not repeat index numbers and do not name single "
                "stocks. Use only the facts given. No buy or sell advice, no bullet points, no "
                "disclaimers, no predictions stated as fact."
            ),
        )
        return " ".join((result.text or "").split()) or None
    except Exception as exc:
        logger.warning("Market review unavailable: %s", exc)
        return None
