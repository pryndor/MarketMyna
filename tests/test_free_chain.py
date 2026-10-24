"""src/llm/providers.free_chain: fallback list from free-tier providers with a saved key."""

from types import SimpleNamespace

from src.llm import providers

LISTS = {
    "cerebras": ["cerebras/llama3.1-8b", "cerebras/gpt-oss-120b", "cerebras/llama-3.3-70b"],
    "groq": ["groq/openai/gpt-oss-120b", "groq/llama-3.3-70b-versatile", "groq/llama-3.1-8b-instant"],
    "openrouter": ["openrouter/openai/gpt-5-mini", "openrouter/meta-llama/llama-3.3-70b-instruct:free"],
}


def fake_list(provider, key=None, base_url=None, include_old=True, hide=()):
    if provider == "openrouter":
        return [{"id": m, "free": m.endswith(":free")} for m in LISTS[provider]]
    return [{"id": m, "free": True} for m in LISTS[provider]]


def test_free_chain_uses_saved_keys_only(monkeypatch):
    monkeypatch.setattr(providers, "list_models", fake_list)
    config = SimpleNamespace(cerebras_api_key="c", groq_api_key="g", openrouter_api_key="o",
                             gemini_api_key=None, nvidia_api_key=None, mistral_api_key=None)
    out = providers.free_chain(config, exclude=["groq/openai/gpt-oss-120b"])
    assert out["models"] == [
        "cerebras/gpt-oss-120b",
        "groq/llama-3.3-70b-versatile",
        "groq/llama-3.1-8b-instant",
        "openrouter/meta-llama/llama-3.3-70b-instruct:free",
    ]
    assert out["skipped"]["gemini"] == "no key saved"


def test_free_chain_survives_a_provider_error(monkeypatch):
    def broken(provider, *a, **k):
        if provider == "groq":
            raise RuntimeError("503")
        return fake_list(provider, *a, **k)

    monkeypatch.setattr(providers, "list_models", broken)
    config = SimpleNamespace(cerebras_api_key="c", groq_api_key="g", openrouter_api_key=None,
                             gemini_api_key=None, nvidia_api_key=None, mistral_api_key=None)
    out = providers.free_chain(config)
    assert out["models"] == ["cerebras/gpt-oss-120b"]
    assert "503" in out["skipped"]["groq"]


def test_second_gemini_model_is_another_tier(monkeypatch):
    LISTS["gemini"] = ["gemini/gemini-flash-latest", "gemini/gemini-3-flash", "gemini/gemini-flash-lite-latest"]
    monkeypatch.setattr(providers, "list_models", fake_list)
    config = SimpleNamespace(gemini_api_key="k", cerebras_api_key=None, groq_api_key=None,
                             openrouter_api_key=None, nvidia_api_key=None, mistral_api_key=None)
    assert providers.free_chain(config)["models"] == ["gemini/gemini-flash-latest", "gemini/gemini-flash-lite-latest"]
