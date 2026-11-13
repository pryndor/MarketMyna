"""Widgets for the terminal app: block-art menu icons, label / value panels
and a candle chart drawn with text characters."""

from __future__ import annotations

from typing import Any

from rich.table import Table
from rich.text import Text
from textual.widget import Widget
from textual.widgets import Static

from marketmyna.tui.look import PAL

# Menu icons drawn with block characters: 5 columns x 3 rows each, so they read
# at a glance instead of being one letter-sized symbol.
ICON_ART: dict[str, list[str]] = {
    "markets":    ["    ▄", "  ▄ █", "▄ █ █"],   # rising bars
    "stock":      [" ▄▄▄ ", "█   █", " ▀▀▀▄"],   # magnifier
    "screener":   ["▀▀▀▀▀", " ▀▄▀ ", "  █  "],   # funnel
    "watchlists": ["  █  ", "▀███▀", "▄▀ ▀▄"],   # star
    "portfolio":  [" ▄▄▄ ", "█▀▀▀█", "█▄▄▄█"],   # briefcase
    "alerts":     [" ▄▄▄ ", " ███ ", "▀▀▄▀▀"],   # bell
    "reports":    ["█▀▀▀█", "█ ═ █", "█▄▄▄█"],   # page
    "console":    ["▄    ", " ▀▄  ", "▄▀ ▄▄"],   # >_ prompt
    "settings":   ["▀▄█▄▀", "██ ██", "▄▀█▀▄"],   # gear
}


def icon_art(key: str) -> str:
    return "\n".join(ICON_ART[key])


# ---------------------------------------------------------------- formatting

def fmt(value: Any, kind: str = "ratio", currency: str = "") -> str:
    """A figure for a panel: money compact (5.16T), pct with %, ratios 2 dp."""
    if value is None or value == "":
        return "-"
    try:
        x = float(value)
    except (TypeError, ValueError):
        return str(value)
    if kind == "money":
        for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(x) >= size:
                return f"{x / size:,.2f}{unit}"
        return f"{x:,.0f}"
    if kind == "pct":
        return f"{x:,.2f}%"
    if kind == "int":
        return f"{x:,.0f}"
    return f"{x:,.2f}"


def tone(value: Any) -> str:
    """Colour for a signed number or a direction word."""
    if isinstance(value, str):
        v = value.lower()
        if v in ("bullish", "uptrend", "good", "strong", "low", "buy"):
            return PAL["up"]
        if v in ("bearish", "downtrend", "weak", "poor", "high", "sell"):
            return PAL["down"]
        return PAL["flat"]
    try:
        x = float(value)
    except (TypeError, ValueError):
        return PAL["figure"]
    return PAL["up"] if x > 0 else PAL["down"] if x < 0 else PAL["muted"]


class KVPanel(Static):
    """A boxed panel of LABEL ...... value rows (the research-terminal look)."""

    def __init__(self, title: str, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self.border_title = title
        self.add_class("kv")

    def rows(self, rows: list[tuple[str, Any]], footer: Any = None) -> None:
        """rows: (label, value) where value is a str or a rich Text; footer: a
        renderable drawn under the rows (the 52-week range bar)."""
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(style=PAL["muted"], no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        for label, value in rows:
            cell = value if isinstance(value, Text) else Text(str(value), style=PAL["figure"])
            grid.add_row(label.upper(), cell)
        if footer is not None:
            from rich.console import Group

            self.update(Group(grid, footer))
        else:
            self.update(grid)

    def waiting(self) -> None:
        self.update(Text("loading...", style=PAL["muted"]))


def range_bar(low: float, high: float, now: float, width: int = 24) -> Text:
    """low ━━━━●━━━ high: where the price sits in its range."""
    if high <= low:
        return Text("")
    pos = round((now - low) / (high - low) * (width - 1))
    pos = max(0, min(width - 1, pos))
    out = Text()
    out.append("━" * pos, style=PAL["primary"])
    out.append("●", style=f"bold {PAL['fg']}")
    out.append("─" * (width - 1 - pos), style=PAL["muted"])
    return out


# ---------------------------------------------------------------- candle chart

class CandleChart(Widget):
    """OHLC candles drawn with text: │ wick, █ body; green up, red down.
    The price scale is on the right, dates along the bottom."""

    DEFAULT_CSS = "CandleChart { height: 1fr; }"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.bars: list[dict] = []
        self.message = "loading chart..."

    def set_bars(self, bars: list[dict], message: str = "") -> None:
        self.bars = [b for b in bars if all(b.get(k) is not None for k in ("open", "high", "low", "close"))]
        self.message = message or ("no price history" if not self.bars else "")
        self.refresh()

    def render(self) -> Text:
        width, height = self.size.width, self.size.height
        axis = 11
        plot_w, plot_h = width - axis, height - 1
        if not self.bars or plot_w < 10 or plot_h < 4:
            return Text(self.message or "", style=PAL["muted"])
        step = 2 if len(self.bars) * 2 <= plot_w else 1
        data = self.bars[-(plot_w // step):]
        hi = max(float(b["high"]) for b in data)
        lo = min(float(b["low"]) for b in data)
        span = (hi - lo) or 1.0

        def row(v: float) -> int:
            return int(round((hi - float(v)) / span * (plot_h - 1)))

        cells: list[list[tuple[str, str]]] = [[(" ", "")] * plot_w for _ in range(plot_h)]
        for i, b in enumerate(data):
            x = i * step
            colour = PAL["up"] if float(b["close"]) >= float(b["open"]) else PAL["down"]
            for y in range(row(b["high"]), row(b["low"]) + 1):
                cells[y][x] = ("│", colour)
            top, bottom = sorted((row(b["open"]), row(b["close"])))
            for y in range(top, bottom + 1):
                cells[y][x] = ("█", colour)
        last = float(data[-1]["close"])
        last_row = row(last)
        for x in range(plot_w):
            if cells[last_row][x][0] == " ":
                cells[last_row][x] = ("┄", PAL["muted"])

        ticks = {0: hi, plot_h // 2: (hi + lo) / 2, plot_h - 1: lo, last_row: last}
        out = Text()
        for y in range(plot_h):
            run_style, run = "", []
            for ch, style in cells[y]:
                if style != run_style and run:
                    out.append("".join(run), style=run_style)
                    run = []
                run_style = style
                run.append(ch)
            if run:
                out.append("".join(run), style=run_style)
            if y in ticks:
                label = f" {ticks[y]:,.2f}"
                out.append(label.ljust(axis), style=f"bold {PAL['fg']}" if y == last_row else PAL["muted"])
            else:
                out.append(" " * axis)
            out.append("\n")
        # date axis: first, middle, last bar
        dates = [str(data[i].get("Date") or data[i].get("date") or "")[:10] for i in (0, len(data) // 2, -1)]
        axis_line = [" "] * plot_w
        for pos, d in zip((0, (len(data) // 2) * step, max(plot_w - 10, 0)), dates):
            for j, ch in enumerate(d):
                if 0 <= pos + j < plot_w:
                    axis_line[pos + j] = ch
        out.append("".join(axis_line), style=PAL["muted"])
        return out
