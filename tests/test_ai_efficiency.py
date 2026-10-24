"""AI cost controls: provider keys, two model levels, response cache, usage, guardrails."""

from dataclasses import replace

import pytest

from marketmyna.core.config import Config
from marketmyna.llm.channels import (
    FailoverGenerationBackend,
    LLMRoute,
    _Cooldowns,
    build_routes,
    provider_of,
)
from marketmyna.llm.protocol import GenerationConfig, GenerationResult


def test_provider_of():
    assert provider_of("groq/llama-3.3-70b-versatile") == "groq"
    assert provider_of("gpt-4o-mini") == "openai"
    assert provider_of("claude-sonnet-5") == "anthropic"
    assert provider_of("ollama/qwen3:8b") == "ollama"


def test_provider_keys_attach_to_routes():
    cfg = Config(llm_model="gemini/g-main", gemini_api_key="gk", groq_api_key="qk",
                 llm_fallback_models=["groq/fast-one", "ollama/qwen3:8b"], ollama_base_url="http://box:11434")
    routes = {r.model: r for r in build_routes(cfg, {})}
    assert routes["gemini/g-main"].api_keys == ["gk"]
    assert routes["groq/fast-one"].api_keys == ["qk"]
    assert routes["ollama/qwen3:8b"].api_base == "http://box:11434"


def test_explicit_main_key_wins_over_provider_key():
    cfg = Config(llm_model="gemini/g", llm_api_key="explicit", gemini_api_key="provider")
    assert build_routes(cfg, {})[0].api_keys == ["explicit"]


def test_fast_tier_goes_first_then_main_chain():
    cfg = Config(llm_model="gemini/deep", llm_fast_model="groq/fast", llm_fallback_models=["openrouter/x:free"])
    assert [r.label() for r in build_routes(cfg, {}, tier="fast")] == [
        "fast:groq/fast", "main:gemini/deep", "fallback:openrouter/x:free"]
    assert [r.model for r in build_routes(cfg, {}, tier="deep")] == ["gemini/deep", "openrouter/x:free"]


class CountingBackend:
    calls = 0

    def __init__(self, cfg):
        self.cfg = cfg

    def generate(self, prompt, config, **kw):
        CountingBackend.calls += 1
        return GenerationResult(text=f"answer:{prompt}", model=self.cfg.llm_model, provider="p", backend="b",
                                usage={"prompt_tokens": 10, "completion_tokens": 5})


@pytest.fixture
def store(tmp_path):
    from marketmyna.llm.store import LLMStore

    return LLMStore(replace(Config(), db_path=tmp_path / "t.db"))


def test_cache_and_usage(store):
    CountingBackend.calls = 0
    backend = FailoverGenerationBackend(Config(), [LLMRoute("groq/m")], backend_factory=CountingBackend,
                                        cooldowns=_Cooldowns(), store=store, tier="fast")
    first = backend.generate("same prompt", GenerationConfig(), system_prompt="sys")
    second = backend.generate("same prompt", GenerationConfig(), system_prompt="sys")
    backend.generate("other prompt", GenerationConfig(), system_prompt="sys")
    assert CountingBackend.calls == 2  # the repeat came from the cache
    assert second.text == first.text and second.diagnostics["cached"] is True
    usage = {r["route"]: r for r in store.usage()}
    assert usage["fast:groq/m"]["calls"] == 2
    assert usage["fast:groq/m"]["prompt_tokens"] == 20
    assert usage["fast:groq/m"]["cache_hits"] == 1


def test_scope_reuses_answer_when_prompt_numbers_move(store):
    """One stock's stage is answered once per cache lifetime, even as the live
    price in its prompt changes; another stock still gets its own answer."""
    CountingBackend.calls = 0
    backend = FailoverGenerationBackend(Config(), [LLMRoute("groq/m")], backend_factory=CountingBackend,
                                        cooldowns=_Cooldowns(), store=store)
    first = backend.generate("TCS at 4100", GenerationConfig(cache_scope="agent|risk|TCS"), system_prompt="sys")
    again = backend.generate("TCS at 4112", GenerationConfig(cache_scope="agent|risk|TCS"), system_prompt="sys")
    backend.generate("INFY at 1500", GenerationConfig(cache_scope="agent|risk|INFY"), system_prompt="sys")
    assert CountingBackend.calls == 2
    assert again.text == first.text and again.diagnostics["cached"] is True


def test_cache_rows_go_once_past_the_ttl(store):
    from datetime import datetime, timedelta

    from marketmyna.storage import LLMCacheRecord

    with store._db.get_session() as session:
        session.add(LLMCacheRecord(key="old", text="x", model="m", created_at=datetime.now() - timedelta(hours=7)))
        session.add(LLMCacheRecord(key="fresh", text="y", model="m", created_at=datetime.now() - timedelta(hours=5)))
        session.commit()
    store.put("new", "z", "m")  # every write sweeps expired rows
    with store._db.get_session() as session:
        assert sorted(r.key for r in session.query(LLMCacheRecord)) == ["fresh", "new"]


def test_cache_can_be_turned_off(tmp_path):
    from marketmyna.llm.store import LLMStore

    CountingBackend.calls = 0
    off = LLMStore(replace(Config(), db_path=tmp_path / "t.db", llm_cache_hours=0))
    backend = FailoverGenerationBackend(Config(), [LLMRoute("groq/m")], backend_factory=CountingBackend,
                                        cooldowns=_Cooldowns(), store=off)
    backend.generate("p", GenerationConfig())
    backend.generate("p", GenerationConfig())
    assert CountingBackend.calls == 2


def test_factory_builds_fast_backend(monkeypatch, tmp_path):
    from marketmyna.llm.backend_factory import create_generation_backend

    for var in ("LLM_CHANNELS", "LLM_FALLBACK_MODELS", "LITELLM_FALLBACK_MODELS"):
        monkeypatch.delenv(var, raising=False)
    cfg = replace(Config(llm_model="gemini/deep", llm_fast_model="groq/fast"), db_path=tmp_path / "t.db")
    deep = create_generation_backend(cfg)
    assert deep.tier == "deep" and deep.fast is not deep and deep.fast.tier == "fast"
    single = create_generation_backend(replace(cfg, llm_fast_model=None))
    assert single.fast is single


def test_guardrail_and_commentary_use_fast_model():
    from marketmyna.agent.agents import GUARDRAIL, _call_llm, _narrate

    class Recorder:
        def __init__(self, name):
            self.name, self.systems = name, []

        def generate(self, prompt, config, system_prompt=None, **kw):
            self.systems.append(system_prompt)
            return GenerationResult(text=self.name, model=self.name, provider="p", backend="b")

    deep, fast = Recorder("deep"), Recorder("fast")
    deep.fast = fast
    assert _narrate(deep, "Explain.", "data", "fallback") == "fast"  # level-1 job
    assert _call_llm(deep, "Decide.", "data") == "deep"  # decisions stay on the main model
    assert fast.systems[0].endswith(GUARDRAIL) and deep.systems[0].endswith(GUARDRAIL)


def test_openai_compatible_base_url_applies_to_every_openai_route():
    cfg = Config(llm_model="openai/main", llm_fast_model="openai/fast", llm_fallback_models=["openai/backup"],
                 openai_base_url="http://lmstudio:1234/v1", openai_api_key="k")
    for route in build_routes(cfg, {}, tier="fast"):
        assert route.api_base == "http://lmstudio:1234/v1" and route.api_keys == ["k"]
