"""Tests for LLM routes, failover, key rotation and env-safe config saving."""

import json

import pytest

from src.core.config import Config
from src.llm.channels import (
    FailoverGenerationBackend,
    LLMRoute,
    _Cooldowns,
    build_routes,
    normalize_model,
)
from src.llm.protocol import GenerationConfig, GenerationError, GenerationErrorCode, GenerationResult


class TestRoutes:
    def test_main_then_channels_then_fallbacks(self):
        cfg = Config(llm_model="gemini/gemini-3-flash-preview", llm_api_key="k1", llm_api_keys=["k2", "k1"])
        env = {
            "LLM_CHANNELS": "groq,mygateway,off",
            "LLM_GROQ_API_KEYS": "g1,g2",
            "LLM_GROQ_MODELS": "llama-3.3-70b-versatile",
            "LLM_MYGATEWAY_BASE_URL": "https://gw.example/v1",
            "LLM_MYGATEWAY_API_KEY": "m1",
            "LLM_MYGATEWAY_MODELS": "qwen-max,deepseek/deepseek-chat",
            "LLM_OFF_ENABLED": "false",
            "LLM_OFF_MODELS": "x",
            "LITELLM_FALLBACK_MODELS": "openrouter/auto, gemini/gemini-3-flash-preview",
        }
        routes = build_routes(cfg, env)
        assert [r.label() for r in routes] == [
            "main:gemini/gemini-3-flash-preview",
            "groq:groq/llama-3.3-70b-versatile",
            "mygateway:openai/qwen-max",
            "mygateway:deepseek/deepseek-chat",
            "fallback:openrouter/auto",
        ]
        assert routes[0].api_keys == ["k1", "k2"]
        assert routes[1].api_keys == ["g1", "g2"]
        assert routes[2].api_base == "https://gw.example/v1"

    def test_channel_without_key_or_models_is_skipped(self):
        env = {"LLM_CHANNELS": "groq,ollama", "LLM_GROQ_MODELS": "llama", "LLM_OLLAMA_MODELS": "qwen3:8b"}
        assert [r.label() for r in build_routes(Config(), env)] == ["ollama:ollama/qwen3:8b"]

    def test_nothing_configured(self):
        assert build_routes(Config(), {}) == []

    def test_normalize_model(self):
        assert normalize_model("gpt-4o-mini", "openai") == "openai/gpt-4o-mini"
        assert normalize_model("groq/llama", "openai") == "groq/llama"
        assert normalize_model("deepseek-ai/DeepSeek-V3", "openai") == "openai/deepseek-ai/DeepSeek-V3"


class FakeBackend:
    """Stands in for LiteLLMGenerationBackend; behaviour keyed by (model, key)."""

    calls: list = []
    script: dict = {}

    def __init__(self, cfg):
        self.cfg = cfg

    def generate(self, prompt, generation_config, **kwargs):
        key = (self.cfg.llm_model, self.cfg.llm_api_key)
        FakeBackend.calls.append(key)
        outcome = FakeBackend.script.get(key, "ok")
        if isinstance(outcome, GenerationError):
            raise outcome
        return GenerationResult(text=f"answer from {key}", model=key[0], provider="x", backend="litellm")


def _err(code, fallbackable=True):
    return GenerationError(code, code.value, fallbackable=fallbackable)


@pytest.fixture
def fake():
    FakeBackend.calls = []
    FakeBackend.script = {}
    return FakeBackend


def _backend(routes, fake, cooldowns=None):
    return FailoverGenerationBackend(Config(), routes, backend_factory=fake, cooldowns=cooldowns or _Cooldowns())


class TestFailover:
    def test_rotates_key_then_model(self, fake):
        routes = [LLMRoute("a/main", ["k1", "k2"]), LLMRoute("b/backup", source="fallback")]
        fake.script = {("a/main", "k1"): _err(GenerationErrorCode.RATE_LIMITED),
                       ("a/main", "k2"): _err(GenerationErrorCode.TIMEOUT)}
        result = _backend(routes, fake).generate("hi", GenerationConfig())
        assert result.text == "answer from ('b/backup', None)"
        assert fake.calls == [("a/main", "k1"), ("a/main", "k2"), ("b/backup", None)]
        assert result.diagnostics["route"] == "fallback:b/backup"

    def test_rate_limited_key_cools_down_across_calls(self, fake):
        routes = [LLMRoute("a/main", ["k1"]), LLMRoute("b/backup", source="fallback")]
        fake.script = {("a/main", "k1"): _err(GenerationErrorCode.RATE_LIMITED)}
        backend = _backend(routes, fake)
        backend.generate("one", GenerationConfig())
        fake.calls = []
        backend.generate("two", GenerationConfig())
        assert fake.calls == [("b/backup", None)]  # main skipped while cooling down

    def test_keys_round_robin(self, fake):
        backend = _backend([LLMRoute("a/main", ["k1", "k2"])], fake)
        backend.generate("1", GenerationConfig())
        backend.generate("2", GenerationConfig())
        assert fake.calls == [("a/main", "k1"), ("a/main", "k2")]

    def test_non_fallbackable_stops(self, fake):
        fake.script = {("a/main", None): _err(GenerationErrorCode.INVALID_RESPONSE, fallbackable=False)}
        with pytest.raises(GenerationError):
            _backend([LLMRoute("a/main"), LLMRoute("b/backup")], fake).generate("x", GenerationConfig())
        assert fake.calls == [("a/main", None)]

    def test_all_fail_reports_attempts(self, fake):
        fake.script = {("a/main", None): _err(GenerationErrorCode.TIMEOUT),
                       ("b/backup", None): _err(GenerationErrorCode.UNKNOWN)}
        with pytest.raises(GenerationError, match="All LLM routes failed"):
            _backend([LLMRoute("a/main"), LLMRoute("b/backup", source="fallback")], fake).generate("x", GenerationConfig())

    def test_factory_uses_failover_only_when_configured(self, monkeypatch):
        from src.llm.backend_factory import create_generation_backend
        from src.llm.litellm_backend import LiteLLMGenerationBackend

        monkeypatch.delenv("LLM_CHANNELS", raising=False)
        monkeypatch.delenv("LLM_FALLBACK_MODELS", raising=False)
        monkeypatch.delenv("LITELLM_FALLBACK_MODELS", raising=False)
        assert isinstance(create_generation_backend(Config()), LiteLLMGenerationBackend)
        assert isinstance(create_generation_backend(Config(llm_model="groq/x")), FailoverGenerationBackend)


class TestConfigSave:
    def test_env_values_are_not_written_to_disk(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({"llm_api_key": "saved-in-file", "telegram_chat_id": "1"}), encoding="utf-8")
        cfg = Config(**json.loads(path.read_text(encoding="utf-8"))).apply_env({"LLM_API_KEY": "from-env", "TELEGRAM_BOT_TOKEN": "t0k"})
        assert cfg.llm_api_key == "from-env"
        cfg.telegram_chat_id = "2"  # a normal UI edit
        cfg.save(path)
        saved = json.loads(path.read_text(encoding="utf-8"))
        # The file keeps its own value (encrypted at rest), never the env one.
        from src.core.secret_store import decrypt

        assert decrypt(saved["llm_api_key"], cfg.app_dir, cfg.secret_key) == "saved-in-file"
        assert "telegram_bot_token" not in saved
        assert saved["telegram_chat_id"] == "2"

def test_repeat_failures_back_off_longer_and_success_resets():
    from src.llm.channels import COOLDOWN_SECONDS, MAX_COOLDOWN_SECONDS

    cooldowns = _Cooldowns()
    key = ("a/main", None, 0)
    assert [cooldowns.fail(key) for _ in range(3)] == [COOLDOWN_SECONDS, COOLDOWN_SECONDS * 2, COOLDOWN_SECONDS * 4]
    for _ in range(20):
        last = cooldowns.fail(key)
    assert last == MAX_COOLDOWN_SECONDS and cooldowns.cooling(key)
    cooldowns.ok(key)
    assert not cooldowns.cooling(key)
    assert cooldowns.fail(key) == COOLDOWN_SECONDS


def test_timed_out_model_is_skipped_next_call(fake):
    routes = [LLMRoute("a/main"), LLMRoute("b/backup", source="fallback")]
    fake.script = {("a/main", None): _err(GenerationErrorCode.TIMEOUT)}
    backend = _backend(routes, fake)
    backend.generate("one", GenerationConfig())
    fake.calls = []
    backend.generate("two", GenerationConfig())
    assert fake.calls == [("b/backup", None)]


def test_all_cooling_still_tries(fake):
    cooldowns = _Cooldowns()
    routes = [LLMRoute("a/main"), LLMRoute("b/backup", source="fallback")]
    cooldowns.mark(("a/main", None, 0), 60)
    cooldowns.mark(("b/backup", None, 0), 60)
    result = _backend(routes, fake, cooldowns).generate("x", GenerationConfig())
    assert result.text == "answer from ('a/main', None)"


class TestNewsAgent:
    class _Backend:
        def __init__(self, text=None, error=False):
            self.text, self.error, self.prompts = text, error, []

        def generate(self, prompt, config, system_prompt=None, **kw):
            self.prompts.append(prompt)
            if self.error:
                raise GenerationError(GenerationErrorCode.BACKEND_NOT_CONFIGURED, "No llm_model configured")
            return GenerationResult(text=self.text, model="m", provider="p", backend="b")

    NEWS = [{"title": "Reliance Q2 profit beats estimates", "source": "Mint", "published": "2026-09-24T10:00:00+00:00"},
            {"title": "Jio tariff hike announced", "source": "ET", "published": "2026-09-23T10:00:00+00:00"}]

    def _ctx(self):
        from src.agent.context import AgentContext

        return AgentContext(symbol="RELIANCE", market="india")

    def test_llm_sentiment(self):
        from src.agent.agents import NewsAgent

        backend = self._Backend('{"sentiment": "bullish", "summary": "Earnings beat and tariff hike."}')
        ctx = self._ctx()
        opinion = NewsAgent(search=lambda s, m, limit, name: self.NEWS).run(ctx, backend)
        assert opinion.signal == "bullish"
        assert opinion.summary == "Earnings beat and tariff hike."
        assert ctx.news == self.NEWS
        assert "Reliance Q2 profit beats estimates" in backend.prompts[0]

    def test_without_llm_still_reports_headlines(self):
        from src.agent.agents import NewsAgent

        opinion = NewsAgent(search=lambda s, m, limit, name: self.NEWS).run(self._ctx(), self._Backend(error=True))
        assert opinion.signal is None
        assert "2 recent headlines" in opinion.summary

class TestNewsSearch:
    def test_first_provider_with_results_wins_and_cleans(self, monkeypatch):
        from src.data.news_search import NewsItem, NewsSearchService

        service = NewsSearchService({"BRAVE_API_KEYS": "b1"})
        assert service.provider_names() == ["brave", "google_news", "yahoo"]

        def brave(q, key, limit, days, market):
            raise RuntimeError("quota")

        def google(q, key, limit, days, market):
            return [NewsItem("Reliance Industries Stock Price, News, Quote & History"),
                    NewsItem("Reliance wins order", source="ET", published="2026-09-24T10:00:00+00:00"),
                    NewsItem("Reliance  wins order", source="Mint")]

        service.providers[0].fn = brave
        service.providers[1].fn = google
        items = service.search("Reliance share", ticker="RELIANCE.NS", market="india", limit=5)
        assert [i.title for i in items] == ["Reliance wins order"]  # junk + duplicate dropped
        assert items[0].provider == "google_news"

    def test_news_query(self):
        from src.data.news_search import news_query

        assert news_query("AAPL", "us", name="Apple Inc.") == "Apple stock"
        assert news_query("RELIANCE", "india", name="Reliance Industries Limited") == "Reliance Industries share"
        assert news_query("BTC-USD", "crypto", name="x") == "BTC crypto"
