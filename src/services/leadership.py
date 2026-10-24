"""CEO and leadership snapshot for one company.

The facts come from Yahoo Finance: the officer list (name, title, age,
reported pay) and ISS governance risk scores (1 = low risk ... 10 = high,
US listings mostly). An optional AI brief (ai_ceo_brief) adds a short
introduction, track record, pitfalls and a verdict on whether the company
looks in safe hands - grounded on the current officer list and recent
headlines so the model does not describe a predecessor.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from ..llm.json_reply import parse_object

logger = logging.getLogger(__name__)

# Most specific first: an "Executive Chairman" must not win over the "CEO".
_CEO_PATTERNS = (
    r"\bceo\b",
    r"chief executive",
    r"\bmanaging director\b|\bmd\b",
    r"\bpresident\b",
    r"\bchairman\b|\bchair\b",
)

_RISK_KEYS = (
    ("overallRisk", "Overall"),
    ("boardRisk", "Board"),
    ("auditRisk", "Audit"),
    ("compensationRisk", "Compensation"),
    ("shareHolderRightsRisk", "Shareholder rights"),
)


def _clean_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return re.sub(r"\s+", " ", name).strip()


def _officer(raw: dict) -> dict:
    pay = raw.get("totalPay")
    return {
        "name": _clean_name(raw.get("name")),
        "title": raw.get("title"),
        "age": raw.get("age"),
        "year_born": raw.get("yearBorn"),
        "total_pay": pay if isinstance(pay, (int, float)) and pay > 0 else None,
        "fiscal_year": raw.get("fiscalYear"),
    }


def pick_ceo(officers: list[dict]) -> Optional[dict]:
    """The officer whose title best matches the chief executive role."""
    for pattern in _CEO_PATTERNS:
        for o in officers:
            if o.get("title") and re.search(pattern, o["title"], re.IGNORECASE):
                return o
    return officers[0] if officers else None


def _epoch_date(value) -> Optional[str]:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).date().isoformat()


def leadership_from_info(info: dict) -> dict:
    officers = [_officer(o) for o in info.get("companyOfficers") or [] if o.get("name")]
    if not officers:
        raise ValueError("no officer data published for this company")
    ceo = pick_ceo(officers)
    governance = [
        {"key": key, "label": label, "score": info[key]}
        for key, label in _RISK_KEYS
        if isinstance(info.get(key), (int, float))
    ]
    return {
        "name": info.get("longName") or info.get("shortName"),
        "currency": info.get("financialCurrency") or info.get("currency"),
        "ceo": ceo,
        "officers": [o for o in officers if o is not ceo][:6],
        "governance": governance,
        "governance_as_of": _epoch_date(info.get("governanceEpochDate")),
    }


def build_leadership(symbol: str, market: str) -> dict:
    if market == "crypto":
        raise ValueError("not applicable to crypto")
    import yfinance as yf

    from .analysis_run import yahoo_symbol

    info = yf.Ticker(yahoo_symbol(symbol, market)).info or {}
    return {"symbol": symbol, "market": market, **leadership_from_info(info)}


def _parse_brief(text: str) -> Optional[dict]:
    data = parse_object(text)
    if data is None:
        return None

    def strings(value) -> list[str]:
        return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []

    verdict = str(data.get("verdict") or "").lower()
    brief = {
        "introduction": str(data.get("introduction") or "").strip(),
        "achievements": strings(data.get("achievements")),
        "pitfalls": strings(data.get("pitfalls")),
        "verdict": verdict if verdict in ("strong", "steady", "uncertain", "concerning") else "uncertain",
        "verdict_reason": str(data.get("verdict_reason") or "").strip(),
    }
    return brief if brief["introduction"] or brief["achievements"] else None


def ai_ceo_brief(data: dict, config, headlines: Optional[list[str]] = None) -> Optional[dict]:
    """LLM brief on the current CEO. None when no LLM is configured or the
    reply cannot be parsed."""
    from ..llm.channels import llm_configured

    if config is None or not llm_configured(config) or not data.get("ceo"):
        return None
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig

    ceo = data["ceo"]
    lines = [
        f"Company: {data['name']} ({data['symbol']}, market {data['market']}).",
        f"Current chief executive per the latest filing: {ceo['name']} - {ceo['title']}"
        + (f", age {ceo['age']}" if ceo.get("age") else "") + ".",
        "Other officers: " + "; ".join(f"{o['name']} ({o['title']})" for o in data["officers"]) + ".",
    ]
    if data["governance"]:
        lines.append("ISS governance risk (1 low - 10 high): "
                     + ", ".join(f"{g['label']} {g['score']}" for g in data["governance"]) + ".")
    if headlines:
        lines.append("Recent headlines:\n" + "\n".join(f"- {h}" for h in headlines))

    system = (
        "You profile company chief executives for retail investors. Write about the CURRENT chief "
        "executive named in the input - if they took the role recently, say so and cover their record "
        "before the role. Reply with ONLY a JSON object, no prose around it:\n"
        '{"introduction": "2-3 sentences: who they are, background, when they took the role", '
        '"achievements": ["3-5 short, concrete wins with years where known"], '
        '"pitfalls": ["2-4 short, concrete missteps, controversies or open risks under their leadership"], '
        '"verdict": "strong | steady | uncertain | concerning", '
        '"verdict_reason": "1-2 sentences on how safe the company looks under this leader"}\n'
        "Be factual and balanced; if you are unsure of a fact, leave it out rather than guess. "
        "No buy/sell advice, no disclaimers."
    )
    try:
        result = create_generation_backend(config).generate(
            "\n".join(lines), GenerationConfig(max_tokens=800, timeout=110), system_prompt=system
        )
    except Exception as exc:
        logger.warning("CEO brief unavailable: %s", exc)
        return None
    return _parse_brief(result.text or "")
