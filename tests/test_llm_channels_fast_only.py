"""A fast model on its own still counts as a configured AI model."""

from types import SimpleNamespace

from src.llm.channels import build_routes, llm_configured


def _config(**kw):
    base = dict(llm_model=None, llm_fast_model=None, llm_api_key=None, llm_api_keys=None, llm_api_base=None,
                llm_channels=None, llm_fallback_models=None, groq_api_key="gsk-test")
    return SimpleNamespace(**{**base, **kw})


def test_fast_model_only_is_configured():
    config = _config(llm_fast_model="groq/openai/gpt-oss-20b")
    assert llm_configured(config)
    assert [r.model for r in build_routes(config, environ={})] == ["groq/openai/gpt-oss-20b"]


def test_main_model_keeps_deep_tier_to_itself():
    config = _config(llm_model="groq/openai/gpt-oss-120b", llm_fast_model="groq/openai/gpt-oss-20b")
    assert [r.model for r in build_routes(config, environ={})] == ["groq/openai/gpt-oss-120b"]


def test_nothing_set_is_not_configured():
    assert not llm_configured(_config())
