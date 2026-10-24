"""Macro dashboard endpoint (marketmyna/services/macro.py)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/macro")
def macro_dashboard() -> dict:
    """Latest US / India / global macro series with changes and sparklines."""
    from marketmyna.services.macro import build

    return build()


@router.get("/macro/commodities")
def commodities() -> dict:
    """Metals, energy and grains futures, plus gold / silver in rupees, with
    the latest price of each contract."""
    from marketmyna.services import commodities, live_market

    def run() -> dict:
        prices = live_market.latest(commodities.tickers())
        return {**commodities.build(live=prices), "live": live_market.status_for(prices)}

    return live_market.memo(("commodities",), run)


@router.get("/macro/cot")
def commitments_of_traders() -> dict:
    """CFTC positioning (hedge funds, producers) in the main commodity futures."""
    from marketmyna.services.cot import build

    return build()


@router.get("/macro/eia")
def us_oil_inventories() -> dict:
    """EIA weekly US crude, gasoline and distillate stocks vs the 5-year average."""
    from marketmyna.services.eia_stocks import build

    return build()


@router.get("/macro/india-flows")
def india_flows() -> dict:
    """FII / DII cash-market flows and participant positioning in index derivatives (NSE)."""
    from marketmyna.services.india_flows import build

    return build()


@router.get("/macro/mood")
def market_mood(market: str = "india") -> dict:
    """Fear-to-greed gauge from breadth, moving averages, highs / lows, momentum and VIX (crypto: funding instead of VIX)."""
    from fastapi import HTTPException

    from marketmyna.data.listings import get_store
    from marketmyna.services import live_market
    from marketmyna.services.analysis_run import MARKET_INDICES
    from marketmyna.services.market_mood import VOL_INDEX, build

    market = market.lower()
    if market == "crypto":
        from marketmyna.services import crypto_mood

        def run_crypto() -> dict:
            live = live_market.market("crypto")
            return {**crypto_mood.build(live_market.merge(get_store().rows("crypto"), live["quotes"])), "live": live["status"]}

        return live_market.memo(("mood", market), run_crypto)
    if market not in ("india", "us", "hong_kong", "china_a"):
        raise HTTPException(status_code=400, detail="Market mood covers India, US, Hong Kong, China A and crypto")
    def run() -> dict:
        live = live_market.market(market)
        rows = live_market.merge(get_store().rows(market), live["quotes"])
        prices = live_market.for_tickers(market, live["quotes"])
        extra = [MARKET_INDICES[market][0][0]] + ([VOL_INDEX[market][0]] if market in VOL_INDEX else [])
        prices.update(live_market.latest(extra))
        return {**build(market, rows=rows, live=prices), "live": live["status"]}

    return live_market.memo(("mood", market), run)


@router.get("/macro/yield-curve")
def yield_curve() -> dict:
    """US Treasury yield curve now vs 1 month and 1 year ago."""
    from marketmyna.services.macro import yield_curve as build

    return build()


@router.get("/macro/india")
def india_rates() -> dict:
    """RBI policy and money-market rates, India yield curve, IBJA gold / silver."""
    from marketmyna.services.india_rates import build

    return build()


@router.get("/macro/crude-sensitivity")
def crude_sensitivity(market: str = "india") -> dict:
    """How oil-linked stocks (india | us | hong_kong | china_a) have moved with
    crude in local currency, net of their market."""
    from marketmyna.services.crude_sensitivity import build

    return build(market=market.lower())


@router.get("/macro/rates")
def market_rates(market: str = "us") -> dict:
    """Rates & bullion for us | hong_kong | china_a | crypto (India: /macro/india)."""
    from marketmyna.services.rates import build

    return build(market)


@router.get("/macro/world")
def world_markets() -> dict:
    """World stock indices, currencies, US yields, VIX term structure, India VIX
    and the crypto fear & greed index."""
    from marketmyna.services import live_market, world_markets

    def run() -> dict:
        prices = live_market.latest(world_markets.tickers())
        return {**world_markets.build(live=prices), "live": live_market.status_for(prices)}

    return live_market.memo(("world",), run)


@router.get("/macro/valuation")
def market_valuation() -> dict:
    """US market P/E, CAPE and yields against their history since 1871; Nifty
    index P/E, P/B and dividend yield (history kept from daily snapshots)."""
    from marketmyna.services.market_valuation import build

    return build()


@router.get("/macro/countries")
def country_macro(codes: str = "") -> dict:
    """IMF growth, inflation, debt, deficits and GDP for chosen countries
    (ISO3 codes, comma separated; blank = a default set of 14)."""
    from marketmyna.services.country_macro import build

    picked = [c.strip() for c in codes.split(",") if c.strip()][:30] or None
    try:
        return build(picked)
    except Exception as exc:  # nothing saved yet and the IMF did not answer
        raise HTTPException(status_code=503, detail="IMF data is unavailable right now. Try again later.") from exc


@router.get("/macro/central-banks")
def central_banks() -> dict:
    """Policy rates of about 40 central banks: level, last move, 1-year change, real rate."""
    from marketmyna.services.central_banks import build

    try:
        return build()
    except Exception as exc:  # nothing saved yet and the BIS did not answer
        raise HTTPException(status_code=503, detail="Central bank rates are unavailable right now.") from exc
