"""config.json keeps keys, tokens and passwords encrypted at rest."""

from __future__ import annotations

import json
import os
import stat

from src.core.config import Config
from src.core.secret_store import PREFIX, SECRET_FIELDS


def _write(tmp_path, **values):
    config = Config(app_dir=tmp_path, data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    for k, v in values.items():
        setattr(config, k, v)
    config.save(tmp_path / "config.json")
    return json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))


def test_secrets_are_encrypted_on_disk_and_decrypted_on_load(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    tmp_path.joinpath(".marketmyna").mkdir()
    app = tmp_path / ".marketmyna"
    on_disk = _write(app, finnhub_api_key="fh_secret_123", angel_totp_secret="JBSWY3DPEHPK3PXP",
                     llm_api_keys=["llm-key-one", "llm-key-two"], email_password="app-pass", email_sender="me@example.org",
                     angel_client_code="A123")
    text = (app / "config.json").read_text(encoding="utf-8")
    for secret in ("rzp_secret_123", "JBSWY3DPEHPK3PXP", "llm-key-one", "app-pass"):
        assert secret not in text
    assert on_disk["finnhub_api_key"].startswith(PREFIX) and on_disk["llm_api_keys"].startswith(PREFIX)
    # Identifiers that aren't secrets stay readable.
    assert on_disk["email_sender"] == "me@example.org" and on_disk["angel_client_code"] == "A123"
    if os.name != "nt":  # Windows has no owner-only mode bits; the user's profile folder is private instead
        assert stat.S_IMODE((app / "config.json").stat().st_mode) == 0o600
        assert stat.S_IMODE((app / "secret.key").stat().st_mode) == 0o600

    loaded = Config.load(app / "config.json")
    assert loaded.finnhub_api_key == "fh_secret_123" and loaded.llm_api_keys == ["llm-key-one", "llm-key-two"]
    assert loaded.angel_totp_secret == "JBSWY3DPEHPK3PXP" and loaded._plaintext_secrets is False


def test_plain_text_secrets_are_flagged_and_encrypted_on_next_save(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    app = tmp_path / ".marketmyna"
    app.mkdir()
    (app / "config.json").write_text(json.dumps({"telegram_bot_token": "123:ABC", "theme": "dark"}), encoding="utf-8")
    config = Config.load(app / "config.json")
    assert config.telegram_bot_token == "123:ABC" and config._plaintext_secrets is True
    config.save(app / "config.json")
    assert "123:ABC" not in (app / "config.json").read_text(encoding="utf-8")
    assert Config.load(app / "config.json").telegram_bot_token == "123:ABC"


def test_wrong_key_drops_value_and_env_values_are_never_written(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    app = tmp_path / ".marketmyna"
    app.mkdir()
    _write(app, finnhub_api_key="fh_key")
    (app / "secret.key").write_text("a-different-key", encoding="utf-8")
    assert Config.load(app / "config.json").finnhub_api_key is None

    monkeypatch.setenv("ANGEL_API_KEY", "from-env")
    config = Config.load(app / "config.json")
    assert config.angel_api_key == "from-env"
    config.save(app / "config.json")
    # The file keeps what it had before (empty here); the env value is never written.
    assert "from-env" not in (app / "config.json").read_text(encoding="utf-8")
    assert json.loads((app / "config.json").read_text(encoding="utf-8")).get("angel_api_key") is None


def test_every_secret_field_is_a_saved_config_field():
    import inspect
    import re
    from dataclasses import fields

    saved = set(re.findall(r'"(\w+)": self\.\w+', inspect.getsource(Config.save)))
    assert SECRET_FIELDS <= {f.name for f in fields(Config)} and SECRET_FIELDS <= saved
