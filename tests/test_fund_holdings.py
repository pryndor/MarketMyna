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


def test_pair_overlap_file_fund_vs_index_fund():
    """A fund house file (ISIN + symbol) against an index fund estimated from the
    index list (symbol, no ISIN) still finds the shared stocks."""
    from marketmyna.services import fund_holdings as fh

    file_fund = {"status": "ok", "holdings": [
        {"isin": "INE040A01034", "symbol": "HDFCBANK", "name": "HDFC Bank Ltd", "kind": "equity", "weight": 8.0},
        {"isin": "US0231351067", "symbol": None, "name": "Amazon", "kind": "foreign_equity", "weight": 3.0}]}
    index_fund = {"status": "ok", "holdings": [
        {"isin": None, "symbol": "HDFCBANK", "name": "HDFC Bank", "kind": "equity", "weight": 12.0},
        {"isin": None, "symbol": "TCS", "name": "TCS", "kind": "equity", "weight": 4.0}]}
    o = fh.pair_overlap(file_fund, index_fund)
    assert o["overlap"] == 8.0 and o["shared_count"] == 1 and o["only_a"] == 1 and o["only_b"] == 1


# ---------------------------------------------------------------- auto-downloaders (offline)

def test_date_in_file_names():
    from marketmyna.services import fund_holdings as fh

    days = {n: fh._date_in_name(n).date().isoformat() for n in [
        "dsp-monthend-portfolio-as-on-30-september-2026.zip", "dsp-monthend-portfolio-as-on-31-aug-2026.zip",
        "monthend-portfolios_31_july_2026.zip", "monthend-portfolio-31march2026.zip",
        "monthend-portfolio-february-28-2026.zip"]}
    assert list(days.values()) == ["2026-09-30", "2026-08-31", "2026-07-31", "2026-03-31", "2026-02-28"]


def test_nippon_picks_latest_monthly_not_fortnightly():
    from marketmyna.services import fund_holdings as fh

    page = ('<a href="/InvestorServices/FactsheetsDocuments/NIMF-FORTNIGHTLY-PORTFOLIO-15-Oct-26.xls">'
            '<a href="/InvestorServices/FactsheetsDocuments/NIMF-MONTHLY-PORTFOLIO-30-Sep-26.xls">'
            '<a href="/InvestorServices/FactsheetsDocuments/NIMF-MONTHLY-PORTFOLIO-31-July-26.xls">')
    got = []
    out = fh._nippon(lambda url: page.encode() if "investor-service" in url else got.append(url) or b"x")
    assert got == ["https://mf.nipponindiaim.com/InvestorServices/FactsheetsDocuments/NIMF-MONTHLY-PORTFOLIO-30-Sep-26.xls"]
    assert out[0][1] == "NIMF-MONTHLY-PORTFOLIO-30-Sep-26.xls"


def test_dsp_picks_latest_month_end_zip():
    from marketmyna.services import fund_holdings as fh

    base = "https://www.dspim.com/media/pages/mandatory-disclosures/portfolio-disclosures/"
    page = (f'<a href="{base}a/dsp-isin-debt-fortnightly-portfolio-as-on-15-october-2026.xlsx">'
            f'<a href="{base}b/dsp-monthend-portfolio-as-on-31-aug-2026.zip">'
            f'<a href="{base}c/dsp-monthend-portfolio-as-on-30-september-2026.zip">')
    got = []
    fh._dsp(lambda url: page.encode() if url.endswith("portfolio-disclosures") else got.append(url) or b"x")
    assert got == [base + "c/dsp-monthend-portfolio-as-on-30-september-2026.zip"]


def test_uti_takes_latest_month_from_its_list(monkeypatch):
    import json

    from marketmyna.services import fund_holdings as fh

    rows = {"rows": [{"month": "January", "url": "https://cdn/jan.zip?v=1"},
                     {"month": "September", "url": "https://cdn/sep.zip"}, {"month": "May", "doc": "https://cdn/may.zip"}]}
    got = []

    def fetch(url):
        if "api/get-consolidate" in url:
            return json.dumps(rows if f"year={fh.datetime.now().year}" in url else {"rows": []}).encode()
        got.append(url)
        return b"x"

    assert fh._uti(fetch)[0][1] == "sep.zip" and got == ["https://cdn/sep.zip"]


def test_mirae_takes_every_scheme_file_of_the_newest_date():
    import json

    from marketmyna.services import fund_holdings as fh

    data = {"d": {"ReturnCode": "0", "Data": [
        {"Title": "Portfolio Details as on 30th September 2026 for Mirae Asset Flexi Cap Fund",
         "URL": "/docs/default-source/portfolios/mafcf_sept2026.xlsx"},
        {"Title": "Portfolio Details as on 30th September 2026 for Mirae Asset Liquid Fund",
         "URL": "/docs/default-source/portfolios/macmf_sept2026.xlsx"},
        {"Title": "Portfolio Details as on 31st August 2026 for Mirae Asset Flexi Cap Fund",
         "URL": "/docs/default-source/portfolios/mafcf_aug2026.xlsx"}]}}
    got = []
    out = fh._mirae(lambda url: got.append(url) or b"x", post=lambda path, body: json.dumps(data).encode())
    assert [n for _, n in out] == ["macmf_sept2026.xlsx", "mafcf_sept2026.xlsx"]
    assert all(u.startswith("https://www.miraeassetmf.co.in/docs/") for u in got)


def test_sbi_walks_months_newest_first_to_the_all_schemes_file():
    import json

    from marketmyna.services import fund_holdings as fh

    year = str(fh.datetime.now().year)

    def post(path, body):
        if path.endswith("GetMonthsByYear"):
            return json.dumps(["August", "October", "September"] if body["year"] == year else []).encode()
        if body["PSMonth"] == "October":  # not published yet
            return b"<table></table>"
        return (f'<a href="https://www.sbimf.com/docs/default-source/scheme-portfolios/'
                f'all-schemes-monthly-portfolio---as-on-30th-{body["PSMonth"].lower()}-{year}.xlsx?sfvrsn=1">').encode()

    got = []
    out = fh._sbi(lambda url: got.append(url) or b"x", post=post)
    assert out[0][1] == f"all-schemes-monthly-portfolio---as-on-30th-september-{year}.xlsx" and len(got) == 1


def _frame(rows):
    import pandas as pd

    width = max(len(r) for r in rows)
    return pd.DataFrame([r + [None] * (width - len(r)) for r in rows])


SBI_HEADER = ["Name of the Instrument", "ISIN", "Industry / Rating", "Quantity", "Market Value", "% to Net Assets"]


def test_title_and_date_in_separate_cells_sbi_layout():
    from datetime import datetime

    from marketmyna.services import fund_holdings as fh

    df = _frame([[None, "SBI Mutual Fund", "007"], [None, "SCHEME NAME :", "SBI Large and Midcap Fund"],
                 [None, "PORTFOLIO STATEMENT AS ON :", datetime(2026, 9, 30)], [None] + SBI_HEADER,
                 [None, "HDFC Bank Ltd.", "INE040A01034", "Banks", 10, 100.0, 6.65],
                 [None, "GRAND TOTAL", None, None, None, None, 100]])
    s = fh.parse_sheet(df)
    assert s["scheme"] == "SBI Large and Midcap Fund" and s["as_of"] == "2026-09-30"


def test_stacked_schemes_are_split_uti_layout():
    from marketmyna.services import fund_holdings as fh

    def block(code, name, isin, stock):
        return [[f"SCHEME CODE{code}STARTS"], ["UTI MUTUAL FUND"], [f"SCHEME: {name}"],
                ["PROVISIONAL AND UNAUDITED PORTFOLIO DISCLOSURE AS OF 30/09/2026 (Market value in Lacs)"],
                ["NAME OF THE INSTRUMENT ", "RATING/INDUSTRY", "QUANTITY", "MARKET-VALUE", "% TO NAV", "ISIN"],
                [f"EQ - {stock}", "Banks", 10, 100.0, 5.5, isin], ["GRAND TOTAL", None, None, None, 100],
                [f"SCHEME CODE{code}ENDS"]]

    df = _frame(block("002", "UTI - Flexi Cap Fund.", "INE090A01021", "ICICI BANK LTD")
                + block("017", "UTI - Large Cap Fund", "INE040A01034", "HDFC BANK LIMITED"))
    parts = fh._split_stacked("EXPOSURE", df)
    assert [n for n, _ in parts] == ["EXPOSURE 002", "EXPOSURE 017"]
    schemes = [fh.parse_sheet(p) for _, p in parts]
    assert [s["scheme"] for s in schemes] == ["UTI - Flexi Cap Fund", "UTI - Large Cap Fund"]
    assert {s["as_of"] for s in schemes} == {"2026-09-30"}
    assert schemes[0]["holdings"][0]["name"] == "ICICI BANK LTD"


def test_month_day_comma_year_without_space():
    from marketmyna.services import fund_holdings as fh

    df = _frame([["RLMF001", "Nippon India Growth Mid Cap Fund (An open-ended equity scheme)"],
                 [None, "Monthly Portfolio Statement as on September 30,2026"],
                 [None, "ISIN", "Name of the Instrument", "Industry / Rating", "Quantity", "Market Value", "% to NAV"],
                 [None, "INE040A01034", "HDFC Bank Limited", "Banks", 10, 100.0, 3.0],
                 [None, "GRAND TOTAL", None, None, None, None, 100]])
    s = fh.parse_sheet(df)
    assert s["scheme"] == "Nippon India Growth Mid Cap Fund" and s["as_of"] == "2026-09-30"
