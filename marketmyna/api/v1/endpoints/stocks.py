"""Quote/history endpoints - thin wrappers over the existing marketmyna/data fetchers."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from marketmyna.api.deps import get_config_dep
from marketmyna.core.constants import Markets, TimeFrame
from marketmyna.data.china import ChinaAFetcher, HongKongFetcher
from marketmyna.data.crypto import CryptoDataFetcher
from marketmyna.data.india import IndiaDataFetcher
from marketmyna.data.stocks import StockDataFetcher
from marketmyna.utils.deadline import call_with_deadline

router = APIRouter()

_FETCHERS = {
    Markets.US: StockDataFetcher(),
    Markets.GLOBAL: StockDataFetcher(),
    Markets.INDIA: IndiaDataFetcher(),
    Markets.CRYPTO: CryptoDataFetcher(),
    Markets.CHINA_A: ChinaAFetcher(),
    Markets.HONG_KONG: HongKongFetcher(),
}


def _resolve_market(market: str) -> Markets:
    try:
        return Markets(market.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown market '{market}'")


@router.get("/stocks/{symbol}/quote")
def get_quote(symbol: str, market: str = Query(default="us")) -> dict:
    fetcher = _FETCHERS[_resolve_market(market)]
    try:
        return call_with_deadline(fetcher.get_quote, 20, symbol)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch quote: {exc}")


@router.get("/stocks/{symbol}/history")
def get_history(
    symbol: str,
    market: str = Query(default="us"),
    period: str = Query(default="1y"),
    interval: str = Query(default=TimeFrame.DAY_1.value),
) -> list[dict]:
    fetcher = _FETCHERS[_resolve_market(market)]
    try:
        timeframe = TimeFrame(interval)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown interval '{interval}'")

    try:
        df = call_with_deadline(fetcher.get_history, 40, symbol, period=period, interval=timeframe)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch history: {exc}")

    if df.empty:
        return []
    return df.reset_index().to_dict(orient="records")


@router.get("/stocks/{symbol}/overview")
def get_overview(symbol: str, market: str = Query(default="us")) -> dict:
    """Technicals, trend, returns, risk, fundamentals, analysts, events,
    profile and news for one stock - all computed, no AI call."""
    from marketmyna.services.overview import build_overview

    try:
        return call_with_deadline(build_overview, 60, symbol.strip().upper(), _resolve_market(market).value)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Overview timed out: {exc}")


def _financials(symbol: str, market: str, period: str) -> dict:
    from marketmyna.services.financials import cached_financials

    if period not in ("annual", "quarterly"):
        raise HTTPException(status_code=400, detail="period must be 'annual' or 'quarterly'")
    try:
        return call_with_deadline(cached_financials, 60, symbol.strip().upper(), _resolve_market(market).value, period)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Financial statements timed out: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch financial statements: {exc}")


@router.get("/stocks/{symbol}/financials")
def get_financials(symbol: str, market: str = Query(default="us"), period: str = Query(default="annual")) -> dict:
    """Income statement, balance sheet and cash flow with derived ratios,
    rule-based findings and a plain-English summary - no AI call."""
    return _financials(symbol, market, period)


@router.post("/stocks/{symbol}/financials/ai-summary")
def get_financials_ai_summary(
    symbol: str,
    market: str = Query(default="us"),
    period: str = Query(default="annual"),
    config=Depends(get_config_dep),
) -> dict:
    """AI analyst narrative over the three statements (uses the configured LLM)."""
    from marketmyna.llm.channels import llm_configured
    from marketmyna.services.financials import ai_summary

    if not llm_configured(config):
        raise HTTPException(status_code=409, detail="No AI model configured. Add one in Settings to get an AI summary.")
    data = _financials(symbol, market, period)
    text = call_with_deadline(ai_summary, 120, data, config)
    if not text:
        raise HTTPException(status_code=502, detail="The AI model did not return a summary. Try again or check Settings.")
    return {"symbol": data["symbol"], "period": data["period"], "summary": text}


@router.get("/stocks/{symbol}/shariah")
def get_shariah(symbol: str, market: str = Query(default="us")) -> dict:
    """Shariah screen: business activity, debt / cash / receivables ratios
    and interest income (S&P + AAOIFI limits), plus purification - no AI."""
    from marketmyna.services.shariah import build_shariah_profile

    try:
        return call_with_deadline(build_shariah_profile, 60, symbol.strip().upper(), _resolve_market(market).value)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Ethical screen timed out: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to run the ethical screen: {exc}")


def _leadership(symbol: str, market: str) -> dict:
    from marketmyna.services.leadership import build_leadership

    try:
        return call_with_deadline(build_leadership, 45, symbol.strip().upper(), _resolve_market(market).value)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Leadership data timed out: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch leadership data: {exc}")


@router.get("/stocks/{symbol}/leadership")
def get_leadership(symbol: str, market: str = Query(default="us")) -> dict:
    """CEO, other officers and governance risk scores - filing data, no AI."""
    return _leadership(symbol, market)


@router.get("/stocks/{symbol}/ownership")
def get_ownership(symbol: str, market: str = Query(default="us")) -> dict:
    """Insider / institution split, top holders, insider trades, short interest."""
    from marketmyna.services.ownership import build

    return build(symbol.upper(), market.lower())


@router.post("/stocks/{symbol}/mdna/ai-summary")
def get_mdna_summary(symbol: str, market: str = Query(default="us"), config=Depends(get_config_dep)) -> dict:
    """AI summary of the MD&A section of the latest 10-K / 10-Q (US SEC filers)."""
    from marketmyna.llm.channels import llm_configured
    from marketmyna.services.sec_mdna import SecNotConfigured, ai_summary

    if market.lower() != "us":
        raise HTTPException(status_code=400, detail="Management discussion summaries are for US (SEC) filers only")
    if not llm_configured(config):
        raise HTTPException(status_code=409, detail="No AI model configured. Add one in Settings to summarise filings.")
    try:
        return ai_summary(symbol.upper(), config)
    except SecNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Filing summary unavailable: {exc}")


@router.post("/stocks/{symbol}/leadership/ai-brief")
def get_leadership_ai_brief(symbol: str, market: str = Query(default="us"), config=Depends(get_config_dep)) -> dict:
    """AI brief on the CEO: introduction, achievements, pitfalls, verdict."""
    from marketmyna.data.news_search import stock_news
    from marketmyna.llm.channels import llm_configured
    from marketmyna.services.leadership import ai_ceo_brief

    if not llm_configured(config):
        raise HTTPException(status_code=409, detail="No AI model configured. Add one in Settings to get a CEO brief.")
    data = _leadership(symbol, market)
    try:
        news = stock_news(data["symbol"], data["market"], limit=10, name=data.get("name"))
        headlines = [n["title"] for n in news if n.get("title")]
    except Exception:
        headlines = []
    brief = call_with_deadline(ai_ceo_brief, 120, data, config, headlines)
    if not brief:
        raise HTTPException(status_code=502, detail="The AI model did not return a usable brief. Try again or check Settings.")
    return {"symbol": data["symbol"], "ceo": data["ceo"]["name"], **brief}


@router.get("/compare")
def compare_stocks(
    s: str = Query(description="Comma-separated SYMBOL:market pairs, e.g. AAPL:us,RELIANCE:india"),
    period: str = Query(default="1y", description="6mo | 1y | 3y | 5y"),
) -> dict:
    """2-5 instruments side by side: rebased prices, returns, risk, fundamentals, correlation."""
    from marketmyna.services.compare import compare

    items = []
    for part in s.split(","):
        if not part.strip():
            continue
        sym, _, mkt = part.partition(":")
        mkt = (mkt or "us").lower()
        _resolve_market(mkt)
        items.append((sym, mkt))
    try:
        return call_with_deadline(compare, 60, items, period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/stocks/{symbol}/peers")
def get_peers(symbol: str, market: str = Query(default="us"), limit: int = Query(default=6, ge=2, le=10)) -> dict:
    """Same-market companies in the same industry (or sector), closest in size."""
    from marketmyna.services.compare import peers

    _resolve_market(market)
    return call_with_deadline(peers, 60, symbol, market, limit)


@router.get("/stocks/{symbol}/valuation")
def get_valuation(symbol: str, market: str = Query(default="us")) -> dict:
    """Valuation meter: P/E, P/B and P/S against the sector median of the
    market's largest companies, plus a growth-at-a-reasonable-price check."""
    from marketmyna.services.valuation import meter

    _resolve_market(market)
    return call_with_deadline(meter, 90, symbol.upper(), market.lower())


@router.get("/stocks/{symbol}/dcf")
def get_dcf(symbol: str, market: str = Query(default="us")) -> dict:
    """Discounted cash flow with its default assumptions, reverse DCF (growth
    the price implies) and the Graham number. The page recomputes the DCF
    as the viewer edits the assumptions."""
    from marketmyna.services.dcf import build

    try:
        return call_with_deadline(build, 90, symbol.strip().upper(), _resolve_market(market).value)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"DCF timed out: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/stocks/{symbol}/checklists")
def get_checklists(symbol: str, market: str = Query(default="us")) -> dict:
    """Graham, Buffett-style, Lynch, Greenblatt and Marks-style rules, each pass / fail with its number."""
    from marketmyna.services.investor_lenses import build

    try:
        return call_with_deadline(build, 90, symbol.strip().upper(), _resolve_market(market).value)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Checklists timed out: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/stocks/{symbol}/estimates")
def get_estimates(symbol: str, market: str = Query(default="us")) -> dict:
    """Consensus EPS / revenue, revisions over 90 days, and recent beats or misses."""
    from marketmyna.services.analysis_run import yahoo_symbol
    from marketmyna.services.estimates import build

    _resolve_market(market)
    if market.lower() == "crypto":
        return {"available": False, "periods": [], "history": []}
    return call_with_deadline(build, 45, yahoo_symbol(symbol, market.lower()))


@router.get("/stocks/{symbol}/dcf/model.xlsx")
def get_dcf_model(symbol: str, market: str = Query(default="us"),
                  growth: Optional[float] = Query(default=None, ge=-0.5, le=1.0),
                  discount: Optional[float] = Query(default=None, gt=0, le=1.0),
                  terminal: Optional[float] = Query(default=None, ge=-0.05, le=0.2)) -> Response:
    """The DCF as an Excel workbook with live formulas and a sensitivity grid,
    at the rates the viewer chose on the page (defaults otherwise)."""
    from marketmyna.services import dcf, dcf_model

    sym = symbol.strip().upper()
    try:
        data = call_with_deadline(dcf.build, 90, sym, _resolve_market(market).value)
        body = dcf_model.build(data, growth, discount, terminal)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"DCF timed out: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(body, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{sym}-dcf-model.xlsx"'})


@router.get("/stocks/{symbol}/earnings")
def get_earnings(symbol: str, market: str = Query(default="us")) -> dict:
    """Earnings preview (next date, consensus, past reactions, options-implied
    move, what to watch) and review (actual vs estimate, price reaction)."""
    from marketmyna.services.earnings import build

    _resolve_market(market)
    if market.lower() == "crypto":
        return {"available": False, "history": []}
    return call_with_deadline(build, 60, symbol.upper(), market.lower())


@router.get("/etf/{symbol}")
def etf_lookthrough(symbol: str, market: str = Query(default="us")) -> dict:
    """ETF holdings, sector mix and costs; is_etf=false for anything else."""
    from marketmyna.services.etf import lookthrough

    _resolve_market(market)
    out = call_with_deadline(lookthrough, 45, symbol, market)
    out.pop("holdings", None)  # full list is only needed for overlap
    return out


@router.get("/etf-overlap")
def etf_overlap(a: str, b: str, market_a: str = Query(default="us"), market_b: Optional[str] = None) -> dict:
    """How much of two ETFs' weight sits in the same stocks."""
    from marketmyna.services.etf import lookthrough, overlap

    market_b = market_b or market_a
    _resolve_market(market_a)
    _resolve_market(market_b)
    x = call_with_deadline(lookthrough, 45, a, market_a)
    y = call_with_deadline(lookthrough, 45, b, market_b)
    if not (x.get("status") == "ok" and y.get("status") == "ok"):
        return {"a": a.upper(), "b": b.upper(), "available": False}
    return {"available": True, **overlap(x, y)}


@router.get("/stocks/{symbol}/dividends")
def get_dividends(symbol: str, market: str = Query(default="us")) -> dict:
    """Payments, yearly totals, trailing yield, 5-year growth and years without a cut."""
    from marketmyna.services.analysis_run import yahoo_symbol
    from marketmyna.services.dividends import build

    _resolve_market(market)
    if market.lower() == "crypto":
        return {"pays": False}
    return call_with_deadline(build, 45, yahoo_symbol(symbol, market.lower()))


def _social(symbol: str, market: str, config, refresh: bool = False) -> dict:
    from marketmyna.api.deps import get_database_manager
    from marketmyna.services import social_sentiment

    market = _resolve_market(market).value
    try:
        db = get_database_manager()
    except Exception:
        db = None
    try:
        return call_with_deadline(social_sentiment.build, 150, symbol, market, config, db, refresh)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Social sentiment timed out: {exc}")


@router.get("/stocks/{symbol}/social")
def get_social_sentiment(
    symbol: str,
    market: str = Query(default="us"),
    refresh: bool = Query(default=False),
    config=Depends(get_config_dep),
) -> dict:
    """What people say on Reddit / StockTwits / ValuePickr / Hacker News:
    score, bull/bear split, themes, timeline and top posts. Lexicon-scored,
    no AI; cached 20 minutes per stock."""
    return _social(symbol, market, config, refresh)


@router.post("/stocks/{symbol}/social/ai-summary")
def get_social_ai_summary(symbol: str, market: str = Query(default="us"), config=Depends(get_config_dep)) -> dict:
    """AI digest of the chatter: summary, bull and bear arguments, hype risk."""
    from marketmyna.llm.channels import llm_configured
    from marketmyna.services.social_sentiment import ai_summary

    if not llm_configured(config):
        raise HTTPException(status_code=409, detail="No AI model configured. Add one in Settings to summarise the chatter.")
    data = _social(symbol, market, config)
    if not data["posts"]:
        raise HTTPException(status_code=404, detail="No recent posts to summarise.")
    summary = call_with_deadline(ai_summary, 120, data, config)
    if not summary:
        raise HTTPException(status_code=502, detail="The AI model did not return a usable summary. Try again or check Settings.")
    return {"symbol": data["symbol"], "posts": data["posts"], **summary}
