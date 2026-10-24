"""The three built agents: technical, risk, decision.

Each agent's `run(ctx, backend)` follows the same shape: pull/compute
deterministic data via MarketMyna's own analysis modules (never
reimplemented here), hand a compact structured summary of that to the
LLM backend for narration, and return an AgentOpinion. The *signal*
each agent reports is derived from the deterministic computation, not
parsed out of the LLM's free text - the LLM's job is narration, not
being the source of truth for a value code can already compute exactly.

DecisionAgent is the one exception: it has no tools of its own (matches
the reference's decision agent having tool_names=[]) and its whole job
IS to produce a decision, so its output does require parsing the LLM's
response - done defensively, with a safe "hold" fallback on anything
that doesn't parse.

Scope cut: no IntelAgent (news search + risk-event detection) - that
needs a news-search API/tool that isn't configured. RiskAgent covers a
narrower, purely data-derived notion of risk (valuation extremes,
volatility, drawdown) instead of news-driven risk events.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

import pandas as pd

from ..analysis.fundamental import FundamentalAnalyzer
from ..analysis.technical import Signal, TechnicalAnalyzer
from ..core.compliance import guard_prompt, outlook
from ..core.constants import Markets
from ..data.china import ChinaAFetcher, HongKongFetcher
from ..data.crypto import CryptoDataFetcher
from ..data.india import IndiaDataFetcher
from ..data.stocks import StockDataFetcher
from ..llm.protocol import GenerationBackend, GenerationConfig
from .context import AgentContext, AgentOpinion
from .skills import Skill

logger = logging.getLogger(__name__)

# Same fetcher-per-market pattern as marketmyna/api/v1/endpoints/stocks.py.
_FETCHERS = {
    Markets.US: StockDataFetcher(),
    Markets.GLOBAL: StockDataFetcher(),
    Markets.INDIA: IndiaDataFetcher(),
    Markets.CRYPTO: CryptoDataFetcher(),
    Markets.CHINA_A: ChinaAFetcher(),
    Markets.HONG_KONG: HongKongFetcher(),
}

_TREND_SIGNAL_MAP = {
    Signal.STRONG_BUY: "bullish",
    Signal.BUY: "bullish",
    Signal.NEUTRAL: "neutral",
    Signal.SELL: "bearish",
    Signal.STRONG_SELL: "bearish",
}


def _resolve_fetcher(market: str):
    try:
        return _FETCHERS[Markets(market.lower())]
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Unknown market '{market}'") from exc


# Appended to every agent's instructions: the app computes the numbers,
# the model only explains them - and must keep facts and opinion apart.
GUARDRAIL = (
    " Use only the figures given in the input; never invent or recompute prices, ratios or "
    "dates. Describe outlooks as possibilities with their reasons, not as certainties, and "
    "do not present the output as personalised investment advice."
)


def _scope(ctx: AgentContext, stage: str) -> str:
    """Cache scope for one stage of one stock's analysis: the AI's wording is
    reused for the cache's lifetime (marketmyna/llm/store.py) even as the live
    numbers in the prompt move, so a stock opened again, or booked by many
    users, costs no new AI call."""
    parts = [stage, ctx.symbol.upper(), ctx.market, getattr(ctx, "mode", ""), getattr(ctx, "area", None) or ""]
    return "|".join(["agent", *parts])


def _call_llm(backend: GenerationBackend, system_prompt: str, prompt: str, scope: Optional[str] = None) -> str:
    """Every agent's one LLM call, unified so error handling/config is in
    one place. Raises GenerationError on failure - callers don't catch it
    themselves, the orchestrator decides critical-vs-not per stage."""
    result = backend.generate(prompt, GenerationConfig(cache_scope=scope), system_prompt=system_prompt + GUARDRAIL)
    return result.text.strip()


def _narrate(backend: GenerationBackend, system_prompt: str, prompt: str, fallback: str,
             scope: Optional[str] = None) -> str:
    """LLM commentary for a stage whose numbers are computed without AI
    (technical, risk). If the LLM is missing or failing, the stage still
    succeeds with a rule-based sentence instead of taking the whole
    pipeline down - only the decision stage truly needs the model."""
    try:
        # Commentary is a "level 1" job: use the fast/cheap model when one
        # is configured (the backend falls back to the main chain itself).
        return _call_llm(getattr(backend, "fast", backend), system_prompt, prompt, scope)
    except Exception as exc:
        logger.info("LLM commentary unavailable (%s); using rule-based summary", exc)
        return fallback


class TechnicalAgent:
    agent_name = "technical"

    def run(self, ctx: AgentContext, backend: GenerationBackend) -> AgentOpinion:
        fetcher = _resolve_fetcher(ctx.market)

        ctx.quote = fetcher.get_quote(ctx.symbol)
        ctx.history = fetcher.get_history(ctx.symbol, period="1y")

        analyzer = TechnicalAnalyzer(ctx.history)
        raw_summary = analyzer.get_summary()
        # get_summary()'s overall_signal is a Signal enum instance, not
        # JSON-safe - normalize before it goes anywhere near a prompt or
        # a dashboard payload.
        overall_signal: Signal = raw_summary["overall_signal"]
        ctx.technical_summary = {
            "overall_signal": overall_signal.value,
            "buy_signals": raw_summary["buy_signals"],
            "sell_signals": raw_summary["sell_signals"],
            "neutral_signals": raw_summary["neutral_signals"],
            "indicators": raw_summary["indicators"],
        }

        total = max(
            ctx.technical_summary["buy_signals"]
            + ctx.technical_summary["sell_signals"]
            + ctx.technical_summary["neutral_signals"],
            1,
        )
        dominant = max(
            ctx.technical_summary["buy_signals"],
            ctx.technical_summary["sell_signals"],
            ctx.technical_summary["neutral_signals"],
        )
        confidence = round(dominant / total, 2)

        system_prompt = (
            "You are a technical analysis assistant for a stock research tool. "
            "Given a structured summary of technical indicators, write a concise "
            "2-4 sentence opinion on the current trend and momentum. Do not "
            "restate raw numbers verbatim, interpret them."
        )
        system_prompt = guard_prompt(system_prompt)
        prompt = (
            f"Symbol: {ctx.symbol} ({ctx.market})\n"
            f"Current price: {ctx.quote.get('price')}\n"
            f"Technical summary: {json.dumps(ctx.technical_summary)}"
        )
        # Without a model: the indicator values only, no verdict words.
        fallback = "Indicator readings: " + ", ".join(
            f"{name} {info['value']:.2f}" if isinstance(info.get("value"), (int, float)) else name
            for name, info in list(ctx.technical_summary["indicators"].items())[:6]) + "."
        narrative = _narrate(backend, system_prompt, prompt, fallback, scope=_scope(ctx, self.agent_name))

        return AgentOpinion(
            agent_name=self.agent_name,
            summary=narrative,
            signal=_TREND_SIGNAL_MAP.get(overall_signal, "neutral"),
            confidence=confidence,
            details=ctx.technical_summary,
        )


def _max_drawdown(close: pd.Series) -> float:
    running_max = close.cummax()
    drawdown = (close - running_max) / running_max
    return float(drawdown.min())


def _annualized_volatility(close: pd.Series) -> float:
    returns = close.pct_change().dropna()
    if returns.empty:
        return 0.0
    return float(returns.std() * (252 ** 0.5))


class RiskAgent:
    agent_name = "risk"

    def run(self, ctx: AgentContext, backend: GenerationBackend) -> AgentOpinion:
        fetcher = _resolve_fetcher(ctx.market)

        # Reuse history/quote TechnicalAgent already fetched when this
        # runs after it in the chain; only fetch if run standalone.
        if ctx.history is None:
            ctx.history = fetcher.get_history(ctx.symbol, period="1y")
        if ctx.quote is None:
            ctx.quote = fetcher.get_quote(ctx.symbol)

        volatility = _annualized_volatility(ctx.history["close"])
        max_drawdown = _max_drawdown(ctx.history["close"])

        fundamental_summary = None
        try:
            info = fetcher.get_info(ctx.symbol)
            ctx.info = info
            fundamental_summary = FundamentalAnalyzer(info).get_summary()
            ctx.fundamental_summary = fundamental_summary
        except Exception:
            # Fundamentals aren't available/meaningful for every market
            # (e.g. crypto) - risk assessment still works from price
            # action alone.
            pass

        risk_level = "low"
        if volatility > 0.5 or max_drawdown < -0.35:
            risk_level = "high"
        elif volatility > 0.25 or max_drawdown < -0.2:
            risk_level = "medium"

        ctx.risk_metrics = {
            "volatility": round(volatility, 4),
            "max_drawdown": round(max_drawdown, 4),
            "risk_level": risk_level,
        }

        system_prompt = (
            "You are a risk analyst for a stock research tool. Given price-risk "
            "statistics and (if available) fundamental valuation data, write a "
            "concise 2-3 sentence risk commentary. Be specific about what is "
            "driving the risk level, not generic."
        )
        system_prompt = guard_prompt(system_prompt)
        prompt_parts = [
            f"Symbol: {ctx.symbol} ({ctx.market})",
            f"Annualized volatility: {volatility:.2%}",
            f"Max drawdown (lookback): {max_drawdown:.2%}",
            f"Computed risk level: {risk_level}",
        ]
        if fundamental_summary:
            prompt_parts.append(
                f"Fundamental valuation: {fundamental_summary['valuation']['status']}, "
                f"overall score {fundamental_summary['overall_score']}/100"
            )
        fallback = (
            f"Annualized volatility {volatility:.0%} and max drawdown {max_drawdown:.0%} "
            f"over the past year put this at {risk_level} risk."
        )
        narrative = _narrate(backend, system_prompt, "\n".join(prompt_parts), fallback,
                             scope=_scope(ctx, self.agent_name))

        return AgentOpinion(
            agent_name=self.agent_name,
            summary=narrative,
            signal=None,
            confidence=None,
            details=ctx.risk_metrics,
        )


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class NewsAgent:
    """Collects recent headlines and reads their tone, so the decision
    reflects events (results, deals, downgrades) and not just charts."""

    agent_name = "news"

    def __init__(self, search: Optional[Callable[..., list]] = None):
        self._search = search

    def run(self, ctx: AgentContext, backend: GenerationBackend) -> AgentOpinion:
        search = self._search
        if search is None:
            from ..data.news_search import stock_news as search

        name = (ctx.info or {}).get("name") or None
        ctx.news = search(ctx.symbol, ctx.market, limit=6, name=name)
        if not ctx.news:
            return AgentOpinion(
                agent_name=self.agent_name,
                summary="No recent news found.",
                signal="neutral",
                confidence=None,
                details={"headlines": []},
            )

        headlines = "\n".join(
            f"- {(n.get('published') or '')[:10]} {n['title']}" + (f" ({n['source']})" if n.get("source") else "")
            for n in ctx.news
        )
        # The tone of the news, not a view on the stock.
        system_prompt = guard_prompt(
            "You summarise recent headlines about one company. Reply ONLY with JSON: "
            "{\"sentiment\": \"positive\"|\"negative\"|\"neutral\" (the tone of the news), "
            "\"summary\": \"2-3 sentences on what the headlines report\"}. "
            "Ignore headlines that are about a different company.")
        prompt = f"Stock: {ctx.symbol} ({ctx.market})\nRecent headlines:\n{headlines}"
        fallback = json.dumps({
            "sentiment": None,  # without a model nobody judged the tone - don't guess
            "summary": f"{len(ctx.news)} recent headlines; latest: {ctx.news[0]['title']}",
        })
        raw = _narrate(backend, system_prompt, prompt, fallback, scope=_scope(ctx, self.agent_name))
        match = _JSON_RE.search(raw)
        try:
            parsed = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            parsed = {}
        sentiment = str(parsed.get("sentiment") or "").lower() or None
        sentiment = {"positive": "bullish", "negative": "bearish"}.get(sentiment, sentiment)
        if sentiment is not None and sentiment not in ("bullish", "bearish", "neutral"):
            sentiment = "neutral"
        return AgentOpinion(
            agent_name=self.agent_name,
            summary=str(parsed.get("summary") or raw).strip(),
            signal=sentiment,
            confidence=None,
            details={"headlines": [n["title"] for n in ctx.news]},
        )


class FundamentalsAgent:
    """Full / Specialist depth: reads the company's filings, its valuation
    against the sector and the analyst consensus (the same services as the
    Analyze page's cards) so the decision stage sees the business, not only
    the chart. Non-critical: any source that fails or times out is skipped."""

    agent_name = "fundamentals"

    def run(self, ctx: AgentContext, backend: GenerationBackend) -> AgentOpinion:
        from ..services.analysis_run import yahoo_symbol
        from ..services.estimates import build as build_estimates
        from ..services.financials import build_financials
        from ..services.valuation import meter
        from ..utils.deadline import call_with_deadline

        if ctx.market == "crypto":
            return AgentOpinion(agent_name=self.agent_name, summary="Company fundamentals don't apply to crypto.",
                                signal=None, confidence=None, details={})

        def safe(fn, seconds, *args):
            try:
                return call_with_deadline(fn, seconds, *args)
            except Exception as exc:  # noqa: BLE001 - one missing source is fine
                logger.info("Fundamentals source %s for %s skipped: %s", getattr(fn, "__name__", fn), ctx.symbol, exc)
                return None

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=3) as pool:  # three independent sources, fetched together
            fin_f = pool.submit(safe, build_financials, 60, ctx.symbol, ctx.market, "annual")
            val_f = pool.submit(safe, meter, 60, ctx.symbol, ctx.market)
            est_f = pool.submit(safe, build_estimates, 45, yahoo_symbol(ctx.symbol, ctx.market))
            fin, val, est = fin_f.result() or {}, val_f.result() or {}, est_f.result() or {}

        facts: dict = {}
        if fin.get("overall"):
            facts["financial_statements"] = {
                "overall": fin["overall"],
                **{k: {"verdict": (fin.get(k) or {}).get("verdict"),
                       "findings": [f["text"] for f in ((fin.get(k) or {}).get("findings") or [])[:4]]}
                   for k in ("income", "balance", "cashflow") if fin.get(k)},
            }
        if val.get("status") == "ok":
            facts["valuation_vs_sector"] = {
                "sector": val.get("sector"), "peers": val.get("peers"), "zone": val.get("zone"),
                "multiples": [{"label": m["label"], "value": m.get("value"), "sector_median": m.get("sector_median")}
                              for m in val.get("multiples") or []],
                "growth_checks_passed": f"{(val.get('garp') or {}).get('passed')}/{(val.get('garp') or {}).get('total')}",
            }
        if est.get("available"):
            facts["analyst_estimates"] = {
                "eps_trend_90d": (est.get("momentum") or {}).get("label"),
                "beats": est.get("beats"),
                "periods": [{"label": p.get("label"), "eps": (p.get("eps") or {}).get("avg"),
                             "eps_growth": (p.get("eps") or {}).get("growth")} for p in (est.get("periods") or [])[:4]],
            }
        if not facts:
            raise RuntimeError("no fundamental data available")

        system_prompt = guard_prompt(
            "You are a fundamental analyst for a stock research tool. Given the company's financial-statement "
            "checks, its valuation multiples against its sector median and the analyst estimate trend, write "
            "3-4 sentences on the quality of the business, how it is priced relative to its sector, and how "
            "expectations are moving. Use the numbers given; don't invent any."
        )
        prompt = f"Symbol: {ctx.symbol} ({ctx.market})\nFundamental data: {json.dumps(facts, default=str)}"
        bits = []
        if "financial_statements" in facts:
            o = facts["financial_statements"]["overall"]
            bits.append(f"filings read {o.get('label')} ({o.get('score')}/100)")
        if "valuation_vs_sector" in facts:
            v = facts["valuation_vs_sector"]
            where = {"below": "below", "above": "above", "in_line": "in line with"}.get(v["zone"], "against")
            bits.append(f"priced {where} its {v['sector']} sector on P/E, P/B and P/S")
        if "analyst_estimates" in facts:
            e = facts["analyst_estimates"]
            bits.append(f"analyst EPS estimates {e['eps_trend_90d'] or 'unchanged'} over 90 days")
        fallback = "Rule-based read: " + "; ".join(bits) + "."
        narrative = _narrate(backend, system_prompt, prompt, fallback, scope=_scope(ctx, self.agent_name))
        return AgentOpinion(agent_name=self.agent_name, summary=narrative, signal=None, confidence=None, details=facts)


_EXPLAIN_FOCUS = {
    "": (
        "what changed recently, the main strengths and weaknesses in the data, the risks to watch "
        "and the questions an investor would want to research next."
    ),
    "trader": (
        "the current trend and momentum, where price sits against its recent support, resistance "
        "and normal range, how volatile it is, upcoming events in the next few weeks and the "
        "questions a short-term trader would check next."
    ),
    "investor": (
        "how the business is doing (growth, margins, debt), how its valuation compares with its "
        "sector and history, the long-term risks and the questions a long-term investor would "
        "research next."
    ),
}


def _trade_levels(ctx: AgentContext) -> dict:
    """Support / resistance / ATR from the history TechnicalAgent already
    fetched (same maths as the smart report), for the trader prompt."""
    if ctx.history is None:
        return {}
    try:
        from ..services.smart_report import compute_snapshot

        snap = compute_snapshot(ctx.history)
    except Exception:
        return {}
    names = {
        "trend": "Trend", "buy_point": "Support", "sell_point": "Resistance", "atr": "ATR (14 days)",
        "normal_low": "Normal range low (20-day band)", "normal_high": "Normal range high",
        "week_low": "1-week expected low", "week_high": "1-week expected high",
        "rsi": "RSI (14)", "volume_ratio": "Volume vs 20-day average",
    }
    return {label: (round(snap[k], 2) if isinstance(snap.get(k), float) else snap.get(k))
            for k, label in names.items() if snap.get(k) is not None}


class DecisionAgent:
    """The last stage: a plain explanation of what the earlier stages found
    and the outlook they point to (bullish / neutral / bearish), never a buy
    / hold / sell call, target or stop loss (marketmyna/core/compliance.py)."""

    agent_name = "decision"

    def run(self, ctx: AgentContext, backend: GenerationBackend) -> AgentOpinion:
        opinions_text = "\n".join(
            f"- {op.agent_name} (signal={op.signal}): {op.summary}" for op in ctx.opinions
        )
        focus = _EXPLAIN_FOCUS.get(getattr(ctx, "area", None) or "", _EXPLAIN_FOCUS[""])
        system_prompt = guard_prompt(
            "You summarise research for a stock analytics tool that is not a registered adviser. "
            f"Write one paragraph that explains what the figures show: {focus} Never recommend buying, holding, selling, "
            "accumulating or exiting, never give a price target or stop loss, and do not use words "
            "like attractive, cheap or expensive as a verdict. Also give the outlook the findings point to: "
            "bullish, neutral or bearish, as a direction, never as an instruction. Respond ONLY with a JSON "
            'object: {"outlook": "bullish"|"neutral"|"bearish", "rationale": "one paragraph"}.'
        )
        prompt = (
            f"Symbol: {ctx.symbol} ({ctx.market})\n"
            f"Current price: {(ctx.quote or {}).get('price')}\n\n"
            f"Findings from the analysis steps:\n{opinions_text}"
        )
        if getattr(ctx, "area", None) == "trader":
            levels = _trade_levels(ctx)
            if levels:
                prompt += "\n\nPrice levels (daily bars):\n" + "\n".join(f"- {k}: {v}" for k, v in levels.items())
        if ctx.news:
            prompt += "\n\nRecent headlines:\n" + "\n".join(
                f"- {(n.get('published') or '')[:10]} {n['title']}" for n in ctx.news[:6]
            )
        try:
            from ..services.macro import cached_context

            macro = cached_context()
        except Exception:
            macro = []
        if macro:
            prompt += "\n\nMacro backdrop (weigh lightly, it moves the whole market):\n" + "\n".join(f"- {m}" for m in macro)
        from .sentiment import social_block

        social = social_block(ctx)
        if social:
            prompt += "\n\n" + social
        narrative = _call_llm(backend, system_prompt, prompt, scope=_scope(ctx, self.agent_name))
        match = _JSON_RE.search(narrative)
        rationale, direction = narrative, None
        if match:
            try:
                parsed = json.loads(match.group(0))
                rationale = parsed.get("rationale") or narrative
                direction = outlook(parsed.get("outlook"))
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
        return AgentOpinion(agent_name=self.agent_name, summary=rationale, signal=direction, confidence=None, details={})


class SkillAgent:
    """Applies one Skill's strategy instructions to whatever real context
    (technical summary, risk metrics, quote) is already on ctx. Multiple
    SkillAgents can run in one pipeline, each under its own agent_name
    (f"skill:{skill.name}") so their opinions don't collide in
    ctx.opinions - unlike the fixed-name agents above, this one is
    constructed per-skill rather than being a singleton in the chain."""

    def __init__(self, skill: Skill):
        self.skill = skill
        self.agent_name = f"skill:{skill.name}"

    def run(self, ctx: AgentContext, backend: GenerationBackend) -> AgentOpinion:
        system_prompt = (
            f"You are applying a specific trading strategy, '{self.skill.display_name}', "
            "to a stock analysis. Follow the strategy instructions below to form an "
            "opinion. If the instructions call for data that isn't provided here "
            "(e.g. news or sector data), say so explicitly rather than inventing it. "
            "Respond with a concise 2-4 sentence opinion.\n\n"
            f"--- Strategy instructions ---\n{self.skill.instructions}"
        )
        system_prompt = guard_prompt(system_prompt)
        prompt_parts = [f"Symbol: {ctx.symbol} ({ctx.market})"]
        if ctx.quote:
            prompt_parts.append(f"Current price: {ctx.quote.get('price')}")
        if ctx.technical_summary:
            prompt_parts.append(f"Technical summary: {json.dumps(ctx.technical_summary)}")
        if ctx.risk_metrics:
            prompt_parts.append(f"Risk metrics: {json.dumps(ctx.risk_metrics)}")
        narrative = _call_llm(backend, system_prompt, "\n".join(prompt_parts),
                              scope=_scope(ctx, self.agent_name))

        return AgentOpinion(
            agent_name=self.agent_name,
            summary=narrative,
            signal=None,
            confidence=None,
            details={"skill": self.skill.name, "category": self.skill.category},
        )
