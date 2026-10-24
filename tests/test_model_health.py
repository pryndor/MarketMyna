"""Retired AI models: picking replacements, healing at runtime, the daily
check, Accept, and hiding superseded models (no real network)."""


import pytest

from src.core.config import Config
from src.llm import model_health
from src.llm.channels import FailoverGenerationBackend, LLMRoute, _Cooldowns
from src.llm.litellm_backend import LiteLLMGenerationBackend
from src.llm.model_catalog import recommend, suggest_replacement, superseded
from src.llm.protocol import (
    GenerationConfig,
    GenerationError,
    GenerationErrorCode,
    GenerationResult,
)
from src.llm.store import clean_error, error_kind

GEMINI = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-flash-latest", "gemini-3-flash-preview",
          "gemini-2.5-flash-lite", "gemini-2.5-flash-preview-09-2025", "gemini-2.5-flash-image",
          "gemini-embedding-001", "gemini-3-pro-preview"]
GROQ = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.1-8b-instant", "whisper-large-v3", "qwen/qwen3-32b"]
GONE = "This model models/gemini-2.5-flash is no longer available to new users."


def _gone(msg=GONE):
    return GenerationError(GenerationErrorCode.MODEL_UNAVAILABLE, msg)


class TestCatalog:
    def test_recommend_prefers_alias_and_skips_non_text(self):
        assert recommend("gemini", GEMINI) == "gemini-flash-latest"
        assert recommend("gemini", ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-flash-image"]) == "gemini-2.5-flash"
        assert recommend("groq", GROQ) == "openai/gpt-oss-120b"
        assert recommend("openai", ["gpt-4o-mini", "gpt-5-mini", "gpt-4.1-mini", "gpt-5"]) == "gpt-5-mini"
        assert recommend("anthropic", ["claude-sonnet-4-5", "claude-haiku-4-5"]) == "claude-haiku-4-5"
        assert recommend("gemini", ["gemini-embedding-001"]) is None

    def test_replacement_same_tier_never_older(self):
        assert suggest_replacement("gemini/gemini-2.5-flash", GEMINI + ["gemini-3-flash"]) == "gemini/gemini-3-flash"
        assert suggest_replacement("gemini/gemini-2.5-flash", GEMINI) == "gemini/gemini-flash-latest"
        assert suggest_replacement("gemini/gemini-2.5-pro", GEMINI) == "gemini/gemini-3-pro-preview"  # Pro stays Pro
        assert suggest_replacement("gemini/gemini-2.5-flash", ["gemini-2.0-flash"]) == "gemini/gemini-2.0-flash"  # only via recommend
        assert suggest_replacement("gemini/gemini-2.5-flash", ["gemini-2.5-pro"]) is None  # never a pricier tier

    def test_replacement_falls_back_to_recommendation(self):
        assert suggest_replacement("groq/llama-3.3-70b-versatile", GROQ) == "groq/openai/gpt-oss-120b"
        assert suggest_replacement("groq/llama-3.3-70b-versatile", GROQ + ["llama-4.1-70b-versatile"]) == \
            "groq/llama-4.1-70b-versatile"
        assert suggest_replacement("gemini/gemini-2.5-flash", GEMINI, exclude=["gemini/gemini-flash-latest"]) == \
            "gemini/gemini-3-flash-preview"

    def test_superseded(self):
        assert superseded(GEMINI) == {"gemini-2.0-flash", "gemini-2.5-flash-preview-09-2025"}
        assert superseded(["llama-3.1-70b-versatile", "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
                           "claude-haiku-4-5", "claude-haiku-4-5-20251001"]) == {"llama-3.1-70b-versatile"}


class TestErrors:
    def _wrap(self, name, message):
        exc = type(name, (Exception,), {})(message)
        return LiteLLMGenerationBackend.__new__(LiteLLMGenerationBackend)._wrap_exception(exc, "gemini/x")

    def test_classification(self):
        assert self._wrap("NotFoundError", "GeminiException - " + GONE).error_code == GenerationErrorCode.MODEL_UNAVAILABLE
        groq = 'The model `llama-3.3-70b-versatile` does not exist or you do not have access to it. "model_not_found"'
        assert self._wrap("NotFoundError", groq).error_code == GenerationErrorCode.MODEL_UNAVAILABLE
        assert self._wrap("AuthenticationError", "API key not valid").error_code == GenerationErrorCode.AUTH_FAILED
        assert self._wrap("RateLimitError", "429 quota").error_code == GenerationErrorCode.RATE_LIMITED

    def test_kind_and_redaction(self):
        assert error_kind(_gone()) == "retired"
        assert error_kind(GenerationError(GenerationErrorCode.RATE_LIMITED)) == "quota"
        text = clean_error("failed https://x/v1beta/models?key=AIzaSySECRETSECRET1234&alt=sse gsk_abcdefghijklmnop")
        assert "SECRET" not in text and "gsk_abc" not in text and "key=***" in text


class Fake:
    calls: list = []
    script: dict = {}

    def __init__(self, cfg):
        self.cfg = cfg

    def generate(self, prompt, generation_config, **kwargs):
        key = (self.cfg.llm_model, self.cfg.llm_api_key)
        Fake.calls.append(key)
        outcome = Fake.script.get(key, "ok")
        if isinstance(outcome, GenerationError):
            raise outcome
        return GenerationResult(text=f"from {key[0]}", model=key[0], provider="x", backend="litellm")


@pytest.fixture
def fake(monkeypatch):
    Fake.calls, Fake.script = [], {}
    notices = []
    monkeypatch.setattr(model_health, "_announce_async", lambda config, m, msg, r: notices.append((m, r)))
    monkeypatch.setattr(model_health, "available_ids", lambda provider, key, base=None, fresh=False:
                        list(GEMINI) if provider == "gemini" else None)
    Fake.notices = notices
    return Fake


def _backend(config, routes):
    return FailoverGenerationBackend(config, routes, backend_factory=Fake, cooldowns=_Cooldowns())


class TestRuntimeHealing:
    def test_platform_model_replaced_until_accepted(self, fake, tmp_path):
        config = Config(app_dir=tmp_path, llm_model="gemini/gemini-2.5-flash")
        fake.script = {("gemini/gemini-2.5-flash", "k"): _gone()}
        backend = _backend(config, [LLMRoute("gemini/gemini-2.5-flash", ["k"])])
        result = backend.generate("hi", GenerationConfig())
        assert result.text == "from gemini/gemini-flash-latest"
        assert result.diagnostics["replaced"] == {"gemini/gemini-2.5-flash": "gemini/gemini-flash-latest"}
        assert fake.notices == [("gemini/gemini-2.5-flash", "gemini/gemini-flash-latest")]
        assert config.llm_model == "gemini/gemini-2.5-flash"  # saved setting untouched

        fake.calls = []
        backend.generate("again", GenerationConfig())
        assert fake.calls == [("gemini/gemini-flash-latest", "k")]  # straight to the replacement
        _backend(config, [LLMRoute("gemini/gemini-2.5-flash", ["k"])]).generate("new backend", GenerationConfig())
        assert fake.notices == [("gemini/gemini-2.5-flash", "gemini/gemini-flash-latest")]  # told once

    def test_no_replacement_moves_down_the_chain(self, fake, tmp_path):
        config = Config(app_dir=tmp_path)
        fake.script = {("groq/llama-3.3-70b-versatile", None): _gone("model_not_found")}
        routes = [LLMRoute("groq/llama-3.3-70b-versatile"), LLMRoute("b/backup", source="fallback")]
        assert _backend(config, routes).generate("hi", GenerationConfig()).text == "from b/backup"
        entry = model_health.load(config)["models"]["groq/llama-3.3-70b-versatile"]
        assert entry["status"] == "unavailable" and entry["replacement"] is None
        assert fake.notices == [("groq/llama-3.3-70b-versatile", None)]

    def test_replacement_also_gone_tries_next(self, fake, tmp_path):
        config = Config(app_dir=tmp_path)
        fake.script = {("gemini/gemini-2.5-flash", "k"): _gone(), ("gemini/gemini-flash-latest", "k"): _gone()}
        result = _backend(config, [LLMRoute("gemini/gemini-2.5-flash", ["k"])]).generate("hi", GenerationConfig())
        assert result.text == "from gemini/gemini-3-flash-preview"

    def test_own_key_model_is_updated(self, fake, tmp_path, monkeypatch):
        from src.services import ai_access

        saved = []
        monkeypatch.setattr(ai_access, "update_byok_model", lambda config, key_id, model: saved.append((key_id, model)))
        config = Config(app_dir=tmp_path)
        fake.script = {("gemini/gemini-2.5-flash", "user-key"): _gone()}
        route = LLMRoute("gemini/gemini-2.5-flash", ["user-key"], source="byok", key_id=7)
        backend = _backend(config, [route])
        assert backend.generate("hi", GenerationConfig()).text == "from gemini/gemini-flash-latest"
        assert saved == [(7, "gemini/gemini-flash-latest")]
        assert route.model == "gemini/gemini-flash-latest"
        assert fake.notices == [] and model_health.load(config)["models"] == {}  # not the admin's business


class TestDailyCheck:
    def test_run_check_finds_and_verifies_replacement(self, fake, tmp_path, monkeypatch):
        announced = []
        monkeypatch.setattr(model_health, "announce", lambda config, m, msg, r: announced.append((m, r)))
        config = Config(app_dir=tmp_path, llm_model="gemini/gemini-2.5-flash", gemini_api_key="k",
                        llm_fallback_models=["groq/some-model"])
        probes = []

        def probe(model, key, base):
            probes.append(model)
            if model == "gemini/gemini-2.5-flash":
                return _gone()
            if model == "groq/some-model":
                return GenerationError(GenerationErrorCode.AUTH_FAILED, "invalid api key")
            return None

        state = model_health.run_check(config, probe=probe)
        main = state["models"]["gemini/gemini-2.5-flash"]
        assert (main["status"], main["replacement"], main["replacement_ok"]) == \
            ("unavailable", "gemini/gemini-flash-latest", True)
        assert state["models"]["groq/some-model"]["status"] == "error"
        assert state["models"]["groq/some-model"]["kind"] == "key"
        assert announced == [("gemini/gemini-2.5-flash", "gemini/gemini-flash-latest")]
        assert model_health.health(config)[0] == "WARNING"

        model_health.run_check(config, probe=probe)
        assert len(announced) == 1  # once per model

    def test_unlisted_model_needs_no_probe(self, fake, tmp_path, monkeypatch):
        monkeypatch.setattr(model_health, "announce", lambda *a: None)
        config = Config(app_dir=tmp_path, llm_model="gemini/gemini-1.5-flash", gemini_api_key="k")
        probes = []
        model_health.run_check(config, probe=lambda m, k, b: probes.append(m))
        assert "gemini/gemini-1.5-flash" not in probes
        assert model_health.load(config)["models"]["gemini/gemini-1.5-flash"]["status"] == "unavailable"

    def test_all_ok(self, fake, tmp_path):
        config = Config(app_dir=tmp_path, llm_model="gemini/gemini-flash-latest", gemini_api_key="k")
        model_health.run_check(config, probe=lambda m, k, b: None)
        assert model_health.health(config) == ("OK", "1 model(s) answering")


class TestAccept:
    def _retired(self, config):
        model_health._mark(config, "gemini/gemini-2.5-flash", status="unavailable", kind="retired", message="gone",
                           replacement="gemini/gemini-flash-latest", replacement_ok=True)

    def test_accept_rewrites_every_field(self, tmp_path):
        config = Config(app_dir=tmp_path, llm_model="gemini/gemini-2.5-flash", llm_fast_model="gemini/gemini-2.5-flash",
                        llm_fallback_models=["groq/x", "gemini/gemini-2.5-flash"])
        self._retired(config)
        assert model_health.accept(config, "gemini/gemini-2.5-flash") == "gemini/gemini-flash-latest"
        assert config.llm_model == config.llm_fast_model == "gemini/gemini-flash-latest"
        assert config.llm_fallback_models == ["groq/x", "gemini/gemini-flash-latest"]
        assert model_health.load(config)["models"] == {}
        assert '"gemini/gemini-flash-latest"' in (tmp_path / "config.json").read_text(encoding="utf-8")

    def test_env_setting_cannot_be_accepted(self, tmp_path):
        config = Config(app_dir=tmp_path).apply_env({"LLM_MODEL": "gemini/gemini-2.5-flash"})
        self._retired(config)
        with pytest.raises(model_health.AcceptError, match="LLM_MODEL is set on the server"):
            model_health.accept(config, "gemini/gemini-2.5-flash")
