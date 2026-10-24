"""PDF layout for the Smart messaging report file (src/services/smart_file.py).

Drawn with PyMuPDF directly rather than through its HTML Story, whose
tables size themselves to their content: here every table fills the page
width with measured columns, numbers line up on the right, and headers
repeat when a table runs onto the next page.

A4 landscape. Page one opens with a title band and summary tiles; then the
report-wide sections, the stock table, and one card per stock with the
details the user ticked. Every page has a footer with the page number.

Text is Helvetica; characters it lacks (₹, Chinese names, Devanagari) fall
back to MuPDF's built-in Noto / Droid fonts, one run at a time.
"""

from __future__ import annotations

import re
from functools import lru_cache

PAGE_W, PAGE_H = 842.0, 595.0  # A4 landscape, points
MARGIN = 32.0
CONTENT_W = PAGE_W - 2 * MARGIN
FOOTER_H = 26.0
BOTTOM = PAGE_H - MARGIN - FOOTER_H + 10

INK = (0.06, 0.08, 0.13)
MUTED = (0.42, 0.45, 0.52)
NAVY = (0.06, 0.16, 0.36)
ACCENT = (0.12, 0.23, 0.54)
LINE = (0.86, 0.88, 0.92)
ZEBRA = (0.965, 0.972, 0.984)
CARD_BG = (0.985, 0.988, 0.995)
WHITE = (1, 1, 1)
UP = (0.04, 0.48, 0.32)
DOWN = (0.75, 0.18, 0.18)
WARN = (0.72, 0.48, 0.05)
TONES = {"up": UP, "down": DOWN, "warn": WARN, "accent": ACCENT, None: INK, "": INK}

_SIGNED = re.compile(r"^[+\-−]\s?[\d.,]")
_NUMERIC = re.compile(r"^[^\w\s]{0,3}\$?[+\-−]?[\d.,]+\s?(%|×|pts)?$|^[\d.,]+–[\d.,]+$")


@lru_cache(maxsize=None)
def _fonts(bold: bool):
    import fitz

    main = fitz.Font("hebo" if bold else "helv")
    fallbacks = []
    for make in (lambda: fitz.Font(script=0), lambda: fitz.Font("cjk"), lambda: fitz.Font(script=9)):
        try:
            fallbacks.append(make())
        except Exception:
            pass
    return [main] + fallbacks


def _runs(text: str, bold: bool):
    """(font, text) runs: each character in the first font that has it."""
    fonts = _fonts(bold)
    runs: list = []
    for ch in text:
        font = next((f for f in fonts if f.has_glyph(ord(ch))), fonts[0])
        if runs and runs[-1][0] is font:
            runs[-1][1] += ch
        else:
            runs.append([font, ch])
    return runs


def text_width(text: str, size: float, bold: bool = False) -> float:
    return sum(font.text_length(part, fontsize=size) for font, part in _runs(text, bold))


def wrap(text: str, width: float, size: float, bold: bool = False) -> list[str]:
    """Lines no wider than `width`; long words are broken where they must be."""
    lines: list[str] = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split():
            candidate = f"{line} {word}" if line else word
            if text_width(candidate, size, bold) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            while text_width(word, size, bold) > width and len(word) > 1:
                cut = len(word)
                while cut > 1 and text_width(word[:cut], size, bold) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines or [""]


def tone_of(value: str):
    """Green for a signed gain, red for a signed loss, the call colours."""
    v = str(value).strip()
    word = v.split(" · ")[0].upper().lstrip("▲◆▼ ")
    if word in ("BUY", "STRONG BUY", "RIGHT", "MOSTLY POSITIVE"):
        return "up"
    if word in ("SELL", "STRONG SELL", "WRONG", "MOSTLY NEGATIVE"):
        return "down"
    if word in ("HOLD", "MIXED"):
        return "warn"
    if _SIGNED.match(v):
        return "down" if v[0] in "-−" else "up"
    return None


class Canvas:
    def __init__(self, title: str, subtitle: str):
        import fitz

        self.doc = fitz.open()
        self.title, self.subtitle = title, subtitle
        self.page = None
        self.y = 0.0
        self.new_page(first=True)

    # ---------------------------------------------------------- primitives

    def new_page(self, first: bool = False) -> None:
        self.page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        if first:
            self._band()
        else:
            self.text(MARGIN, MARGIN + 8, self.title, 8, bold=True, color=MUTED)
            self.page.draw_line((MARGIN, MARGIN + 13), (PAGE_W - MARGIN, MARGIN + 13), color=LINE, width=0.6)
            self.y = MARGIN + 26

    def ensure(self, height: float) -> bool:
        """Start a new page unless `height` fits; True when it did."""
        if self.y + height > BOTTOM:
            self.new_page()
            return True
        return False

    def text(self, x: float, baseline: float, text: str, size: float, bold: bool = False, color=INK,
             align: str = "left", width: float = 0.0) -> None:
        import fitz

        if not text:
            return
        if align != "left":
            w = text_width(text, size, bold)
            x += (width - w) if align == "right" else (width - w) / 2
        writer = fitz.TextWriter(self.page.rect)
        for font, part in _runs(text, bold):
            writer.append((x, baseline), part, font=font, fontsize=size)
            x += font.text_length(part, fontsize=size)
        writer.write_text(self.page, color=color)

    def rect(self, x, y, w, h, fill=None, color=None, radius=None, width: float = 0.6) -> None:
        import fitz

        r = fitz.Rect(x, y, x + w, y + h)
        if radius:
            self.page.draw_rect(r, color=color, fill=fill, width=width, radius=radius)
        else:
            self.page.draw_rect(r, color=color, fill=fill, width=width)

    def badge(self, x: float, baseline: float, label: str, tone, size: float = 7.0) -> float:
        """A filled pill with white text; returns its width."""
        w = text_width(label, size, True) + 8
        self.rect(x, baseline - size - 1.5, w, size + 5, fill=TONES.get(tone, ACCENT), radius=0.25)
        self.text(x + 4, baseline + 0.5, label, size, bold=True, color=WHITE)
        return w

    def paragraph(self, x: float, text: str, width: float, size: float = 8.0, color=INK,
                  bold: bool = False, leading: float = 1.35) -> None:
        for line in wrap(text, width, size, bold):
            self.ensure(size * leading)
            self.y += size * leading
            self.text(x, self.y - size * 0.3, line, size, bold=bold, color=color)

    # ---------------------------------------------------------- blocks

    def _band(self) -> None:
        self.rect(0, 0, PAGE_W, 74, fill=NAVY)
        self.rect(0, 74, PAGE_W, 3, fill=ACCENT)
        self.text(MARGIN, 36, self.title, 19, bold=True, color=WHITE)
        self.text(MARGIN, 56, self.subtitle, 9, color=(0.78, 0.83, 0.92))
        self.text(MARGIN, 36, "MarketMyna", 11, bold=True, color=WHITE, align="right", width=CONTENT_W)
        self.text(MARGIN, 52, "Smart report", 8, color=(0.78, 0.83, 0.92), align="right", width=CONTENT_W)
        self.y = 92

    def tiles(self, tiles) -> None:
        if not tiles:
            return
        gap, h = 10.0, 50.0
        w = (CONTENT_W - gap * (len(tiles) - 1)) / len(tiles)
        for i, t in enumerate(tiles):
            x = MARGIN + i * (w + gap)
            self.rect(x, self.y, w, h, fill=CARD_BG, color=LINE, radius=0.08)
            self.rect(x, self.y + 6, 3, h - 12, fill=TONES.get(t.tone, ACCENT))
            self.text(x + 12, self.y + 15, t.label.upper(), 6.5, bold=True, color=MUTED)
            self.text(x + 12, self.y + 33, t.value, 16, bold=True, color=TONES.get(t.tone, INK) if t.tone else INK)
            if t.sub:
                self.text(x + 12, self.y + 44, wrap(t.sub, w - 18, 6.5)[0], 6.5, color=MUTED)
        self.y += h + 6

    def notice(self, text: str) -> None:
        """A highlighted box: what the report is and is not."""
        lines = wrap(text, CONTENT_W - 120, 8.5)
        h = len(lines) * 12 + 18
        self.ensure(h + 8)
        self.y += 4
        self.rect(MARGIN, self.y, CONTENT_W, h, fill=(0.93, 0.95, 0.99), color=(0.78, 0.84, 0.95), radius=0.06)
        self.rect(MARGIN, self.y, 4, h, fill=ACCENT)
        self.text(MARGIN + 14, self.y + 16, "PLEASE NOTE", 7.5, bold=True, color=ACCENT)
        for k, line in enumerate(lines):
            self.text(MARGIN + 100, self.y + 16 + k * 12, line, 8.5, color=INK)
        self.y += h + 4

    def heading(self, title: str, caption: str = "") -> None:
        self.ensure(60)
        self.y += 16
        self.text(MARGIN, self.y, title, 12, bold=True, color=NAVY)
        if caption:
            self.text(MARGIN, self.y, caption, 7.5, color=MUTED, align="right", width=CONTENT_W)
        self.y += 5
        self.page.draw_line((MARGIN, self.y), (MARGIN + 36, self.y), color=ACCENT, width=2)
        self.page.draw_line((MARGIN + 36, self.y), (PAGE_W - MARGIN, self.y), color=LINE, width=0.6)
        self.y += 6

    def table(self, columns: list[str], rows: list[list], note: str = "", size: float = 7.5) -> None:
        pad = 4.0
        cells = [[str(v) if v is not None else "" for v in row] for row in rows]
        numeric = [bool(col_vals) and all(_NUMERIC.match(v) for v in col_vals)
                   for col_vals in ([r[i] for r in cells if i < len(r) and r[i]] for i in range(len(columns)))]
        badge_cols = {i for i, c in enumerate(columns) if c in ("Call", "Result", "Indicators")}
        widths = self._widths(columns, cells, size, pad, numeric, badge_cols)
        while widths is None and size > 5.5:  # too many columns: a smaller font before squeezing words
            size -= 0.5
            widths = self._widths(columns, cells, size, pad, numeric, badge_cols)
        if widths is None:
            widths = self._widths(columns, cells, size, pad, numeric, badge_cols, force=True)
        table_w = sum(widths)

        def header() -> None:
            h = max(len(wrap(c, widths[i] - 2 * pad, size, True)) for i, c in enumerate(columns)) * size * 1.25 + 2 * pad
            self.rect(MARGIN, self.y, table_w, h, fill=NAVY)
            x = MARGIN
            for i, c in enumerate(columns):
                for k, line in enumerate(wrap(c, widths[i] - 2 * pad, size, True)):
                    self.text(x + pad, self.y + pad + size * (1 + 1.25 * k) - 1, line, size, bold=True, color=WHITE,
                              align="right" if numeric[i] else "left", width=widths[i] - 2 * pad)
                x += widths[i]
            self.y += h

        self.ensure(40)
        header()
        for n, row in enumerate(cells):
            wrapped = [wrap(row[i] if i < len(row) else "", widths[i] - 2 * pad, size, i == 0)
                       for i in range(len(columns))]
            h = max(1 if i in badge_cols else len(w) for i, w in enumerate(wrapped)) * size * 1.3 + 2 * pad
            # The last row keeps the note under it on the same page.
            tail = len(wrap(note, CONTENT_W, 7)) * 7 * 1.35 + 2 if note and n == len(cells) - 1 else 0
            if self.ensure(h + tail):
                header()
            if n % 2:
                self.rect(MARGIN, self.y, table_w, h, fill=ZEBRA)
            x = MARGIN
            for i, lines in enumerate(wrapped):
                value = row[i] if i < len(row) else ""
                tone = tone_of(value)
                if i in badge_cols and tone and value:
                    self.badge(x + pad, self.y + pad + size, value, tone, size - 0.5)
                else:
                    for k, line in enumerate(lines):
                        self.text(x + pad, self.y + pad + size * (1 + 1.3 * k) - 1, line, size,
                                  bold=i == 0, color=TONES[tone] if tone and len(lines) == 1 else INK,
                                  align="right" if numeric[i] else "left", width=widths[i] - 2 * pad)
                x += widths[i]
            self.page.draw_line((MARGIN, self.y + h), (MARGIN + table_w, self.y + h), color=LINE, width=0.4)
            self.y += h
        if note:
            self.y += 2
            self.paragraph(MARGIN, note, CONTENT_W, size=7, color=MUTED)

    @staticmethod
    def _widths(columns, cells, size, pad, numeric, badge_cols, force: bool = False):
        """Column widths that never break a number, a badge or a word: the
        natural width of each column, long text capped; spare room goes to
        the text columns. None when the columns cannot fit at this size
        (the caller tries a smaller font), unless `force`."""
        natural, floor = [], []
        for i, c in enumerate(columns):
            values = [r[i] for r in cells if i < len(r) and r[i]]
            if i in badge_cols:
                longest = max([text_width(v, size - 0.5, True) + 8 for v in values] + [text_width(c, size, True)])
            else:
                longest = max([text_width(v, size, i == 0) for v in values] + [text_width(c, size, True)])
            words = max([text_width(w, size, i == 0) for v in values for w in v.split()] +
                        [text_width(w, size, True) for w in c.split()] + [0])
            natural.append(min(longest, 260) + 2 * pad + 1)
            # Numbers and badges keep their full width; text may wrap down to its longest word.
            floor.append(natural[-1] if numeric[i] or i in badge_cols else min(natural[-1], words + 2 * pad + 1))
        total = sum(natural)
        if total <= CONTENT_W:
            texty = [i for i, w in enumerate(natural) if w > 90 and not numeric[i]]
            if not texty:  # a small table of figures: keep it compact, not stretched across the page
                target = min(CONTENT_W, max(total * 1.35, CONTENT_W * 0.45))
                return [w * target / total for w in natural]
            spare = CONTENT_W - total
            return [w + (spare / len(texty) if i in texty else 0) for i, w in enumerate(natural)]
        if sum(floor) > CONTENT_W and not force:
            return None
        squeeze = (total - CONTENT_W) / max(sum(w - f for w, f in zip(natural, floor)), 1)
        widths = [w - (w - f) * min(squeeze, 1) for w, f in zip(natural, floor)]
        scale = CONTENT_W / sum(widths) if sum(widths) > CONTENT_W else 1
        return [w * scale for w in widths]

    def lines(self, lines: list[str]) -> None:
        for line in lines:
            self.paragraph(MARGIN, f"•  {line}", CONTENT_W, size=8)

    def card(self, card) -> None:
        """One stock: header strip, a grid of facts, then the AI's notes side by side."""
        inner = CONTENT_W - 24
        cols = 6
        cell_w = inner / cols
        fact_rows = (len(card.facts) + cols - 1) // cols
        est = 34 + fact_rows * 26 + sum(
            max(len(wrap(t, inner / len(g) - 10, 7.5)) for _, t, _ in g) * 10.2 + 18 for g in card.notes
        ) + (len(card.news) * 11 + 16 if card.news else 0)
        self.ensure(min(est, BOTTOM - MARGIN - 40) + 12)
        top = self.y + 6
        # header strip
        self.rect(MARGIN, top, CONTENT_W, 26, fill=(0.93, 0.95, 0.98), color=LINE, radius=0.12)
        x = MARGIN + 12
        self.text(x, top + 17, card.symbol, 11, bold=True, color=NAVY)
        x += text_width(card.symbol, 11, True) + 8
        if card.name and card.name.upper() != card.symbol.upper():
            name = wrap(card.name, 260, 8.5)[0]
            self.text(x, top + 17, name, 8.5, color=MUTED)
            x += text_width(name, 8.5) + 10
        if card.call:
            self.badge(x, top + 16.5, card.call, tone_of(card.call) or "accent")
        right = card.price + (f"   {card.change}" if card.change else "")
        if right.strip():
            self.text(MARGIN, top + 17, card.change, 9, bold=True, color=TONES[tone_of(card.change)],
                      align="right", width=CONTENT_W - 12)
            self.text(MARGIN, top + 17, card.price, 10, bold=True, color=INK, align="right",
                      width=CONTENT_W - 12 - (text_width(card.change, 9, True) + 10 if card.change else 0))
        self.y = top + 30
        # facts grid
        for k in range(fact_rows):
            self.ensure(26)
            for j, (label, value) in enumerate(card.facts[k * cols:(k + 1) * cols]):
                fx = MARGIN + 12 + j * cell_w
                self.text(fx, self.y + 10, label.upper(), 6, bold=True, color=MUTED)
                self.text(fx, self.y + 21, wrap(value, cell_w - 8, 8.5, True)[0], 8.5, bold=True,
                          color=TONES[tone_of(value)] if tone_of(value) in ("up", "down") else INK)
            self.y += 26
        # AI notes: each group's views side by side
        for group in card.notes:
            w = inner / len(group)
            wrapped = [wrap(text, w - 10, 7.5) for _, text, _ in group]
            self.ensure(30)
            self.y += 6
            self.page.draw_line((MARGIN + 12, self.y), (PAGE_W - MARGIN - 12, self.y), color=LINE, width=0.4)
            start = self.y + 4
            for j, (label, _, tone) in enumerate(group):
                self.text(MARGIN + 12 + j * w, start + 8, label.upper(), 6.5, bold=True, color=TONES.get(tone, ACCENT))
            self.y = start + 12
            for k in range(max(len(w_) for w_ in wrapped)):
                self.ensure(10.2)
                self.y += 10.2
                for j, lines in enumerate(wrapped):
                    if k < len(lines):
                        self.text(MARGIN + 12 + j * w, self.y - 2.5, lines[k], 7.5, color=INK)
        if card.news:
            self.ensure(24)
            self.y += 6
            self.page.draw_line((MARGIN + 12, self.y), (PAGE_W - MARGIN - 12, self.y), color=LINE, width=0.4)
            self.text(MARGIN + 12, self.y + 12, "NEWS", 6.5, bold=True, color=ACCENT)
            self.y += 14
            for item in card.news:
                for line in wrap(f"•  {item}", inner, 7.5):
                    self.ensure(10.5)
                    self.y += 10.5
                    self.text(MARGIN + 12, self.y - 2.5, line, 7.5, color=INK)
        self.y += 8
        self.page.draw_line((MARGIN, self.y), (PAGE_W - MARGIN, self.y), color=LINE, width=0.8)
        self.y += 4

    def finish(self, disclaimer: str) -> bytes:
        total = len(self.doc)
        for n, page in enumerate(self.doc, start=1):
            self.page = page
            y = PAGE_H - MARGIN + 6
            page.draw_line((MARGIN, y - 12), (PAGE_W - MARGIN, y - 12), color=LINE, width=0.5)
            self.text(MARGIN, y, disclaimer, 6.5, color=MUTED)
            self.text(MARGIN, y, f"Page {n} of {total}", 6.5, bold=True, color=MUTED, align="right", width=CONTENT_W)
        data = self.doc.tobytes(garbage=3, deflate=True)
        self.doc.close()
        return data


def render(doc, disclaimer: str) -> bytes:
    """The Document (smart_file.Document) as PDF bytes."""
    from .smart_file import Table

    canvas = Canvas(doc.title, doc.subtitle)
    canvas.tiles(doc.highlights)
    if doc.notice:
        canvas.notice(doc.notice)
    for block in doc.blocks:
        canvas.heading(block.title, getattr(block, "caption", ""))
        if isinstance(block, Table):
            columns = block.pdf_columns or block.columns
            keep = [block.columns.index(c) for c in columns]
            canvas.table(columns, [[row[i] for i in keep] for row in block.rows], block.note)
        else:
            canvas.lines(block.lines)
    if doc.cards:
        canvas.new_page()
        canvas.heading("Stock details", "The key figures for every stock")
        for card in doc.cards:
            canvas.card(card)
    return canvas.finish(disclaimer)
