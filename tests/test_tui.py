"""The terminal app (marketmyna tui), the web / tui switch and the default face."""

import asyncio
import json
import sys

import pytest

from marketmyna import launcher
from marketmyna.core import ui_mode


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETMYNA_HOME", str(tmp_path))
    monkeypatch.delenv("MARKETMYNA_UI", raising=False)
    return tmp_path


# ---------------------------------------------------------------- default face

def test_default_is_web_when_nothing_saved(home):
    assert ui_mode.default_mode() == "web"


def test_save_mode_round_trip(home):
    ui_mode.save_mode("tui")
    assert json.loads((home / "ui.json").read_text()) == {"default": "tui"}
    assert ui_mode.default_mode() == "tui"


def test_save_mode_rejects_unknown(home):
    with pytest.raises(ValueError):
        ui_mode.save_mode("gui")


def test_broken_file_falls_back_to_web(home):
    (home / "ui.json").write_text("not json")
    assert ui_mode.saved_mode() == "web"


def test_env_overrides_saved(home, monkeypatch):
    ui_mode.save_mode("tui")
    monkeypatch.setenv("MARKETMYNA_UI", "web")
    assert ui_mode.default_mode() == "web"


# ---------------------------------------------------------------- launcher

def _tty(monkeypatch, value: bool):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: value, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: value, raising=False)


def test_named_command_wins(home):
    ui_mode.save_mode("tui")
    assert launcher.resolve_mode(launcher.parser().parse_args(["web"])) == "web"


def test_saved_tui_used_in_a_terminal(home, monkeypatch):
    ui_mode.save_mode("tui")
    _tty(monkeypatch, True)
    assert launcher.resolve_mode(launcher.parser().parse_args([])) == "tui"


def test_saved_tui_falls_back_to_web_without_a_terminal(home, monkeypatch):
    ui_mode.save_mode("tui")
    _tty(monkeypatch, False)
    assert launcher.resolve_mode(launcher.parser().parse_args([])) == "web"


def test_mode_command_saves(home, capsys):
    launcher.run(launcher.parser().parse_args(["mode", "tui"]))
    assert ui_mode.saved_mode() == "tui"
    assert "terminal app" in capsys.readouterr().out
    launcher.run(launcher.parser().parse_args(["mode"]))
    assert "Default: tui" in capsys.readouterr().out


def test_mode_command_rejects_unknown(home):
    with pytest.raises(SystemExit):
        launcher.run(launcher.parser().parse_args(["mode", "gui"]))


def test_old_options_still_parse():
    args = launcher.parser().parse_args(["--port", "9000", "--no-browser"])
    assert (args.command, args.port, args.no_browser) == (None, 9000, True)


def test_web_rejects_extra_word(home):
    with pytest.raises(SystemExit):
        launcher.run(launcher.parser().parse_args(["web", "extra"]))


# ---------------------------------------------------------------- update restart

def test_restart_calls_handler_instead_of_exec(monkeypatch):
    from marketmyna.api.v1.endpoints import updates

    called = []
    monkeypatch.setattr(updates, "RESTART_HANDLERS", [lambda: called.append(True)])
    monkeypatch.setattr(updates.os, "execv", lambda *a: pytest.fail("must not exec"), raising=False)
    updates.restart("package", delay=0)
    for _ in range(50):
        if called:
            break
        asyncio.run(asyncio.sleep(0.02))
    assert called == [True]


# ---------------------------------------------------------------- the app

class FakeApi:
    """Canned answers for the routes the first tabs call."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.calls: list[tuple[str, str]] = []

    def close(self) -> None:
        pass

    def get(self, path: str, **params):
        self.calls.append(("GET", path))
        if path == "/macro/indices":
            return {"groups": [{"label": "India", "items": [
                {"label": "NIFTY 50", "price": 24000, "change": 120, "change_pct": 0.5}]}]}
        if path == "/listings/watch":
            return {"boards": [{"title": "Gainers", "rows": [
                {"symbol": "TCS", "name": "Tata Consultancy", "price": 4000, "change_percent": 2.1,
                 "why": "up on volume", "market": "india"}]}]}
        if path == "/bot/commands":
            return [{"name": "quote", "group": "Prices", "usage": "/quote SYMBOL", "description": "A quote"}]
        return {}

    def command(self, text: str):
        self.calls.append(("CMD", text))
        return f"ran {text}", True


def test_app_starts_and_fills_markets(monkeypatch, home):
    pytest.importorskip("textual")
    from textual.widgets import DataTable, RichLog

    from marketmyna.tui import app as tui

    monkeypatch.setattr(tui, "Api", FakeApi)

    async def go():
        app = tui.MarketMynaTUI(url="http://127.0.0.1:1")
        async with app.run_test(size=(140, 45)) as pilot:
            for _ in range(100):
                await pilot.pause(0.05)
                if app.api and app._pane("markets").query_one("#watch", DataTable).row_count:
                    break
            assert app.server is None  # joined the given url, started nothing
            pane = app._pane("markets")
            assert pane.query_one("#indices", DataTable).row_count == 1
            assert pane.query_one("#watch", DataTable).row_count == 1

            app.run_console("/quote TCS india")
            for _ in range(100):
                await pilot.pause(0.05)
                if ("CMD", "/quote TCS india") in app.api.calls:
                    break
            await pilot.pause(0.2)
            log = app._pane("console").query_one("#log", RichLog)
            assert any("ran /quote TCS india" in str(line.text) for line in log.lines)

    asyncio.run(go())


def test_no_buy_sell_words_in_tui_text():
    """Directions only: the terminal app never shows buy / sell calls, targets or stops."""
    from pathlib import Path

    import marketmyna.tui.app as tui

    text = Path(tui.__file__).read_text(encoding="utf-8").lower()
    for word in ("target price", "stop loss", "stop-loss", "strong buy", "buy signal", "sell signal"):
        assert word not in text
