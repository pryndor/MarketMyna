"""AI review of any mutual fund on the Analyze page.

Reads the same figures the fund page shows (rolling returns and risk against
the category benchmark, rank among competitors, style, holdings, Direct vs
Regular cost), condenses them into a short fact sheet and asks the model to
explain them. Wording follows src/core/compliance.py: the owner gets a view,
public users an explanation without a recommendation.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600  # the inputs change monthly (holdings) or daily (NAV)
# Reasoning models (gpt-oss, Gemini thinking) spend part of max_tokens before
# answering; too tight a budget cuts the JSON off mid-way.
MAX_TOKENS = 3000
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()



def _r(x, nd=1):
    return round(x, nd) if isinstance(x, (int, float)) else None


def _pct(x, nd=1):
    """A 0-1 fraction as a percentage."""
    return round(x * 100, nd) if isinstance(x, (int, float)) else None


def facts(code: str) -> dict:
    """The fund's numbers, trimmed to what an explanation needs. Each part is
    optional: a source that fails just leaves its section out."""
    from . import fund_analytics, fund_cost, fund_holdings, fund_peers, fund_style

    parts = {"analytics": fund_analytics.build, "peers": fund_peers.compare, "style": fund_style.build,
             "cost": fund_cost.build, "holdings": fund_holdings.for_fund}

    def run(fn):
        try:
            out = fn(code)
            return out if isinstance(out, dict) and out.get("status") == "ok" else None
        except Exception as exc:
            logger.info("Fund AI facts: %s failed for %s: %s", fn.__module__, code, exc)
            return None

    with ThreadPoolExecutor(max_workers=len(parts)) as pool:
        got = dict(zip(parts, pool.map(run, parts.values())))

    out: dict = {"code": code}
    peers, a, st, cost, h = got["peers"], got["analytics"], got["style"], got["cost"], got["holdings"]
    if peers:
        out.update(name=peers.get("name"), category=peers.get("category"), plan=peers.get("plan"))
        out["rank_among_peers"] = {
            k: {"rank": v["rank"], "of": v["of"]} for k, v in (peers.get("ranks") or {}).items() if v and v.get("rank")
        }
        out["rank_notes"] = "r1/r3/r5 = 1/3/5-year return; volatility and drawdown rank 1 = least risky"
    if a:
        out.setdefault("category", a.get("category"))
        out["nav_history_from"] = a.get("nav_from")
        out["benchmark"] = (a.get("benchmark") or {}).get("name")
        out["rolling_returns_pct"] = [
            {"years": w["years"], "median": _r(w.get("median")), "benchmark_median": _r(w.get("bench_median")),
             "beat_benchmark_pct_of_windows": _r(w.get("beat_pct")), "negative_pct_of_windows": _r(w.get("negative_pct")),
             "worst": _r(w.get("min")), "best": _r(w.get("max"))}
            for w in (a.get("rolling") or {}).get("windows", [])
        ]
        r = a.get("risk") or {}
        if r:
            out[f"risk_last_{r.get('years', 3)}y"] = {
                "annual_return_pct": _pct(r.get("annual_return")), "benchmark_return_pct": _pct(r.get("bench_annual_return")),
                "volatility_pct": _pct(r.get("volatility")), "benchmark_volatility_pct": _pct(r.get("bench_volatility")),
                "max_drawdown_pct": _pct(r.get("max_drawdown")), "benchmark_max_drawdown_pct": _pct(r.get("bench_max_drawdown")),
                "sharpe": _r(r.get("sharpe"), 2), "sortino": _r(r.get("sortino"), 2), "beta": _r(r.get("beta"), 2),
                "alpha_pct": _pct(r.get("alpha")), "up_capture_pct": _pct(r.get("up_capture"), 0),
                "down_capture_pct": _pct(r.get("down_capture"), 0),
            }
        d = a.get("drawdowns") or {}
        if d:
            out["drawdown_pct"] = {"now_from_peak": _r(d.get("current")), "worst_ever": _r(d.get("max"))}
    if st:
        out["style"] = {
            "label": (st.get("style") or {}).get("label"), "size": st.get("size"),
            "pe": _r((st.get("fund") or {}).get("pe")), "market_pe": _r((st.get("market") or {}).get("pe")),
            "equity_pct": _r(st.get("equity_pct")), "cap_split_pct": {k: _r(v) for k, v in (st.get("split") or {}).items() if v},
            "category_rules_failed": [c["rule"] for c in st.get("checks") or [] if not c.get("ok")],
        }
    if h:
        out["portfolio"] = {
            "as_of": h.get("as_of"), "aum_crore": _r(h.get("aum_cr"), 0), "stocks": h.get("count"),
            "top10_weight_pct": _r(h.get("top10_weight")),
            "effective_stocks": _r((h.get("concentration") or {}).get("effective_stocks"), 0),
            "top_holdings": [f"{x['name']} {_r(x.get('weight'))}%" for x in (h.get("top") or [])[:5]],
            "top_sectors": [f"{x['name']} {_r(x.get('weight'))}%" for x in (h.get("sectors") or [])[:5]],
            "asset_mix": [f"{x['kind']} {_r(x.get('weight'))}%" for x in (h.get("mix") or [])[:4]],
        }
        out.setdefault("name", h.get("scheme"))
    if cost:
        p = cost.get("plans") or {}
        if p.get("gap") is not None:
            out["direct_vs_regular"] = {"years": p.get("years"), "direct_return_pct": _r(p.get("direct")),
                                        "regular_return_pct": _r(p.get("regular")), "yearly_gap_pct": _r(p.get("gap"), 2)}
        out["tax"] = (cost.get("tax") or {}).get("text")
    return out


def _system() -> str:
    shape = ('{"summary": "3-4 sentences", "strengths": ["2-4 short points"], "concerns": ["2-4 short points"], '
             '"sections": {"returns": "1-2 sentences", "risk": "1-2 sentences", "portfolio": "1-2 sentences", '
             '"peers": "1-2 sentences", "cost": "1 sentence"}')
    return (
        "You explain mutual fund data to retail investors for an analytics tool that is not registered with SEBI as "
        "an investment adviser or research analyst. Using only the figures given, explain how the fund has behaved: "
        "returns over rolling periods against its benchmark, risk, where it ranks among competitors, what it holds "
        "and what it costs. Describe observations only. Never recommend investing, buying, holding, switching or "
        "selling, give no view on whether it is a good choice, and do not call it attractive, cheap, expensive, "
        "undervalued or overvalued. Reply with ONLY a JSON object: " + shape
    )


def _parse(text: str) -> Optional[dict]:
    from ..llm.json_reply import parse_object

    data = parse_object(text)
    if not data or not data.get("summary"):
        return None

    def points(key):
        return [str(x) for x in (data.get(key) or []) if x][:4]

    sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    out = {
        "summary": str(data["summary"]),
        "strengths": points("strengths"),
        "concerns": points("concerns"),
        "sections": {k: str(sections[k]) for k in ("returns", "risk", "portfolio", "peers", "cost") if sections.get(k)},
        "view": None,  # no verdict on the fund (src/core/compliance.py)
        "suits": None,
    }
    return out


def review(code: str, config, use_cache: bool = True) -> Optional[dict]:
    """The AI review, or None when the model's reply can't be used. Raises
    LookupError when there is no fund data at all, and lets GenerationError
    (no key / quota) through for the endpoint to report."""
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig

    key = code
    if use_cache:
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]

    sheet = facts(code)
    if len(sheet) <= 2:  # nothing beyond the code (and maybe a name)
        raise LookupError("No data for this fund yet, so there is nothing to review.")
    prompt = "Fund data (JSON):\n" + json.dumps(sheet, default=str)
    result = create_generation_backend(config).generate(
        prompt, GenerationConfig(max_tokens=MAX_TOKENS, timeout=120), system_prompt=_system())
    out = _parse(result.text)
    if out is None:
        text = result.text or ""
        logger.warning("%s: unusable reply from %s (%d chars): %s ... %s", "Fund AI review", result.model,
                       len(text), " ".join(text[:150].split()), " ".join(text[-150:].split()))
        return None
    out.update(name=sheet.get("name"), category=sheet.get("category"), generated_at=time.strftime("%Y-%m-%d %H:%M"),
               compliance="analytics")
    with _lock:
        _cache[key] = (time.time(), out)
    return out
