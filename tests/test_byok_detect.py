"""Provider and model detection for pasted AI keys (no real network)."""

from unittest import mock

import pytest
import requests

from src.services import byok_detect as bd


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


def _fake(routes):
    """routes: url prefix -> _Resp | Exception."""
    def get(url, headers=None, timeout=None):
        for prefix, resp in routes.items():
            if url.startswith(prefix):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected call {url}")
    return mock.patch.object(bd, "_get", side_effect=get)


def test_prefixes():
    assert bd.candidates("AIzaSyX") == ["gemini"]
    assert bd.candidates("gsk_abc") == ["groq"]
    assert bd.candidates("sk-or-v1-abc") == ["openrouter"]
    assert bd.candidates("sk-ant-api03-x") == ["anthropic"]
    assert bd.candidates("sk-proj-abc") == []
    assert bd.candidates("sk-" + "a1" * 16) == []
    assert bd.candidates("x" * 32) == ["mistral"]


def test_gemini_free_model_from_list():
    body = {"models": [{"name": "models/gemini-2.0-flash"}]}
    with _fake({"https://generativelanguage": _Resp(200, body)}):
        d = bd.detect("AIzaSyTest")
    assert (d.provider, d.model, d.free) == ("gemini", "gemini/gemini-2.0-flash", True)


def test_openai_style_key_not_supported():
    with _fake({}), pytest.raises(bd.KeyDetectError, match="OpenAI or DeepSeek"):
        bd.detect("sk-proj-abc")


def test_anthropic_is_paid():
    with _fake({"https://api.anthropic.com": _Resp(200, {"data": [{"id": "claude-haiku-4-5"}]})}):
        d = bd.detect("sk-ant-api03-x")
    assert (d.provider, d.model, d.free) == ("anthropic", "anthropic/claude-haiku-4-5", False)


def test_mistral_free_tier():
    with _fake({"https://api.mistral.ai": _Resp(200, {"data": [{"id": "mistral-small-latest"}]})}):
        d = bd.detect("x" * 32)
    assert (d.provider, d.model, d.free) == ("mistral", "mistral/mistral-small-latest", True)


def test_openrouter_free_tier_picks_free_model():
    models = {"data": [{"id": "deepseek/deepseek-chat-v3-0324:free", "pricing": {"prompt": "0", "completion": "0"}}]}
    with _fake({"https://openrouter.ai/api/v1/key": _Resp(200, {"data": {"is_free_tier": True}}),
                "https://openrouter.ai/api/v1/models": _Resp(200, models)}):
        d = bd.detect("sk-or-v1-abc")
    assert d.model == "openrouter/deepseek/deepseek-chat-v3-0324:free" and d.free is True


def test_rejected_key():
    with _fake({"https://api.groq.com": _Resp(401)}), pytest.raises(bd.KeyDetectError):
        bd.detect("gsk_bad")


def test_unreachable_single_candidate_saved_unverified():
    with _fake({"https://api.groq.com": requests.ConnectionError("down")}):
        d = bd.detect("gsk_x")
    assert d.provider == "groq" and d.verified is False
