"""Bot command registry: every command documented, no alias clashes,
symbol / market parsing, grouped /help and the console's command list."""

from dataclasses import replace

import pytest

from src.bot.commands import common
from src.bot.models import IncomingMessage
from src.bot.registry import build_default_dispatcher
from src.core.config import Config


@pytest.fixture
def dispatcher(tmp_path):
    return build_default_dispatcher(replace(Config(), db_path=tmp_path / "bot.db", app_dir=tmp_path))


def _say(d, text):
    return d.dispatch(IncomingMessage(platform="http", chat_id="t", text=text))


def test_every_command_is_documented(dispatcher):
    for c in dispatcher.list_commands():
        d = c.describe()
        assert d["usage"].startswith(f"/{c.name}"), c.name
        assert d["description"] and d["example"].startswith("/"), c.name
        assert d["group"] != "Other", c.name


def test_no_alias_points_at_two_commands(dispatcher):
    seen: dict[str, str] = {}
    for c in dispatcher.list_commands():
        for word in [c.name, *c.aliases]:
            assert word not in seen, f"/{word} used by {seen[word]} and {c.name}"
            seen[word] = c.name
    assert dispatcher.get_command("a").name == "analyze"


def test_help_is_grouped_and_explains_one_command(dispatcher):
    text = _say(dispatcher, "/help").text
    for heading in ("Stock research", "Markets", "Portfolio", "Trading", "AI analysis", "System"):
        assert heading in text
    assert text.index("Stock research") < text.index("System")
    one = _say(dispatcher, "/help q").text
    assert one.startswith("/quote SYMBOL") and "Example: /quote" in one


def test_missing_symbol_shows_usage(dispatcher):
    r = _say(dispatcher, "/valuation")
    assert not r.success and "Usage: /valuation" in r.text


def test_parse_symbol_market_forms(monkeypatch):
    monkeypatch.setattr(common, "guess_market", lambda sym, config: "india")
    assert common.parse_symbol("aapl us", None) == ("AAPL", "us", [])
    assert common.parse_symbol("us:aapl annual", None) == ("AAPL", "us", ["annual"])
    assert common.parse_symbol("tcs nse quarterly", None) == ("TCS", "india", ["quarterly"])
    assert common.parse_symbol("reliance", None) == ("RELIANCE", "india", [])
    assert common.parse_symbol("BTC-USD", object())[0] == "BTC-USD"


def test_portfolio_commands_without_portfolios(dispatcher):
    assert "No portfolios yet" in _say(dispatcher, "/portfolio").text
    assert "No portfolios yet" in _say(dispatcher, "/review").text
    assert "No watchlists yet" in _say(dispatcher, "/watchlist").text


def test_commands_endpoint_lists_groups_in_order(dispatcher):
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    from fastapi import FastAPI

    from api.deps import get_bot_dispatcher
    from api.middlewares.auth import require_admin
    from api.v1.endpoints import bot

    app = FastAPI()
    app.include_router(bot.router, prefix="/api/v1")
    app.dependency_overrides[get_bot_dispatcher] = lambda: dispatcher
    app.dependency_overrides[require_admin] = lambda: None
    rows = fastapi_testclient.TestClient(app).get("/api/v1/bot/commands").json()
    names = [r["name"] for r in rows]
    assert {"quote", "market", "review", "analyze", "alert", "help"} <= set(names)
    assert rows[0]["group"] == "Stock research" and rows[-1]["group"] == "System"


def test_long_replies_split_for_telegram():
    from src.bot.telegram_listener import split_message

    text = "\n".join(f"line {i} " + "x" * 90 for i in range(100))
    parts = split_message(text)
    assert len(parts) > 1 and all(len(p) <= 4000 for p in parts)
    assert "\n".join(parts) == text
    assert split_message("short") == ["short"]
