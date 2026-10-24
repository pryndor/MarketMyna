"""Investor checklists (marketmyna/services/investor_lenses.py), offline."""

from marketmyna.services import investor_lenses as il


def _fin(financial=False, **over):
    rows = {
        "income": {"revenue": [2000e6, 1800e6, 1600e6, 1500e6], "net_income": [300e6, 260e6, 230e6, 200e6],
                   "eps": [3.0, 2.6, 2.3, 2.0], "gross_profit": [1000e6, 880e6, 780e6, 720e6],
                   "operating_income": [400e6, 350e6, 300e6, 280e6], "interest_expense": [20e6, 20e6, 20e6, 20e6],
                   "ebitda": [500e6, 440e6, 380e6, 350e6]},
        "balance": {"equity": [1500e6, 1400e6, 1300e6, 1200e6], "current_assets": [900e6], "current_liabilities": [400e6],
                    "total_debt": [300e6], "cash": [400e6], "inventory": [100e6, 95e6], "ppe": [600e6]},
        "cashflow": {"operating_cf": [400e6, 350e6, 300e6, 280e6], "capex": [-80e6, -70e6, -60e6, -60e6],
                     "dividends": [-60e6, -50e6, -45e6, -40e6]},
    }
    for k, v in over.items():
        st, key = k.split("__")
        rows[st][key] = v
    return {"currency": "USD", "financial_sector": financial, "periods": ["2025", "2024", "2023", "2022"],
            **{st: {"rows": [{"key": k, "values": v} for k, v in r.items()]} for st, r in rows.items()}}


INFO = {"trailingPE": 12.0, "priceToBook": 1.5, "beta": 0.8, "currentPrice": 36.0, "fiftyTwoWeekHigh": 45.0,
        "dividendYield": 2.0, "sharesOutstanding": 100e6, "marketCap": 3600e6, "currency": "USD"}


def _lens(d, key):
    return next(l for l in d["lenses"] if l["key"] == key)


def _rule(lens, key):
    return next(r for r in lens["rules"] if r["key"] == key)


def test_sound_company_passes_most():
    d = il.evaluate(_fin(), INFO)
    g = _lens(d, "graham")
    assert _rule(g, "size")["pass"] and _rule(g, "current")["pass"] and _rule(g, "pe_pb")["pass"]
    assert _rule(g, "growth")["pass"] and "EPS" in _rule(g, "growth")["value"]
    lynch = _lens(d, "lynch")
    # EPS growth 14.5% a year, P/E 12: PEG 0.83; (14.5 + 2) / 12 = 1.37
    assert _rule(lynch, "peg")["pass"] and _rule(lynch, "adj_peg")["pass"]
    assert _rule(lynch, "net_cash")["pass"]  # cash 400m > debt 300m
    gb = _lens(d, "greenblatt")
    # EV = 3600 + 300 - 400 = 3500m; EBIT 400m -> 11.4%; capital 900-400+600 = 1100m -> 36%
    assert _rule(gb, "ey")["pass"] and _rule(gb, "roc")["pass"]
    m = _lens(d, "marks")
    assert _rule(m, "cover")["pass"] and _rule(m, "fallen")["pass"]  # 20% below the high
    assert all(l["tested"] <= l["total"] for l in d["lenses"])


def test_negative_working_capital_and_growth_fallback():
    d = il.evaluate(_fin(balance__current_assets=[300e6], income__eps=[None, None, None, None]), INFO)
    g = _lens(d, "graham")
    assert _rule(g, "debt_wc")["pass"] is False and _rule(g, "debt_wc")["value"] == "working capital negative"
    assert "net income" in _rule(g, "growth")["value"]


def test_banks_skip_balance_sheet_rules():
    d = il.evaluate(_fin(financial=True), INFO)
    assert _rule(_lens(d, "graham"), "current")["pass"] is None
    assert _lens(d, "greenblatt")["tested"] == 0 and "banks" in _lens(d, "greenblatt")["note"]
    assert _rule(_lens(d, "buffett"), "debt")["pass"] is None
