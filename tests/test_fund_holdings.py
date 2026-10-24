"""Fund holdings from official monthly portfolio files (SEBI layout)."""

from __future__ import annotations

import io

import pandas as pd
import pytest

from marketmyna.services import fund_holdings as fh

HEADER = [None, "Name of the Instrument", "ISIN", "Industry / Rating", "Quantity",
          "Market/Fair Value (Rs. in Lakhs)", "% to Net Assets"]


def _sheet(title, as_of, rows, grand):
    data = [[None, f"{title} (An open-ended dynamic equity scheme)", None, None, None, None, None],
            [None, None, None, None, None, None, None],
            [None, f"Monthly Portfolio Statement as on {as_of}", None, None, None, None, None],
            HEADER,
            [None, "Equity & Equity related", None, None, None, None, None],
            [None, "(a) Listed / awaiting listing on Stock Exchanges", None, None, None, None, None]]
    data += rows
    data += [[None, "Sub Total", None, None, None, 1000, None],
             [None, "Reverse Repo / TREPS", None, None, None, None, None],
             ["TRP", "TRP_010926", None, None, None, 50, grand * 0.05],
             [None, "GRAND TOTAL", None, None, None, 1050, grand],
             [None, "Derivatives", None, None, None, None, None],
             ["X", "Reliance Industries September 2026 Future", "INE002A01018", "(Short)", -10, -5, -0.5]]
    return pd.DataFrame(data)


def _book(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, header=False, index=False)
    return buf.getvalue()


AUG = {
    "ABC": _sheet("Alpha Flexi Cap Fund", "August 31, 2026", [
        ["H1", "HDFC Bank Limited", "INE040A01034", "Banks", 100, 700, 0.07],
        ["I1", "Infosys Limited", "INE009A01021", "IT - Software", 50, 300, 0.03],
        [None, "Arbitrage", None, None, None, None, None],
        ["H2", "HDFC Bank Limited", "INE040A01034", "Banks", 10, 100, 0.01],
        [None, "Equity & Equity related Foreign Investments", None, None, None, None, None],
        ["G1", "Alphabet Inc A", "US02079K3059", "Software", 5, 400, 0.04],
        [None, "Certificate of Deposit", None, None, None, None, None],
        ["N1", "NABARD CD", "INE261F16AB5", "CRISIL A1+", 8, 200, 0.02],
    ], 1),
    "XYZ": _sheet("Alpha Liquid Fund", "August 31, 2026", [
        [None, "Treasury Bill", None, None, None, None, None],
        ["T1", "364 Days Tbill", "IN002026Z136", "Sovereign", 1, 900, 90.0],
    ], 100),
}


def test_parse_fraction_and_percent_sections():
    schemes = fh.parse_workbook(_book(AUG), "aug.xlsx")
    flexi, liquid = schemes
    assert flexi["scheme"] == "Alpha Flexi Cap Fund" and flexi["as_of"] == "2026-08-31"
    kinds = {(h["name"], h["kind"]): round(h["weight"], 2) for h in flexi["holdings"]}
    assert kinds == {("HDFC Bank Limited", "equity"): 7.0, ("Infosys Limited", "equity"): 3.0,
                     ("HDFC Bank Limited", "arbitrage"): 1.0, ("Alphabet Inc A", "foreign_equity"): 4.0,
                     ("NABARD CD", "debt"): 2.0}  # derivatives after GRAND TOTAL ignored
    assert liquid["holdings"][0]["weight"] == 90.0 and liquid["holdings"][0]["kind"] == "debt"  # percent file


def test_not_a_portfolio_file():
    with pytest.raises(ValueError, match="No scheme portfolios"):
        fh.parse_workbook(_book({"S": pd.DataFrame([["hello", "world"]])}))


def test_name_matching():
    schemes = [{"scheme": "Alpha Flexi Cap Fund"}, {"scheme": "Alpha Large & Mid Cap Fund"}, {"scheme": "Alpha Liquid Fund"}]
    assert fh.match_scheme("Alpha Flexi Cap Fund - Direct Plan - Growth", schemes)["scheme"] == "Alpha Flexi Cap Fund"
    assert fh.match_scheme("ALPHA LARGE AND MID CAP FUND - REGULAR PLAN - IDCW", schemes)["scheme"] == "Alpha Large & Mid Cap Fund"
    assert fh.match_scheme("Alpha Small Cap Fund - Direct - Growth", schemes) is None


def test_store_view_changes_and_reverse_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(fh.Path, "home", lambda: tmp_path)
    fh._load.cache_clear()
    jul = {"ABC": _sheet("Alpha Flexi Cap Fund", "July 31, 2026", [
        ["H1", "HDFC Bank Limited", "INE040A01034", "Banks", 100, 500, 0.05],
        ["T1", "TCS Limited", "INE467B01029", "IT - Software", 10, 200, 0.02],
    ], 1)}
    fh.ingest("Alpha Mutual Fund", _book(jul), "jul.xlsx")
    fh.ingest("Alpha Mutual Fund", _book(AUG), "aug.xlsx")
    assert [s["month"] for s in fh.status()][0] == "2026-08" and fh.status()[0]["months"] == ["2026-08", "2026-07"]

    rows = [{"type": "mf", "symbol": "101", "name": "Alpha Flexi Cap Fund - Direct Plan - Growth", "amc": "Alpha Mutual Fund"},
            {"type": "stock", "symbol": "HDFCBANK", "isin": "INE040A01034", "sector": "Banks"},
            {"type": "stock", "symbol": "INFY", "isin": "INE009A01021"}]
    monkeypatch.setattr(fh, "_isin_symbols", lambda: {r["isin"]: r for r in rows if r.get("isin")})
    out = fh.for_fund("101", rows=rows)
    assert out["status"] == "ok" and out["as_of"] == "2026-08-31"
    hdfc = out["top"][0]
    assert hdfc["symbol"] == "HDFCBANK" and round(hdfc["weight"], 2) == 8.0 and round(hdfc["hedged"], 2) == 1.0
    mix = {m["kind"]: round(m["weight"], 1) for m in out["mix"]}
    assert mix["equity"] == 11.0 and mix["foreign_equity"] == 4.0 and mix["cash"] > 0
    ch = out["changes"]
    assert {c["name"] for c in ch["new"]} == {"Infosys Limited", "Alphabet Inc A"}
    assert [c["name"] for c in ch["exited"]] == ["TCS Limited"]
    assert ch["moved"][0]["name"] == "HDFC Bank Limited" and round(ch["moved"][0]["to"], 1) == 8.0

    from marketmyna.data import listings

    class _Store:
        def rows(self, market):
            return rows

    monkeypatch.setattr(listings, "get_store", lambda: _Store())
    held = fh.funds_holding("hdfcbank")
    assert held["count"] == 1 and held["funds"][0]["scheme"] == "Alpha Flexi Cap Fund"
    assert round(held["funds"][0]["weight"], 1) == 8.0 and round(held["funds"][0]["prev_weight"], 1) == 5.0

    missing = fh.for_fund("101", rows=[{**rows[0], "name": "Alpha Small Cap Fund - Direct - Growth"}])
    assert missing["status"] == "missing"
    fh._load.cache_clear()


def test_ppfas_link_picker():
    page = b'''<a href="/downloads/portfolio-disclosure/2026/PPFAS_Monthly_Portfolio_Report_July_31_2026.xls?1">
    <a href="/downloads/portfolio-disclosure/2026/PPFAS_Monthly_Portfolio_Report_August_31_2026.xls?2">
    <a href="/downloads/portfolio-disclosure/2026/PPFCF_PPFAS_Monthly_Portfolio_Report_August_31_2026.xlsx?2">'''
    got = []

    def fetch(url):
        got.append(url)
        return page if url.endswith("/portfolio-disclosure/") else b"file"

    files = fh._ppfas(fetch)
    assert [n for _, n in files] == ["/downloads/portfolio-disclosure/2026/PPFAS_Monthly_Portfolio_Report_August_31_2026.xls"]


def test_concentration_and_churn():
    from marketmyna.services import fund_holdings as fh

    stocks = [{"weight": 25.0}, {"weight": 25.0}, {"weight": 25.0}, {"weight": 25.0}]
    c = fh.concentration(stocks)
    assert c["effective_stocks"] == pytest.approx(4) and c["top_weight"] == 25
    before = [{"isin": "A", "kind": "equity", "qty": 100, "value_lakh": 100.0},
              {"isin": "B", "kind": "equity", "qty": 100, "value_lakh": 100.0}]
    # A doubled in price with no trade; 20 shares of B sold; C bought fresh
    now = [{"isin": "A", "kind": "equity", "qty": 100, "value_lakh": 200.0},
           {"isin": "B", "kind": "equity", "qty": 80, "value_lakh": 80.0},
           {"isin": "C", "kind": "equity", "qty": 10, "value_lakh": 30.0}]
    ch = fh.churn(now, before, aum_cr=3.1)
    assert ch["sold_cr"] == pytest.approx(0.2) and ch["bought_cr"] == pytest.approx(0.3)  # price rise is not trading
    assert ch["month_pct"] == pytest.approx(0.2 / 3.1 * 100) and ch["yearly_pct"] == pytest.approx(ch["month_pct"] * 12)
    assert fh.churn(now, [], aum_cr=3.1) is None


def test_pair_overlap():
    from marketmyna.services import fund_holdings as fh

    a = {"status": "ok", "holdings": [{"isin": "X", "name": "X Ltd", "kind": "equity", "weight": 10.0},
                                      {"isin": "Y", "name": "Y Ltd", "kind": "equity", "weight": 5.0},
                                      {"isin": "Z", "name": "Gilt", "kind": "debt", "weight": 20.0}]}
    b = {"status": "ok", "holdings": [{"isin": "X", "name": "X Ltd", "kind": "equity", "weight": 4.0},
                                      {"isin": "W", "name": "W Ltd", "kind": "equity", "weight": 7.0}]}
    o = fh.pair_overlap(a, b)
    assert o["overlap"] == 4.0 and o["shared_count"] == 1 and o["only_a"] == 1 and o["only_b"] == 1
    assert o["shared"] == [{"name": "X Ltd", "symbol": None, "weight_a": 10.0, "weight_b": 4.0}]
    assert fh.pair_overlap(a, {"status": "missing"}) is None
