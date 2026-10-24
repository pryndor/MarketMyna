"""AI review of a whole mutual fund portfolio (Portfolio page).

Builds a fact sheet from what the page already computes - the fund table
(marketmyna/services/mf_lumpsum.portfolio_funds) and the health check
(marketmyna/services/mf_insights.insights) - plus a look-through of the stocks and
sectors held across all funds, then asks the model to explain it. Wording
follows marketmyna/core/compliance.py: the owner gets a view and suggested actions,
public users an explanation without a recommendation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600
# Reasoning models (gpt-oss, Gemini thinking) spend part of max_tokens before
# answering; too tight a budget cuts the JSON off mid-way.
MAX_TOKENS = 4500
LOOK_THROUGH_SECONDS = 60  # holdings files are cached after the first read; don't hang on a slow one
MIN_COVERAGE = 50  # % of the portfolio whose holdings must be known to show the look-through
_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()



def _r(x, nd=1):
    return round(x, nd) if isinstance(x, (int, float)) else None


def _short(name: str) -> str:
    return (name or "").split(" - ")[0]


def look_through(weights: dict[str, float]) -> dict:
    """Stocks and sectors across all funds, each fund's holdings scaled by its
    share of the portfolio. Funds whose holdings can't be read are skipped and
    reported in `covered_pct`."""
    from . import fund_holdings

    pool = ThreadPoolExecutor(max_workers=8)
    futures = {pool.submit(fund_holdings.for_fund, code): code for code in weights}
    done, _ = wait(futures, timeout=LOOK_THROUGH_SECONDS)
    pool.shutdown(wait=False, cancel_futures=True)

    stocks: dict[str, float] = {}
    sectors: dict[str, float] = {}
    covered = 0.0
    for fut in done:
        try:
            h = fut.result()
        except Exception:
            continue
        if not isinstance(h, dict) or h.get("status") != "ok":
            continue
        w = weights[futures[fut]]
        covered += w
        for x in h.get("holdings") or []:
            if x.get("kind") not in ("equity", "foreign_equity") or not x.get("weight"):
                continue
            stocks[x["name"]] = stocks.get(x["name"], 0) + w * x["weight"]
        for s in h.get("sectors") or []:
            if s.get("weight"):
                sectors[s["name"]] = sectors.get(s["name"], 0) + w * s["weight"]

    def top(d, n):
        return [f"{k} {_r(v)}%" for k, v in sorted(d.items(), key=lambda kv: -kv[1])[:n]]

    return {"covered_pct": _r(covered * 100, 0), "top_stocks_of_portfolio": top(stocks, 10),
            "top_sectors_of_portfolio": top(sectors, 8)}


def facts(funds_view: dict, health: dict) -> dict:
    funds = [f for f in funds_view.get("funds") or [] if (f.get("value") or 0) > 0]
    total = sum(f["value"] for f in funds)
    invested = sum(f.get("invested") or 0 for f in funds)
    weights = {f["code"]: f["value"] / total for f in funds} if total else {}
    out: dict = {
        "funds": len(funds),
        "invested": _r(invested, 0),
        "value": _r(total, 0),
        "gain_pct": _r((total - invested) / invested * 100, 2) if invested else None,
        "holdings": [
            {"code": f["code"], "fund": _short(f.get("name")), "category": f.get("category"),
             "asset_class": f.get("asset_class"), "weight_pct": _r(weights[f["code"]] * 100),
             "gain_pct": _r(f.get("gain_pct"), 2),
             "below_high_pct": _r(((f.get("lumpsum") or {}).get("below_high") or 0) * 100)
             if (f.get("lumpsum") or {}).get("status") == "ok" else None}
            for f in sorted(funds, key=lambda f: -f["value"])
        ],
    }
    if health.get("funds"):
        out["health_check"] = {
            "score": health.get("score"), "grade": health.get("grade"),
            "asset_classes_pct": {a["name"]: _r(a["weight"] * 100) for a in health.get("asset_classes") or []},
            "categories": [f"{c['name']} {_r(c['weight'] * 100)}% ({c['count']} funds)" for c in health.get("categories") or []],
            "funds_that_move_together": [f"{p['a_name']} & {p['b_name']} (correlation {_r(p['correlation'], 2)})"
                                         for p in (health.get("similar_pairs") or [])[:5]],
            "issues": list(health.get("issues") or [])[:6],
        }
    if weights:
        lt = look_through(weights)
        if (lt["covered_pct"] or 0) >= MIN_COVERAGE:
            out["look_through"] = lt
        else:  # a few small funds' stocks would misstate the whole portfolio
            out["look_through"] = {"covered_pct": lt["covered_pct"],
                                   "note": "Holdings are known for too little of the portfolio; say nothing about its stocks or sectors."}
    return out


def _system() -> str:
    shape = ('{"summary": "3-4 sentences on the portfolio as a whole", "strengths": ["2-4 short points"], '
             '"concerns": ["2-4 short points"], "sections": {"mix": "1-2 sentences", "overlap": "1-2 sentences", '
             '"concentration": "1-2 sentences", "risk": "1-2 sentences"}, '
             '"funds": [{"code": "scheme code from the data", "note": "one sentence on this fund\'s role in the portfolio"}]')
    return (
        "You explain a mutual fund portfolio to its owner for an analytics tool that is not registered with SEBI as "
        "an investment adviser or research analyst. Using only the figures given, describe how the portfolio is made "
        "up: asset mix, categories, funds that move together, look-through stocks and sectors, and how concentrated "
        "it is. Gains since a recent purchase are too short to say anything about a fund. Describe observations "
        "only. Never recommend buying, selling, switching, adding, merging or rebalancing, and give no view on "
        "whether the portfolio or any fund is good. Reply with ONLY a JSON object: " + shape + "}"
    )


def _parse(text: str, codes: set[str]) -> Optional[dict]:
    from ..llm.json_reply import parse_object

    data = parse_object(text)
    if not data or not data.get("summary"):
        return None

    def points(key, n=4):
        return [str(x) for x in (data.get(key) or []) if x][:n]

    sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
    notes = [{"code": str(f.get("code")), "note": str(f["note"])} for f in data.get("funds") or []
             if isinstance(f, dict) and f.get("note") and str(f.get("code")) in codes]
    out = {
        "summary": str(data["summary"]),
        "strengths": points("strengths"),
        "concerns": points("concerns"),
        "sections": {k: str(sections[k]) for k in ("mix", "overlap", "concentration", "risk") if sections.get(k)},
        "funds": notes,
        "view": None,  # no verdict or actions (marketmyna/core/compliance.py)
        "actions": [],
    }
    return out


def review(name: str, funds_view: dict, health: dict, config, use_cache: bool = True) -> Optional[dict]:
    """The AI review, or None when the reply can't be used. Raises LookupError
    with no funds; lets GenerationError through for the endpoint."""
    from ..core import tenant
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig

    funds = [f for f in funds_view.get("funds") or [] if (f.get("value") or 0) > 0]
    if not funds:
        raise LookupError("This portfolio has no mutual funds to review.")
    # Same user, portfolio and holdings -> same review; any trade changes the key.
    holdings = ",".join(sorted(f"{f['code']}:{round(f.get('units') or 0, 3)}" for f in funds))
    key = (str(tenant.current()), name, hashlib.sha1(holdings.encode()).hexdigest())
    if use_cache:
        with _lock:
            hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]

    sheet = facts(funds_view, health)
    result = create_generation_backend(config).generate(
        "Mutual fund portfolio (JSON):\n" + json.dumps(sheet, default=str),
        GenerationConfig(max_tokens=MAX_TOKENS, timeout=150), system_prompt=_system())
    out = _parse(result.text, {f["code"] for f in funds})
    if out is None:
        text = result.text or ""
        logger.warning("%s: unusable reply from %s (%d chars): %s ... %s", "Fund portfolio AI review", result.model,
                       len(text), " ".join(text[:150].split()), " ".join(text[-150:].split()))
        return None
    names = {f["code"]: _short(f.get("name")) for f in funds}
    weights = {h["code"]: h["weight_pct"] for h in sheet["holdings"]}
    for n in out["funds"]:
        n.update(name=names.get(n["code"]), weight_pct=weights.get(n["code"]))
    out.update(generated_at=time.strftime("%Y-%m-%d %H:%M"), compliance="analytics",
               look_through=sheet.get("look_through"))
    with _lock:
        _cache[key] = (time.time(), out)
    return out
