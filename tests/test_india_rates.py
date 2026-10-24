"""Tests for RBI / IBJA scraping and the stale fallback (offline)."""

import html
import json

import pytest

from src.services import india_rates as ir

RBI = """
<h3>Policy&nbsp; Rates</h3><table>
<tr><th> Policy Repo Rate </th><td> : 5.25% </td></tr>
<tr><th>Standing Deposit Facility Rate</th><td>: 5.00%</td></tr>
<tr><th>CRR</th><td>: 3.00%</td></tr>
<tr><th>INR / 1 USD</th><td>: 95.9927</td></tr>
<tr><th>INR / 100 JPY</th><td>: 60.6700</td></tr></table>
<p>(As at 1.00pm of October 01, 2026)</p>
<h3>Call Rates</h3><span>: 4.60% - 5.30% *</span>
<p>Government Securities Market</p><table>
<tr><th>6.94% GS 2036</th><td>: 7.1775% #</td></tr>
<tr><th>6.20% GS 2029</th><td>: 6.6705% #</td></tr>
<tr><th>91 day T-bills</th><td>: 5.5199%*</td></tr>
<tr><th>364 day T-bills</th><td>: 6.1798%*</td></tr></table>
<p>as on September 30, 2026</p>
"""

GOLD_JSON = html.escape(json.dumps({"labels": ["29/09/2026", "30/09/2026"], "purity999": [147667, 147888]}), quote=True)
IBJA = f"""
<span id="lblGold999_AM">148687</span><span id="lblGold999_PM"></span>
<span id="lblSilver999_AM">221954</span><span id="lblSilver999_PM">222100</span>
<input type="hidden" id="HdnGold" value="{GOLD_JSON}" />
"""


def test_parse_rbi():
    r = ir.parse_rbi(RBI)
    pol = {p["key"]: p["value"] for p in r["policy"]}
    assert pol == {"repo": 5.25, "sdf": 5.0, "crr": 3.0}
    assert r["call_rate"] == {"low": 4.6, "high": 5.3}
    assert {f["pair"]: f["per"] for f in r["fx"]} == {"USD/INR": 1, "JPY/INR": 100}
    assert r["fx_as_of"] == "October 01, 2026" and r["gsec_as_of"] == "September 30, 2026"
    labels = [p["label"] for p in r["curve"]]
    assert labels == ["91D", "364D", "2029", "2036"]  # sorted by maturity
    assert r["curve"][-1]["yield"] == pytest.approx(7.1775)


def test_parse_rbi_rejects_unknown_layout():
    with pytest.raises(ValueError):
        ir.parse_rbi("<html>maintenance</html>")


def test_parse_ibja_latest_session_and_change():
    d = ir.parse_ibja(IBJA)
    gold = next(i for i in d["items"] if i["key"] == "gold_999")
    silver = next(i for i in d["items"] if i["key"] == "silver_999")
    assert gold["latest"] == 148687 and gold["session"] == "AM"
    assert silver["latest"] == 222100 and silver["session"] == "PM"
    assert gold["change_pct"] == pytest.approx((148687 / 147888 - 1) * 100)
    assert d["history"]["gold_999"][-1] == {"date": "2026-09-30", "value": 147888.0}


def test_ibja_falls_back_to_history_before_morning_fix():
    page = f'<span id="lblGold999_AM"></span><input type="hidden" id="HdnGold" value="{GOLD_JSON}" />'
    d = ir.parse_ibja(page)
    assert d["items"][0]["latest"] == 147888 and d["as_of"] == "2026-09-30"


def test_build_serves_stale_copy_when_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(ir.Path, "home", lambda: tmp_path)
    ok = {ir.RBI_URL: RBI, ir.IBJA_URL: IBJA}
    first = ir.build(lambda url: ok[url], use_cache=False)
    assert not first["rbi"]["stale"] and not first["ibja"]["stale"]
    assert ir.history("rbi")  # daily snapshot written

    def blocked(url):
        raise RuntimeError("403")
    again = ir.build(blocked, use_cache=False)
    assert again["rbi"]["stale"] and again["rbi"]["policy"][0]["value"] == 5.25
    assert "Live fetch failed" in again["rbi"]["error"]


def test_build_without_any_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(ir.Path, "home", lambda: tmp_path)
    out = ir.build(lambda url: (_ for _ in ()).throw(RuntimeError("down")), use_cache=False)
    assert out["ibja"]["stale"] and "unavailable" in out["ibja"]["error"]
