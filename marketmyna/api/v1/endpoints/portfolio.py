"""Portfolio CRUD - thin wrapper over the existing (now DB-backed) PortfolioManager."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from marketmyna.api.deps import get_config_dep
from marketmyna.portfolio.manager import PortfolioManager
from marketmyna.portfolio.models import TransactionType
from marketmyna.utils.deadline import call_with_deadline

router = APIRouter()


def get_portfolio_manager(config=Depends(get_config_dep)) -> PortfolioManager:
    return PortfolioManager(config.data_dir, config=config)


class CreatePortfolioRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    currency: str = "USD"
    kind: str = Field(default="stocks", pattern="^(stocks|funds)$")  # funds = mutual funds


class RenamePortfolioRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ParseCASRequest(BaseModel):
    file_b64: str = Field(min_length=1, max_length=14_000_000)  # ~10 MB PDF
    password: str = Field(default="", max_length=64)


class ReconcileRequest(BaseModel):
    filename: str = Field(default="statement.csv", max_length=200)
    file_b64: str = Field(min_length=1, max_length=14_000_000)  # ~10 MB
    password: str = Field(default="", max_length=64)


class ReconcileFix(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    market: str = Field(default="india", max_length=32)
    type: str = Field(pattern="^(buy|sell|split)$")
    quantity: float = Field(gt=0)
    price: float = Field(ge=0)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str = Field(default="Reconciliation", max_length=200)


class ReconcileApplyRequest(BaseModel):
    fixes: list[ReconcileFix] = Field(min_length=1, max_length=500)


class ImportFund(BaseModel):
    amfi: str = Field(min_length=1, max_length=12)
    scheme: str = ""
    units: float = Field(ge=0)
    nav: float = Field(gt=0)
    cost: Optional[float] = Field(default=None, ge=0)
    date: Optional[str] = None


class ImportFundsRequest(BaseModel):
    holdings: list[ImportFund] = Field(min_length=1, max_length=500)


class AddTransactionRequest(BaseModel):
    symbol: str
    transaction_type: TransactionType
    quantity: float
    price: float
    date: Optional[datetime] = None
    fees: float = 0.0
    notes: str = ""
    market: str = "US"


@router.get("/portfolio")
def list_portfolios(manager: PortfolioManager = Depends(get_portfolio_manager)) -> list[str]:
    return manager.get_all_portfolios()


def _summary(manager: PortfolioManager, name: str) -> dict:
    """Portfolio summary with its kind and scheme name / category on mutual fund holdings."""
    from marketmyna.services.mf_holdings import MARKET, latest

    out = manager.get_portfolio_summary(name)
    portfolio = manager.portfolios[name]
    out["kind"] = portfolio_kind(portfolio.kind, [h.market for h in portfolio.holdings.values()])
    for h in out.get("holdings", {}).values():
        if (h.get("market") or "").lower() == MARKET and (info := latest(h["symbol"])):
            h.update(name=info["name"], amc=info["amc"], category=info["category"], nav_date=info["nav_date"])
    return out


def portfolio_kind(kind: Optional[str], markets) -> str:
    """A portfolio's kind; old rows without one are "funds" when they hold only mutual funds."""
    if kind in ("stocks", "funds"):
        return kind
    return "funds" if {(m or "").lower() for m in markets} == {"mf"} else "stocks"


@router.get("/portfolio/{name}")
def get_portfolio(name: str, manager: PortfolioManager = Depends(get_portfolio_manager)) -> dict:
    try:
        return _summary(manager, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/portfolio/cas/parse")
def parse_cas(body: ParseCASRequest) -> dict:
    """Read a CAMS / KFintech CAS PDF into per-scheme holdings for preview.
    The file and password are used in memory only and never stored."""
    import base64
    import binascii

    from marketmyna.services.mf_holdings import CASError
    from marketmyna.services.mf_holdings import parse_cas as parse

    try:
        pdf = base64.b64decode(body.file_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="File is not valid base64")
    if not pdf.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="That file is not a PDF")
    try:
        return parse(pdf, body.password.strip())
    except CASError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/portfolio/{name}/reconcile")
def reconcile(name: str, body: ReconcileRequest, manager: PortfolioManager = Depends(get_portfolio_manager)) -> dict:
    """Tie the portfolio out against a broker holdings export or a CAS PDF, and
    check the stored holdings against the transaction history. Read-only: fixes
    are only proposed. The file is used in memory and never stored."""
    import base64
    import binascii

    from marketmyna.services import reconcile as rc

    if name not in manager.portfolios:
        raise HTTPException(status_code=404, detail=f"Portfolio '{name}' not found")
    try:
        data = base64.b64decode(body.file_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="File is not valid base64")
    try:
        kind, rows = rc.read_statement(body.filename, data, body.password.strip())
    except rc.StatementError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    unknown: list[dict] = []
    if kind == "broker":
        from marketmyna.data.listings import get_store

        rows, unknown = rc.resolve(rows, [r for r in get_store().rows("india") if r.get("type") in ("stock", "etf")])
    portfolio = manager.portfolios[name]
    result = call_with_deadline(rc.compare, 60, rc.holdings_for(portfolio, kind), rows)
    return {"kind": kind, "rows_read": len(rows) + len(unknown),
            "unresolved": [{"symbol": u["symbol"], "name": u["name"], "isin": u["isin"], "quantity": u["quantity"]}
                           for u in unknown],
            **result, "ledger": rc.ledger_check(portfolio)}


@router.post("/portfolio/{name}/reconcile/apply")
def reconcile_apply(name: str, body: ReconcileApplyRequest,
                    manager: PortfolioManager = Depends(get_portfolio_manager)) -> dict:
    """Post the fixes the user ticked, oldest first; each one stands alone."""
    if name not in manager.portfolios:
        raise HTTPException(status_code=404, detail=f"Portfolio '{name}' not found")
    applied, errors = 0, []
    for f in sorted(body.fixes, key=lambda f: f.date):
        try:
            manager.add_transaction(
                portfolio_name=name, symbol=f.symbol.upper() if f.market != "mf" else f.symbol,
                transaction_type=TransactionType(f.type), quantity=f.quantity, price=f.price,
                date=datetime.fromisoformat(f.date), notes=f.notes, market=f.market,
            )
            applied += 1
        except ValueError as exc:
            errors.append(f"{f.symbol}: {exc}")
    return {"applied": applied, "errors": errors, "portfolio": _summary(manager, name)}


@router.post("/portfolio/{name}/import-funds")
def import_funds(
    name: str, body: ImportFundsRequest, manager: PortfolioManager = Depends(get_portfolio_manager)
) -> dict:
    """Bring mutual fund units in line with a statement (adds only the differences)."""
    from marketmyna.services.mf_holdings import MARKET, plan_import

    if name not in manager.portfolios:
        raise HTTPException(status_code=404, detail=f"Portfolio '{name}' not found")
    held = {s: h.quantity for s, h in manager.portfolios[name].holdings.items() if (h.market or "").lower() == MARKET}
    plan = plan_import(held, [f.model_dump() for f in body.holdings])
    for t in plan:
        try:
            manager.add_transaction(
                portfolio_name=name, symbol=t["symbol"], transaction_type=TransactionType(t["type"]),
                quantity=t["quantity"], price=t["price"], date=datetime.fromisoformat(t["date"]),
                notes=t["notes"], market=MARKET,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    return {"applied": len(plan), "unchanged": len(body.holdings) - len(plan), "portfolio": _summary(manager, name)}


@router.get("/portfolio/{name}/analytics")
def portfolio_analytics(name: str, manager: PortfolioManager = Depends(get_portfolio_manager)) -> dict:
    """Risk / return ratios, correlation and optimizer targets for the current mix."""
    from marketmyna.portfolio.analytics import analyze

    try:
        summary = manager.get_portfolio_summary(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        out = analyze(list(summary["holdings"].values()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Fund holdings are keyed by AMFI code; show their names in the warnings
    from marketmyna.services.mf_holdings import MARKET, latest

    names = {s: info["name"].split(" - ")[0] for s, h in summary["holdings"].items()
             if (h.get("market") or "").lower() == MARKET and (info := latest(s))}
    if names:
        import re

        pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b")
        out["warnings"] = [pattern.sub(lambda m: names[m.group(1)], w) for w in out.get("warnings", [])]
    # A recommended mix is Investment Adviser territory (marketmyna/core/compliance.py).
    out["compliance"] = "analytics"
    out["optimizer"] = None
    return out


@router.get("/funds/{code}/nav")
def fund_nav(code: str, on: Optional[str] = None) -> dict:
    """Official AMFI NAV of a scheme on a date (the last one before it on a
    holiday), so the fund form can fill NAV and work out units from an amount."""
    from datetime import date

    from marketmyna.services.mf_holdings import nav_on

    try:
        day = date.fromisoformat(on) if on else date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    out = nav_on(code, day)
    if out is None:
        raise HTTPException(status_code=404, detail="No NAV found for this fund on or before that date")
    return out


@router.get("/portfolio/{name}/funds")
def portfolio_funds(name: str, manager: PortfolioManager = Depends(get_portfolio_manager)) -> dict:
    """Mutual fund view: per fund value, XIRR, best SIP day and lumpsum window check."""
    from marketmyna.services.mf_lumpsum import portfolio_funds as build

    try:
        summary = _summary(manager, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return build(summary)


@router.post("/portfolio/{name}/funds/{code}/ai-review")
def fund_ai_review(name: str, code: str, manager: PortfolioManager = Depends(get_portfolio_manager),
                   config=Depends(get_config_dep)) -> dict:
    """AI read of one held fund's dip (a lumpsum view for the owner, an
    explanation for everyone else)."""
    from marketmyna.llm.channels import llm_configured
    from marketmyna.llm.protocol import GenerationError
    from marketmyna.services.mf_lumpsum import ai_review

    if name not in manager.get_all_portfolios():
        raise HTTPException(status_code=404, detail=f"Portfolio '{name}' not found")
    held = {s for s, h in manager.portfolios[name].holdings.items() if (h.market or "").lower() == "mf"}
    if code not in held:
        raise HTTPException(status_code=404, detail="That fund isn't in this portfolio.")
    if not llm_configured(config):
        raise HTTPException(status_code=409, detail="No AI model is set up. Add an AI key under Settings → AI keys.")
    try:
        out = call_with_deadline(ai_review, 100, code, config)
    except GenerationError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    if not out:
        raise HTTPException(status_code=502, detail="The AI model did not return a usable review. Try again.")
    return out


class DipRulesRequest(BaseModel):
    levels: list[float] = Field(default_factory=list)
    overrides: dict[str, list[float]] = Field(default_factory=dict)


@router.get("/portfolio/{name}/dip-alerts")
def get_dip_alerts(name: str, config=Depends(get_config_dep)) -> dict:
    """The user's own % dip-alert levels: portfolio default and per-fund overrides."""
    from marketmyna.services.mf_lumpsum import get_rules

    try:
        return get_rules(config, name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/portfolio/{name}/dip-alerts")
def set_dip_alerts(name: str, body: DipRulesRequest, config=Depends(get_config_dep)) -> dict:
    from marketmyna.services.mf_lumpsum import set_rules

    try:
        return set_rules(config, name, body.levels, body.overrides)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/portfolio/{name}/dip-alerts/test")
def test_dip_alert(name: str, config=Depends(get_config_dep)) -> dict:
    """Sends a sample dip alert through the user's channels."""
    from marketmyna.services.mf_lumpsum import send_test_alert

    try:
        out = send_test_alert(config, name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not any(out["sent"].values()):
        raise HTTPException(status_code=409, detail="No channel reached you. Turn on push, email or Telegram in Settings first.")
    return out


def _fund_health(summary: dict) -> dict:
    from marketmyna.portfolio.analytics import MF_PREFIX, _download_closes
    from marketmyna.services.mf_holdings import MARKET
    from marketmyna.services.mf_insights import insights

    funds = [h for h in summary["holdings"].values() if (h.get("market") or "").lower() == MARKET]
    if not funds:
        return {"funds": 0}
    closes = _download_closes([MF_PREFIX + f["symbol"] for f in funds])
    navs = {k[len(MF_PREFIX):]: v for k, v in closes.items()}
    return insights(funds, navs)


@router.get("/portfolio/{name}/fund-insights")
def fund_insights(name: str, manager: PortfolioManager = Depends(get_portfolio_manager)) -> dict:
    """Health check for the mutual funds held: category mix, duplicates, similar-moving funds, plan costs."""
    try:
        summary = _summary(manager, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _fund_health(summary)


@router.post("/portfolio/{name}/funds/ai-review")
def funds_ai_review(name: str, refresh: bool = Query(default=False),
                    manager: PortfolioManager = Depends(get_portfolio_manager), config=Depends(get_config_dep)) -> dict:
    """AI read of the whole fund portfolio: mix, overlap, look-through
    concentration and each fund's role (marketmyna/services/mf_portfolio_ai.py)."""
    from marketmyna.llm.channels import llm_configured
    from marketmyna.llm.protocol import GenerationError
    from marketmyna.services import mf_portfolio_ai
    from marketmyna.services.mf_lumpsum import portfolio_funds

    try:
        summary = _summary(manager, name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not llm_configured(config):
        raise HTTPException(status_code=409, detail="No AI model is set up. Add an AI key under Settings → AI keys.")

    def run():
        return mf_portfolio_ai.review(name, portfolio_funds(summary), _fund_health(summary), config,
                                      use_cache=not refresh)

    try:
        out = call_with_deadline(run, 240)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except GenerationError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    if not out:
        raise HTTPException(status_code=502, detail="The AI model did not return a usable review. Try again.")
    return out


def _review(manager: PortfolioManager, name: str, config) -> dict:
    from marketmyna.portfolio.review import for_portfolio

    return for_portfolio(manager, name, config)


@router.get("/portfolio/{name}/review")
def portfolio_review(name: str, manager: PortfolioManager = Depends(get_portfolio_manager),
                     config=Depends(get_config_dep)) -> dict:
    """What in the current mix could be changed, why, and the levers for it."""
    try:
        return _review(manager, name, config)
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class ReviewLimitsRequest(BaseModel):
    max_holding: Optional[float] = None
    max_sector: Optional[float] = None
    max_cash: Optional[float] = None
    loss_review: Optional[float] = None
    min_holdings: Optional[int] = None


@router.put("/portfolio/{name}/review/limits")
def set_review_limits(name: str, body: ReviewLimitsRequest, config=Depends(get_config_dep)) -> dict:
    from marketmyna.portfolio.review import set_limits

    try:
        return set_limits(config, name, body.model_dump(exclude_none=True))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/portfolio/{name}/review/ai")
def portfolio_review_ai(name: str, manager: PortfolioManager = Depends(get_portfolio_manager),
                        config=Depends(get_config_dep)) -> dict:
    """AI analyst read of the review: priorities for the owner, an explanation for everyone else."""
    from marketmyna.llm.channels import llm_configured
    from marketmyna.llm.protocol import GenerationError
    from marketmyna.portfolio.review import ai_summary

    if not llm_configured(config):
        raise HTTPException(status_code=409, detail="No AI model is set up. Add an AI key under Settings → AI keys.")
    try:
        review = _review(manager, name, config)
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not review["findings"] and not review["good"]:
        raise HTTPException(status_code=422, detail="Add holdings first.")
    try:
        out = call_with_deadline(ai_summary, 100, review, config)
    except GenerationError as exc:
        raise HTTPException(status_code=402, detail=str(exc))
    if not out:
        raise HTTPException(status_code=502, detail="The AI model did not return a usable review. Try again.")
    return out


@router.post("/portfolio", status_code=201)
def create_portfolio(
    body: CreatePortfolioRequest,
    manager: PortfolioManager = Depends(get_portfolio_manager),
    config=Depends(get_config_dep),
) -> dict:
    try:
        portfolio = manager.create_portfolio(body.name.strip(), currency=body.currency, kind=body.kind)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return portfolio.to_dict()


@router.post("/portfolio/{name}/transactions", status_code=201)
def add_transaction(
    name: str,
    body: AddTransactionRequest,
    manager: PortfolioManager = Depends(get_portfolio_manager),
) -> dict:
    market = "mf" if (body.market or "").lower() == "mf" else body.market
    try:
        manager.add_transaction(
            portfolio_name=name,
            symbol=body.symbol,
            transaction_type=body.transaction_type,
            quantity=body.quantity,
            price=body.price,
            date=body.date,
            fees=body.fees,
            notes=body.notes,
            # Mutual funds are keyed by AMFI code under market "mf" (any case from the form).
            market=market,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _summary(manager, name)


@router.patch("/portfolio/{name}")
def rename_portfolio(
    name: str, body: RenamePortfolioRequest, manager: PortfolioManager = Depends(get_portfolio_manager)
) -> dict:
    if name not in manager.portfolios:
        raise HTTPException(status_code=404, detail=f"Portfolio '{name}' not found")
    try:
        portfolio = manager.rename_portfolio(name, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _summary(manager, portfolio.name)


@router.delete("/portfolio/{name}", status_code=204)
def delete_portfolio(name: str, manager: PortfolioManager = Depends(get_portfolio_manager)) -> Response:
    try:
        manager.delete_portfolio(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(status_code=204)


@router.delete("/portfolio/{name}/transactions/{index}")
def delete_transaction(
    name: str, index: int, manager: PortfolioManager = Depends(get_portfolio_manager)
) -> dict:
    """Remove one transaction and rebuild holdings from the rest of the history."""
    if name not in manager.portfolios:
        raise HTTPException(status_code=404, detail=f"Portfolio '{name}' not found")
    try:
        manager.delete_transaction(name, index)
    except IndexError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _summary(manager, name)
