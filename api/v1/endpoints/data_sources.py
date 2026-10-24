"""Optional data-source keys (Settings -> Data sources): live US prices,
backup price sources and Reddit. Secrets are never sent back, only whether
they are set (and the last 4). A value from an environment variable can't be
changed here."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_config_dep
from api.middlewares.auth import accounts_db, require_admin

router = APIRouter(prefix="/system-config/data-sources", dependencies=[Depends(require_admin)])


def _db(config):
    return accounts_db(config)


INTEGRATIONS = [
    {
        "id": "finnhub",
        "title": "Finnhub live prices (US)",
        "help": "Real-time US stock prices for the Markets and Watchlist tables (trade by trade). "
                "Free key at finnhub.io -> Dashboard. The free plan streams about 50 symbols at once; "
                "without a key, US prices come from the default source.",
        "fields": [("finnhub_api_key", "API key", "secret")],
    },
    {
        "id": "market_data",
        "title": "Backup price sources",
        "help": "Used only when the default price source fails or rate-limits, tried in this order. All have free keys: "
                "twelvedata.com (800 calls/day, also NSE / BSE), tiingo.com, alphavantage.co (25 calls/day), "
                "polygon.io (5 calls/min, daily bars). US stocks also fall back to Nasdaq and crypto to CoinGecko, "
                "which need no key (a free CoinGecko demo key raises its rate limit).",
        "fields": [
            ("twelvedata_api_key", "Twelve Data API key", "secret"),
            ("tiingo_api_key", "Tiingo API token", "secret"),
            ("alpha_vantage_key", "Alpha Vantage API key", "secret"),
            ("polygon_key", "Polygon API key", "secret"),
            ("coingecko_api_key", "CoinGecko demo key (optional, crypto)", "secret"),
        ],
    },
    {
        "id": "social",
        "title": "Social sentiment (Reddit, StockTwits)",
        "help": "Reddit is read with a headless browser (Playwright) unless API keys are set - Reddit blocks "
                "scrapers quickly, especially from cloud servers. For the API: reddit.com/prefs/apps -> create a "
                "'script' app; mode 'auto' then uses the API first. StockTwits always needs the browser. "
                "Install it with: pip install playwright && python -m playwright install --with-deps chromium",
        "fields": [
            ("reddit_client_id", "Reddit client ID", "text"),
            ("reddit_client_secret", "Reddit client secret", "secret"),
            ("reddit_user_agent", "Reddit user agent (e.g. MarketMyna/1.0 by u/you)", "text"),
            ("social_reddit_mode", "Reddit mode: auto | api | playwright", "text"),
            ("social_playwright", "Allow headless-browser scraping", "bool"),
        ],
    },
]
_FIELD_KINDS = {name: kind for group in INTEGRATIONS for name, _label, kind in group["fields"]}


def _integrations(config) -> dict:
    env = getattr(config, "_env_fields", set())
    groups = []
    for group in INTEGRATIONS:
        fields = []
        for name, label, kind in group["fields"]:
            value = getattr(config, name, None)
            item = {"name": name, "label": label, "kind": kind, "from_env": name in env}
            if kind == "secret":
                item["is_set"] = bool(value)
                item["last4"] = value[-4:] if value and len(value) > 8 else ""
            else:
                item["value"] = value
            fields.append(item)
        groups.append({"id": group["id"], "title": group["title"], "help": group["help"], "fields": fields})
    return {"groups": groups}


@router.get("")
def get_data_sources(config=Depends(get_config_dep)) -> dict:
    _db(config)
    return _integrations(config)


@router.put("")
def update_data_sources(body: dict, config=Depends(get_config_dep)) -> dict:
    """Partial update: only the fields present change; null or "" clears one."""
    _db(config)
    env = getattr(config, "_env_fields", set())
    changes = {}
    for name, value in body.items():
        kind = _FIELD_KINDS.get(name)
        if kind is None:
            raise HTTPException(status_code=400, detail=f"Unknown setting '{name}'.")
        if name in env:
            raise HTTPException(status_code=400, detail=f"{name.upper()} is set by an environment variable on the server.")
        if value in (None, ""):
            changes[name] = None
        elif kind == "bool":
            changes[name] = bool(value)
        else:
            value = str(value).strip()
            if len(value) > 500:
                raise HTTPException(status_code=400, detail="Value is too long.")
            changes[name] = value
    for name, value in changes.items():
        setattr(config, name, value)
    config.save()
    return _integrations(config)


def _test_market_data() -> dict:
    """One quote per configured source, straight from that source."""
    from src.data import extra_sources as xs

    xs._key_cache.clear()  # a key saved a moment ago counts
    checks = [
        ("Twelve Data", xs.twelvedata_key, lambda: xs.twelvedata_quote("RELIANCE", "india"), "₹"),
        ("Tiingo", xs.tiingo_key, lambda: xs.tiingo_quote("AAPL"), "$"),
        ("Alpha Vantage", xs.alphavantage_key, lambda: xs.alphavantage_quote("AAPL"), "$"),
        ("Polygon", xs.polygon_key, lambda: xs.polygon_quote("AAPL"), "$"),
        ("Nasdaq", lambda: True, lambda: xs.nasdaq_quote("AAPL"), "$"),
        ("CoinGecko", lambda: True, lambda: xs.coingecko_quote("BTC"), "$"),
    ]
    parts, failed = [], []
    for name, has_key, fetch, cur in checks:
        if not has_key():
            continue
        try:
            q = fetch()
            parts.append(f"{name} OK ({q['symbol']} {cur}{q['price']:,.2f})")
        except Exception as exc:  # noqa: BLE001 - report every source, not just the first failure
            failed.append(f"{name}: {str(exc)[:120]}")
    if failed:
        raise HTTPException(status_code=400, detail="; ".join(failed + parts))
    return {"ok": True, "message": ". ".join(parts) + "."}


@router.post("/{group_id}/test")
def test_data_source(group_id: str, config=Depends(get_config_dep)) -> dict:
    if group_id == "finnhub":
        import requests

        key = getattr(config, "finnhub_api_key", None)
        if not key:
            raise HTTPException(status_code=400, detail="Enter the Finnhub API key first.")
        try:
            q = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": "AAPL", "token": key}, timeout=10)
        except requests.RequestException as exc:
            raise HTTPException(status_code=400, detail=f"Finnhub unreachable: {exc}")
        if q.status_code in (401, 403):
            raise HTTPException(status_code=400, detail="Finnhub rejected the API key.")
        price = (q.json() if q.ok else {}).get("c")
        return {"ok": True, "message": f"Finnhub connected. AAPL ${price:,.2f}." if price else "Finnhub connected."}
    if group_id == "market_data":
        return _test_market_data()
    if group_id == "social":
        from src.data.social import browser, reddit

        parts = ["Headless browser: " + ("installed." if browser.available() else "not installed - scraping is off.")]
        client_id, secret = getattr(config, "reddit_client_id", None), getattr(config, "reddit_client_secret", None)
        if client_id and secret:
            try:
                reddit._token.update(value=None, expires=0.0)
                reddit._api_token(client_id, secret, getattr(config, "reddit_user_agent", None) or "MarketMyna/1.0")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Reddit API: {exc}")
            parts.append("Reddit API keys work.")
        else:
            parts.append("No Reddit API keys - Reddit will be scraped.")
        return {"ok": True, "message": " ".join(parts)}
    raise HTTPException(status_code=404, detail="Nothing to test here.")
