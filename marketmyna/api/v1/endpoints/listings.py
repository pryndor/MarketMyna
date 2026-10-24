"""Market-wide listing endpoints: browse/search every stock, ETF and mutual
fund per market (screener-style), backed by marketmyna/data/listings.py."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from marketmyna.api.deps import get_config_dep
from marketmyna.data.listings import MARKET_LABELS, get_store, query
from marketmyna.data.mutual_funds import MutualFundDataFetcher

router = APIRouter()

_MARKETS = set(MARKET_LABELS) | {"all", "global"}
_TYPES = {"all", "stock", "etf", "mf", "crypto"}

_mf = MutualFundDataFetcher()


def _market(market: str) -> str:
    market = market.lower()
    if market not in _MARKETS:
        raise HTTPException(status_code=400, detail=f"Unknown market '{market}'")
    return market


def _csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@router.get("/listings")
def list_instruments(
    market: str = Query(default="india"),
    type: str = Query(default="all", description="all | stock | etf | mf | crypto"),
    q: str = Query(default="", max_length=100),
    sector: str = Query(default=""),
    exchange: str = Query(default=""),
    plan: str = Query(default="", description="Mutual funds: Direct | Regular"),
    option: str = Query(default="", description="Mutual funds: Growth | IDCW"),
    min_cap: Optional[float] = Query(default=None),
    max_cap: Optional[float] = Query(default=None),
    category: str = Query(default="", description="Comma-separated broad categories, e.g. Technology,Agriculture"),
    cap: str = Query(default="", description="Comma-separated size bands: large,mid,small,micro"),
    shariah: str = Query(default="", description="Comma-separated Shariah screen statuses: halal,doubtful,haram,unknown"),
    price_min: Optional[float] = Query(default=None, ge=0),
    price_max: Optional[float] = Query(default=None, ge=0),
    change_min: Optional[float] = Query(default=None, description="Day change %, lower bound"),
    change_max: Optional[float] = Query(default=None, description="Day change %, upper bound"),
    near_high: Optional[float] = Query(default=None, ge=0, le=100, description="Within N% of 52-week high"),
    near_low: Optional[float] = Query(default=None, ge=0, le=100, description="Within N% of 52-week low"),
    min_volume: Optional[float] = Query(default=None, ge=0),
    max_volume: Optional[float] = Query(default=None, ge=0),
    markets: str = Query(default="", description="All-markets view: comma-separated markets to keep"),
    sip_edge: str = Query(default="", description="Funds / ETFs: consistent | no_edge | short (historically best SIP day)"),
    sort: str = Query(default="market_cap"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    market = _market(market)
    if type not in _TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown type '{type}'")
    store = get_store()
    from marketmyna.services import sip_days

    rows = store.rows(market)
    sip_days.annotate(rows, market)
    if sip_edge:
        rows = [r for r in rows if r.get("sip_edge") in set(_csv(sip_edge))]
    result = query(
        rows,
        q=q,
        type_=type,
        sector=sector,
        exchange=exchange,
        plan=plan,
        option=option,
        min_cap=min_cap,
        max_cap=max_cap,
        categories=_csv(category),
        cap_sizes=_csv(cap),
        shariah=_csv(shariah),
        price_min=price_min,
        price_max=price_max,
        change_min=change_min,
        change_max=change_max,
        near_high=near_high,
        near_low=near_low,
        min_volume=min_volume,
        max_volume=max_volume,
        markets=_csv(markets),
        sort=sort,
        order=order,
        offset=offset,
        limit=limit,
    )
    result["sources"] = [s for s in store.status() if s["source"] in store.keys_for(market)]
    return result


# Typeahead answers with the markets loaded by then; slower ones join later searches.
SEARCH_WAIT = 8.0


@router.get("/listings/search")
def search_instruments(
    q: str = Query(..., min_length=1, max_length=100),
    market: str = Query(default="all"),
    type: str = Query(default="all"),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict]:
    """Typeahead: best matches by relevance, then size."""
    market = _market(market)
    rows = get_store().rows(market, wait=SEARCH_WAIT)
    return query(rows, q=q, type_=type if type in _TYPES else "all", limit=limit)["rows"]


@router.get("/listings/discovery")
def market_discovery(
    market: str = Query(default="india"),
    size: int = Query(default=500, ge=20, le=3000, description="Rank the N largest names"),
) -> dict:
    """Index snapshot, breadth, gainers / losers / most active, 52-week extremes, sectors."""
    from marketmyna.services import live_market
    from marketmyna.services.discovery import DISCOVERY_MARKETS, build

    market = market.lower()
    if market not in DISCOVERY_MARKETS:
        raise HTTPException(status_code=400, detail=f"Discovery not available for '{market}'")
    return build(market, size, live=live_market.market(market))


@router.get("/listings/hot")
def hot_stocks(
    market: str = Query(default="india"),
    area: str = Query(default="trader", pattern="^(trader|investor)$"),
) -> dict:
    """Hot stocks for the login area: what is moving today (trader) or the
    businesses being re-priced with fundamentals behind them (investor)."""
    from marketmyna.services import hot_stocks as hot
    from marketmyna.services import live_market
    from marketmyna.services.discovery import DISCOVERY_MARKETS
    from marketmyna.utils.deadline import call_with_deadline

    market = market.lower()
    if market not in DISCOVERY_MARKETS:
        raise HTTPException(status_code=400, detail=f"Hot stocks not available for '{market}'")
    live = live_market.market(market)
    if area == "trader":
        return hot.trader(market, live=live)
    return hot.with_live_prices(call_with_deadline(hot.investor, 90, market), live)


@router.get("/listings/rotation")
def sector_rotation(market: str = Query(default="india")) -> dict:
    """Relative rotation of sector baskets vs the market index (RRG), with
    today's live prices moving the current week's point."""
    from marketmyna.services import live_market
    from marketmyna.services.analysis_run import MARKET_INDICES
    from marketmyna.services.rotation import ROTATION_MARKETS, build

    market = market.lower()
    if market not in ROTATION_MARKETS:
        raise HTTPException(status_code=400, detail=f"Sector rotation not available for '{market}'")

    def run() -> dict:
        live = live_market.market(market)
        prices = live_market.for_tickers(market, live["quotes"])
        if market != "crypto":
            prices.update(live_market.latest([MARKET_INDICES[market][0][0]]))
        return {**build(market, live=prices), "live": live["status"]}

    try:
        return live_market.memo(("rotation", market), run)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/listings/deals")
def nse_deals(days: int = Query(default=1, ge=1, le=90)) -> dict:
    """NSE bulk and block deals over the last N days (history builds up daily)."""
    from marketmyna.data.nse_deals import recent

    return recent(days)


@router.get("/listings/live")
def live_quotes(market: str, symbols: str = Query(..., max_length=2000)) -> dict:
    """Latest prices for the rows on screen; the page asks every second.
    Served from a shared cache that refreshes upstream every few seconds
    (marketmyna/services/live_quotes.py), so polling stays cheap."""
    from marketmyna.services import live_quotes as live

    if market not in MARKET_LABELS:
        raise HTTPException(status_code=400, detail=f"Unknown market '{market}'")
    return live.get(market, symbols.split(","))


_KNOWN: dict[str, tuple[float, frozenset]] = {}
KNOWN_TTL = 600.0


def _listed(market: str, symbol: str) -> bool:
    """Whether `symbol` is a listing of `market` (set rebuilt every 10 min).
    Unlisted text never joins the live watch list, where every extra symbol
    slows the shared per-second refresh. With no listings loaded, allow."""
    import time

    hit = _KNOWN.get(market)
    if hit is None or time.monotonic() - hit[0] > KNOWN_TTL:
        hit = (time.monotonic(), frozenset(str(r.get("symbol", "")).upper() for r in get_store().rows(market)))
        _KNOWN[market] = hit
    return not hit[1] or symbol in hit[1]


@router.get("/listings/activity")
def trading_activity(market: str, symbol: str = Query(..., max_length=40)) -> dict:
    """Live trading activity for one stock page: price and volume from the
    shared live cache, plus for India the broker's pending buy / sell
    quantity and best five bids / offers, and last session's delivery %."""
    from marketmyna.services import live_quotes as live

    if market not in MARKET_LABELS:
        raise HTTPException(status_code=400, detail=f"Unknown market '{market}'")
    sym = symbol.strip().upper()
    if market == "india":
        sym = sym.removesuffix(".NS").removesuffix(".BO")
    elif market == "hong_kong":
        sym = sym.removesuffix(".HK").zfill(5)  # listings use 00700
    elif market == "china_a":
        sym = sym.removesuffix(".SS").removesuffix(".SZ")
    quotes = live.get(market, [sym] if _listed(market, sym) else [], depth=True)
    out = {k: quotes[k] for k in ("market", "open", "age_seconds", "refresh_seconds", "source", "error")}
    out["symbol"], out["quote"] = sym, quotes["quotes"].get(sym)
    if market == "india":
        from marketmyna.services import delivery

        out["delivery"] = delivery.get(sym)
    return out


@router.get("/listings/etf-rotation")
def etf_rotation(market: str = Query(default="us"), view: Optional[str] = Query(default=None, max_length=60)) -> dict:
    """ETF rotation vs the home market (us | hong_kong | china_a): the
    non-India counterpart of the mutual-fund rotation."""
    from marketmyna.services import etf_rotation as er
    from marketmyna.services import live_market
    from marketmyna.utils.deadline import call_with_deadline

    market = market.lower()

    def run() -> dict:
        prices = live_market.latest(er.tickers(market, view)) if market in er.UNIVERSES else {}
        out = call_with_deadline(er.build, 90, market, view, live=prices)
        return {**out, "live": live_market.status_for(prices)}

    try:
        return live_market.memo(("etf-rotation", market, view), run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TimeoutError:
        raise HTTPException(status_code=503, detail="Still loading ETF prices - try again in a minute.")


class TranslateRequest(BaseModel):
    market: str = "china_a"
    names: list[dict] = Field(default_factory=list, max_length=200)  # [{"symbol", "name"}]
    texts: list[str] = Field(default_factory=list, max_length=300)


@router.post("/translate")
def translate(req: TranslateRequest) -> dict:
    """English for Chinese stock names (official English name from Yahoo,
    cached) and free text such as broker branches (glossary + pinyin)."""
    from marketmyna.services import translate as tr
    from marketmyna.utils.deadline import call_with_deadline

    items = [(str(n.get("symbol", ""))[:20], str(n.get("name", ""))[:200]) for n in req.names
             if n.get("symbol") and tr.has_cjk(str(n.get("name", "")))]
    try:
        names = call_with_deadline(tr.english_names, 60, items, req.market.lower()) if items else {}
    except TimeoutError:
        names = {}
    texts = {t: tr.english_text(t) for t in dict.fromkeys(req.texts) if tr.has_cjk(t)}
    return {"names": names, "texts": texts}


@router.get("/listings/big-trades")
def big_trades(market: str = Query(default="us"), days: int = Query(default=1, ge=1, le=30)) -> dict:
    """Big trades outside India: US insider Form 4 trades, China block trades,
    HK southbound Stock Connect, crypto big-trader positioning."""
    from marketmyna.services import big_trades as bt
    from marketmyna.services.sec_mdna import SecNotConfigured
    from marketmyna.utils.deadline import call_with_deadline

    try:
        return call_with_deadline(bt.build, 120, market, days)
    except SecNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TimeoutError:
        raise HTTPException(status_code=503, detail="Still collecting trades - try again in a minute.")


@router.get("/listings/fund-rotation")
def fund_rotation(by: str = Query(default="category", pattern="^(category|amc)$"),
                  group: Optional[str] = Query(default=None, max_length=120)) -> dict:
    """Leading / weakening / lagging / improving for equity fund categories or
    fund houses vs the Nifty 500; with `group`, each fund inside it."""
    from marketmyna.services import fund_rotation as fr
    from marketmyna.utils.deadline import call_with_deadline

    try:
        return call_with_deadline(fr.build, 120, by, group)
    except ValueError as exc:
        raise HTTPException(status_code=404 if group else 503, detail=str(exc))
    except TimeoutError:
        raise HTTPException(status_code=503, detail="Still gathering fund NAVs - try again in a minute.")


@router.post("/listings/refresh")
def refresh_listings(market: str = Query(default="all")) -> list[dict]:
    market = _market(market)
    store = get_store()
    store.rows(market, force=True)
    return [s for s in store.status() if s["source"] in store.keys_for(market)]


@router.get("/listings/mf/{scheme_code}/history")
def mutual_fund_history(scheme_code: int, days: int = Query(default=365, ge=7, le=3650)) -> list[dict]:
    df = _mf.get_historical_nav(scheme_code, days=days)
    if df.empty:
        raise HTTPException(status_code=502, detail=f"No NAV history for scheme {scheme_code}")
    return [{"date": d.strftime("%Y-%m-%d"), "nav": float(v)} for d, v in df["nav"].items()]


@router.get("/listings/mf/{scheme_code}/holdings")
def mutual_fund_holdings(scheme_code: int) -> dict:
    """Stocks (and other assets) a fund holds, from its fund house's official
    monthly portfolio file; index funds fall back to the NSE index list."""
    from marketmyna.services import fund_holdings as fh

    return fh.for_fund(str(scheme_code))


@router.get("/listings/mf/{scheme_code}/peers")
def mutual_fund_peers(scheme_code: int) -> dict:
    """The fund against its competitors: same SEBI category and plan, one
    scheme per fund house, ranked on returns and risk from NAV history."""
    from marketmyna.services import fund_peers
    from marketmyna.utils.deadline import call_with_deadline

    try:
        return call_with_deadline(fund_peers.compare, 90, str(scheme_code))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))


@router.get("/listings/mf/{scheme_code}/style")
def mutual_fund_style(scheme_code: int) -> dict:
    """Style (value / blend / growth, size) from the holdings, and SEBI category rule checks."""
    from marketmyna.services import fund_style
    from marketmyna.utils.deadline import call_with_deadline

    try:
        return call_with_deadline(fund_style.build, 90, str(scheme_code))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))


@router.get("/listings/mf/{scheme_code}/cost")
def mutual_fund_cost(scheme_code: int) -> dict:
    """Direct vs Regular plan cost (from both plans' NAVs) and how gains are taxed."""
    from marketmyna.services import fund_cost
    from marketmyna.utils.deadline import call_with_deadline

    try:
        return call_with_deadline(fund_cost.build, 60, str(scheme_code))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))


@router.get("/listings/mf/{scheme_code}/overlap")
def mutual_fund_overlap(scheme_code: int, other: int = Query(...)) -> dict:
    """Stocks two funds hold in common and how much of the money that is."""
    from marketmyna.services import fund_holdings as fh

    return fh.overlap(str(scheme_code), str(other))


@router.get("/listings/mf/{scheme_code}/analytics")
def mutual_fund_analytics(scheme_code: int) -> dict:
    """Rolling returns, risk against the category benchmark (total return),
    and drawdowns with recovery times, from the fund's daily NAV history."""
    from marketmyna.services import fund_analytics
    from marketmyna.utils.deadline import call_with_deadline

    try:
        return call_with_deadline(fund_analytics.build, 90, str(scheme_code))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))


@router.post("/listings/mf/{scheme_code}/ai-review")
def mutual_fund_ai_review(scheme_code: int, refresh: bool = Query(default=False), config=Depends(get_config_dep)) -> dict:
    """AI read of any fund from the figures on its page (an explanation for
    public users, a view for the owner; see marketmyna/services/fund_ai.py)."""
    from marketmyna.llm.channels import llm_configured
    from marketmyna.llm.protocol import GenerationError
    from marketmyna.services import fund_ai
    from marketmyna.utils.deadline import call_with_deadline

    if not llm_configured(config):
        raise HTTPException(status_code=409, detail="No AI model is set up. Add an AI key under Settings → AI keys.")
    try:
        out = call_with_deadline(lambda: fund_ai.review(str(scheme_code), config, use_cache=not refresh), 180)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except GenerationError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    if not out:
        raise HTTPException(status_code=502, detail="The AI model did not return a usable review. Try again.")
    return out


@router.get("/listings/stock/{symbol}/funds")
def funds_holding_stock(symbol: str) -> dict:
    """Mutual fund schemes holding an NSE stock (loaded fund houses only)."""
    from marketmyna.services import fund_holdings as fh

    return fh.funds_holding(symbol)


@router.get("/listings/mf/{scheme_code}/sip")
def mutual_fund_sip(
    scheme_code: int,
    monthly: float = Query(default=5000, gt=0, le=10_000_000),
    years: int = Query(default=5, ge=1, le=30),
    day: int = Query(default=5, ge=1, le=28),
    step_up: float = Query(default=10, ge=0, le=100),
    expected: float = Query(default=12, ge=-50, le=50),
    horizon: int = Query(default=10, ge=1, le=40),
) -> dict:
    """SIP backtest on real NAV (vs lumpsum, by SIP day) plus a step-up projection."""
    from marketmyna.services import sip

    df = _mf.get_historical_nav(scheme_code, days=100_000)
    if df.empty:
        raise HTTPException(status_code=502, detail=f"No NAV history for scheme {scheme_code}")
    return {"backtest": sip.backtest(df["nav"], monthly, years, day),
            "step_up": sip.step_up(monthly, step_up, horizon, expected)}


@router.get("/listings/{market}/{kind}/{symbol}/sip-days")
def best_sip_day(market: str, kind: str, symbol: str, years: int = Query(default=10, ge=3, le=10)) -> dict:
    """Historically best SIP day for one mutual fund or ETF: the stored
    3 / 5 / 10-year summary (computed fresh if missing) plus the XIRR of
    every day 1-28 over `years`."""
    from marketmyna.services import sip_days

    market = _market(market)
    if kind not in ("mf", "etf") or (kind == "mf" and market != "india") or market not in ("india", *sip_days.ETF_MARKETS):
        raise HTTPException(status_code=400, detail="Best SIP day covers Indian mutual funds and ETFs in India, US and Hong Kong")
    series = sip_days.mf_nav(symbol) if kind == "mf" else sip_days.etf_prices(symbol, market)
    if series is None or series.empty:
        raise HTTPException(status_code=502, detail=f"No price history for {symbol}")
    summary = sip_days.analyze(series)
    if summary is None:
        return {"summary": None, "curve": [], "years": years, "note": "Needs at least 3 years of prices."}
    span = (series.index.max() - series.index.min()).days / 365.25
    years = min(years, max(3, int(span)))
    return {"summary": summary, "curve": sip_days.curve(series, years), "years": years}


@router.get("/screens")
def screen_presets(market: str = Query(default="india"), asset: str = Query(default="stock")) -> list[dict]:
    """Ready-made screens: fundamental for stock markets, price-based for crypto and ETFs."""
    if asset == "etf":
        from marketmyna.services.etf_screens import list_presets as etf_presets

        return etf_presets()
    if market.lower() == "crypto":
        from marketmyna.services.crypto_screens import list_presets as crypto_presets

        return crypto_presets()
    from marketmyna.services.screens import list_presets

    return list_presets()


@router.get("/screens/metrics")
def screen_metrics() -> list[dict]:
    """Metrics a custom screen can filter on, in groups."""
    from marketmyna.services.screens import catalogue

    return catalogue()


class ScreenRuleIn(BaseModel):
    field: str = Field(max_length=40)
    op: str = Field(max_length=20)
    value: Optional[float] = None
    value2: Optional[float] = None


class CustomScreenIn(BaseModel):
    market: str = "india"
    rules: list[ScreenRuleIn] = Field(default_factory=list, max_length=12)
    sectors: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=40)
    sort: Optional[str] = Field(default=None, max_length=40)
    descending: bool = True
    columns: list[Annotated[str, Field(max_length=40)]] = Field(default_factory=list, max_length=20)
    large_only: bool = False


@router.post("/screens/custom")
def run_custom_screen(body: CustomScreenIn) -> dict:
    """Run the user's own rules over the largest stocks of a market."""
    from marketmyna.services import screens
    from marketmyna.utils.deadline import call_with_deadline

    market = _market(body.market)
    if market not in ("india", "us", "hong_kong", "china_a"):
        raise HTTPException(status_code=400, detail="Custom screens cover India, US, Hong Kong and China A")
    try:
        return call_with_deadline(screens.run_custom, 90, market, [r.model_dump() for r in body.rules], body.sectors,
                                  body.sort, body.descending, body.columns, body.large_only)
    except screens.RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/screens/{key}")
def run_screen(key: str, market: str = Query(default="india"), asset: str = Query(default="stock")) -> dict:
    """Run one preset over the largest stocks (or most-traded coins, or ETFs) of a market."""
    from marketmyna.utils.deadline import call_with_deadline

    market = _market(market)
    if asset == "etf":
        from marketmyna.services import etf_screens

        if market not in etf_screens.MARKETS:
            raise HTTPException(status_code=400, detail="ETF screens cover India, US, Hong Kong and China A")
        if key not in etf_screens.PRESETS:
            raise HTTPException(status_code=404, detail=f"Unknown screen '{key}'")
        return call_with_deadline(etf_screens.run, 90, key, market)
    if market == "crypto":
        from marketmyna.services import crypto_screens

        if key not in crypto_screens.PRESETS:
            raise HTTPException(status_code=404, detail=f"Unknown screen '{key}'")
        return call_with_deadline(crypto_screens.run, 90, key)
    from marketmyna.services.screens import PRESETS, run

    if key not in PRESETS:
        raise HTTPException(status_code=404, detail=f"Unknown screen '{key}'")
    if market not in ("india", "us", "hong_kong", "china_a"):
        raise HTTPException(status_code=400, detail="Screens cover India, US, Hong Kong, China A and crypto")
    return call_with_deadline(run, 90, key, market)
