"""MarketMyna in the terminal (Textual).

    marketmyna tui

Same engine as the web app: this app joins a MarketMyna server that is
already running, or starts one inside this process. Press w to open the same
running app in your browser; your data is shared because it is one server.

Directions are bullish / neutral / bearish only: no buy / sell calls, targets
or stops, the same as everywhere else in MarketMyna.
"""

from __future__ import annotations

import re
import webbrowser
from typing import Any, Callable

from rich.text import Text
from textual import on
from textual import work as _work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.suggester import SuggestFromList
from textual.widgets import (
    Button,
    ContentSwitcher,
    DataTable,
    Digits,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    RichLog,
    Select,
    Sparkline,
    Static,
)

from marketmyna.tui import look
from marketmyna.tui.client import Api, ApiError
from marketmyna.tui.look import PAL

MARKETS = [("India", "india"), ("US", "us"), ("China A", "china_a"), ("Hong Kong", "hong_kong"), ("Crypto", "crypto")]
MARKET_LABEL = {v: k for k, v in MARKETS}
CURRENCY = {"india": "INR", "us": "USD", "china_a": "CNY", "hong_kong": "HKD", "crypto": "USD"}

# (key, label, symbol icon, plain icon). Single-width symbols line up in every
# terminal font. MARKETMYNA_TUI_ICONS=emoji swaps in colour emoji; =plain (or the
# Linux text console, TERM=linux) uses ASCII.
TABS = [
    ("markets", "Markets", "↗", "~"), ("stock", "Stock", "⌕", "?"), ("screener", "Screener", "≡", "#"),
    ("watchlists", "Watchlists", "★", "*"), ("portfolio", "Portfolio", "◔", "$"), ("alerts", "Alerts", "⚑", "!"),
    ("reports", "Reports", "▤", "="), ("console", "Console", "❯", ">"), ("settings", "Settings", "⚙", "%"),
]
EMOJI = {"markets": "📈", "stock": "🔎", "screener": "🧮", "watchlists": "⭐", "portfolio": "💼", "alerts": "🔔",
         "reports": "📰", "console": "💻", "settings": "🔧"}
MARKET_CODES = {"india": "IN", "us": "US", "china_a": "CN", "hong_kong": "HK", "crypto": "CR"}


def icon_set() -> str:
    """'symbols' (default), 'emoji' or 'plain'."""
    import os

    want = os.environ.get("MARKETMYNA_TUI_ICONS", "").strip().lower()
    if want in ("plain", "ascii"):
        return "plain"
    if want == "emoji":
        return "emoji"
    return "plain" if os.environ.get("TERM", "") == "linux" else "symbols"


def icon(key: str, symbol: str, plain: str, kind: str) -> str:
    return EMOJI[key] if kind == "emoji" else plain if kind == "plain" else symbol


def saved_theme() -> str:
    import os

    want = os.environ.get("MARKETMYNA_TUI_THEME", "").strip().lower()
    if want in look.THEMES:
        return want
    try:
        import json

        from marketmyna.core.home import app_home

        name = json.loads((app_home() / "ui.json").read_text(encoding="utf-8")).get("theme")
    except (OSError, ValueError, AttributeError):
        name = None
    return name if name in look.THEMES else look.DEFAULT


def save_theme(name: str) -> None:
    import json

    from marketmyna.core.home import app_home

    path = app_home() / "ui.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data["theme"] = name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def gradient(text: str, colours: list[str], style: str = "bold") -> Text:
    """text with its letters shaded across colours (the boot logo)."""
    out = Text()
    chars = [c for c in text]
    n = max(len(chars) - 1, 1)
    for i, ch in enumerate(chars):
        out.append(ch, style=f"{style} {colours[round(i / n * (len(colours) - 1))]}")
    return out


def work(**kwargs: Any):
    """@work for this app: a failing background job shows a message instead of closing the app."""
    return _work(exit_on_error=False, **kwargs)


# ---------------------------------------------------------------- formatting

def num(v: Any, digits: int = 2) -> str:
    if v is None or v == "":
        return "-"
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return str(v)


def compact(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "-"
    for size, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= size:
            return f"{x / size:,.2f}{unit}"
    return f"{x:,.0f}"


def signed(v: Any, suffix: str = "%", digits: int = 2) -> Text:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return Text("-", style="dim")
    style = PAL["up"] if x > 0 else PAL["down"] if x < 0 else PAL["muted"]
    arrow = "▲ " if x > 0 else "▼ " if x < 0 else ""
    return Text(f"{arrow}{x:+,.{digits}f}{suffix}" if suffix == "%" else f"{x:+,.{digits}f}{suffix}", style=style)


def short_date(v: Any) -> str:
    return str(v or "-")[:16].replace("T", " ")


_SIGNED = re.compile(r"(?<![\w.])([+-]\d[\d,]*(?:\.\d+)?%?)")
_WORDS = {"bullish": ("bold", "up"), "bearish": ("bold", "down"), "neutral": ("bold", "flat"),
          "uptrend": ("", "up"), "downtrend": ("", "down")}


def pretty(text: str) -> Text:
    """Command output in the terminal look: 'Label: value' lines get a grey
    label and cyan figures; +/- numbers are green / red; directions coloured."""
    out = Text()
    for i, line in enumerate(text.splitlines()):
        if i:
            out.append("\n")
        head, sep, rest = line.partition(": ")
        if sep and 0 < len(head) <= 32 and not head.startswith(("/", "http")):
            out.append(head.upper(), style=PAL["muted"])
            out.append("  ")
            body = Text(rest, style=PAL["figure"])
        else:
            body = Text(line, style=PAL["fg"])
        for match in _SIGNED.finditer(body.plain):
            body.stylize(PAL["up"] if match.group(1).startswith("+") else PAL["down"], match.start(1), match.end(1))
        for word, (weight, colour) in _WORDS.items():
            body.highlight_words([word], style=f"{weight} {PAL[colour]}".strip(), case_sensitive=False)
        out.append_text(body)
    return out


# ---------------------------------------------------------------- shared pane

class Pane(Vertical):
    """One tab. load() fetches its data on a worker thread when the tab is first shown."""

    loaded = False

    @property
    def api(self) -> Api:
        return self.app.api  # type: ignore[attr-defined]

    @property
    def market(self) -> str:
        return self.app.market  # type: ignore[attr-defined]

    def load(self) -> None:  # override
        pass

    def market_changed(self) -> None:
        if self.loaded:
            self.load()

    # Helpers for worker threads.
    def ui(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        return self.app.call_from_thread(fn, *args, **kwargs)

    def fail(self, exc: Exception) -> None:
        self.ui(self.app.notify, str(exc), title="MarketMyna", severity="error", timeout=8)

    def say(self, message: str) -> None:
        self.ui(self.app.notify, message, title="MarketMyna", timeout=4)


def table(id: str, *columns: str, title: str = "") -> DataTable:
    t = DataTable(id=id, cursor_type="row", zebra_stripes=True)
    t.add_columns(*columns)
    if title:
        t.border_title = title
    return t


def section(text: str) -> Label:
    return Label(f"◢ {text.upper()}", classes="section")


def picked(sel: Select) -> Any:
    """The chosen value, or None when nothing is chosen."""
    return None if sel.is_blank() else sel.value


def selected_key(t: DataTable) -> str | None:
    if t.row_count == 0:
        return None
    try:
        return t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
    except Exception:  # noqa: BLE001 - no row under the cursor
        return None


# ---------------------------------------------------------------- 1 markets

class IndexCard(Vertical):
    """One headline index: name, big price, change, the day's line."""

    def compose(self) -> ComposeResult:
        yield Static("", classes="card-name")
        yield Digits("-", classes="card-price")
        yield Static("", classes="card-change")
        yield Sparkline([0, 0], classes="card-spark")

    def show(self, item: dict | None) -> None:
        if not item:
            self.display = False
            return
        self.display = True
        live = "●" if item.get("open") else "○"
        self.query_one(".card-name", Static).update(
            Text.assemble((f"{live} ", PAL["up"] if item.get("open") else PAL["muted"]),
                          (str(item.get("label") or item.get("key") or "").upper(), f"bold {PAL['heading']}")))
        price = item.get("price")
        self.query_one(".card-price", Digits).update(num(price) if price is not None else "-")
        self.query_one(".card-change", Static).update(
            Text.assemble(signed(item.get("change"), ""), "  ", signed(item.get("change_pct"))))
        spark = [float(v) for v in (item.get("spark") or []) if v is not None]
        line = self.query_one(".card-spark", Sparkline)
        line.data = spark[-60:] if len(spark) > 1 else [0, 0]
        self.set_class((item.get("change_pct") or 0) < 0, "down")


class MarketsPane(Pane):
    def on_mount(self) -> None:
        self.set_interval(60, self._auto)

    def _auto(self) -> None:
        # Keep the board live while it is on screen.
        if self.loaded and self.app.tab == "markets":  # type: ignore[attr-defined]
            self.load()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Label("Stocks to watch:", classes="lbl")
            yield Select([("Today", "day"), ("This week", "week"), ("This month", "month")], value="day",
                         allow_blank=False, id="period", classes="narrow")
            yield Button("Refresh (r)", id="refresh")
            yield Static("", id="mk-status", classes="status")
        with Horizontal(id="cards"):
            for _ in range(4):
                yield IndexCard(classes="card")
        yield table("indices", "Group", "Index", "Price", "Change", "Change %", "Day low", "Day high",
                    title="INDEX BOARD")
        yield table("watch", "List", "Symbol", "Name", "Price", "Change %", "Why it is on the list",
                    title="STOCKS TO WATCH · ENTER OPENS")

    def load(self) -> None:
        self.loaded = True
        self.fetch(self.market, self.query_one("#period", Select).value)

    @on(Select.Changed, "#period")
    def _period(self) -> None:
        if self.loaded:
            self.load()

    @on(Button.Pressed, "#refresh")
    def _refresh(self) -> None:
        self.load()

    @work(thread=True, exclusive=True, group="markets")
    def fetch(self, market: str, period: Any) -> None:
        self.ui(self.query_one("#mk-status", Static).update, f"Loading {MARKET_LABEL.get(market, market)}...")
        try:
            board = self.api.get("/macro/indices", market=market)
        except ApiError as exc:
            board = {"groups": []}
            self.fail(exc)
        self.ui(self._show_indices, board)
        self.ui(self.app.set_tape, board)  # type: ignore[attr-defined]
        if market in ("india", "us", "china_a", "hong_kong"):
            try:
                watch = self.api.get("/listings/watch", market=market, period=period)
            except ApiError as exc:
                watch = {"boards": []}
                self.fail(exc)
        else:
            watch = {"boards": []}
        self.ui(self._show_watch, watch)
        self.ui(self.query_one("#mk-status", Static).update, MARKET_LABEL.get(market, market))

    def _show_indices(self, board: dict) -> None:
        groups = board.get("groups", [])
        heads = [i for i in (groups[0].get("items", []) if groups else []) if i.get("price") is not None][:4]
        for card, item in zip(self.query(IndexCard), heads + [None] * 4):
            card.show(item)
        t = self.query_one("#indices", DataTable)
        t.clear()
        for group in board.get("groups", []):
            for item in group.get("items", []):
                t.add_row(group.get("label", ""), item.get("label", item.get("key", "")), num(item.get("price")),
                          signed(item.get("change"), ""), signed(item.get("change_pct")),
                          num(item.get("day_low")), num(item.get("day_high")))

    def _show_watch(self, watch: dict) -> None:
        t = self.query_one("#watch", DataTable)
        t.clear()
        for b in watch.get("boards", []):
            for r in b.get("rows", []):
                t.add_row(b.get("title", ""), r.get("symbol", ""), (r.get("name") or "")[:32], num(r.get("price")),
                          signed(r.get("change_percent")), r.get("why", ""),
                          key=f"{t.row_count}|{r.get('symbol')}|{r.get('market', self.market)}")
        if t.row_count == 0:
            t.add_row("", "", "No list for this market", "", "", "")

    @on(DataTable.RowSelected, "#watch")
    def _open(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value and event.row_key.value.count("|") == 2:
            _, symbol, market = event.row_key.value.split("|", 2)
            self.app.open_stock(symbol, market)  # type: ignore[attr-defined]


# ---------------------------------------------------------------- 2 stock

SECTIONS = [("Quote", "quote"), ("Overview", "overview"), ("Valuation", "valuation"), ("Financials", "financials"),
            ("Estimates", "estimates"), ("Dividends", "dividends"), ("Peers", "peers"), ("Ethical", "ethical"),
            ("AI analysis", "analyze")]


class StockPane(Pane):
    symbol: str = ""
    symbol_market: str = ""

    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Input(placeholder="Symbol or company name, then Enter (e.g. RELIANCE, AAPL, Infosys)", id="sym")
            yield Static("", id="current", classes="status")
        yield table("matches", "Symbol", "Name", "Market", "Type", "Exchange", "Price", title="MATCHES")
        with Horizontal(classes="buttons"):
            for label, key in SECTIONS:
                yield Button(label, id=f"sec-{key}", classes="small")
            yield Button("+ Watchlist", id="watch-add", classes="small", variant="primary")
        yield RichLog(id="out", wrap=True, markup=False, highlight=False)

    def on_mount(self) -> None:
        self.query_one("#out", RichLog).border_title = "EQUITY RESEARCH"
        self.query_one("#matches").display = False
        out = self.query_one("#out", RichLog)
        out.write("Look up any stock, ETF or fund: type a symbol or name and press Enter.\n"
                  "Then pick a section above. AI analysis gives a bullish / neutral / bearish outlook,\n"
                  "never a buy or sell call. It needs an AI key (Settings, key 9).")

    def open(self, symbol: str, market: str) -> None:
        self.symbol, self.symbol_market = symbol, market
        self.query_one("#sym", Input).value = symbol
        self.query_one("#matches").display = False
        self.query_one("#current", Static).update(f"{symbol} ({MARKET_LABEL.get(market, market)})")
        self.run_section("overview")

    @on(Input.Submitted, "#sym")
    def _search(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.search(text)

    @work(thread=True, exclusive=True, group="stock-search")
    def search(self, text: str) -> None:
        try:
            rows = self.api.get("/listings/search", q=text, market="all", limit=20)
        except ApiError as exc:
            self.fail(exc)
            return
        exact = [r for r in rows if str(r.get("symbol", "")).upper() == text.upper()]
        here = [r for r in exact if r.get("market") == self.market]
        pick = here[0] if here else exact[0] if len(exact) == 1 else rows[0] if len(rows) == 1 else None
        if pick:
            self.ui(self.open, pick["symbol"], pick.get("market") or self.market)
            return
        if not rows:  # not in the listings: try it as typed (a Yahoo symbol such as TSLA or 0700.HK)
            self.ui(self.open, text.upper(), self.market)
            return
        self.ui(self._show_matches, rows)

    def _show_matches(self, rows: list[dict]) -> None:
        t = self.query_one("#matches", DataTable)
        t.clear()
        for r in rows:
            t.add_row(r.get("symbol", ""), (r.get("name") or "")[:40], MARKET_LABEL.get(r.get("market"), r.get("market")),
                      r.get("type", ""), r.get("exchange", "") or "", num(r.get("price")),
                      key=f"{t.row_count}|{r.get('symbol')}|{r.get('market')}")
        t.display = True
        t.focus()

    @on(DataTable.RowSelected, "#matches")
    def _pick(self, event: DataTable.RowSelected) -> None:
        _, symbol, market = str(event.row_key.value).split("|", 2)
        self.open(symbol, market)

    @on(Button.Pressed)
    def _button(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid.startswith("sec-"):
            self.run_section(bid[4:])
        elif bid == "watch-add":
            self.add_to_watchlist()

    def run_section(self, section: str) -> None:
        if not self.symbol:
            self.app.notify("Look up a stock first.", title="MarketMyna")
            return
        self.command(section, self.symbol, self.symbol_market)

    @work(thread=True, exclusive=True, group="stock-run")
    def command(self, section: str, symbol: str, market: str) -> None:
        out = self.query_one("#out", RichLog)
        self.ui(out.clear)
        label = dict((v, k) for k, v in SECTIONS).get(section, section)
        if section == "analyze":
            try:
                ready = self.api.get("/agent/status").get("configured")
            except ApiError as exc:
                self.fail(exc)
                return
            if not ready:
                self.ui(out.write, "AI analysis needs an AI key. Add one in Settings (press 9): Gemini, OpenAI, "
                                   "Claude, Groq, OpenRouter, DeepSeek or Mistral, or a local Ollama.")
                return
            self.ui(out.write, f"Running the AI analysts on {symbol}... this can take a minute.")
        else:
            self.ui(out.write, f"{label}: {symbol}...")
        try:
            text, ok = self.api.command(f"/{section} {symbol} {market}")
        except ApiError as exc:
            text, ok = str(exc), False
        self.ui(out.clear)
        self.ui(out.write, Text.assemble((f"◢ {label.upper()}  ", f"bold {PAL['heading']}"),
                                         (symbol, f"bold {PAL['fg']}"),
                                         (f" · {MARKET_LABEL.get(market, market)}", PAL["muted"])))
        self.ui(out.write, pretty(text) if ok else Text(text, style=PAL["flat"]))

    @work(thread=True, group="stock-watch")
    def add_to_watchlist(self) -> None:
        if not self.symbol:
            self.say("Look up a stock first.")
            return
        try:
            lists = self.api.get("/watchlists")
            wid = lists[0]["id"] if lists else self.api.post("/watchlists", {"name": "My watchlist"})["id"]
            self.api.post(f"/watchlists/{wid}/items", {"symbol": self.symbol, "market": self.symbol_market})
        except (ApiError, KeyError, IndexError) as exc:
            self.fail(exc if isinstance(exc, ApiError) else ApiError(str(exc)))
            return
        self.say(f"{self.symbol} added to {lists[0]['name'] if lists else 'My watchlist'}.")


# ---------------------------------------------------------------- 3 screener

TYPES = [("All", "all"), ("Stocks", "stock"), ("ETFs", "etf"), ("Mutual funds", "mf"), ("Crypto", "crypto")]
SORTS = [("Market cap", "market_cap"), ("Change %", "change_percent"), ("Price", "price"), ("Volume", "volume"),
         ("Name", "name")]
PAGE = 50


class ScreenerPane(Pane):
    page_offset = 0
    total = 0

    BINDINGS = [Binding("n", "page(1)", "Next page"), Binding("p", "page(-1)", "Previous page")]

    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Input(placeholder="Filter by name / symbol (Enter)", id="q")
            yield Select(TYPES, value="all", allow_blank=False, id="type", classes="narrow")
            yield Select(SORTS, value="market_cap", allow_blank=False, id="sort", classes="narrow")
            yield Select([("Order: high first", "desc"), ("Order: low first", "asc")], value="desc",
                         allow_blank=False, id="order", classes="narrow")
        with Horizontal(classes="bar"):
            yield Label("Ready-made screen:", classes="lbl")
            yield Select([], prompt="All listings (no screen)", id="screen", classes="wide")
            yield Static("", id="sc-status", classes="status")
        yield table("rows", "Symbol", "Name", "Sector", "Price", "Change %", "Market cap", "52w low", "52w high",
                    "Ethical", title="SCREENER")

    def load(self) -> None:
        self.loaded = True
        self.page_offset = 0
        self.screens(self.market)
        self.fetch()

    def action_page(self, step: int) -> None:
        if picked(self.query_one("#screen", Select)) is not None:
            return
        new = self.page_offset + step * PAGE
        if 0 <= new < max(self.total, 1):
            self.page_offset = new
            self.fetch()

    @on(Input.Submitted, "#q")
    @on(Select.Changed, "#type")
    @on(Select.Changed, "#sort")
    @on(Select.Changed, "#order")
    @on(Select.Changed, "#screen")
    def _changed(self) -> None:
        if self.loaded:
            self.page_offset = 0
            self.fetch()

    @work(thread=True, exclusive=True, group="screens")
    def screens(self, market: str) -> None:
        try:
            rows = self.api.get("/screens", market=market) if market in ("india", "us") else []
        except ApiError:
            rows = []
        self.ui(self.query_one("#screen", Select).set_options, [(r["title"], r["key"]) for r in rows])

    def fetch(self) -> None:
        screen = picked(self.query_one("#screen", Select))
        if screen is not None:
            self.fetch_screen(self.market, str(screen))
        else:
            self.fetch_rows(self.market, self.query_one("#q", Input).value.strip(),
                            self.query_one("#type", Select).value, self.query_one("#sort", Select).value,
                            self.query_one("#order", Select).value, self.page_offset)

    @work(thread=True, exclusive=True, group="screener")
    def fetch_rows(self, market: str, q: str, type_: Any, sort: Any, order: Any, offset: int) -> None:
        self.ui(self.query_one("#sc-status", Static).update, "Loading...")
        try:
            data = self.api.get("/listings", market=market, q=q, type=type_, sort=sort, order=order,
                                offset=offset, limit=PAGE)
        except ApiError as exc:
            self.fail(exc)
            self.ui(self.query_one("#sc-status", Static).update, "")
            return
        self.total = int(data.get("total") or 0)
        self.ui(self._show, data.get("rows", []), None)
        end = min(offset + PAGE, self.total)
        self.ui(self.query_one("#sc-status", Static).update,
                f"{offset + 1 if self.total else 0}-{end} of {self.total:,}  ·  n / p: pages  ·  Enter: open")

    @work(thread=True, exclusive=True, group="screener")
    def fetch_screen(self, market: str, key: str) -> None:
        self.ui(self.query_one("#sc-status", Static).update, "Running the screen (can take a minute)...")
        try:
            data = self.api.get(f"/screens/{key}", market=market)
        except ApiError as exc:
            self.fail(exc)
            self.ui(self.query_one("#sc-status", Static).update, "")
            return
        self.ui(self._show, data.get("results", []), data.get("columns", []))
        rules = " · ".join(data.get("rules", []))
        self.ui(self.query_one("#sc-status", Static).update,
                f"{len(data.get('results', []))} matches of {data.get('scanned', '?')} scanned  ·  {rules}")

    def _show(self, rows: list[dict], columns: list[dict] | None) -> None:
        t = self.query_one("#rows", DataTable)
        t.clear(columns=True)
        if columns is None:
            t.add_columns("Symbol", "Name", "Sector", "Price", "Change %", "Market cap", "52w low", "52w high",
                          "Ethical")
            for r in rows:
                t.add_row(r.get("symbol", ""), (r.get("name") or "")[:36], (r.get("sector") or "")[:24],
                          num(r.get("price")), signed(r.get("change_percent")), compact(r.get("market_cap")),
                          num(r.get("low_52w")), num(r.get("high_52w")), r.get("shariah") or "-",
                          key=f"{t.row_count}|{r.get('symbol')}|{r.get('market', self.market)}")
        else:
            t.add_columns("Symbol", "Name", "Price", "Change %", "Market cap", *[c["label"] for c in columns])
            for r in rows:
                t.add_row(r.get("symbol", ""), (r.get("name") or "")[:36], num(r.get("price")),
                          signed(r.get("change_percent")), compact(r.get("market_cap")),
                          *[num(r.get(c["key"])) for c in columns],
                          key=f"{t.row_count}|{r.get('symbol')}|{r.get('market', self.market)}")

    @on(DataTable.RowSelected, "#rows")
    def _open(self, event: DataTable.RowSelected) -> None:
        _, symbol, market = str(event.row_key.value).split("|", 2)
        self.app.open_stock(symbol, market)  # type: ignore[attr-defined]


# ---------------------------------------------------------------- 4 watchlists

class WatchlistsPane(Pane):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Select([], prompt="Watchlist", id="lists", classes="wide")
            yield Input(placeholder="Add: SYMBOL [market]  (Enter)", id="add")
            yield Button("Remove selected", id="remove", variant="error")
        with Horizontal(classes="bar"):
            yield Input(placeholder="New watchlist name (Enter)", id="newlist")
            yield Button("Delete this watchlist", id="droplist", variant="error")
        yield table("items", "Symbol", "Name", "Market", "Price", "Change %", "52w low", "52w high", "Note",
                    title="WATCHLIST")

    def load(self) -> None:
        self.loaded = True
        self.fetch_lists()

    def market_changed(self) -> None:
        pass  # a watchlist holds every market

    @work(thread=True, exclusive=True, group="wl")
    def fetch_lists(self, pick: int | None = None) -> None:
        try:
            lists = self.api.get("/watchlists")
        except ApiError as exc:
            self.fail(exc)
            return
        sel = self.query_one("#lists", Select)
        current = pick if pick is not None else sel.value
        self.ui(sel.set_options, [(f"{w['name']} ({w['count']})", w["id"]) for w in lists])
        ids = [w["id"] for w in lists]
        if ids:
            self.ui(setattr, sel, "value", current if current in ids else ids[0])

    @on(Select.Changed, "#lists")
    def _list(self, event: Select.Changed) -> None:
        if picked(event.select) is not None:
            self.fetch_items(int(event.value))

    @work(thread=True, exclusive=True, group="wl-items")
    def fetch_items(self, wid: int) -> None:
        try:
            data = self.api.get(f"/watchlists/{wid}")
        except ApiError as exc:
            self.fail(exc)
            return
        self.ui(self._show, data.get("items", []))

    def _show(self, items: list[dict]) -> None:
        t = self.query_one("#items", DataTable)
        t.clear()
        for r in items:
            t.add_row(r.get("symbol", ""), (r.get("name") or "")[:36], MARKET_LABEL.get(r.get("market"), r.get("market")),
                      num(r.get("price")), signed(r.get("change_percent")), num(r.get("low_52w")),
                      num(r.get("high_52w")), r.get("note") or "", key=f"{r['id']}|{r['symbol']}|{r.get('market')}")

    def _wid(self) -> int | None:
        v = picked(self.query_one("#lists", Select))
        return None if v is None else int(v)

    @on(Input.Submitted, "#add")
    def _add(self, event: Input.Submitted) -> None:
        parts = event.value.split()
        if parts and self._wid() is not None:
            market = parts[1].lower() if len(parts) > 1 else self.market
            self.write(self._wid(), "add", {"symbol": parts[0].upper(), "market": market})
            event.input.value = ""

    @on(Input.Submitted, "#newlist")
    def _new(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.write(None, "new", {"name": event.value.strip()})
            event.input.value = ""

    @on(Button.Pressed, "#remove")
    def _remove(self) -> None:
        key = selected_key(self.query_one("#items", DataTable))
        if key and self._wid() is not None:
            self.write(self._wid(), "remove", {"item": key.split("|")[0]})

    @on(Button.Pressed, "#droplist")
    def _drop(self) -> None:
        if self._wid() is not None:
            self.write(self._wid(), "drop", {})

    @on(DataTable.RowSelected, "#items")
    def _open(self, event: DataTable.RowSelected) -> None:
        _, symbol, market = str(event.row_key.value).split("|", 2)
        self.app.open_stock(symbol, market)  # type: ignore[attr-defined]

    @work(thread=True, group="wl-write")
    def write(self, wid: int | None, action: str, body: dict) -> None:
        try:
            if action == "add":
                self.api.post(f"/watchlists/{wid}/items", body)
            elif action == "remove":
                self.api.delete(f"/watchlists/{wid}/items/{body['item']}")
            elif action == "new":
                wid = self.api.post("/watchlists", body)["id"]
            elif action == "drop":
                self.api.delete(f"/watchlists/{wid}")
                wid = None
        except ApiError as exc:
            self.fail(exc)
            return
        self.ui(self.fetch_lists, wid)
        if wid is not None and action != "new":
            self.ui(self.fetch_items, wid)


# ---------------------------------------------------------------- 5 portfolio

class PortfolioPane(Pane):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Select([], prompt="Portfolio", id="pf", classes="wide")
            yield Input(placeholder="New portfolio name (Enter)", id="pfnew")
            yield Button("Review (AI-free)", id="review")
        yield Static("", id="summary", classes="summary")
        yield table("holdings", "Symbol", "Market", "Quantity", "Avg cost", "Price", "Value", "Gain", "Gain %",
                    title="HOLDINGS")
        with Horizontal(classes="bar"):
            yield Input(placeholder="Symbol", id="t-sym", classes="narrow")
            yield Select([("Buy", "buy"), ("Sell", "sell"), ("Dividend", "dividend")], value="buy",
                         allow_blank=False, id="t-type", classes="narrow")
            yield Input(placeholder="Quantity", id="t-qty", type="number", classes="narrow")
            yield Input(placeholder="Price", id="t-price", type="number", classes="narrow")
            yield Input(placeholder="Date YYYY-MM-DD (optional)", id="t-date", classes="narrow")
            yield Button("Add transaction", id="t-add", variant="primary")
        with Horizontal(classes="bar"):
            yield Button("Delete transaction", id="t-del", variant="error")
            yield Button("Delete portfolio", id="pf-del", variant="error")
        yield table("txns", "#", "Date", "Type", "Symbol", "Quantity", "Price", "Total",
                    title="TRANSACTION HISTORY · SELECT ONE TO DELETE")

    def load(self) -> None:
        self.loaded = True
        self.fetch_list()

    def market_changed(self) -> None:
        pass  # a portfolio can hold every market

    def _portfolio(self) -> str | None:
        v = picked(self.query_one("#pf", Select))
        return None if v is None else str(v)

    @work(thread=True, exclusive=True, group="pf")
    def fetch_list(self, pick: str | None = None) -> None:
        try:
            names = self.api.get("/portfolio")
        except ApiError as exc:
            self.fail(exc)
            return
        sel = self.query_one("#pf", Select)
        current = pick or sel.value
        self.ui(sel.set_options, [(n, n) for n in names])
        if names:
            self.ui(setattr, sel, "value", current if current in names else names[0])
        else:
            self.ui(self.query_one("#summary", Static).update,
                    "No portfolio yet: type a name above and press Enter to make one.")

    @on(Select.Changed, "#pf")
    def _pf(self) -> None:
        if self._portfolio():
            self.fetch(self._portfolio())

    @work(thread=True, exclusive=True, group="pf-one")
    def fetch(self, name: str) -> None:
        self.ui(self.query_one("#summary", Static).update, "Loading prices...")
        try:
            data = self.api.get(f"/portfolio/{name}")
        except ApiError as exc:
            self.fail(exc)
            return
        self.ui(self._show, data)

    def _show(self, d: dict) -> None:
        cur = d.get("currency", "")
        summary = Text.assemble(
            (f"{d.get('name')}  ", "bold"), f"Value {num(d.get('total_value'))} {cur}   ",
            f"Cost {num(d.get('total_cost_basis'))}   Gain ", signed(d.get("total_unrealized_gain"), ""),
            " (", signed(d.get("total_unrealized_gain_percent")), ")   ", f"Cash {num(d.get('cash_balance'))}")
        self.query_one("#summary", Static).update(summary)
        t = self.query_one("#holdings", DataTable)
        t.clear()
        for h in (d.get("holdings") or {}).values():
            t.add_row(h.get("symbol", ""), MARKET_LABEL.get(h.get("market"), h.get("market") or ""),
                      num(h.get("quantity"), 4).rstrip("0").rstrip("."), num(h.get("avg_cost")),
                      num(h.get("current_price")), num(h.get("market_value")), signed(h.get("unrealized_gain"), ""),
                      signed(h.get("unrealized_gain_percent")), key=f"{h.get('symbol')}|{h.get('market')}")
        tx = self.query_one("#txns", DataTable)
        tx.clear()
        for x in reversed(d.get("transactions") or []):
            tx.add_row(str(x.get("index")), short_date(x.get("date"))[:10], x.get("transaction_type", ""),
                       x.get("symbol", ""), num(x.get("quantity"), 4).rstrip("0").rstrip("."), num(x.get("price")),
                       num(x.get("total")), key=str(x.get("index")))

    @on(DataTable.RowSelected, "#holdings")
    def _open(self, event: DataTable.RowSelected) -> None:
        symbol, market = str(event.row_key.value).split("|", 1)
        self.app.open_stock(symbol, market if market != "None" else self.market)  # type: ignore[attr-defined]

    @on(Input.Submitted, "#pfnew")
    def _new(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if name:
            self.write("new", {"name": name, "currency": CURRENCY.get(self.market, "USD")}, name)
            event.input.value = ""

    @on(Button.Pressed, "#t-add")
    def _add(self) -> None:
        name = self._portfolio()
        if not name:
            self.app.notify("Make a portfolio first.", title="MarketMyna")
            return
        try:
            qty = float(self.query_one("#t-qty", Input).value)
            price = float(self.query_one("#t-price", Input).value)
        except ValueError:
            self.app.notify("Enter a quantity and a price.", title="MarketMyna", severity="warning")
            return
        symbol = self.query_one("#t-sym", Input).value.strip().upper()
        if not symbol:
            self.app.notify("Enter a symbol.", title="MarketMyna", severity="warning")
            return
        body = {"symbol": symbol, "market": self.market, "transaction_type": self.query_one("#t-type", Select).value,
                "quantity": qty, "price": price}
        date = self.query_one("#t-date", Input).value.strip()
        if date:
            body["date"] = f"{date}T00:00:00" if len(date) == 10 else date
        self.write("txn", body, name)
        for i in ("#t-sym", "#t-qty", "#t-price", "#t-date"):
            self.query_one(i, Input).value = ""

    @on(Button.Pressed, "#t-del")
    def _del_txn(self) -> None:
        key = selected_key(self.query_one("#txns", DataTable))
        if key and self._portfolio():
            self.write("del-txn", {"index": key}, self._portfolio())

    @on(Button.Pressed, "#pf-del")
    def _del_pf(self) -> None:
        if self._portfolio():
            self.write("del-pf", {}, self._portfolio())

    @on(Button.Pressed, "#review")
    def _review(self) -> None:
        name = self._portfolio()
        if name:
            self.app.run_console(f"/review {name}")  # type: ignore[attr-defined]

    @work(thread=True, group="pf-write")
    def write(self, action: str, body: dict, name: str) -> None:
        try:
            if action == "new":
                self.api.post("/portfolio", body)
            elif action == "txn":
                self.api.post(f"/portfolio/{name}/transactions", body)
            elif action == "del-txn":
                self.api.delete(f"/portfolio/{name}/transactions/{body['index']}")
            elif action == "del-pf":
                self.api.delete(f"/portfolio/{name}")
                name = ""
        except ApiError as exc:
            self.fail(exc)
            return
        self.ui(self.fetch_list, name or None)
        if name and action != "new":
            self.ui(self.fetch, name)


# ---------------------------------------------------------------- 6 alerts

class AlertsPane(Pane):
    kinds: list[dict] = []

    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Input(placeholder="Symbol", id="a-sym", classes="narrow")
            yield Select([], prompt="Condition", id="a-kind", classes="wide")
            yield Input(placeholder="Value", id="a-val", type="number", classes="narrow")
            yield Input(placeholder="Note (optional)", id="a-note")
            yield Button("Add alert", id="a-add", variant="primary")
        with Horizontal(classes="bar"):
            yield Button("Pause / resume", id="a-toggle")
            yield Button("Delete", id="a-del", variant="error")
            yield Button("Check now", id="a-check")
            yield Static("Alerts are checked all day while MarketMyna runs; they go to your notification "
                         "channels (Settings in the web app).", classes="status")
        yield table("alerts", "ID", "Symbol", "Market", "Condition", "Status", "Last value", "Triggered", "Note",
                    title="PRICE ALERTS")
        yield table("events", "When", "Symbol", "Message", title="RECENT TRIGGERS")

    def load(self) -> None:
        self.loaded = True
        self.fetch()

    def market_changed(self) -> None:
        pass

    @work(thread=True, exclusive=True, group="alerts")
    def fetch(self) -> None:
        try:
            if not self.kinds:
                self.kinds = self.api.get("/trade/alert-kinds")
                self.ui(self.query_one("#a-kind", Select).set_options,
                        [(f"{k['label']} ({k['unit']})", k["kind"]) for k in self.kinds])
            alerts = self.api.get("/trade/alerts")
            events = self.api.get("/trade/alerts/events")
        except ApiError as exc:
            self.fail(exc)
            return
        self.ui(self._show, alerts, events if isinstance(events, list) else events.get("events", []))

    def _show(self, alerts: list[dict], events: list[dict]) -> None:
        t = self.query_one("#alerts", DataTable)
        t.clear()
        for a in alerts:
            t.add_row(str(a["id"]), a.get("symbol", ""), MARKET_LABEL.get(a.get("market"), a.get("market")),
                      a.get("description", a.get("kind", "")), a.get("status", ""), num(a.get("last_value")),
                      str(a.get("trigger_count", 0)), a.get("note") or "", key=f"{a['id']}|{a.get('status')}")
        e = self.query_one("#events", DataTable)
        e.clear()
        for ev in events[:50]:
            e.add_row(short_date(ev.get("created_at") or ev.get("triggered_at")), ev.get("symbol", ""),
                      ev.get("message") or ev.get("description") or "")

    @on(Button.Pressed, "#a-add")
    def _add(self) -> None:
        kind = picked(self.query_one("#a-kind", Select))
        symbol = self.query_one("#a-sym", Input).value.strip().upper()
        try:
            value = float(self.query_one("#a-val", Input).value)
        except ValueError:
            value = None
        if not symbol or kind is None or value is None:
            self.app.notify("Enter a symbol, a condition and a value.", title="MarketMyna", severity="warning")
            return
        self.write("add", {"symbol": symbol, "market": self.market, "kind": kind, "value": value,
                           "note": self.query_one("#a-note", Input).value.strip()})
        for i in ("#a-sym", "#a-val", "#a-note"):
            self.query_one(i, Input).value = ""

    @on(Button.Pressed, "#a-toggle")
    def _toggle(self) -> None:
        key = selected_key(self.query_one("#alerts", DataTable))
        if key:
            aid, status = key.split("|", 1)
            self.write("patch", {"id": aid, "status": "active" if status == "paused" else "paused"})

    @on(Button.Pressed, "#a-del")
    def _del(self) -> None:
        key = selected_key(self.query_one("#alerts", DataTable))
        if key:
            self.write("delete", {"id": key.split("|")[0]})

    @on(Button.Pressed, "#a-check")
    def _check(self) -> None:
        self.write("check", {})

    @work(thread=True, group="alerts-write")
    def write(self, action: str, body: dict) -> None:
        try:
            if action == "add":
                self.api.post("/trade/alerts", body)
                self.say(f"Alert added for {body['symbol']}.")
            elif action == "patch":
                self.api.patch(f"/trade/alerts/{body['id']}", {"status": body["status"]})
            elif action == "delete":
                self.api.delete(f"/trade/alerts/{body['id']}")
            elif action == "check":
                self.api.post("/trade/alerts/check")
                self.say("Alerts checked.")
        except ApiError as exc:
            self.fail(exc)
            return
        self.ui(self.fetch)


# ---------------------------------------------------------------- 7 reports

class ReportsPane(Pane):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Button("Run report now", id="run", variant="primary")
            yield Button("Refresh", id="r-refresh")
            yield Button("Edit schedule in browser", id="r-web")
        yield Static("", id="sched", classes="summary")
        yield table("reports", "Created", "Title", "Stocks", title="SAVED REPORTS · ENTER OPENS IN BROWSER")

    def load(self) -> None:
        self.loaded = True
        self.fetch()

    def market_changed(self) -> None:
        pass

    @work(thread=True, exclusive=True, group="reports")
    def fetch(self) -> None:
        try:
            status = self.api.get("/scheduler/status")
            reports = self.api.get("/reports", limit=50)
            run = self.api.get("/scheduler/run-now")
        except ApiError as exc:
            self.fail(exc)
            return
        self.ui(self._show, status, reports, run)

    def _show(self, status: dict, reports: list[dict], run: dict) -> None:
        s = status.get("schedule") or {}
        when = (f"every day at {s['time_of_day']}" if s.get("time_of_day")
                else f"every {s['interval_minutes']} minutes" if s.get("interval_minutes") else "no time set")
        lines = [
            Text.assemble(("Scheduled report: ", "bold"),
                          ("on" if s.get("enabled") else "off", PAL["up"] if s.get("enabled") else PAL["flat"]),
                          f"  ·  {when}  ·  market {MARKET_LABEL.get(s.get('market'), s.get('market'))}"),
            Text(f"Stocks: {', '.join(s.get('symbols') or []) or 'none chosen'}"),
            Text(f"Last run: {short_date(s.get('last_run_at'))}  {s.get('last_run_status') or ''}  "
                 f"{(s.get('last_run_summary') or '')[:160]}"),
            Text(f"Scheduler: {'running' if status.get('running') else 'stopped'}"
                 f"{'  ·  a report is running now...' if run.get('running') else ''}"),
            Text("Reports show a Bullish / Neutral / Bearish list from company figures, with the reasons.", style="dim"),
        ]
        self.query_one("#sched", Static).update(Text("\n").join(lines))
        t = self.query_one("#reports", DataTable)
        t.clear()
        for r in reports:
            t.add_row(short_date(r.get("created_at")), r.get("title") or "", str(r.get("stock_count") or 0),
                      key=r.get("token"))

    @on(Button.Pressed, "#r-refresh")
    def _refresh(self) -> None:
        self.fetch()

    @on(Button.Pressed, "#r-web")
    def _web(self) -> None:
        self.app.open_web("/scheduler")  # type: ignore[attr-defined]

    @on(DataTable.RowSelected, "#reports")
    def _open(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self.app.open_web(f"/r/{event.row_key.value}")  # type: ignore[attr-defined]

    @on(Button.Pressed, "#run")
    def _run(self) -> None:
        self.run_now()

    @work(thread=True, exclusive=True, group="reports-run")
    def run_now(self) -> None:
        import time

        try:
            self.api.post("/scheduler/run-now")
        except ApiError as exc:
            self.fail(exc)
            return
        self.say("Report started: it is sent to your notification channels when done.")
        for _ in range(180):
            time.sleep(5)
            try:
                state = self.api.get("/scheduler/run-now")
            except ApiError:
                break
            if not state.get("running"):
                result = state.get("result") or {}
                self.say(str(result.get("message") or result.get("summary") or "Report finished."))
                break
        self.ui(self.fetch)


# ---------------------------------------------------------------- 8 console

class CommandInput(Input):
    """Input with up / down history."""

    BINDINGS = [Binding("up", "history(-1)", show=False), Binding("down", "history(1)", show=False)]
    history: list[str] = []
    pos = 0

    def action_history(self, step: int) -> None:
        if not self.history:
            return
        self.pos = max(0, min(len(self.history), self.pos + step))
        self.value = self.history[self.pos] if self.pos < len(self.history) else ""
        self.cursor_position = len(self.value)


class ConsolePane(Pane):
    def compose(self) -> ComposeResult:
        log = RichLog(id="log", wrap=True, markup=False, highlight=False)
        log.border_title = "COMMAND CONSOLE"
        yield log
        yield CommandInput(placeholder="/help, /quote RELIANCE india, /market us, /ask ... (Up / Down: history)",
                           id="cmd")

    def load(self) -> None:
        self.loaded = True
        self.commands()

    def market_changed(self) -> None:
        pass

    @work(thread=True, group="console-help")
    def commands(self) -> None:
        log = self.query_one("#log", RichLog)
        try:
            cmds = self.api.get("/bot/commands")
        except ApiError as exc:
            self.fail(exc)
            return
        names = sorted({f"/{c['name']} " for c in cmds})
        self.ui(setattr, self.query_one("#cmd", CommandInput), "suggester", SuggestFromList(names, case_sensitive=False))
        self.ui(log.write, Text("The same commands as the Telegram bot. Tab completes a command.", style="bold"))
        group = None
        for c in cmds:
            if c["group"] != group:
                group = c["group"]
                self.ui(log.write, Text(f"\n{group}", style=f"bold {PAL['heading']}"))
            self.ui(log.write, Text.assemble((f"  {c['usage']:<44}", PAL["figure"]), (c["description"], PAL["muted"])))

    @on(Input.Submitted, "#cmd")
    def _submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        box = self.query_one("#cmd", CommandInput)
        box.history = [*box.history, text][-200:]
        box.pos = len(box.history)
        box.value = ""
        self.execute(text if text.startswith("/") else f"/ask {text}")

    @work(thread=True, group="console-run")
    def execute(self, text: str) -> None:
        log = self.query_one("#log", RichLog)
        self.ui(log.write, Text(f"\n› {text}", style=f"bold {PAL['heading']}"))
        try:
            out, ok = self.api.command(text)
        except ApiError as exc:
            out, ok = str(exc), False
        self.ui(log.write, pretty(out) if ok else Text(out, style=PAL["flat"]))


# ---------------------------------------------------------------- 9 settings

class SettingsPane(Pane):
    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield section("AI keys (AI analysis, /ask and AI notes)")
            yield Static("", id="ai-status", classes="status")
            yield table("keys", "ID", "Provider", "Key", "Model", "Added", title="AI KEYS")
            with Horizontal(classes="bar"):
                yield Input(placeholder="Paste an AI key (provider is detected), then Enter", password=True, id="key")
                yield Button("Remove selected key", id="key-del", variant="error")
            yield section("Default face")
            with Horizontal(classes="bar"):
                yield Label("`marketmyna` with no command opens:", classes="lbl")
                yield Select([("Web app (browser)", "web"), ("Terminal app", "tui")], allow_blank=False,
                             value="web", id="mode", classes="wide")
                yield Button("Open web app now (w)", id="open-web")
            yield Static("", id="engine", classes="summary")
            yield section("Updates")
            yield Static("", id="upd", classes="summary")
            with Horizontal(classes="bar"):
                yield Button("Check for updates", id="upd-check")
                yield Button("Update now", id="upd-apply", variant="warning")
            yield Static("Notification channels (Telegram, email, push and more), report options and data "
                         "sources are set in the web app: Settings.", classes="status")

    def on_mount(self) -> None:
        from marketmyna.core.ui_mode import saved_mode

        self.query_one("#mode", Select).value = saved_mode()

    def load(self) -> None:
        self.loaded = True
        self.fetch()
        engine = self.app.engine_text()  # type: ignore[attr-defined]
        self.query_one("#engine", Static).update(engine)

    def market_changed(self) -> None:
        pass

    @work(thread=True, exclusive=True, group="settings")
    def fetch(self, force: bool = False) -> None:
        try:
            keys = self.api.get("/api/auth/account/api-keys")
            ai = self.api.get("/agent/status")
        except ApiError as exc:
            self.fail(exc)
            return
        self.ui(self._keys, keys, ai)
        try:
            upd = self.api.get("/system/updates", force=str(force).lower())
        except ApiError as exc:
            upd = {"error": str(exc)}
        self.ui(self._updates, upd)

    def _keys(self, keys: dict, ai: dict) -> None:
        self.query_one("#ai-status", Static).update(
            Text("AI is ready." if ai.get("configured") else "No AI key yet: paste one below. "
                 f"Providers: {', '.join(keys.get('providers', []))}.",
                 style=PAL["up"] if ai.get("configured") else PAL["flat"]))
        t = self.query_one("#keys", DataTable)
        t.clear()
        for k in keys.get("keys", []):
            t.add_row(str(k["id"]), k.get("provider", ""), f"...{k.get('last4', '')}", k.get("model") or "",
                      short_date(k.get("added_at")), key=str(k["id"]))

    def _updates(self, u: dict) -> None:
        if u.get("error"):
            self.query_one("#upd", Static).update(Text(f"Update check failed: {u['error']}", style=PAL["flat"]))
            return
        latest, current = u.get("latest"), u.get("current")
        newer = bool(latest and current and latest != current and u.get("update_available", True))
        msg = f"Installed {current}  ·  latest {latest or '?'}  ·  checked {short_date(u.get('checked_at'))}"
        if isinstance(u.get("checked_at"), (int, float)):
            import datetime as dt

            msg = (f"Installed {current}  ·  latest {latest or '?'}  ·  checked "
                   f"{dt.datetime.fromtimestamp(u['checked_at']).strftime('%Y-%m-%d %H:%M')}")
        if u.get("commands"):
            msg += "\nBy hand: " + "  &&  ".join(u["commands"])
        self.query_one("#upd", Static).update(Text(msg, style=PAL["up"] if newer else PAL["figure"]))

    @on(Input.Submitted, "#key")
    def _add_key(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.write("add", event.value.strip())
            event.input.value = ""

    @on(Button.Pressed, "#key-del")
    def _del_key(self) -> None:
        key = selected_key(self.query_one("#keys", DataTable))
        if key:
            self.write("delete", key)

    @on(Button.Pressed, "#upd-check")
    def _check(self) -> None:
        self.fetch(force=True)

    @on(Button.Pressed, "#upd-apply")
    def _apply(self) -> None:
        self.write("update", "")

    @on(Button.Pressed, "#open-web")
    def _web(self) -> None:
        self.app.action_open_web()  # type: ignore[attr-defined]

    @on(Select.Changed, "#mode")
    def _mode(self, event: Select.Changed) -> None:
        from marketmyna.core.ui_mode import save_mode, saved_mode

        if event.value in ("web", "tui") and event.value != saved_mode():
            save_mode(str(event.value))
            self.app.notify(f"`marketmyna` now opens the {'terminal' if event.value == 'tui' else 'web'} app.",
                            title="MarketMyna")

    @work(thread=True, group="settings-write")
    def write(self, action: str, value: str) -> None:
        try:
            if action == "add":
                out = self.api.put("/api/auth/account/api-keys", {"key": value})
                for err in out.get("errors") or []:
                    self.fail(ApiError(str(err.get("message") if isinstance(err, dict) else err)))
            elif action == "delete":
                self.api.delete(f"/api/auth/account/api-keys/{value}")
            elif action == "update":
                self.say("Updating MarketMyna... this can take a few minutes.")
                out = self.api.post("/system/updates/apply")
                self.say(str(out.get("message") or "Update finished.") if isinstance(out, dict) else "Update finished.")
        except ApiError as exc:
            self.fail(exc)
            return
        self.ui(self.fetch)


# ---------------------------------------------------------------- the app

LOGO_FONT = {
    "M": ["█▄ ▄█", "█ ▀ █", "▀   ▀"], "A": ["▄▀▀▄", "█▀▀█", "▀  ▀"], "R": ["█▀▀▄", "█▀▀▄", "▀  ▀"],
    "K": ["█ ▄▀", "█▀▄ ", "▀  ▀"], "E": ["█▀▀▀", "█▀▀ ", "▀▀▀▀"], "T": ["▀█▀", " █ ", " ▀ "],
    "Y": ["█ █", "▀█▀", " ▀ "], "N": ["█▄ █", "█ ▀█", "▀  ▀"],
}


def logo(word: str = "MARKETMYNA") -> Text:
    """The boot logo in block letters, shaded left to right."""
    rows = ["  ".join(LOGO_FONT[ch][r] for ch in word) for r in range(3)]
    colours = [PAL["heading"], PAL["accent"], PAL["brand2"]]
    out = Text()
    for r, row in enumerate(rows):
        if r:
            out.append("\n")
        out.append_text(gradient(row, colours))
    return out


class MarketMynaTUI(App):
    TITLE = "MarketMyna"
    CSS = """
    Screen { background: $background; }

    /* top bar: brand, live dot, command box, market, clock */
    #topbar { height: 3; background: $bar-bg; }
    #brand { width: auto; padding: 1 1 0 1; }
    #live { width: auto; padding: 1 1 0 1; color: $success; text-style: bold; }
    #cmdbar { width: 1fr; border: round $line; background: $panel-bg; }
    #cmdbar:focus { border: round $glow; }
    #market { width: 20; }
    #market > SelectCurrent { border: round $line; background: $panel-bg; }
    #clock { width: auto; padding: 1 2 0 1; color: $heading; text-style: bold; }
    #tape { height: 1; background: $tape-bg; color: $muted; border-top: none; }

    /* icon rail */
    #rail { width: 8; background: $rail-bg; border-right: tall $rail-edge; }
    #rail-logo { height: 3; content-align: center middle; background: $bar-bg; color: $glow; text-style: bold; }
    #sidebar { background: $rail-bg; color: $rail-fg; padding: 1 0; height: 1fr; }
    #sidebar > ListItem { background: $rail-bg; color: $rail-fg; height: 3; }
    #sidebar > ListItem Label { width: 100%; height: 3; content-align: center middle; text-style: bold; }
    #sidebar > ListItem:hover { background: $rail-hover; }
    #sidebar > ListItem.-highlight { background: $rail-hover; }
    #sidebar > ListItem.active { background: $rail-active-bg; color: $rail-active-fg; }
    #sidebar:focus > ListItem.-highlight { background: $rail-hover; color: $rail-fg; }
    #sidebar:focus > ListItem.active { background: $rail-active-bg; color: $rail-active-fg; }

    #main { width: 1fr; }
    #pagehead { height: 1; padding: 0 1; background: $boost; }

    /* boot screen */
    #boot { align: center middle; height: 1fr; }
    #boot > Static { width: auto; height: auto; }
    #boot-logo { margin-bottom: 1; }
    #boot-sub { color: $muted; margin-bottom: 1; }
    #boot LoadingIndicator { width: 30; height: 1; color: $glow; }
    #connecting { color: $muted; margin-top: 1; }

    /* bottom status bar */
    #statusbar { height: 1; background: $bar-bg; color: $muted; padding: 0 1; }

    /* index cards */
    #cards { height: 10; padding: 0 0 0 1; }
    .card { width: 1fr; height: 9; margin: 1 1 0 0; border: round $line; background: $panel-bg; padding: 0 1; }
    .card:hover { border: round $glow; }
    .card-name { height: 1; }
    .card-price { height: 3; color: $foreground; }
    .card-change { height: 1; }
    .card-spark { height: 2; margin-top: 0; }
    .card Sparkline > .sparkline--max-color { color: $success; }
    .card Sparkline > .sparkline--min-color { color: $success 25%; }
    .card.down Sparkline > .sparkline--max-color { color: $error; }
    .card.down Sparkline > .sparkline--min-color { color: $error 25%; }

    /* panels */
    .bar { height: auto; padding: 0 1; }
    .bar > Input { width: 1fr; }
    .bar > Button { margin: 1 0 0 1; }
    .buttons { height: auto; padding: 1 1 0 1; }
    .buttons > Button { margin-right: 1; }
    Input { border: round $line; background: $panel-bg; }
    Input:focus { border: round $glow; }
    Select > SelectCurrent { border: round $line; background: $panel-bg; }
    Select:focus > SelectCurrent { border: round $glow; }
    /* flat one-line buttons, like a terminal's function keys */
    Button { height: 1; min-width: 6; border: none; padding: 0 1; background: $boost; color: $foreground;
             text-style: bold; }
    Button:hover { background: $primary 25%; }
    Button:focus { background: $primary 45%; text-style: bold; }
    Button.-primary { background: $primary; color: $background; }
    Button.-warning { background: $warning 20%; color: $warning; }
    Button.-error { background: $error 15%; color: $error; }
    Button.-error:hover { background: $error; color: $background; }
    .narrow { width: 22; }
    .wide { width: 44; }
    .lbl { padding: 1 1 0 0; color: $muted; }
    .section { padding: 1 1 0 1; text-style: bold; color: $heading; }
    .status { padding: 1 1 0 1; color: $muted; width: 1fr; }
    .summary { padding: 1 1; height: auto; color: $figure; }
    DataTable { height: 1fr; margin: 1 1 0 1; border: round $line; background: $panel-bg;
                border-title-color: $heading; border-title-style: bold; scrollbar-size-vertical: 1; }
    DataTable:focus { border: round $glow; }
    DataTable > .datatable--header { background: $boost; color: $heading; text-style: bold; }
    DataTable > .datatable--even-row { background: $row-even; }
    DataTable > .datatable--cursor { background: $primary 30%; }
    DataTable > .datatable--hover { background: $primary 12%; }
    #indices { height: 12; }
    #matches { height: 10; }
    #keys { height: 8; }
    #events { height: 9; }
    #txns { height: 11; }
    RichLog { height: 1fr; margin: 1 1 0 1; border: round $line; background: $panel-bg; padding: 0 1;
              border-title-color: $heading; border-title-style: bold; scrollbar-size-vertical: 1; }
    RichLog:focus { border: round $glow; }
    Footer { background: $bar-bg; }
    Footer .footer-key--key { color: $heading; background: $bar-bg; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("colon", "focus_command", "Command"),
        Binding("w", "open_web", "Browser"),
        Binding("m", "next_market", "Market"),
        Binding("r", "refresh", "Refresh"),
        Binding("t", "cycle_theme", "Theme"),
        Binding("escape", "focus_menu", "Menu", show=False),
        *[Binding(str(i + 1), f"tab('{key}')", label, show=False) for i, (key, label, _, _) in enumerate(TABS)],
    ]

    def __init__(self, host: str = "127.0.0.1", port: int = 8001, url: str | None = None) -> None:
        super().__init__()
        self.host, self.port = host, port
        self.fixed_url = url
        self.market = "india"
        self.tab = "markets"
        self.api: Api = None  # type: ignore[assignment]
        self.server = None
        self.url = ""
        self.exit_message = ""
        self.tape_text = Text()
        self.tape_pos = 0
        from marketmyna.core.home import app_home

        self.log_file = app_home() / "logs" / "tui-server.log"
        self.look = saved_theme()
        for name in look.THEMES:
            self.register_theme(look.textual_theme(name))
        self.theme = look.use(self.look)

    def get_theme_variable_defaults(self) -> dict[str, str]:
        # Our own CSS variables, so any theme (even a built-in one) can draw the app.
        return dict(look.THEMES[look.DEFAULT]["vars"])

    # -- layout
    def compose(self) -> ComposeResult:
        kind = icon_set()
        with Horizontal(id="topbar"):
            yield Static("", id="brand")
            yield Static("○ BOOT", id="live")
            yield Input(placeholder="›  symbol (RELIANCE, AAPL), /command, or PF SCR WL AL", id="cmdbar")
            yield Select(MARKETS, value="india", allow_blank=False, id="market")
            yield Static("", id="clock")
        yield Static("", id="tape")
        with Horizontal(id="body"):
            with Vertical(id="rail"):
                yield Static("◆", id="rail-logo")
                yield ListView(
                    *[self._menu_item(i, key, label, icon(key, sym, plain, kind))
                      for i, (key, label, sym, plain) in enumerate(TABS)],
                    id="sidebar")
            with Vertical(id="main"):
                yield Static("", id="pagehead")
                with Vertical(id="boot"):
                    yield Static("", id="boot-logo")
                    yield Static("", id="boot-sub")
                    yield LoadingIndicator()
                    yield Static("Starting the engine: market data, scheduler, alerts...", id="connecting")
                with ContentSwitcher(initial="p-markets", id="tabs"):
                    yield MarketsPane(id="p-markets")
                    yield StockPane(id="p-stock")
                    yield ScreenerPane(id="p-screener")
                    yield WatchlistsPane(id="p-watchlists")
                    yield PortfolioPane(id="p-portfolio")
                    yield AlertsPane(id="p-alerts")
                    yield ReportsPane(id="p-reports")
                    yield ConsolePane(id="p-console")
                    yield SettingsPane(id="p-settings")
        yield Static("", id="statusbar")
        yield Footer()

    @staticmethod
    def _menu_item(i: int, key: str, label: str, glyph: str) -> ListItem:
        """Icon only; the name shows as a tooltip and in the page title."""
        item = ListItem(Label(glyph), id=f"nav-{key}", classes="active" if i == 0 else "")
        item.tooltip = f"{label}  ({i + 1})"
        return item

    def on_mount(self) -> None:
        self.query_one("#tabs").display = False
        self._paint()
        self._tick()
        self.set_interval(1, self._tick)
        self.set_interval(0.12, self._scroll_tape)
        self.set_interval(60, self._tape_refresh)
        self.connect()

    def _paint(self) -> None:
        """Text drawn in Python follows the theme: redraw it after a theme change."""
        self.query_one("#brand", Static).update(
            Text.assemble(("◆ ", PAL["brand2"]), gradient("MARKETMYNA", [PAL["heading"], PAL["accent"]]),
                          (" TERMINAL", f"bold {PAL['muted']}")))
        self.query_one("#boot-logo", Static).update(logo())
        self.query_one("#boot-sub", Static).update(
            Text("M A R K E T S   ·   R E S E A R C H   ·   T E R M I N A L", style=PAL["muted"]))
        self._head()
        self._status("READY" if self.api is not None else "STARTING")
        if not self.tape_text.plain:
            self.tape_text = Text("  ◆ MARKETMYNA  ·  bullish / neutral / bearish, never buy or sell calls  ",
                                  style=PAL["muted"])

    def _tick(self) -> None:
        import datetime as dt

        for clock in self.query("#clock"):  # empty while the app is closing
            clock.update(dt.datetime.now().strftime("%d %b %y  %H:%M:%S").upper())

    def _head(self) -> None:
        label = next(lbl for key, lbl, _, _ in TABS if key == self.tab)
        self.query_one("#pagehead", Static).update(
            Text.assemble(("◢ ", PAL["heading"]), (label.upper(), f"bold {PAL['heading']}"), ("  ›  ", PAL["muted"]),
                          (MARKET_LABEL.get(self.market, self.market).upper(), f"bold {PAL['fg']}")))

    def _status(self, state: str) -> None:
        from marketmyna import __version__

        codes = "  ".join(MARKET_CODES.values())
        engine = ("ENGINE HERE" if self.server else "JOINED") + f" {self.url}" if self.url else "ENGINE ..."
        left = f"v{__version__}  │  {codes}  │  {engine}  │  theme {self.look}  │  : command  1-9 menu  t theme"
        colour = PAL["up"] if state == "READY" else PAL["flat"]
        width = max(self.size.width - 2, len(left) + len(state) + 4)
        self.query_one("#statusbar", Static).update(
            Text.assemble(left, " " * (width - len(left) - len(state) - 2), ("● ", colour), (state, f"bold {colour}")))

    def on_resize(self) -> None:
        self._status("READY" if self.api is not None else "STARTING")

    # -- ticker tape
    def set_tape(self, board: dict) -> None:
        parts = Text()
        for group in board.get("groups", []):
            for item in group.get("items", []):
                if item.get("price") is None:
                    continue
                pct = item.get("change_pct") or 0
                colour = PAL["up"] if pct > 0 else PAL["down"] if pct < 0 else PAL["muted"]
                parts.append(f"  {str(item.get('label') or item.get('key')).upper()} ", style=f"bold {PAL['fg']}")
                parts.append(num(item.get("price")) + "  ", style=PAL["figure"])
                parts.append(f"{'▲' if pct > 0 else '▼' if pct < 0 else '■'} {pct:+.2f}%", style=colour)
                parts.append("   ◆", style=PAL["muted"])
        if parts.plain:
            self.tape_text = parts

    def _scroll_tape(self) -> None:
        text = self.tape_text
        if not text.plain:
            return
        width = max(self.size.width, 1)
        loop = text.copy()
        while len(loop.plain) < width + len(text.plain):
            loop.append_text(text)
        self.tape_pos = (self.tape_pos + 1) % len(text.plain)
        for tape in self.query("#tape"):  # empty while the app is closing
            tape.update(loop[self.tape_pos:self.tape_pos + width])

    def _tape_refresh(self) -> None:
        if self.api is not None and self.tab != "markets":  # the Markets page refreshes it itself
            self.fetch_tape(self.market)

    @work(thread=True, exclusive=True, group="tape")
    def fetch_tape(self, market: str) -> None:
        try:
            board = self.api.get("/macro/indices", market=market)
        except ApiError:
            return
        self.call_from_thread(self.set_tape, board)

    @work(thread=True, exclusive=True, group="connect")
    def connect(self) -> None:
        try:
            if self.fixed_url:
                url, server = self.fixed_url, None
            else:
                from marketmyna.tui.server import connect

                url, server = connect(self.host, self.port, self.log_file)
        except Exception as exc:  # noqa: BLE001 - shown on screen
            self.call_from_thread(self.query_one("#connecting", Static).update,
                                  Text(f"Could not start MarketMyna: {exc}\nLog: {self.log_file}\nPress q to quit.",
                                       style=PAL["down"]))
            self.call_from_thread(self._status, "ERROR")
            return
        self.url, self.server = url, server
        self.api = Api(url)
        if server is not None:
            from marketmyna.api.v1.endpoints import updates

            updates.RESTART_HANDLERS.append(self._updated)
        self.call_from_thread(self._connected)

    def _connected(self) -> None:
        self.sub_title = self.url
        self.query_one("#boot").display = False
        self.query_one("#tabs").display = True
        self.query_one("#live", Static).update("● LIVE")
        self._status("READY")
        self.query_one("#sidebar", ListView).focus()
        self._load_active()

    def engine_text(self) -> Text:
        if self.server:
            how = ("This terminal runs the MarketMyna engine (scheduler, alerts, bot). Closing it stops them;\n"
                   "for an always-on engine run `marketmyna web --no-browser` and connect with `marketmyna tui`.")
        else:
            how = "Joined a MarketMyna engine that is already running (web app and terminal share it)."
        return Text(f"Engine: {self.url}\n{how}\nServer log: {self.log_file}")

    def _updated(self) -> None:
        self.exit_message = "MarketMyna was updated. Start it again: marketmyna tui"
        self.call_from_thread(self.exit)

    # -- navigation
    def _pane(self, tab: str) -> Pane:
        return self.query_one(f"#p-{tab}", Pane)

    def _load_active(self) -> None:
        if self.api is None:
            return
        pane = self._pane(self.tab)
        if not pane.loaded:
            pane.load()

    @on(ListView.Selected, "#sidebar")
    def _menu(self, event: ListView.Selected) -> None:
        if event.item is not None and event.item.id:
            self.action_tab(event.item.id.removeprefix("nav-"))

    def action_tab(self, tab: str) -> None:
        self.tab = tab
        self.query_one("#tabs", ContentSwitcher).current = f"p-{tab}"
        menu = self.query_one("#sidebar", ListView)
        keys = [k for k, _, _, _ in TABS]
        for item in menu.children:
            item.set_class(item.id == f"nav-{tab}", "active")
        if menu.index != keys.index(tab):
            menu.index = keys.index(tab)
        self._head()
        self._load_active()

    def action_focus_command(self) -> None:
        self.query_one("#cmdbar", Input).focus()

    def action_focus_menu(self) -> None:
        self.query_one("#sidebar", ListView).focus()

    @on(Input.Submitted, "#cmdbar")
    def _command_bar(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or self.api is None:
            return
        if text.startswith("/"):
            self.run_console(text)
            return
        jump = {"MKT": "markets", "SCR": "screener", "WL": "watchlists", "PF": "portfolio", "AL": "alerts",
                "RPT": "reports", "CON": "console", "SET": "settings"}
        if text.upper() in jump:
            self.action_tab(jump[text.upper()])
            return
        self.action_tab("stock")
        self._pane("stock").search(text)  # type: ignore[attr-defined]

    @on(Select.Changed, "#market")
    def _market(self, event: Select.Changed) -> None:
        if picked(event.select) is None or event.value == self.market:
            return
        self.market = str(event.value)
        self._head()
        if self.api is None:
            return
        for pane in self.query(Pane):
            pane.market_changed()

    def action_next_market(self) -> None:
        values = [v for _, v in MARKETS]
        self.query_one("#market", Select).value = values[(values.index(self.market) + 1) % len(values)]

    def action_refresh(self) -> None:
        if self.api is not None:
            self._pane(self.tab).load()

    def open_stock(self, symbol: str, market: str) -> None:
        self.action_tab("stock")
        self._pane("stock").open(symbol, market)  # type: ignore[attr-defined]

    def run_console(self, text: str) -> None:
        self.action_tab("console")
        self._pane("console").execute(text)  # type: ignore[attr-defined]

    def open_web(self, path: str = "/") -> None:
        if not self.url:
            return
        webbrowser.open(self.url + path)
        self.notify(f"Opened {self.url + path} in your browser: same data, same engine.", title="MarketMyna")

    def action_open_web(self) -> None:
        self.open_web("/")

    def action_cycle_theme(self) -> None:
        self.look = look.ORDER[(look.ORDER.index(self.look) + 1) % len(look.ORDER)]
        self.theme = look.use(self.look)
        save_theme(self.look)
        self.tape_text = Text()
        self._paint()
        for card in self.query(IndexCard):
            card.display = False
        if self.api is not None:
            self._pane(self.tab).load()
        self.notify(f"Theme: {self.look}  (t for the next one)", title="MarketMyna", timeout=3)

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState

        if event.state == WorkerState.ERROR:
            self.notify(f"Something went wrong: {event.worker.error}", title="MarketMyna", severity="error",
                        timeout=10)

    # -- shutdown
    def on_unmount(self) -> None:
        if self.api is not None:
            self.api.close()


def run(host: str = "127.0.0.1", port: int = 8001, url: str | None = None) -> str:
    """Run the terminal app; returns a message to print after the screen is restored."""
    app = MarketMynaTUI(host=host, port=port, url=url)
    app.run()
    if app.server is not None:
        print("Stopping the MarketMyna engine...")
        app.server.stop()
    return app.exit_message
