"""Portfolio reconciliation: your MarketMyna records against a statement.

Adapted from the GL-reconciler and statement-auditor workflows in
anthropics/financial-services (Apache-2.0): tie every position out against an
outside statement, list each break with the evidence and the most likely
cause, and propose a correcting entry that is only posted after the user
approves it. Two checks:

  ledger      the stored holdings against a replay of the transaction history
              (they should always agree; a difference is internal drift)
  statement   the holdings against a broker holdings export (CSV / Excel from
              Zerodha, Groww, Angel One, Upstox...) or a CAMS / KFintech CAS PDF

Causes, in the order they are tested: a split or bonus Yahoo knows about that
explains the exact ratio; a position only on one side (bought or sold outside
the records, IPO, gift, transfer); a quantity difference (a partial buy or
sale not recorded); and, for equal quantities, an average-cost difference
(brokers often include charges or use a different lot method) - reported for
information only.

The statement file is read in memory and never stored.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date
from typing import Callable, Optional

import pandas as pd

logger = logging.getLogger(__name__)

QTY_TOL = 1e-3  # shares / units
COST_TOL = 0.02  # an average cost within 2% is a match
RATIO_TOL = 0.01

SYMBOL_COLS = ("symbol", "tradingsymbol", "trading symbol", "instrument", "scrip", "scrip code", "stock symbol",
               "nse symbol", "ticker")
NAME_COLS = ("stock name", "company name", "company", "name", "security name", "scrip name", "stock")
QTY_COLS = ("quantity available", "quantity", "qty", "net qty", "total quantity", "holding qty", "holdings",
            "shares", "units", "free qty", "available qty")
AVG_COLS = ("average price", "avg. cost", "avg cost", "average cost", "average buy price", "avg price",
            "avg. price", "buy avg", "buy average", "average cost price")
ISIN_COLS = ("isin", "isin code")

ActionsFetch = Callable[[str, str, date], list[tuple[date, float]]]


class StatementError(ValueError):
    pass


# ------------------------------------------------------------------ reading statements


def _norm(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _pick(columns: list[str], wanted: tuple[str, ...]) -> Optional[str]:
    cols = {_norm(c): c for c in columns}
    for w in wanted:
        if w in cols:
            return cols[w]
    for w in wanted:  # "Quantity Available (T1)" and similar
        for k, c in cols.items():
            if k.startswith(w):
                return c
    return None


def _table(df: pd.DataFrame) -> pd.DataFrame:
    """Broker exports often have a preamble (client id, dates) above the table:
    find the first row that looks like the header."""
    if _pick(list(df.columns), QTY_COLS):
        return df
    for i in range(min(len(df), 40)):
        row = [str(v) for v in df.iloc[i].tolist()]
        if _pick(row, QTY_COLS) and (_pick(row, SYMBOL_COLS) or _pick(row, NAME_COLS) or _pick(row, ISIN_COLS)):
            out = df.iloc[i + 1:].copy()
            out.columns = row
            return out
    raise StatementError("Couldn't find a holdings table (no quantity column) in this file.")


def _num(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(str(v).replace(",", "").replace("₹", "").strip())
    except ValueError:
        return None


def read_table(filename: str, data: bytes) -> list[dict]:
    """A broker holdings export -> [{symbol, name, isin, quantity, avg_cost}]."""
    name = filename.lower()
    try:
        if name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(data), header=None, dtype=object)
            df.columns = [f"c{i}" for i in range(len(df.columns))]
        else:
            # csv module, not pandas: a short preamble line ("Client ID,AB1234") would
            # make pandas size the table to 2 columns and drop the real rows.
            text = data.decode("utf-8-sig", errors="replace")
            try:
                dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            lines = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
            width = max((len(r) for r in lines), default=0)
            df = pd.DataFrame([r + [""] * (width - len(r)) for r in lines], columns=[f"c{i}" for i in range(width)])
    except StatementError:
        raise
    except Exception as exc:
        raise StatementError(f"Couldn't read this file ({type(exc).__name__}). Upload a CSV or Excel holdings export.") from exc
    df = _table(df)
    cols = list(df.columns)
    sym_c, name_c, isin_c = _pick(cols, SYMBOL_COLS), _pick(cols, NAME_COLS), _pick(cols, ISIN_COLS)
    qty_c, avg_c = _pick(cols, QTY_COLS), _pick(cols, AVG_COLS)
    rows = []
    for _, r in df.iterrows():
        qty = _num(r.get(qty_c))
        sym = str(r.get(sym_c) or "").strip() if sym_c else ""
        nm = str(r.get(name_c) or "").strip() if name_c else ""
        isin = str(r.get(isin_c) or "").strip().upper() if isin_c else ""
        if qty is None or not (sym or nm or isin) or _norm(sym or nm) in ("total", "grand total"):
            continue
        rows.append({"symbol": sym, "name": nm, "isin": isin if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", isin) else "",
                     "quantity": qty, "avg_cost": _num(r.get(avg_c)) if avg_c else None})
    if not rows:
        raise StatementError("The file has a holdings table but no rows with a quantity.")
    return rows


def read_cas(data: bytes, password: str) -> list[dict]:
    """A CAMS / KFintech CAS PDF -> one row per scheme (AMFI code as the symbol)."""
    from .mf_holdings import CASError, parse_cas

    try:
        cas = parse_cas(data, password)
    except CASError as exc:
        raise StatementError(str(exc)) from exc
    return [{"symbol": str(h["amfi"]), "name": h["scheme"], "isin": h.get("isin") or "", "quantity": h["units"],
             "avg_cost": (h["cost"] / h["units"]) if h.get("cost") and h["units"] else None, "market": "mf",
             "resolved": True} for h in cas["holdings"]]


def read_statement(filename: str, data: bytes, password: str = "") -> tuple[str, list[dict]]:
    """-> (kind, rows): kind "cas" (mutual funds) or "broker" (Indian equities)."""
    if data.startswith(b"%PDF"):
        return "cas", read_cas(data, password)
    return "broker", read_table(filename, data)


# ------------------------------------------------------------------ matching


def _clean_symbol(s: str) -> str:
    s = s.strip().upper()
    s = re.sub(r"^(NSE|BSE)[:\s]+", "", s)
    return re.sub(r"(-EQ|-BE|-BZ|\.NS|\.BO)$", "", s)


def resolve(rows: list[dict], listings: list[dict]) -> tuple[list[dict], list[dict]]:
    """Give each broker row its NSE symbol: by symbol, then ISIN, then exact name."""
    by_symbol = {str(r["symbol"]).upper(): r for r in listings}
    by_isin = {r["isin"]: r for r in listings if r.get("isin")}
    by_name = {_norm(r.get("name")): r for r in listings if r.get("name")}
    done, unknown = [], []
    for row in rows:
        if row.get("resolved"):
            done.append(row)
            continue
        hit = by_symbol.get(_clean_symbol(row["symbol"])) if row["symbol"] else None
        hit = hit or (by_isin.get(row["isin"]) if row["isin"] else None)
        hit = hit or (by_name.get(_norm(row["name"])) if row["name"] else None)
        if hit is None:
            unknown.append(row)
            continue
        done.append({**row, "symbol": str(hit["symbol"]).upper(), "name": row["name"] or hit.get("name", ""),
                     "market": "india"})
    return done, unknown


def _yahoo_actions(symbol: str, market: str, since: date) -> list[tuple[date, float]]:
    """Splits and bonuses (Yahoo reports bonuses as splits: 1:1 bonus = 2.0) since a date."""
    import yfinance as yf

    from .analysis_run import yahoo_symbol

    s = yf.Ticker(yahoo_symbol(symbol, market)).splits
    if s is None or s.empty:
        return []
    out = []
    for when, ratio in s.items():
        d = pd.Timestamp(when).date()
        if d >= since and ratio and ratio > 0:
            out.append((d, float(ratio)))
    return out


def _ratio_text(r: float) -> str:
    """2.0 -> "×2 (each share became 2)": unambiguous, unlike "1:1 bonus" vs "1:2"."""
    return f"×{r:g} (each share became {r:g})"


def _explained_by_actions(app_qty: float, stmt_qty: float, actions: list[tuple[date, float]]) -> Optional[list[tuple[date, float]]]:
    """The corporate actions (in order) whose combined ratio turns app_qty into stmt_qty."""
    if app_qty <= 0 or not actions:
        return None
    target = stmt_qty / app_qty
    total = 1.0
    for i, (_, r) in enumerate(actions):
        total *= r
        if abs(total - target) <= RATIO_TOL * target:
            return actions[: i + 1]
    return None


def compare(app: dict[str, dict], stmt: list[dict], actions: Optional[ActionsFetch] = _yahoo_actions,
            today: Optional[date] = None) -> dict:
    """app: symbol -> {quantity, avg_cost, market, current_price, first_date}; stmt rows are resolved.

    Returns matches, breaks (each with cause and a proposed fix) and cost differences."""
    today = today or date.today()
    stmt_by = {}
    for r in stmt:  # a symbol in several rows (two demat lines, two folios) is one position
        cur = stmt_by.get(r["symbol"])
        if cur is None:
            stmt_by[r["symbol"]] = dict(r)
        else:
            q = cur["quantity"] + r["quantity"]
            if cur.get("avg_cost") is not None and r.get("avg_cost") is not None and q:
                cur["avg_cost"] = (cur["avg_cost"] * cur["quantity"] + r["avg_cost"] * r["quantity"]) / q
            cur["quantity"] = q
    matches, breaks, costs = [], [], []
    note = f"Reconciliation {today.isoformat()}"
    for sym in sorted(set(app) | set(stmt_by)):
        a, s = app.get(sym), stmt_by.get(sym)
        market = (s or {}).get("market") or (a or {}).get("market") or "india"
        base = {"symbol": sym, "market": market, "name": (s or {}).get("name") or "",
                "statement_qty": s["quantity"] if s else 0.0, "app_qty": a["quantity"] if a else 0.0,
                "statement_avg": (s or {}).get("avg_cost"), "app_avg": (a or {}).get("avg_cost")}
        base["diff"] = base["statement_qty"] - base["app_qty"]
        price_now = (a or {}).get("current_price") or (s or {}).get("avg_cost") or 0.0

        if s and s["quantity"] > QTY_TOL and (not a or a["quantity"] <= QTY_TOL):
            breaks.append({**base, "kind": "not_in_app",
                           "cause": "On the statement but not in your records: a buy not recorded here, "
                                    "or shares from an IPO, gift or transfer-in.",
                           "fix": {"type": "buy", "quantity": s["quantity"], "price": s.get("avg_cost") or price_now,
                                   "date": today.isoformat(), "notes": note, "needs_price": not s.get("avg_cost")}})
            continue
        if a and a["quantity"] > QTY_TOL and (not s or s["quantity"] <= QTY_TOL):
            breaks.append({**base, "kind": "not_in_statement",
                           "cause": "In your records but not on the statement: sold (not recorded here), or held "
                                    "in another demat account or folio.",
                           "fix": {"type": "sell", "quantity": a["quantity"], "price": price_now,
                                   "date": today.isoformat(), "notes": note, "needs_price": True}})
            continue
        if not a or not s:
            continue
        tol = max(QTY_TOL, a["quantity"] * 1e-5) if market == "mf" else QTY_TOL  # fund units carry 3 decimals
        if abs(base["diff"]) <= tol:
            matches.append(base)
            sa, aa = s.get("avg_cost"), a.get("avg_cost")
            if sa and aa and abs(sa / aa - 1) > COST_TOL:
                costs.append({**base, "cause": "Same quantity, different average cost: brokers often add charges "
                                               "to the cost or use a different lot method. Nothing to fix."})
            continue
        found = None
        if actions and market != "mf":
            try:
                since = a.get("first_date") or date(2000, 1, 1)
                found = _explained_by_actions(a["quantity"], s["quantity"], actions(sym, market, since))
            except Exception as exc:
                logger.info("Corporate actions for %s unavailable: %s", sym, exc)
        if found:
            labels = ", ".join(f"{_ratio_text(r)} on {d.isoformat()}" for d, r in found)
            breaks.append({**base, "kind": "split",
                           "cause": f"A split / bonus ({labels}) is not recorded: it explains the difference exactly.",
                           "fixes": [{"type": "split", "quantity": r, "price": 0.0, "date": d.isoformat(),
                                      "notes": f"Split / bonus ×{r:g} (reconciliation)"} for d, r in found]})
            continue
        if base["diff"] > 0:
            # cost of the missing lot, from the statement's total cost less what is recorded
            lot = None
            if s.get("avg_cost") and a.get("avg_cost"):
                lot = (s["quantity"] * s["avg_cost"] - a["quantity"] * a["avg_cost"]) / base["diff"]
            breaks.append({**base, "kind": "short",
                           "cause": f"The statement shows {base['diff']:g} more: a buy not recorded here.",
                           "fix": {"type": "buy", "quantity": base["diff"], "price": lot if lot and lot > 0 else price_now,
                                   "date": today.isoformat(), "notes": note, "needs_price": not (lot and lot > 0)}})
        else:
            breaks.append({**base, "kind": "excess",
                           "cause": f"Your records show {-base['diff']:g} more: a sale not recorded here, or part "
                                    "held in another account.",
                           "fix": {"type": "sell", "quantity": -base["diff"], "price": price_now,
                                   "date": today.isoformat(), "notes": note, "needs_price": True}})
    for b in breaks:  # one shape for the client: always a list of fixes
        if "fix" in b:
            b["fixes"] = [b.pop("fix")]
    return {"matches": matches, "breaks": breaks, "cost_differences": costs}


# ------------------------------------------------------------------ ledger check


def ledger_check(portfolio) -> list[dict]:
    """Stored holdings vs a replay of the transaction history."""
    from ..portfolio.manager import PortfolioManager

    try:
        # recorded order, as the portfolio itself applies them
        replayed = PortfolioManager._replay(list(portfolio.transactions), {})
    except ValueError as exc:
        return [{"symbol": None, "issue": f"The transaction history doesn't replay cleanly: {exc}"}]
    out = []
    for sym in sorted(set(replayed) | set(portfolio.holdings)):
        h, r = portfolio.holdings.get(sym), replayed.get(sym)
        hq, rq = (h.quantity if h else 0.0), (r.quantity if r else 0.0)
        if abs(hq - rq) > QTY_TOL:
            out.append({"symbol": sym, "stored": hq, "from_history": rq,
                        "issue": "Holding and transaction history disagree" if h and r else
                        ("Holding with no transactions behind it" if h else "Transactions with no holding")})
    return out


def holdings_for(portfolio, kind: str) -> dict[str, dict]:
    """The positions a statement of this kind covers: CAS -> funds, broker -> Indian equities."""
    want = {"cas": ("mf",), "broker": ("india",)}[kind]
    first: dict[str, date] = {}
    for t in portfolio.transactions:
        if t.date and (t.symbol not in first or t.date.date() < first[t.symbol]):
            first[t.symbol] = t.date.date()
    return {sym: {"quantity": h.quantity, "avg_cost": h.avg_cost, "market": (h.market or "").lower(),
                  "current_price": h.current_price, "first_date": first.get(sym)}
            for sym, h in portfolio.holdings.items() if (h.market or "").lower() in want}
