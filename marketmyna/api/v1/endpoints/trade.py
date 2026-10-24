"""Trade section: intraday chart data, price alerts, trade journal.
Read-only market data; nothing here places orders."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from marketmyna.api.deps import get_config_dep
from marketmyna.storage import (
    DatabaseManager,
    PriceAlertEventRecord,
    PriceAlertRecord,
    TradeRecord,
    get_db_url,
)
from marketmyna.trading import chart as chart_mod
from marketmyna.trading.alerts import KINDS, AlertMonitor, describe
from marketmyna.trading.journal import r_multiple, stats, trade_pnl
from marketmyna.utils.deadline import call_with_deadline

router = APIRouter()

MARKETS = {"us", "india", "china_a", "hong_kong", "crypto", "global"}


def _db(config):
    return DatabaseManager.instance(get_db_url(config=config))


def _row(rec) -> dict:
    out = {}
    for c in rec.__table__.columns:
        v = getattr(rec, c.name)
        out[c.name] = v.isoformat() if isinstance(v, datetime) else v
    return out


def _check_market(market: str) -> str:
    market = market.lower()
    if market not in MARKETS:
        raise HTTPException(status_code=400, detail=f"Unknown market '{market}'")
    return market


# ------------------------------------------------------------------ pairs


@router.get("/trade/pairs")
def trade_pairs(
    a: str,
    b: str,
    market: str = "us",
    market_b: Optional[str] = None,
    period: Literal["1y", "2y", "5y"] = "2y",
) -> dict:
    """Engle-Granger cointegration test, hedge ratio, half-life and spread z-score."""
    from concurrent.futures import ThreadPoolExecutor

    from marketmyna.trading.pairs import analyze

    market = _check_market(market)
    market_b = _check_market(market_b or market)
    a, b = a.strip().upper(), b.strip().upper()
    if a == b and market == market_b:
        raise HTTPException(status_code=400, detail="Pick two different symbols")

    def bars(sym, mkt):
        return call_with_deadline(chart_mod.fetch_bars, 30, sym, mkt, "1d", period)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa, fb = pool.submit(bars, a, market), pool.submit(bars, b, market_b)
            da, db = fa.result(), fb.result()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load prices: {exc}")

    def closes(df):
        if df is None or df.empty:
            return None
        col = "close" if "close" in df.columns else "Close"
        s = df[col].astype(float)
        s.index = s.index.tz_localize(None).normalize() if getattr(s.index, "tz", None) else s.index.normalize()
        return s[~s.index.duplicated(keep="last")]

    sa, sb = closes(da), closes(db)
    if sa is None or sb is None:
        raise HTTPException(status_code=404, detail=f"No price history for {a if sa is None else b}")
    try:
        out = analyze(sa, sb)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"a": a, "b": b, "market": market, "market_b": market_b, "period": period, **out}


# ------------------------------------------------------------------ chart


@router.get("/trade/chart")
def trade_chart(
    symbol: str,
    market: str = "us",
    interval: str = "5m",
    period: Optional[str] = None,
    indicators: str = Query(default="vwap,ema9,ema21,supertrend"),
) -> dict:
    market = _check_market(market)
    if interval not in chart_mod.INTERVALS:
        raise HTTPException(status_code=400, detail=f"Interval must be one of {', '.join(chart_mod.INTERVALS)}")
    period = chart_mod.clamp_period(interval, period)
    wanted = [i for i in indicators.split(",") if i in chart_mod.INDICATORS]
    try:
        df = call_with_deadline(chart_mod.fetch_bars, 30, symbol.strip().upper(), market, interval, period)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load {interval} bars: {exc}")
    return {"symbol": symbol.upper(), "market": market, "interval": interval, "period": period,
            **chart_mod.build_chart(df, interval, wanted)}


@router.get("/trade/levels")
def trade_levels(symbol: str, market: str = "us") -> dict:
    """Buy / sell / stop levels (same maths as the smart report) for
    one-click alerts."""
    from marketmyna.services.smart_report import snapshot

    try:
        row = call_with_deadline(snapshot, 25, symbol.strip().upper(), _check_market(market))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    if "error" in row:
        raise HTTPException(status_code=502, detail=row["error"])
    from marketmyna.core.compliance import CALL_FIELDS

    # The volatility band and ranges only, no buy / sell / stop.
    row = {k: v for k, v in row.items() if k not in CALL_FIELDS}
    # "at its buy / sell point" is the same call in words.
    row["reasons"] = [r for r in row.get("reasons") or [] if "buy point" not in r and "sell point" not in r]
    return row


# ------------------------------------------------------------------ alerts


class AlertIn(BaseModel):
    symbol: str
    market: str = "us"
    kind: str
    value: float
    note: str = ""
    repeat: bool = False
    cooldown_minutes: int = Field(default=30, ge=0, le=1440)
    expires_at: Optional[datetime] = None


class AlertPatch(BaseModel):
    value: Optional[float] = None
    note: Optional[str] = None
    repeat: Optional[bool] = None
    cooldown_minutes: Optional[int] = Field(default=None, ge=0, le=1440)
    status: Optional[Literal["active", "paused"]] = None
    expires_at: Optional[datetime] = None


def _alert_dict(rec: PriceAlertRecord) -> dict:
    return {**_row(rec), "description": describe(rec.kind, rec.value)}


@router.get("/trade/alert-kinds")
def alert_kinds() -> list[dict]:
    return [{"kind": k, "label": label, "unit": unit} for k, (label, unit, _) in KINDS.items()]


@router.get("/trade/alerts")
def list_alerts(config=Depends(get_config_dep)) -> list[dict]:
    with _db(config).get_session() as s:
        recs = s.query(PriceAlertRecord).order_by(PriceAlertRecord.status, PriceAlertRecord.id.desc()).all()
        return [_alert_dict(r) for r in recs]


@router.post("/trade/alerts", status_code=201)
def create_alert(body: AlertIn, config=Depends(get_config_dep)) -> dict:
    if body.kind not in KINDS:
        raise HTTPException(status_code=400, detail=f"Unknown alert kind '{body.kind}'")
    symbol = body.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    if KINDS[body.kind][1] in ("price", "x avg", "days") and body.value <= 0:
        raise HTTPException(status_code=400, detail="Value must be above zero")
    with _db(config).get_session() as s:
        rec = PriceAlertRecord(
            symbol=symbol, market=_check_market(body.market), kind=body.kind, value=body.value,
            note=body.note.strip(), repeat=body.repeat, cooldown_minutes=body.cooldown_minutes,
            expires_at=body.expires_at, status="active", armed=True,
        )
        s.add(rec)
        s.flush()
        return _alert_dict(rec)


@router.patch("/trade/alerts/{alert_id}")
def update_alert(alert_id: int, body: AlertPatch, config=Depends(get_config_dep)) -> dict:
    with _db(config).get_session() as s:
        rec = s.get(PriceAlertRecord, alert_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Alert not found")
        for k, v in body.model_dump(exclude_unset=True).items():
            setattr(rec, k, v)
        if body.status == "active":
            rec.armed = True  # re-activating a fired alert arms it again
        return _alert_dict(rec)


@router.delete("/trade/alerts/{alert_id}", status_code=204)
def delete_alert(alert_id: int, config=Depends(get_config_dep)) -> None:
    with _db(config).get_session() as s:
        rec = s.get(PriceAlertRecord, alert_id)
        if rec is not None:
            s.delete(rec)


@router.get("/trade/alerts/events")
def alert_events(limit: int = 50, config=Depends(get_config_dep)) -> list[dict]:
    with _db(config).get_session() as s:
        recs = (
            s.query(PriceAlertEventRecord)
            .order_by(PriceAlertEventRecord.created_at.desc(), PriceAlertEventRecord.id.desc())
            .limit(max(1, min(500, limit)))
            .all()
        )
        return [_row(r) for r in recs]


@router.post("/trade/alerts/check")
def check_alerts_now(request: Request, config=Depends(get_config_dep)) -> dict:
    """Run one alert check immediately, ignoring market hours."""
    monitor = getattr(request.app.state, "alert_monitor", None) or AlertMonitor(config)
    return monitor.tick(force=True)


@router.get("/trade/alerts/status")
def alert_monitor_status(request: Request) -> dict:
    monitor = getattr(request.app.state, "alert_monitor", None)
    return {"running": bool(monitor and monitor.is_running()),
            "poll_seconds": getattr(monitor, "_poll", None)}


# ------------------------------------------------------------------ journal


class TradeIn(BaseModel):
    symbol: str
    market: str = "us"
    side: Literal["long", "short"] = "long"
    quantity: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    entry_at: Optional[datetime] = None
    exit_price: Optional[float] = Field(default=None, gt=0)
    exit_at: Optional[datetime] = None
    stop: Optional[float] = Field(default=None, gt=0)
    target: Optional[float] = Field(default=None, gt=0)
    fees: Optional[float] = Field(default=None, ge=0)  # empty = estimate from the charges schedule
    product: Optional[Literal["intraday", "delivery", "futures", "options"]] = None
    setup: str = ""
    notes: str = ""


class TradePatch(BaseModel):
    side: Optional[Literal["long", "short"]] = None
    quantity: Optional[float] = Field(default=None, gt=0)
    entry_price: Optional[float] = Field(default=None, gt=0)
    entry_at: Optional[datetime] = None
    exit_price: Optional[float] = Field(default=None, gt=0)
    exit_at: Optional[datetime] = None
    stop: Optional[float] = Field(default=None, gt=0)
    target: Optional[float] = Field(default=None, gt=0)
    fees: Optional[float] = Field(default=None, ge=0)
    product: Optional[Literal["intraday", "delivery", "futures", "options"]] = None
    setup: Optional[str] = None
    notes: Optional[str] = None


def _auto_fees(rec: TradeRecord) -> None:
    """Keep estimated fees current: entry side while open, round trip once closed."""
    from marketmyna.trading.charges import for_trade

    if rec.fees_auto:
        rec.fees = for_trade(_plain(rec))


def _plain(rec: TradeRecord) -> dict:
    return {c.name: getattr(rec, c.name) for c in rec.__table__.columns}


def _trade_dict(rec: TradeRecord) -> dict:
    plain = _plain(rec)
    pnl, r = trade_pnl(plain), r_multiple(plain)
    return {**_row(rec), "pnl": round(pnl, 2) if pnl is not None else None,
            "r_multiple": round(r, 2) if r is not None else None}


@router.get("/trade/journal")
def journal(market: Optional[str] = None, config=Depends(get_config_dep)) -> dict:
    with _db(config).get_session() as s:
        q = s.query(TradeRecord)
        if market:
            q = q.filter(TradeRecord.market == _check_market(market))
        recs = q.order_by(TradeRecord.entry_at.desc(), TradeRecord.id.desc()).all()
        markets = sorted({m for (m,) in s.query(TradeRecord.market).distinct()})
        return {"trades": [_trade_dict(r) for r in recs], "stats": stats([_plain(r) for r in recs]),
                "markets": markets}


@router.post("/trade/journal", status_code=201)
def add_trade(body: TradeIn, config=Depends(get_config_dep)) -> dict:
    data = body.model_dump()
    data["symbol"] = data["symbol"].strip().upper()
    data["market"] = _check_market(data["market"])
    data["entry_at"] = data["entry_at"] or datetime.now()
    if data["exit_price"] is not None and data["exit_at"] is None:
        data["exit_at"] = datetime.now()
    data["fees_auto"] = data["fees"] is None
    data["fees"] = data["fees"] or 0.0
    with _db(config).get_session() as s:
        rec = TradeRecord(**data)
        _auto_fees(rec)
        s.add(rec)
        s.flush()
        return _trade_dict(rec)


@router.patch("/trade/journal/{trade_id}")
def update_trade(trade_id: int, body: TradePatch, config=Depends(get_config_dep)) -> dict:
    with _db(config).get_session() as s:
        rec = s.get(TradeRecord, trade_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Trade not found")
        changes = body.model_dump(exclude_unset=True)
        if "fees" in changes:
            rec.fees_auto = changes["fees"] is None
            changes["fees"] = changes["fees"] or 0.0
        for k, v in changes.items():
            setattr(rec, k, v)
        if changes.get("exit_price") is not None and rec.exit_at is None:
            rec.exit_at = datetime.now()
        _auto_fees(rec)
        return _trade_dict(rec)


@router.delete("/trade/journal/{trade_id}", status_code=204)
def delete_trade(trade_id: int, config=Depends(get_config_dep)) -> None:
    with _db(config).get_session() as s:
        rec = s.get(TradeRecord, trade_id)
        if rec is not None:
            s.delete(rec)


# ------------------------------------------------------------------ scanner


class Universe(BaseModel):
    sources: list[Literal["top", "watchlist", "portfolio", "custom"]] = ["top"]
    market: str = "india"
    top_n: int = Field(default=100, ge=1, le=500)
    watchlist_ids: list[int] = []
    portfolio_names: list[str] = []
    symbols: list[str] = []


class ScanIn(BaseModel):
    universe: Universe = Universe()
    scans: list[str]
    params: dict[str, float] = {}
    match: Literal["any", "all"] = "any"


class SavedScanIn(ScanIn):
    name: str
    notify: bool = False
    interval_minutes: int = Field(default=15, ge=5, le=1440)


class SavedScanPatch(BaseModel):
    name: Optional[str] = None
    universe: Optional[Universe] = None
    scans: Optional[list[str]] = None
    params: Optional[dict[str, float]] = None
    match: Optional[Literal["any", "all"]] = None
    notify: Optional[bool] = None
    interval_minutes: Optional[int] = Field(default=None, ge=5, le=1440)


def _clean_scans(scans: list[str]) -> list[str]:
    from marketmyna.trading.scanner import SCANS

    clean = [s for s in dict.fromkeys(scans) if s in SCANS]
    if not clean:
        raise HTTPException(status_code=400, detail="Pick at least one scan")
    return clean


@router.get("/trade/scans/catalog")
def scan_catalog() -> list[dict]:
    from marketmyna.trading.scanner import SCANS

    return [
        {"id": k, "label": label, "group": group, "intraday": intraday, "default": default, "param": param}
        for k, (label, group, intraday, default, param) in SCANS.items()
    ]


@router.post("/trade/scan")
def run_scan_now(body: ScanIn, config=Depends(get_config_dep)) -> dict:
    from marketmyna.trading.scanner import resolve_universe, run_scan

    universe = body.universe.model_dump()
    universe["market"] = _check_market(universe["market"])
    targets, names = resolve_universe(universe, config)
    if not targets:
        raise HTTPException(status_code=400, detail="The chosen universe has no stocks")
    try:
        return call_with_deadline(run_scan, 170, targets, _clean_scans(body.scans), body.params, body.match, names=names)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=f"Scan timed out: {exc}")


@router.get("/trade/scans/saved")
def list_saved_scans(config=Depends(get_config_dep)) -> list[dict]:
    from marketmyna.storage import SavedScanRecord

    with _db(config).get_session() as s:
        return [_row(r) for r in s.query(SavedScanRecord).order_by(SavedScanRecord.id)]


@router.post("/trade/scans/saved", status_code=201)
def save_scan(body: SavedScanIn, config=Depends(get_config_dep)) -> dict:
    from marketmyna.storage import SavedScanRecord

    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    with _db(config).get_session() as s:
        rec = SavedScanRecord(
            name=body.name.strip(), universe=body.universe.model_dump(), scans=_clean_scans(body.scans),
            params=body.params, match=body.match, notify=body.notify, interval_minutes=body.interval_minutes,
        )
        s.add(rec)
        s.flush()
        return _row(rec)


@router.patch("/trade/scans/saved/{scan_id}")
def update_saved_scan(scan_id: int, body: SavedScanPatch, config=Depends(get_config_dep)) -> dict:
    from marketmyna.storage import SavedScanRecord

    with _db(config).get_session() as s:
        rec = s.get(SavedScanRecord, scan_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="Saved scan not found")
        changes = body.model_dump(exclude_unset=True)
        if "scans" in changes:
            changes["scans"] = _clean_scans(changes["scans"])
        for k, v in changes.items():
            setattr(rec, k, v)
        return _row(rec)


@router.delete("/trade/scans/saved/{scan_id}", status_code=204)
def delete_saved_scan(scan_id: int, config=Depends(get_config_dep)) -> None:
    from marketmyna.storage import SavedScanRecord

    with _db(config).get_session() as s:
        rec = s.get(SavedScanRecord, scan_id)
        if rec is not None:
            s.delete(rec)


# ------------------------------------------------------------------ daily risk


class RiskSettingsIn(BaseModel):
    market: Optional[str] = None
    capital: Optional[float] = Field(default=None, gt=0)
    daily_loss_limit_pct: Optional[float] = Field(default=None, ge=0, le=100)
    max_open_risk_pct: Optional[float] = Field(default=None, ge=0, le=100)
    max_trades_per_day: Optional[int] = Field(default=None, ge=0, le=1000)
    notify: Optional[bool] = None


@router.get("/trade/risk")
def risk_status(config=Depends(get_config_dep)) -> dict:
    from marketmyna.trading.risk import status

    return status(config)


@router.put("/trade/risk/settings")
def update_risk_settings(body: RiskSettingsIn, config=Depends(get_config_dep)) -> dict:
    from marketmyna.trading.risk import save_settings

    changes = body.model_dump(exclude_unset=True)
    if "market" in changes:
        changes["market"] = _check_market(changes["market"])
    return save_settings(config, **changes)


# ------------------------------------------------------------------ backtest


class BacktestIn(BaseModel):
    symbol: str
    market: str = "india"
    interval: Literal["1d", "1wk", "1h"] = "1d"
    period: Literal["1y", "2y", "5y", "10y", "max"] = "5y"
    strategy: str = "ema_cross"
    params: dict[str, float] = {}
    capital: float = Field(default=100000, gt=0)
    sizing: Literal["percent", "risk"] = "percent"
    position_pct: float = Field(default=100, gt=0, le=100)
    risk_pct: float = Field(default=1, gt=0, le=100)
    stop_type: Literal["none", "percent", "atr"] = "none"
    stop_value: float = Field(default=2, gt=0)
    target_r: Optional[float] = Field(default=None, gt=0)
    cost_pct: float = Field(default=0.1, ge=0, le=5)
    slippage_pct: float = Field(default=0.05, ge=0, le=5)
    allow_short: bool = False
    optimize: bool = False
    objective: Literal["sharpe", "total_return", "profit_factor", "cagr"] = "sharpe"


@router.get("/trade/backtest/strategies")
def backtest_strategies() -> list[dict]:
    from marketmyna.trading.backtest import STRATEGIES

    return [{"id": k, **v} for k, v in STRATEGIES.items()]


@router.post("/trade/backtest")
def backtest(body: BacktestIn) -> dict:
    from marketmyna.trading import backtest as bt

    if body.strategy not in bt.STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Unknown strategy '{body.strategy}'")
    market = _check_market(body.market)
    period = "2y" if body.interval == "1h" and body.period not in ("1y", "2y") else body.period
    try:
        df = chart_mod.normalize(call_with_deadline(chart_mod.fetch_bars, 45, body.symbol.strip().upper(), market, body.interval, period))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load history: {exc}")
    if len(df) < 60:
        raise HTTPException(status_code=400, detail=f"Only {len(df)} bars of history; need at least 60")
    settings = bt.Settings(
        strategy=body.strategy, params=body.params, capital=body.capital, sizing=body.sizing,
        position_pct=body.position_pct, risk_pct=body.risk_pct, stop_type=body.stop_type,
        stop_value=body.stop_value, target_r=body.target_r, cost_pct=body.cost_pct,
        slippage_pct=body.slippage_pct, allow_short=body.allow_short,
    )
    out: dict = {"symbol": body.symbol.upper(), "market": market, "interval": body.interval, "period": period}
    if body.optimize:
        opt = bt.optimize(df, settings, body.interval, body.objective)
        out["optimization"] = opt
        settings.params = opt["best"]
    out["params"] = {**bt.STRATEGIES[body.strategy]["params"], **settings.params}
    out.update(bt.run(df, settings, body.interval))
    out["split"] = bt.split_test(df, settings, body.interval)
    return out


# ------------------------------------------------------------------ options


class Leg(BaseModel):
    type: Literal["call", "put", "stock"]
    side: Literal["buy", "sell"]
    strike: float = 0
    premium: float = Field(default=0, ge=0)
    quantity: float = Field(gt=0)
    iv: Optional[float] = Field(default=None, gt=0, le=500)


class PayoffIn(BaseModel):
    legs: list[Leg] = Field(min_length=1, max_length=8)
    spot: float = Field(gt=0)
    days: float = Field(default=7, ge=0, le=1000)
    market: str = "india"
    width_pct: float = Field(default=15, gt=1, le=80)


@router.get("/trade/options/chain")
def option_chain(symbol: str, market: str = "india", expiry: Optional[str] = None) -> dict:
    from marketmyna.trading import options

    market = _check_market(market)
    if market in ("china_a", "crypto"):
        raise HTTPException(status_code=400, detail="Option chains are available for India (NSE) and US/global (Yahoo)")
    try:
        return call_with_deadline(options.chain, 40, symbol.strip().upper(), market, expiry)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Option chain unavailable: {exc}")


@router.post("/trade/options/payoff")
def option_payoff(body: PayoffIn) -> dict:
    from marketmyna.trading import options

    legs = [leg.model_dump() for leg in body.legs]
    for leg in legs:
        if leg["type"] != "stock" and leg["strike"] <= 0:
            raise HTTPException(status_code=400, detail="Every option leg needs a strike")
    rate = options.RATES.get(_check_market(body.market), 0.05)
    return options.payoff(legs, body.spot, body.days, rate, body.width_pct)


# ------------------------------------------------------------------ live quotes (SSE)


STREAM_SECONDS = 15


@router.get("/trade/stream")
async def quote_stream(request: Request, symbols: str, every: int = 10):
    """Server-sent events: `{"symbol", "market", "price", "change_percent",
    "volume", "time"}` for each `market:SYMBOL` in `symbols`, every `every`
    seconds (min 5). Stock prices carry the source's delay (~15 min on free
    data); crypto is live."""
    import asyncio
    import json

    from fastapi.responses import StreamingResponse

    from marketmyna.trading.alerts import _default_quote
    from marketmyna.trading.market_hours import is_open

    pairs = []
    for item in symbols.split(",")[:20]:
        if ":" in item:
            mkt, sym = item.split(":", 1)
            pairs.append((sym.strip().upper(), _check_market(mkt)))
    if not pairs:
        raise HTTPException(status_code=400, detail="symbols must look like india:RELIANCE,crypto:BTC-USD")
    every = max(5, min(300, every))

    async def events():
        # Each connection lives ~15s, then the browser's EventSource reconnects
        # (after `retry` ms). A never-ending response would otherwise block the
        # server's graceful shutdown - and with it every --reload - for as long
        # as a Trade page is open.
        import time

        started = time.monotonic()
        yield "retry: 1000\n\n"
        while not await request.is_disconnected() and time.monotonic() - started < STREAM_SECONDS:
            for sym, mkt in pairs:
                try:
                    q = await asyncio.to_thread(call_with_deadline, _default_quote, 15, sym, mkt)
                except Exception as exc:
                    yield f"event: error\ndata: {json.dumps({'symbol': sym, 'error': str(exc)})}\n\n"
                    continue
                payload = {"symbol": sym, "market": mkt, "open": is_open(mkt),
                           "price": q.get("price"), "change_percent": q.get("change_percent"),
                           "day_high": q.get("day_high"), "day_low": q.get("day_low"), "volume": q.get("volume"),
                           "time": datetime.now().isoformat(timespec="seconds")}
                yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(every)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ charges


class ChargesIn(BaseModel):
    market: str = "india"
    product: Optional[Literal["intraday", "delivery", "futures", "options"]] = None
    buy_value: float = Field(default=0, ge=0)
    sell_value: float = Field(default=0, ge=0)
    quantity: float = Field(default=0, ge=0)
    commission_pct: float = Field(default=0, ge=0, le=10)
    flat: float = Field(default=0, ge=0)


@router.post("/trade/charges")
def trade_charges(body: ChargesIn) -> dict:
    from marketmyna.trading.charges import estimate

    return estimate(_check_market(body.market), body.buy_value, body.sell_value, body.quantity, body.product,
                    body.commission_pct, body.flat)


@router.get("/trade/lot-size")
def trade_lot_size(symbol: str) -> dict:
    """NSE F&O lot size (nearest expiry) from the brokers' instrument files."""
    from marketmyna.trading.lots import lot_size

    try:
        return {"symbol": symbol.upper(), "lot_size": lot_size(symbol.strip())}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Lot sizes unavailable: {exc}")


@router.get("/trade/market-status")
def market_status(market: str = "india") -> dict:
    from marketmyna.trading.market_hours import status

    return status(_check_market(market))
