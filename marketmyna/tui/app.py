"""MarketMyna in the terminal (Textual).

    marketmyna tui

Same engine as the web app: this app joins a MarketMyna server that is
already running, or starts one inside this process. Press w to open the same
running app in your browser; your data is shared because it is one server.

Directions are bullish / neutral / bearish only: no buy / sell calls, targets
or stops, the same as everywhere else in MarketMyna.
"""

from __future__ import annotations

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
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from marketmyna.tui.client import Api, ApiError

MARKETS = [("India", "india"), ("US", "us"), ("China A", "china_a"), ("Hong Kong", "hong_kong"), ("Crypto", "crypto")]
MARKET_LABEL = {v: k for k, v in MARKETS}
CURRENCY = {"india": "INR", "us": "USD", "china_a": "CNY", "hong_kong": "HKD", "crypto": "USD"}

TABS = [
    ("markets", "1 Markets"), ("stock", "2 Stock"), ("screener", "3 Screener"), ("watchlists", "4 Watchlists"),
    ("portfolio", "5 Portfolio"), ("alerts", "6 Alerts"), ("reports", "7 Reports"), ("console", "8 Console"),
    ("settings", "9 Settings"),
]


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
    style = "green" if x > 0 else "red" if x < 0 else ""
    return Text(f"{x:+,.{digits}f}{suffix}", style=style)


def short_date(v: Any) -> str:
    return str(v or "-")[:16].replace("T", " ")


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


def table(id: str, *columns: str) -> DataTable:
    t = DataTable(id=id, cursor_type="row", zebra_stripes=True)
    t.add_columns(*columns)
    return t


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

class MarketsPane(Pane):
    def compose(self) -> ComposeResult:
        with Horizontal(classes="bar"):
            yield Label("Stocks to watch:", classes="lbl")
            yield Select([("Today", "day"), ("This week", "week"), ("This month", "month")], value="day",
                         allow_blank=False, id="period", classes="narrow")
            yield Button("Refresh (r)", id="refresh")
            yield Static("", id="mk-status", classes="status")
        yield Label("Index board", classes="section")
        yield table("indices", "Group", "Index", "Price", "Change", "Change %", "Day low", "Day high")
        yield Label("Stocks to watch (Enter opens the stock)", classes="section")
        yield table("watch", "List", "Symbol", "Name", "Price", "Change %", "Why it is on the list")

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
        yield table("matches", "Symbol", "Name", "Market", "Type", "Exchange", "Price")
        with Horizontal(classes="buttons"):
            for label, key in SECTIONS:
                yield Button(label, id=f"sec-{key}", classes="small")
            yield Button("+ Watchlist", id="watch-add", classes="small", variant="primary")
        yield RichLog(id="out", wrap=True, markup=False, highlight=False)

    def on_mount(self) -> None:
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
        self.ui(out.write, Text(f"{label} · {symbol} · {MARKET_LABEL.get(market, market)}", style="bold"))
        self.ui(out.write, Text(text, style="" if ok else "yellow"))

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
                    "Ethical")

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
        yield table("items", "Symbol", "Name", "Market", "Price", "Change %", "52w low", "52w high", "Note")

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
        yield table("holdings", "Symbol", "Market", "Quantity", "Avg cost", "Price", "Value", "Gain", "Gain %")
        with Horizontal(classes="bar"):
            yield Input(placeholder="Symbol", id="t-sym", classes="narrow")
            yield Select([("Buy", "buy"), ("Sell", "sell"), ("Dividend", "dividend")], value="buy",
                         allow_blank=False, id="t-type", classes="narrow")
            yield Input(placeholder="Quantity", id="t-qty", type="number", classes="narrow")
            yield Input(placeholder="Price", id="t-price", type="number", classes="narrow")
            yield Input(placeholder="Date YYYY-MM-DD (optional)", id="t-date", classes="narrow")
            yield Button("Add transaction", id="t-add", variant="primary")
        yield Label("Transactions (select one, then Delete transaction)", classes="section")
        with Horizontal(classes="bar"):
            yield Button("Delete transaction", id="t-del", variant="error")
            yield Button("Delete portfolio", id="pf-del", variant="error")
        yield table("txns", "#", "Date", "Type", "Symbol", "Quantity", "Price", "Total")

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
        yield table("alerts", "ID", "Symbol", "Market", "Condition", "Status", "Last value", "Triggered", "Note")
        yield Label("Recent triggers", classes="section")
        yield table("events", "When", "Symbol", "Message")

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
        yield Label("Saved reports (Enter opens the full table in your browser)", classes="section")
        yield table("reports", "Created", "Title", "Stocks")

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
                          ("on" if s.get("enabled") else "off", "green" if s.get("enabled") else "yellow"),
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
        yield RichLog(id="log", wrap=True, markup=False, highlight=False)
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
                self.ui(log.write, Text(f"\n{group}", style="bold cyan"))
            self.ui(log.write, Text.assemble((f"  {c['usage']:<44}", "green"), c["description"]))

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
        self.ui(log.write, Text(f"\n> {text}", style="bold magenta"))
        try:
            out, ok = self.api.command(text)
        except ApiError as exc:
            out, ok = str(exc), False
        self.ui(log.write, Text(out, style="" if ok else "yellow"))


# ---------------------------------------------------------------- 9 settings

class SettingsPane(Pane):
    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Label("AI keys (used for AI analysis, /ask and AI notes)", classes="section")
            yield Static("", id="ai-status", classes="status")
            yield table("keys", "ID", "Provider", "Key", "Model", "Added")
            with Horizontal(classes="bar"):
                yield Input(placeholder="Paste an AI key (provider is detected), then Enter", password=True, id="key")
                yield Button("Remove selected key", id="key-del", variant="error")
            yield Label("Default face", classes="section")
            with Horizontal(classes="bar"):
                yield Label("`marketmyna` with no command opens:", classes="lbl")
                yield Select([("Web app (browser)", "web"), ("Terminal app", "tui")], allow_blank=False,
                             value="web", id="mode", classes="wide")
                yield Button("Open web app now (w)", id="open-web")
            yield Static("", id="engine", classes="summary")
            yield Label("Updates", classes="section")
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
                 style="green" if ai.get("configured") else "yellow"))
        t = self.query_one("#keys", DataTable)
        t.clear()
        for k in keys.get("keys", []):
            t.add_row(str(k["id"]), k.get("provider", ""), f"...{k.get('last4', '')}", k.get("model") or "",
                      short_date(k.get("added_at")), key=str(k["id"]))

    def _updates(self, u: dict) -> None:
        if u.get("error"):
            self.query_one("#upd", Static).update(Text(f"Update check failed: {u['error']}", style="yellow"))
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
        self.query_one("#upd", Static).update(Text(msg, style="green" if newer else ""))

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

class MarketMynaTUI(App):
    TITLE = "MarketMyna"
    CSS = """
    Screen { background: $surface; }
    .bar { height: auto; padding: 0 1; }
    .bar > Input { width: 1fr; }
    .bar > Button { margin-left: 1; }
    .buttons { height: auto; padding: 0 1; }
    .buttons > Button { margin-right: 1; min-width: 8; }
    Button.small { height: 3; }
    .narrow { width: 22; }
    .wide { width: 44; }
    .lbl { padding: 1 1 0 0; }
    .section { padding: 1 1 0 1; text-style: bold; color: $accent; }
    .status { padding: 1 1 0 1; color: $text-muted; width: 1fr; }
    .summary { padding: 1 1; height: auto; }
    DataTable { height: 1fr; margin: 0 1; }
    #indices { height: 12; }
    #matches { height: 10; }
    #keys { height: 7; }
    #events { height: 8; }
    #txns { height: 10; }
    RichLog { height: 1fr; margin: 0 1; border: round $panel; }
    #topbar { height: auto; padding: 0 1; background: $boost; }
    #topbar > Static { width: 1fr; padding: 1 1 0 1; }
    #market { width: 26; }
    #connecting { padding: 2 4; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("w", "open_web", "Open in browser"),
        Binding("m", "next_market", "Next market"),
        Binding("r", "refresh", "Refresh"),
        Binding("d", "toggle_dark", "Light / dark"),
        *[Binding(str(i + 1), f"tab('{key}')", label, show=False) for i, (key, label) in enumerate(TABS)],
    ]

    def __init__(self, host: str = "127.0.0.1", port: int = 8001, url: str | None = None) -> None:
        super().__init__()
        self.host, self.port = host, port
        self.fixed_url = url
        self.market = "india"
        self.api: Api = None  # type: ignore[assignment]
        self.server = None
        self.url = ""
        self.exit_message = ""
        from marketmyna.core.home import app_home

        self.log_file = app_home() / "logs" / "tui-server.log"

    # -- layout
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="topbar"):
            yield Select(MARKETS, value="india", allow_blank=False, id="market")
            yield Static("Connecting...", id="engine-line")
        yield Static("Starting the MarketMyna engine (first start can take a minute)...", id="connecting")
        with TabbedContent(id="tabs"):
            with TabPane(TABS[0][1], id="markets"):
                yield MarketsPane()
            with TabPane(TABS[1][1], id="stock"):
                yield StockPane()
            with TabPane(TABS[2][1], id="screener"):
                yield ScreenerPane()
            with TabPane(TABS[3][1], id="watchlists"):
                yield WatchlistsPane()
            with TabPane(TABS[4][1], id="portfolio"):
                yield PortfolioPane()
            with TabPane(TABS[5][1], id="alerts"):
                yield AlertsPane()
            with TabPane(TABS[6][1], id="reports"):
                yield ReportsPane()
            with TabPane(TABS[7][1], id="console"):
                yield ConsolePane()
            with TabPane(TABS[8][1], id="settings"):
                yield SettingsPane()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#tabs").display = False
        self.connect()

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
                                       style="red"))
            return
        self.url, self.server = url, server
        self.api = Api(url)
        if server is not None:
            from marketmyna.api.v1.endpoints import updates

            updates.RESTART_HANDLERS.append(self._updated)
        self.call_from_thread(self._connected)

    def _connected(self) -> None:
        self.sub_title = self.url
        self.query_one("#connecting").display = False
        self.query_one("#tabs").display = True
        self.query_one("#engine-line", Static).update(
            f"{'Engine in this terminal' if self.server else 'Joined the running app'} at {self.url}"
            "  ·  w: same app in your browser  ·  1-9: tabs  ·  m: market")
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
        return self.query_one(f"#{tab}", TabPane).query_one(Pane)

    def _load_active(self) -> None:
        if self.api is None:
            return
        tab = self.query_one("#tabs", TabbedContent).active
        if tab:
            pane = self._pane(tab)
            if not pane.loaded:
                pane.load()

    @on(TabbedContent.TabActivated)
    def _tab_changed(self) -> None:
        self._load_active()

    def action_tab(self, tab: str) -> None:
        if self.api is not None:
            self.query_one("#tabs", TabbedContent).active = tab

    @on(Select.Changed, "#market")
    def _market(self, event: Select.Changed) -> None:
        if picked(event.select) is None or event.value == self.market:
            return
        self.market = str(event.value)
        if self.api is None:
            return
        for pane in self.query(Pane):
            pane.market_changed()

    def action_next_market(self) -> None:
        values = [v for _, v in MARKETS]
        self.query_one("#market", Select).value = values[(values.index(self.market) + 1) % len(values)]

    def action_refresh(self) -> None:
        if self.api is None:
            return
        tab = self.query_one("#tabs", TabbedContent).active
        if tab:
            self._pane(tab).load()

    def open_stock(self, symbol: str, market: str) -> None:
        self.query_one("#tabs", TabbedContent).active = "stock"
        self._pane("stock").open(symbol, market)  # type: ignore[attr-defined]

    def run_console(self, text: str) -> None:
        self.query_one("#tabs", TabbedContent).active = "console"
        pane = self._pane("console")
        if not pane.loaded:
            pane.load()
        pane.execute(text)  # type: ignore[attr-defined]

    def open_web(self, path: str = "/") -> None:
        if not self.url:
            return
        webbrowser.open(self.url + path)
        self.notify(f"Opened {self.url + path} in your browser: same data, same engine.", title="MarketMyna")

    def action_open_web(self) -> None:
        self.open_web("/")

    def action_toggle_dark(self) -> None:
        self.theme = "textual-light" if self.theme != "textual-light" else "textual-dark"

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
