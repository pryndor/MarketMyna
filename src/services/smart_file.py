"""The report file Smart messaging sends with its short message.

Not a copy of every section ticked for the message: the file always holds
the same core set, the figures that matter for each stock, rendered as a
PDF (to read) or an Excel workbook (to sort and filter):

  summary     tiles (stocks, bullish / neutral / bearish counts, best / worst today)
  market      index levels and the AI's read of the day
  readings    what the indicators show, bullish / neutral / bearish; never a
              buy / sell call (src/core/compliance.py)
  portfolio   value, today's change and total gain, when the schedule has one
  stocks      price, day, reading, valuation vs sector and the AI summary
  guide       how to read the report, term by term
  cards       one per stock: ranges, trend, RSI, risk, next results, the AI
              summary and valuation vs sector

Stock ideas, news, alerts and mutual funds stay in the message and the
report link. Nothing here calls the AI except the one-paragraph market read.
"""

from __future__ import annotations

import io
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..core.numbers import finite as _num

logger = logging.getLogger(__name__)

WORKERS = 6
# Per-stock data the file needs from collect_extras (src/services/analysis_run.py).
FILE_EXTRAS = {"valuation", "events"}
FILE_TYPES = {"pdf": "pdf", "xlsx": "xlsx"}
# Marks AI-reviewed stocks (plain text: the PDF font has no emoji).
AI_TAG = " · AI"
DISCLAIMER = "MarketMyna · Computed from market data; AI notes may be wrong. Not investment advice."


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list] = field(default_factory=list)
    note: str = ""
    # The columns the PDF shows when the page is too narrow for all (Excel keeps every one).
    pdf_columns: Optional[list[str]] = None


@dataclass
class Text:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class Tile:
    """A summary figure at the top of the report."""
    label: str
    value: str
    sub: str = ""
    tone: Optional[str] = None  # up | down | warn | accent


@dataclass
class StockCard:
    """One stock's details, following the ticked sections."""
    symbol: str
    name: str
    call: str
    price: str
    change: str
    facts: list[tuple[str, str]] = field(default_factory=list)
    # Groups of (label, text, tone) shown side by side: the AI's view, bull vs bear, the risk team.
    notes: list[list[tuple[str, str, Optional[str]]]] = field(default_factory=list)
    news: list[str] = field(default_factory=list)


@dataclass
class Document:
    title: str
    subtitle: str
    blocks: list = field(default_factory=list)
    highlights: list[Tile] = field(default_factory=list)
    cards: list[StockCard] = field(default_factory=list)
    # Shown in a box under the summary: what this report is and is not (general users).
    notice: str = ""


# ------------------------------------------------------------- formatting

def _fmt(value, digits: int = 2) -> str:
    v = _num(value)
    if v is None:
        return ""
    return f"{v:,.{digits}f}" if abs(v) >= 1 else f"{v:.4f}"


def _pct(value, signed: bool = True) -> str:
    v = _num(value)
    if v is None:
        return ""
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def _ratio_pct(value) -> str:
    """0.12 -> 12% (risk metrics and yields come as fractions)."""
    v = _num(value)
    return "" if v is None else f"{v * 100:.0f}%"


def _word(value) -> str:
    return str(value or "").replace("_", " ").strip().capitalize()


# ------------------------------------------------------------- building

def _extras(rows: list[dict]) -> dict:
    """symbol -> collect_extras() for the file's per-stock data (parallel)."""
    from .analysis_run import collect_extras

    good = [r for r in rows if "error" not in r]

    def one(r):
        try:
            return r["symbol"], collect_extras(r["symbol"], r["market"], FILE_EXTRAS)
        except Exception as exc:
            logger.warning("Extras for %s unavailable: %s", r["symbol"], exc)
            return r["symbol"], {}

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return dict(pool.map(one, good))


def _results_like(rows: list[dict]) -> list[dict]:
    """Smart rows in the shape the normal report helpers take."""
    return [{"symbol": r["symbol"], "market": r["market"],
             "quote": {"price": r.get("price"), "change_percent": r.get("change_percent")},
             "dashboard": {}} for r in rows if "error" not in r]


def _call(r: dict) -> str:
    """The indicators' reading (bullish / neutral / bearish), never a call."""
    from .smart_report import reading_label

    return reading_label(r) + (AI_TAG if r.get("ai") else "")


def _why(r: dict) -> str:
    return r.get("ai_summary") or ", ".join(r.get("reasons") or [])


def _valuation(r: dict, ex: dict) -> str:
    """Valuation against the sector median, as a comparison: an
    "undervalued / overvalued" verdict would be a call."""
    val = ex.get("valuation") or {}
    position = _num(val.get("position"))
    sector = val.get("sector") or "sector"
    if position:
        gap = (position - 1) * 100
        where = (f"in line with the {sector} median" if abs(gap) < 1 else
                 f"{abs(gap):.0f}% {'below' if gap < 0 else 'above'} the {sector} median")
        return f"Priced {where}"
    pe = _num(r.get("pe"))
    return f"P/E {pe:.1f}; no sector median to compare" if pe else ""


def _stock_table(rows: list[dict], extras: dict) -> Table:
    from .report import CURRENCY_SYMBOLS, MARKET_NAMES

    multi = len({r["market"] for r in rows}) > 1
    cols = (["Stock", "Name"] + (["Market"] if multi else []) + ["Indicators", "Price", "Day",
            "Valuation vs sector", "What stands out"])
    table = Table("Stocks at a glance", cols, note=(
        "Indicators: how trend, momentum, the price's place in its range and valuation lean today. Marked AI: "
        "an AI summary of the figures; otherwise what the data flags. A description, not a recommendation."))
    for r in rows:
        if "error" in r:
            table.rows.append([r["symbol"], f"no data: {str(r['error'])[:60]}"] + [""] * (len(cols) - 2))
            continue
        cur = CURRENCY_SYMBOLS.get(r["market"], "")
        table.rows.append([r["symbol"], r.get("name") or ""] + ([MARKET_NAMES.get(r["market"], r["market"])] if multi else [])
                          + [_call(r), f"{cur}{_fmt(r.get('price'))}", _pct(r.get("change_percent")),
                             _valuation(r, extras.get(r["symbol"]) or {}), _why(r)])
    return table


def _band_position(r: dict) -> str:
    """Where the price sits in its normal (20-day) range: 0% bottom, 100% top."""
    low, high, price = _num(r.get("normal_low")), _num(r.get("normal_high")), _num(r.get("price"))
    if None in (low, high, price) or high <= low:
        return ""
    pos = (price - low) / (high - low) * 100
    return f"{pos:.0f}%" + (" (above it)" if pos > 100 else " (below it)" if pos < 0 else "")


def _rsi_word(rsi) -> str:
    v = _num(rsi)
    if v is None:
        return ""
    return f"{v:.0f}" + (" (fast rise)" if v >= 70 else " (fast fall)" if v <= 30 else "")


def _range_position(r: dict) -> str:
    """Where today's price sits between the 52-week low (0%) and high (100%)."""
    low, high, price = _num(r.get("low_52w")), _num(r.get("high_52w")), _num(r.get("price"))
    if None in (low, high, price) or high <= low:
        return ""
    return f"{(price - low) / (high - low) * 100:.0f}% of range"


def _card(r: dict, ex: dict) -> StockCard:
    """The important figures for one stock, the same for every report."""
    from .report import CURRENCY_SYMBOLS

    cur = CURRENCY_SYMBOLS.get(r["market"], "")
    facts: list[tuple[str, str]] = []

    def add(label: str, value) -> None:
        if value not in (None, "", "–", " ()"):
            facts.append((label, str(value)))

    add("Normal range", f"{_fmt(r.get('normal_low'))}–{_fmt(r.get('normal_high'))}")
    add("Position in normal range", _band_position(r))
    add("Expected 1-week range", f"{_fmt(r.get('week_low'))}–{_fmt(r.get('week_high'))}")
    add("52-week low", _fmt(r.get("low_52w")))
    add("52-week high", _fmt(r.get("high_52w")))
    add("In 52-week range", _range_position(r))
    add("Trend", _word(r.get("trend")))
    add("RSI (14)", _rsi_word(r.get("rsi")))
    add("P/E", _fmt(r.get("pe"), 1))
    add("Volatility (yearly)", _ratio_pct(r.get("volatility")))
    add("Max drawdown", _ratio_pct(r.get("max_drawdown")))
    add("Average daily move (ATR)", _fmt(r.get("atr")))
    ev = ex.get("events") or {}
    add("Next results", str(ev.get("earnings_date") or "")[:10])
    add("Ex-dividend", str(ev.get("ex_dividend_date") or "")[:10])

    summary = []
    if _why(r):
        label = "AI summary of the figures" if r.get("ai") else "What stands out"
        summary.append((label, _why(r), "accent"))
    if _valuation(r, ex):
        summary.append(("Valuation vs sector", _valuation(r, ex), "accent"))
    notes: list = [summary] if summary else []
    return StockCard(symbol=r["symbol"], name=r.get("name") or "", call=_call(r),
                     price=f"{cur}{_fmt(r.get('price'))}", change=_pct(r.get("change_percent")),
                     facts=facts, notes=notes)


def _highlights(rows: list[dict], good: list[dict]) -> list[Tile]:
    ai = sum(1 for r in good if r.get("ai"))
    tiles = [Tile("Stocks", str(len(rows)), f"{ai} reviewed by the AI" if ai else "computed readings", "accent")]
    if good:
        counts = {k: sum(1 for r in good if r.get("reading") == k) for k in ("positive", "mixed", "negative")}
        tiles += [Tile("Bullish", str(counts["positive"]), "indicators lean up", "up"),
                  Tile("Neutral", str(counts["mixed"]), "indicators split", "warn"),
                  Tile("Bearish", str(counts["negative"]), "indicators lean down", "down")]
    moves = [r for r in good if _num(r.get("change_percent")) is not None]
    if moves:
        best = max(moves, key=lambda r: r["change_percent"])
        worst = min(moves, key=lambda r: r["change_percent"])
        tiles.append(Tile("Best today", _pct(best["change_percent"]), best["symbol"], "up" if best["change_percent"] >= 0 else "down"))
        tiles.append(Tile("Worst today", _pct(worst["change_percent"]), worst["symbol"], "down" if worst["change_percent"] < 0 else "up"))
    return tiles


def _guide() -> Table:
    """"How to read this report": every term the file uses, in plain words."""
    terms = [
        ("Indicators", "▲ Bullish, ◆ Neutral or ▼ Bearish: how most of trend, momentum (RSI), "
                       "the price's place in its normal range and valuation lean today. It describes the data "
                       "and is not a recommendation to buy, sell or hold."),
        ("Valuation vs sector", "How the stock's P/E, P/B and P/S compare with the median of its sector among "
                                "the market's largest companies. A lower or higher price than peers can have "
                                "good reasons; it is a comparison, not a verdict."),
    ]
    terms += [
        ("Normal range", "Where the price usually trades: the 20-day Bollinger band. Outside it means an unusually "
                         "large move for recent weeks."),
        ("1-week range", "Where about 2 of 3 weeks end, from recent volatility. Not a forecast or a target."),
        ("52-week range", "The lowest and highest price of the past year; 0% of range = at the low, 100% = at the high."),
        ("Trend", "Uptrend: price above its 50- and 200-day averages; downtrend: below both; sideways: neither."),
        ("RSI", "Momentum from 0 to 100. Above 70 the price rose fast recently, below 30 it fell fast."),
        ("Volatility", "How much the price swings in a year; 25% means a typical yearly move of about a quarter of "
                       "the price."),
        ("Max drawdown", "The deepest fall from a high during the past year."),
        ("AI summary of the figures", "Written by an AI model from the figures above. It can be wrong."),
    ]
    return Table("How to read this report", ["Term", "What it means"], [list(t) for t in terms])


def build_document(rows: list[dict], prefs, config, now: datetime, title: str) -> Document:
    """The report file: the same core set every time (see the module doc)."""
    from .smart_report import READING_LABELS, READING_NOTE, reading_label

    good = [r for r in rows if "error" not in r]
    ai_count = sum(1 for r in good if r.get("ai"))
    doc = Document(title, f"{now:%d %b %Y, %H:%M %Z}".strip() + f" · {len(rows)} stocks"
                          + (f" · {ai_count} reviewed by the AI" if ai_count else ""),
                   notice=READING_NOTE)
    results = _results_like(rows)

    try:
        from .analysis_run import market_overview
        from .report import market_review

        overview = market_overview(r["market"] for r in good)
        if overview:
            take = market_review(overview, results, config)
            doc.blocks.append(Table("Market overview", ["Index", "Level", "Day"],
                                    [[i["name"], _fmt(i.get("price")), _pct(i.get("change_percent"))]
                                     for i in overview], note=take or ""))
    except Exception as exc:
        logger.warning("Market overview unavailable for the report file: %s", exc)

    if good:
        groups = {k: [r["symbol"] + (AI_TAG if r.get("ai") else "") for r in good if r.get("reading") == k]
                  for k in READING_LABELS}
        doc.blocks.append(Table("What the indicators show", ["Indicators", "Stocks", "Count"],
                                [[reading_label({"reading": k}), ", ".join(v) or "—", len(v)] for k, v in groups.items()],
                                note="Grouped by how most indicators (trend, momentum, place in the range, valuation) "
                                     "lean today. This sorts the data; it does not say what to do."))

    if getattr(prefs, "portfolios", None):
        try:
            from .analysis_run import portfolio_snapshots

            ports = portfolio_snapshots(prefs.portfolios, results, config)
            if ports:
                doc.blocks.append(Table("Your portfolio", ["Portfolio", "Value", "Today", "Today %", "Total gain", "Gain %", "Moved most"], [
                    [p["name"], f"{p.get('currency_symbol', '')}{_fmt(p.get('value'), 0)}", _fmt(p.get("day_change"), 0),
                     _pct(p.get("day_change_pct")), _fmt(p.get("gain"), 0), _pct(p.get("gain_pct")),
                     ", ".join(f"{m['symbol']} {_pct(m.get('change_pct'))}" for m in p.get("movers", []))]
                    for p in ports]))
        except Exception as exc:
            logger.warning("Portfolio unavailable for the report file: %s", exc)

    extras = _extras(rows)
    doc.blocks.append(_stock_table(rows, extras))

    if good:
        doc.blocks.append(_guide())
    doc.cards = [_card(r, extras.get(r["symbol"]) or {}) for r in good]
    doc.highlights = _highlights(rows, good)
    return doc


# ------------------------------------------------------------- rendering

def to_pdf(doc: Document) -> bytes:
    """A4 landscape: title band, summary tiles, the sections, a card per stock."""
    from .smart_pdf import render

    return render(doc, DISCLAIMER)


def _cell_value(value):
    """'₹1,312.40' -> 1312.4, '+1.2%' -> (0.012, percent format), so Excel
    sorts and filters numbers as numbers; anything else stays as it is."""
    from .report import CURRENCY_SYMBOLS

    if not isinstance(value, str) or not any(ch.isdigit() for ch in value):  # also keeps "INF", "NAN" as text
        return value, None
    text = value.replace(",", "")
    for sign in sorted(filter(None, CURRENCY_SYMBOLS.values()), key=len, reverse=True):
        text = text.removeprefix(sign)
    percent = text.endswith("%")
    try:
        number = float(text.rstrip("%"))
    except ValueError:
        return value, None
    if percent:
        return number / 100, "0.0%" if "." in text else "0%"
    return number, "#,##0.00" if "." in text else "#,##0"


def to_xlsx(doc: Document) -> bytes:
    """A styled workbook: a Summary sheet (title, summary figures, the
    report-wide tables), "Stocks" to sort and filter, "Stock details" with
    every ticked detail and the AI's notes per stock, and a sheet for any
    other long table. Numbers are stored as numbers; gains are green,
    losses red, calls coloured."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    from .smart_pdf import tone_of

    fill = lambda hex_: PatternFill("solid", fgColor=hex_)  # noqa: E731
    tone_font = {"up": "0B7A52", "down": "C02F2F", "warn": "9A6408", "accent": "1F3A8A"}
    tone_fill = {"up": "E3F4EC", "down": "FBE7E7", "warn": "FDF3DC", "accent": "E8EDF8"}
    thin = Side(style="thin", color="DCE0E8")
    grid = Border(bottom=thin, top=thin, left=thin, right=thin)
    head_font, head_fill = Font(bold=True, color="FFFFFF", size=10), fill("0F2A5C")
    top_left = Alignment(vertical="top", wrap_text=True)
    signed_pct = '[Color10]+0.0%;[Red]-0.0%;0.0%'

    wb = Workbook()

    def banner(ws, width: int) -> None:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=width)
        ws.cell(1, 1, doc.title).font = Font(bold=True, size=16, color="FFFFFF")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=width)
        ws.cell(2, 1, doc.subtitle).font = Font(italic=True, size=9, color="D6DEEE")
        for row in (1, 2):
            for col in range(1, width + 1):
                ws.cell(row, col).fill = head_fill
        ws.row_dimensions[1].height = 30
        ws.cell(1, 1).alignment = Alignment(vertical="center", indent=1)
        ws.cell(2, 1).alignment = Alignment(vertical="center", indent=1)

    def style_value(cell, value, column: str) -> None:
        number, number_format = _cell_value(value)
        cell.value = number
        cell.border = grid
        cell.alignment = Alignment(vertical="top", wrap_text=isinstance(number, str) and len(number) > 40,
                                   horizontal="right" if number_format else None)
        tone = tone_of(value) if isinstance(value, str) else None
        if number_format:
            signed = isinstance(value, str) and value[:1] in "+-−" and number_format.endswith("%")
            cell.number_format = signed_pct if signed else number_format
        elif tone and column in ("Call", "Result", "Indicators"):
            cell.font = Font(bold=True, color=tone_font[tone])
            cell.fill = fill(tone_fill[tone])
            cell.alignment = Alignment(horizontal="center", vertical="top")
        elif tone in ("up", "down"):
            cell.font = Font(color=tone_font[tone])

    def put_table(ws, table: Table, row: int, zebra: bool = True) -> int:
        for j, name in enumerate(table.columns, start=1):
            c = ws.cell(row, j, name)
            c.font, c.fill, c.border = head_font, head_fill, grid
            c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 20
        for i, values in enumerate(table.rows, start=1):
            for j, (name, value) in enumerate(zip(table.columns, values), start=1):
                c = ws.cell(row + i, j)
                style_value(c, value, name)
                if j == 1:
                    c.font = Font(bold=True, color="0F2A5C")
                if zebra and i % 2 == 0 and c.fill.fgColor.rgb in (None, "00000000"):
                    c.fill = fill("F5F7FA")
        row += len(table.rows) + 1
        if table.note:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=max(len(table.columns), 1))
            c = ws.cell(row, 1, table.note)
            c.font, c.alignment = Font(italic=True, size=8, color="6B7280"), Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[row].height = 14 * (1 + len(table.note) // 140)
            row += 1
        return row

    def section_title(ws, row: int, title: str, width: int) -> int:
        c = ws.cell(row, 1, title)
        c.font = Font(bold=True, size=12, color="0F2A5C")
        for col in range(1, max(width, 1) + 1):
            ws.cell(row, col).border = Border(bottom=Side(style="medium", color="1F3A8A"))
        return row + 1

    def fit(ws, first_row: int, cap: int = 60, wide: Optional[set] = None) -> None:
        for i, col in enumerate(ws.iter_cols(min_row=first_row, max_row=min(ws.max_row, 400)), start=1):
            longest = max((len(str(c.value)) for c in col if c.value is not None and not
                           (isinstance(c.value, str) and len(c.value) > 140)), default=8)
            width = 55 if wide and i in wide else min(max(longest + 3, 9), cap)
            ws.column_dimensions[get_column_letter(i)].width = width

    def page_setup(ws) -> None:
        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.sheet_view.showGridLines = False

    # ---- Summary
    summary = wb.active
    summary.title = "Summary"
    small = [b for b in doc.blocks if not (isinstance(b, Table) and (b.title.startswith("Stocks") or len(b.rows) > 8))]
    width = max([len(doc.highlights)] + [len(b.columns) for b in small if isinstance(b, Table)] + [6])
    banner(summary, width)
    row = 4
    if doc.notice:
        summary.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
        c = summary.cell(row, 1, doc.notice)
        c.font = Font(bold=True, size=10, color="0F2A5C")
        c.fill = fill("EEF3FB")
        c.alignment = Alignment(wrap_text=True, vertical="center", indent=1)
        c.border = Border(left=Side(style="thick", color="1F3A8A"))
        summary.row_dimensions[row].height = 48
        row += 2
    if doc.highlights:
        for j, t in enumerate(doc.highlights, start=1):
            color = tone_font.get(t.tone, "0F2A5C")
            for k, (value, font) in enumerate(((t.label.upper(), Font(bold=True, size=8, color="6B7280")),
                                               (t.value, Font(bold=True, size=18, color=color)),
                                               (t.sub, Font(size=8, color="6B7280")))):
                c = summary.cell(row + k, j, value)
                c.font, c.fill = font, fill("F7F9FC")
                c.alignment = Alignment(horizontal="left", vertical="center", indent=1)
                c.border = Border(left=Side(style="thick", color=color), top=thin if k == 0 else None,
                                  bottom=thin if k == 2 else None, right=thin)
        summary.row_dimensions[row + 1].height = 28
        row += 4
    for b in small:
        row = section_title(summary, row, b.title, len(b.columns) if isinstance(b, Table) else width)
        if isinstance(b, Table):
            row = put_table(summary, b, row)
        else:
            for line in b.lines:
                summary.cell(row, 1, line).alignment = Alignment(wrap_text=True)
                row += 1
        row += 1
    c = summary.cell(row, 1, DISCLAIMER)
    c.font = Font(italic=True, size=8, color="6B7280")
    fit(summary, 4, cap=48)
    page_setup(summary)

    used = {"Summary"}

    def sheet(title: str):
        name = title[:31].replace("/", "-")
        while name in used:
            name = name[:28] + "_2"
        used.add(name)
        ws = wb.create_sheet(name)
        page_setup(ws)
        return ws

    # ---- big tables (the stocks at a glance, a long track record or ideas list)
    for b in doc.blocks:
        if b in small:
            continue
        ws = sheet("Stocks" if b.title.startswith("Stocks") else b.title)
        end = put_table(ws, b, 1)
        ws.freeze_panes = "B2"
        if b.rows:
            ws.auto_filter.ref = f"A1:{get_column_letter(len(b.columns))}{len(b.rows) + 1}"
        fit(ws, 1)
        if b.note and end:
            ws.row_dimensions[end - 1].height = 28

    # ---- Stock details: one row per stock with every ticked detail and the AI's notes
    if doc.cards:
        labels: list[str] = []
        for card in doc.cards:
            labels += [label for label, _ in card.facts if label not in labels]
        # The AI's reasoning and the computed reasons share one column.
        same = {"Why (computed)": "AI view"}
        note_labels: list[str] = []
        for card in doc.cards:
            for group in card.notes:
                note_labels += [same.get(label, label) for label, _, _ in group
                                if same.get(label, label) not in note_labels]
        news = any(card.news for card in doc.cards)
        columns = ["Stock", "Name", "Call", "Price", "Day"] + labels + note_labels + (["News"] if news else [])
        rows = []
        for card in doc.cards:
            facts = dict(card.facts)
            notes = {same.get(label, label): text for group in card.notes for label, text, _ in group}
            rows.append([card.symbol, card.name, card.call, card.price, card.change]
                        + [facts.get(label, "") for label in labels]
                        + [notes.get(label, "") for label in note_labels]
                        + (["\n".join(card.news)] if news else []))
        ws = sheet("Stock details")
        put_table(ws, Table("Stock details", columns, rows), 1)
        ws.freeze_panes = "B2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
        long_cols = {i for i, name in enumerate(columns, start=1) if name in note_labels or name == "News"}
        fit(ws, 1, wide=long_cols)
        for i in range(2, len(rows) + 2):
            for j in long_cols:
                ws.cell(i, j).alignment = top_left
            if long_cols:
                longest = max(len(str(ws.cell(i, j).value or "")) for j in long_cols)
                ws.row_dimensions[i].height = min(max(15, 15 * (longest // 55 + 1)), 400)

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def report_file(rows: list[dict], prefs, config, now: datetime, title: str) -> Optional[tuple[str, bytes]]:
    """(filename, bytes) in the format the user picked, or None for "none"
    or when building fails (the short message still goes out)."""
    kind = FILE_TYPES.get(getattr(prefs, "smart_file", "pdf"))
    if not kind or not rows:
        return None
    try:
        doc = build_document(rows, prefs, config, now, title)
        data = to_pdf(doc) if kind == "pdf" else to_xlsx(doc)
    except Exception:
        logger.exception("Smart report file could not be built")
        return None
    return f"MarketMyna-report-{now:%Y-%m-%d}.{kind}", data
