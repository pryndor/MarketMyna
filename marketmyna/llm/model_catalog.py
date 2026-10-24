"""Picks models from a provider's live model list instead of hard-coded
names that go stale when providers retire models.

- recommend(provider, ids): the model to suggest for a new key or a fresh
  setup - a fast, cheap, capable one (e.g. the newest stable Gemini Flash).
- suggest_replacement(model, ids): when `model` has been retired, the closest
  current model of the same family and tier (Flash -> newer Flash, never Pro,
  so costs don't jump), else recommend().

Preferences below are name *patterns*, not versions, so a new release
(gemini-4-flash, gpt-6-mini) is picked up without a code change. Ids are
bare provider ids ("gemini-3-flash"); callers add the litellm prefix.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# Per provider, best first. Within a pattern the newest stable version wins.
# Aliases the provider keeps pointing at its current model come first where
# they exist: a listed but closed model (Gemini lists 2.5 Flash, yet refuses it
# to new keys) can't be told apart from a working one by the list alone.
PREFERRED_PATTERNS: dict[str, list[str]] = {
    "gemini": [r"gemini-flash-latest", r"gemini-[\d.]+-flash", r"gemini-[\d.]+-flash-preview(-[\w-]+)?",
               r"gemini-flash-lite-latest", r"gemini-[\d.]+-flash-lite"],
    "groq": [r"openai/gpt-oss-120b", r"llama-[\d.]+-\d+b-versatile", r"meta-llama/llama-[\d.]+-.*instruct",
             r"openai/gpt-oss-20b", r"llama-[\d.]+-\d+b-instant"],
    "openai": [r"gpt-[\d.]+-mini", r"gpt-4o-mini"],
    "anthropic": [r"claude-haiku-[\d-]+", r"claude-[\d-]+-haiku(-\d+)?", r"claude-sonnet-[\d-]+"],
    "mistral": [r"mistral-small-latest", r"mistral-medium-latest", r"mistral-large-latest"],
    "deepseek": [r"deepseek-chat"],
    "cerebras": [r"gpt-oss-120b", r"llama-[\d.]+-70b", r"qwen-[\d.]+-\d+b(-[\w-]+)?", r"llama[\d.]+-\d+b"],
    "nvidia_nim": [r"openai/gpt-oss-120b", r"meta/llama-[\d.]+-70b-instruct", r"meta/llama-[\d.]+-\d+b-instruct"],
    "openrouter": [r"openai/gpt-[\d.]+-mini", r"google/gemini-[\d.]+-flash", r"anthropic/claude-haiku-[\d.-]+"],
}

# Words that tell a model's size/price tier; a replacement keeps the same set.
TIER_WORDS = {
    "lite", "mini", "nano", "flash", "pro", "ultra", "haiku", "sonnet", "opus", "small", "medium", "large",
    "instant", "versatile", "chat", "reasoner", "turbo", "max", "plus",
}
UNSTABLE_WORDS = {"preview", "exp", "experimental", "beta", "alpha"}
# Not for text generation, even if a provider's list says otherwise.
NON_TEXT_WORDS = {
    "tts", "image", "imagen", "embedding", "embed", "live", "audio", "vision", "native", "transcribe",
    "whisper", "guard", "moderation", "veo", "robotics", "computer", "search", "realtime", "dall",
}


def bare(model: str) -> str:
    """'gemini/gemini-3-flash' -> 'gemini-3-flash'; OpenRouter / Groq ids keep
    their own vendor part ('groq/openai/gpt-oss-120b' -> 'openai/gpt-oss-120b')."""
    return model.split("/", 1)[1] if "/" in model else model


def _words(model_id: str) -> list[str]:
    return [w for w in re.split(r"[^a-z]+", model_id.lower()) if w]


def _version(model_id: str) -> tuple[int, ...]:
    """Numbers in the name, sizes like '70b' and dates left out:
    'gemini-2.5-flash' -> (2, 5); 'claude-haiku-4-5-20251001' -> (4, 5)."""
    name = model_id.lower().rsplit("/", 1)[-1]
    # Numbers after "preview" / "exp" are release dates ("-preview-09-2025").
    name = re.split(r"[-_.](?:%s)(?:[-_.]|$)" % "|".join(UNSTABLE_WORDS), name)[0]
    nums = re.findall(r"(?<![a-z])(\d+(?:\.\d+)*)(?![a-z\d])", name)
    out: list[int] = []
    for n in nums:
        if len(n) >= 4:  # a year or date stamp, not a version
            continue
        out.extend(int(p) for p in n.split(".") if p)
    return tuple(out)


def _unstable(model_id: str) -> bool:
    return bool(set(_words(model_id)) & UNSTABLE_WORDS)


def is_text_model(model_id: str) -> bool:
    return not (set(_words(model_id)) & NON_TEXT_WORDS)


def _rank_key(model_id: str) -> tuple:
    # Stable before preview; newer version first; shorter (plain) names first.
    return (_unstable(model_id), tuple(-v for v in _version(model_id)), len(model_id), model_id)


def recommend(provider: str, ids: Iterable[str], exclude: Iterable[str] = ()) -> Optional[str]:
    """Best model id for `provider` among `ids` (bare ids), or None."""
    skip = {bare(x) if "/" in x and x.split("/", 1)[0] == provider else x for x in exclude}
    pool = [i for i in dict.fromkeys(ids) if i and i not in skip and is_text_model(i)]
    for pattern in PREFERRED_PATTERNS.get(provider, []):
        rx = re.compile(rf"^{pattern}$", re.I)
        hits = [i for i in pool if rx.match(i)]
        if hits:
            return sorted(hits, key=_rank_key)[0]
    return None


def suggest_replacement(model: str, ids: Iterable[str], exclude: Iterable[str] = ()) -> Optional[str]:
    """Closest current model to a retired `model` (litellm id), as a litellm id.

    Same family (first word) and the same tier words, never an older version;
    a concrete newer stable release beats the provider's '-latest' alias,
    which beats a newer preview. Nothing like it -> recommend() for the
    provider. None when the list offers nothing usable."""
    provider = model.split("/", 1)[0] if "/" in model else ""
    old = bare(model)
    skip = {old} | {bare(x) for x in exclude}
    pool = [i for i in dict.fromkeys(ids) if i and i not in skip and is_text_model(i)]
    words = _words(old)
    family = words[0] if words else ""
    tiers = set(words) & TIER_WORDS
    old_version = _version(old)

    def same_kind(i: str) -> bool:
        w = _words(i)
        return bool(w) and w[0] == family and (set(w) & TIER_WORDS) == tiers

    alike = [i for i in pool if same_kind(i)]
    newer = [i for i in alike if _version(i) and _version(i) > old_version]
    stable = sorted([i for i in newer if not _unstable(i)], key=_rank_key)
    alias = sorted([i for i in alike if "latest" in _words(i)], key=len)
    preview = sorted([i for i in newer if _unstable(i)], key=_rank_key)
    pick = (stable or alias or preview or [None])[0]
    if pick is None:
        pick = recommend(provider, pool) if provider else None
    if pick is None:
        return None
    return f"{provider}/{pick}" if provider else pick


def tier_of(model_id: str) -> tuple:
    """Family and tier: ('gemini', {'flash', 'lite'}); sizes ('70b') count too."""
    w = _words(model_id.rsplit("/", 1)[-1])
    return (w[0] if w else "", frozenset(set(w) & TIER_WORDS), _size(model_id))


def _size(model_id: str) -> tuple[str, ...]:
    return tuple(re.findall(r"(?<![a-z\d])(\d+b)(?![a-z])", model_id.lower()))


def superseded(ids: Iterable[str]) -> set[str]:
    """Ids a newer stable release of the same family, tier and size replaces
    (gemini-2.0-flash when gemini-2.5-flash is listed; a preview once its
    version is out as stable). Aliases and unversioned ids are never hidden."""
    pool = [i for i in dict.fromkeys(ids) if i]
    kinds: dict[str, tuple] = {}
    for i in pool:
        w = _words(i)
        kinds[i] = (w[0] if w else "", frozenset(set(w) & TIER_WORDS), _size(i))
    out = set()
    for i in pool:
        v = _version(i)
        if not v or "latest" in _words(i):
            continue
        for j in pool:
            if j == i or kinds[j] != kinds[i] or _unstable(j) or not _version(j):
                continue
            vj = _version(j)
            if vj > v or (vj == v and _unstable(i)):
                out.add(i)
                break
    return out

