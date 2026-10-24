"""Telegram bot: only the owner's chat runs commands; token changes apply live."""

import tempfile
from dataclasses import replace
from pathlib import Path

from src.bot.models import CommandResult
from src.bot.telegram_listener import TelegramListener
from src.core.config import Config
from src.notifiers.telegram import TelegramSender


class FakeDispatcher:
    def __init__(self):
        self.seen = []

    def dispatch(self, incoming):
        self.seen.append(incoming.text)
        return CommandResult(text=f"ran {incoming.text}")


def _listener(chat_id=None):
    # Own db: the listener also checks testers' linked chats (telegram_subscribers).
    db_path = Path(tempfile.mkdtemp()) / "t.db"
    config = replace(Config(), telegram_bot_token="t", telegram_chat_id=chat_id, db_path=db_path)
    d = FakeDispatcher()
    listener = TelegramListener(config, d)
    replies = []
    listener._reply = lambda chat, text: replies.append((chat, text))
    return config, listener, d, replies


def _msg(chat, text):
    return {"chat": {"id": chat}, "from": {"id": chat}, "text": text}


def test_owner_runs_commands_strangers_do_not():
    _, listener, d, replies = _listener("111")
    listener._handle_message(_msg(111, "/risk"))
    assert d.seen == ["/risk"] and replies[-1] == ("111", "ran /risk")
    listener._handle_message(_msg(999, "/risk"))
    assert d.seen == ["/risk"] and len(replies) == 1  # ignored silently
    listener._handle_message(_msg(999, "/start"))
    assert d.seen == ["/risk"] and "Your chat ID is 999" in replies[-1][1]


def test_setup_mode_reveals_chat_id_and_runs_nothing():
    _, listener, d, replies = _listener(None)
    listener._handle_message(_msg(555, "hello"))
    assert d.seen == [] and "Your chat ID is 555" in replies[-1][1]


def test_start_confirms_connection_and_several_chats_allowed():
    _, listener, d, replies = _listener("111, -1002")
    listener._handle_message(_msg(111, "/start"))
    assert "Connected" in replies[-1][1] and d.seen == []
    listener._handle_message(_msg(-1002, "/alerts"))
    assert d.seen == ["/alerts"]


def test_token_saved_later_is_picked_up():
    config = replace(Config(), telegram_bot_token=None, telegram_chat_id="1")
    listener = TelegramListener(config, FakeDispatcher())
    assert not listener.is_configured()
    config.telegram_bot_token = "new"  # what Settings -> Save does to the shared config
    assert listener.is_configured() and listener._bot_token == "new"


def test_sender_sends_to_every_chat(monkeypatch):
    sent = []

    class Resp:
        status_code = 200
        text = "ok"

    monkeypatch.setattr("src.notifiers.telegram.requests.post", lambda url, json, timeout: sent.append(json["chat_id"]) or Resp())
    assert TelegramSender(Config(telegram_bot_token="t", telegram_chat_id="1, 2")).send("hi")
    assert sent == ["1", "2"]


def test_settings_reject_bot_number_as_chat_id(tmp_path, login_as):
    import pytest

    testclient = pytest.importorskip("fastapi.testclient")
    from fastapi import FastAPI

    from api.deps import get_config_dep
    from api.v1.endpoints import system_config

    config = replace(Config(), app_dir=tmp_path, telegram_bot_token="8568520747:AAsecret")
    app = FastAPI()
    app.include_router(system_config.router, prefix="/api/v1")
    app.dependency_overrides[get_config_dep] = lambda: config
    client = testclient.TestClient(app)
    login_as(client)
    r = client.put("/api/v1/system-config/notifications", json={"telegram_chat_id": "8568520747"})
    assert r.status_code == 400 and "bot's own number" in r.json()["detail"]
    assert client.put("/api/v1/system-config/notifications", json={"telegram_chat_id": "123456"}).status_code == 200
