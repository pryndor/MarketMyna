"""The DCF as an Excel workbook with live formulas, so the model can be
audited and changed outside MarketMyna.

Follows the model-builder conventions of anthropics/financial-services
(Apache-2.0): every calculation cell is a formula, never a typed number;
inputs are blue and labelled with their source or as an assumption; a check
row flags an impossible set-up; a sensitivity grid recomputes the value per
share for other discount and terminal rates (plain formulas, no Excel data
table, so LibreOffice and Google Sheets read it too).

Same two-stage model as services/dcf.py and frontend/src/lib/dcf.ts: free
cash flow grows at the chosen rate for 5 years, fades in a straight line to
the terminal rate by year 10, then a Gordon-growth terminal value.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BLUE = Font(color="1F4FBF")  # inputs
BOLD = Font(bold=True)
HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="2F3E57")
KEY_FILL = PatternFill("solid", fgColor="EAF1FB")
MONEY = '#,##0;[Red]-#,##0'
PER_SHARE = '#,##0.00;[Red]-#,##0.00'
PCT = '0.0%'

YEARS = 10
HIGH = 5
COLS = [get_column_letter(c) for c in range(3, 3 + YEARS)]  # C..L = years 1..10


def _row(ws, r: int, label: str, value, fmt: Optional[str] = None, note: str = "", font=None):
    ws.cell(r, 1, label)
    c = ws.cell(r, 2, value)
    if fmt:
        c.number_format = fmt
    if font:
        c.font = font
    if note:
        ws.cell(r, 3, note).font = Font(italic=True, color="666666")
    return c


def _grid_formula(w: str, t: str, high: str) -> str:
    """Value per share at discount w and terminal growth t: years 1-5 are as
    projected; years 6-10 fade to *this* terminal rate (as the page's sliders
    do), then the terminal value."""
    pv = [f"SUMPRODUCT($C$16:${high}$16/(1+{w})^$C$14:${high}$14)"]
    flow = f"${high}$16"
    fade = YEARS - HIGH
    for k in range(1, fade + 1):
        flow = f"{flow}*(1+$B$7+({t}-$B$7)*{k}/{fade})"
        pv.append(f"{flow}/(1+{w})^{HIGH + k}")
    pv.append(f"{flow}*(1+{t})/({w}-{t})/(1+{w})^{YEARS}")
    return f"=IF({w}>{t},({'+'.join(pv)}+$B$10)/$B$11,\"n/a\")"


def build(data: dict, growth: Optional[float] = None, discount: Optional[float] = None,
          terminal: Optional[float] = None) -> bytes:
    """data: services/dcf.build() output with a "dcf" block. Rates default to the page's defaults."""
    d = data.get("dcf")
    if not d:
        raise ValueError(data.get("note") or "No DCF for this stock")
    dflt = d["defaults"]
    growth = dflt["growth"] if growth is None else growth
    discount = dflt["discount"] if discount is None else discount
    terminal = dflt["terminal"] if terminal is None else terminal
    ccy = data.get("currency") or ""

    wb = Workbook()
    ws = wb.active
    ws.title = "DCF"
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 20
    for col in COLS:
        ws.column_dimensions[col].width = 15

    ws["A1"] = f"{data.get('name') or data['symbol']} ({data['symbol']}) - discounted cash flow"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = (f"Built by MarketMyna on {date.today().isoformat()} from {data.get('source', 'company filings')}. "
                f"Amounts in {ccy}. Blue cells are inputs: change them and everything recalculates.")
    ws["A3"] = "A model, not a forecast or a recommendation: the result is only as good as the assumptions."
    ws["A3"].font = Font(italic=True, color="666666")

    # ---------------------------------------------------------------- inputs (rows 5-11)
    ws["A5"] = "Inputs"
    ws["A5"].font = BOLD
    conv = f", converted from {d['converted_from']}" if d.get("converted_from") else ""
    _row(ws, 6, f"Base free cash flow ({ccy})", d["base_fcf"], MONEY,
         f"Operating cash flow minus capex and stock-based compensation, {d.get('base_label', 'latest year')}{conv}", BLUE)
    _row(ws, 7, f"Growth a year, years 1-{HIGH}", growth, PCT,
         "[ASSUMPTION] page default = recent revenue growth, capped 0-15%", BLUE)
    _row(ws, 8, "Discount rate", discount, PCT, "[ASSUMPTION] the return you require a year", BLUE)
    _row(ws, 9, "Terminal growth", terminal, PCT, "[ASSUMPTION] growth a year after year 10, for ever", BLUE)
    _row(ws, 10, f"Net cash: cash and investments minus debt ({ccy})", d["net_cash"], MONEY,
         "Latest balance sheet: cash, short-term and long-term investments, minus total debt", BLUE)
    _row(ws, 11, "Shares outstanding", d["shares"], '#,##0', "Market data feed", BLUE)
    _row(ws, 12, f"Share price ({ccy})", data.get("price"), PER_SHARE, "Market data feed, when the model was built", BLUE)

    # ---------------------------------------------------------------- projection (rows 14-18)
    ws["A14"] = "Year"
    ws["A15"] = "Growth"
    ws["A16"] = f"Free cash flow ({ccy})"
    ws["A17"] = "Discount factor"
    ws["A18"] = f"Present value ({ccy})"
    for c in ("A14", "A15", "A16", "A17", "A18"):
        ws[c].font = BOLD
    ws["A14"].font, ws["A14"].fill = HEAD, HEAD_FILL
    for i, col in enumerate(COLS, start=1):
        head = ws[f"{col}14"]
        head.value, head.font, head.fill = i, HEAD, HEAD_FILL
        head.alignment = Alignment(horizontal="center")
        if i <= HIGH:
            ws[f"{col}15"] = "=$B$7"
        else:  # straight-line fade to the terminal rate by year 10
            ws[f"{col}15"] = f"=$B$7+($B$9-$B$7)*({col}$14-{HIGH})/({YEARS}-{HIGH})"
        prev = "$B$6" if i == 1 else f"{COLS[i - 2]}16"
        ws[f"{col}16"] = f"={prev}*(1+{col}15)"
        ws[f"{col}17"] = f"=1/(1+$B$8)^{col}$14"
        ws[f"{col}18"] = f"={col}16*{col}17"
        ws[f"{col}15"].number_format = PCT
        ws[f"{col}16"].number_format = MONEY
        ws[f"{col}17"].number_format = '0.0000'
        ws[f"{col}18"].number_format = MONEY
    last = COLS[-1]

    # ---------------------------------------------------------------- valuation (rows 20-28)
    ws["A20"] = "Valuation"
    ws["A20"].font = BOLD
    _row(ws, 21, "Present value, years 1-10", f"=SUM(C18:{last}18)", MONEY)
    _row(ws, 22, "Terminal value at year 10", f"={last}16*(1+$B$9)/($B$8-$B$9)", MONEY, "Gordon growth")
    _row(ws, 23, "Present value of the terminal value", f"=B22*{last}17", MONEY)
    _row(ws, 24, "Enterprise value", "=B21+B23", MONEY)
    _row(ws, 25, "Equity value (+ net cash)", "=B24+B10", MONEY)
    v = _row(ws, 26, f"Value per share ({ccy})", "=B25/B11", PER_SHARE, font=BOLD)
    v.fill = KEY_FILL
    _row(ws, 27, "Price against the value", "=IF(B26>0,B12/B26-1,\"n/a\")", PCT,
         "Above 0 = the price is higher than this value")
    _row(ws, 28, "Terminal value share of the total", "=B23/(B21+B23)", PCT,
         "Above ~75%: the answer rests mostly on the far future")
    _row(ws, 29, "Check", "=IF($B$8>$B$9,\"OK\",\"Discount rate must be above terminal growth\")")

    # ---------------------------------------------------------------- sensitivity (rows 31-38)
    ws["A31"] = f"Value per share ({ccy}): discount rate (rows) x terminal growth (columns)"
    ws["A31"].font = BOLD
    steps = (-0.01, -0.005, 0.0, 0.005, 0.01)
    ws["B32"] = "Disc. \\ term."
    ws["B32"].font = HEAD
    ws["B32"].fill = HEAD_FILL
    tcols = COLS[:len(steps)]
    for col, step in zip(tcols, steps):
        c = ws[f"{col}32"]
        c.value = f"=$B$9+{step}" if step else "=$B$9"
        c.number_format, c.font, c.fill = PCT, HEAD, HEAD_FILL
    high = COLS[HIGH - 1]  # year 5: the last cash flow the rates don't change
    for r, step in enumerate((-0.02, -0.01, 0.0, 0.01, 0.02), start=33):
        w = ws[f"B{r}"]
        w.value = f"=$B$8+{step}" if step else "=$B$8"
        w.number_format, w.font, w.fill = PCT, HEAD, HEAD_FILL
        for col in tcols:
            cell = ws[f"{col}{r}"]
            cell.value = _grid_formula(f"$B{r}", f"{col}$32", high)
            cell.number_format = PER_SHARE
            if step == 0 and col == tcols[2]:
                cell.fill, cell.font = KEY_FILL, BOLD

    # ---------------------------------------------------------------- history sheet
    hs = wb.create_sheet("History")
    hs.column_dimensions["A"].width = 16
    hs.column_dimensions["B"].width = 22
    hs["A1"] = "Year ending"
    hs["B1"] = f"Free cash flow ({ccy})"
    for c in ("A1", "B1"):
        hs[c].font, hs[c].fill = HEAD, HEAD_FILL
    for i, (period, value) in enumerate(zip(data.get("periods") or [], d.get("fcf_history") or []), start=2):
        hs.cell(i, 1, period)
        cell = hs.cell(i, 2, value)
        cell.number_format, cell.font = MONEY, BLUE
    hs.cell(len(d.get("fcf_history") or []) + 3, 1,
            f"Source: {data.get('source', 'company filings')}. Operating cash flow minus capital expenditure "
            "and stock-based compensation.")

    ws.freeze_panes = "B5"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
