"""Tests for the economic calendar parsers and merge (offline)."""

from datetime import date

from marketmyna.services import econ_calendar as ec

FED = """
<h4>2026 FOMC Meetings</h4>
<div class="fomc-meeting__month"><strong>October</strong></div><div class="fomc-meeting__date">27-28</div>
<div class="fomc-meeting__month"><strong>Dec</strong></div><div class="fomc-meeting__date">8-9*</div>
<h4>2027 FOMC Meetings</h4>
<div class="fomc-meeting__month"><strong>Apr/May</strong></div><div class="fomc-meeting__date">30-1</div>
<div class="fomc-meeting__month"><strong>March</strong></div><div class="fomc-meeting__date">(notation vote)</div>
"""

RBI = """<td>Meeting Schedule of the Monetary Policy Committee for 2026-2027</td>
<td>October 5, 6 and 7, 2026</td><td>December 2, 3 and 4, 2026</td>
<td>Monetary Policy Press Conference: August 5, 2026 (Wednesday)</td>
<td>Monetary Policy Committee Meeting, August 3 to 5, 2026</td><td>MPC August 3 to 5, 2026</td>"""

FRED = """
<span style="font-weight: bold;">Wednesday October 14, 2026</span></td></tr>
<tr><td nowrap style="width:5%">  7:30 am  </td><td text-align="left"><a href="/release?rid=10">Consumer Price Index</a></td></tr>
<span style="font-weight: bold;">Tuesday November 10, 2026</span></td></tr>
<tr><td nowrap style="width:5%">  7:30 am  </td><td text-align="left"><a href="/release?rid=10">Consumer Price Index</a></td></tr>
"""


def test_parse_fed():
    ev = ec.parse_fed(FED)
    assert [(e["date"], e["title"]) for e in ev] == [
        ("2026-10-28", "Fed rate decision"),
        ("2026-12-09", "Fed rate decision + projections"),
        ("2027-05-01", "Fed rate decision"),  # Apr/May 30-1 ends in May
    ]
    assert ev[0]["tz"] == "America/New_York" and ev[0]["time"] == "14:00"


def test_parse_rbi_dedupes_and_skips_single_dates():
    assert [e["date"] for e in ec.parse_rbi(RBI)] == ["2026-10-07", "2026-12-04", "2026-08-05"]


def test_parse_fred_times():
    ev = ec.parse_fred(FRED, 10)
    assert [(e["date"], e["time"], e["tz"]) for e in ev] == [
        ("2026-10-14", "07:30", "America/Chicago"), ("2026-11-10", "07:30", "America/Chicago")]
    assert ev[0]["title"] == "US inflation (CPI)"


def test_india_rules_shift_off_weekends():
    ev = ec.india_releases(date(2026, 11, 1), date(2026, 12, 31))
    assert [(e["date"], e["title"]) for e in ev] == [
        ("2026-11-12", "India inflation (CPI)"), ("2026-11-30", "India GDP"),
        ("2026-12-14", "India inflation (CPI)")]  # 12 Dec 2026 is a Saturday
    assert all(e["estimated"] for e in ev)


def test_local_time_conversion():
    e = {"date": "2026-10-14", "time": "07:30", "tz": "America/Chicago"}
    assert ec.local_time(e, "Asia/Kolkata") == "18:00"
    late = {"date": "2026-10-28", "time": "14:00", "tz": "America/New_York"}
    assert ec.local_time(late, "Asia/Kolkata") == "23:30"
    assert ec.local_time({"date": "2026-10-28", "time": "20:00", "tz": "America/New_York"}, "Asia/Kolkata") == "05:30 (+1d)"


def test_collect_merges_and_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(ec.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ec, "_cache", {})
    pages = {ec.FED_URL: FED, ec.RBI_URL: RBI}

    def fetch(url):
        if url in pages:
            return pages[url]
        return FRED if "rid=10&" in url else ""

    out = ec.collect(date(2026, 10, 1), 45, fetch)
    titles = [e["title"] for e in out["events"]]
    assert titles[:3] == ["RBI rate decision", "India inflation (CPI)", "US inflation (CPI)"]
    assert "Fed rate decision" in titles
    assert out["events"][0]["days_away"] == 6
    assert any("fred_9" in w for w in out["warnings"])  # empty page -> unavailable

    monkeypatch.setattr(ec, "_cache", {})
    blocked = ec.collect(date(2026, 10, 1), 45, lambda url: (_ for _ in ()).throw(RuntimeError("403")))
    assert "Fed rate decision" in [e["title"] for e in blocked["events"]]  # served from saved copy
    assert any("last saved" in w for w in blocked["warnings"])


def test_reminder_digest_includes_economy():
    from marketmyna.services.calendar import digest

    text = digest([], [{"title": "RBI rate decision", "region": "India", "days_away": 1, "date": "2026-10-07",
                        "local_time": "10:00"}])
    assert "Economic calendar" in text and "RBI rate decision (India): tomorrow 10:00" in text


def _monthly(values, start="2025-01-01"):
    import pandas as pd

    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float)


def test_readings_lines():
    cpi = _monthly([100 + i for i in range(14)])  # Feb 2026 / Feb 2025 = 113/101
    jobs = _monthly([1000, 1100, 1150])
    out = ec.readings(fetch=lambda sid, start: {"CPIAUCSL": cpi, "PAYEMS": jobs, "UNRATE": _monthly([4.1, 4.2])}.get(sid),
                      rbi=lambda: "Repo rate now 5.50%", use_cache=False)
    assert out["us_cpi"].startswith("11.9% YoY in Feb, down from 12.0%")
    assert out["us_jobs"] == "+50k jobs in Mar (before: +100k), unemployment 4.2%"
    assert out["rbi"] == "Repo rate now 5.50%"
    assert "us_gdp" not in out  # missing series just drops out


def test_enrich_adds_context_and_exposure():
    events = [{"title": "Fed rate decision + projections", "region": "US"},  # an old saved event without a key
              {"key": "in_cpi", "title": "India inflation (CPI)", "region": "India"}]
    followed = {("TSLA", "us"): [], ("GOOGL", "us"): [], ("TCS", "india"): []}
    ec.enrich(events, followed, read=lambda: {"fed": "Target range now 3.75-4.00%"})
    assert events[0]["key"] == "fed" and events[0]["last"].startswith("Target range")
    assert events[0]["exposure"] == ["GOOGL", "TSLA"] and "cut" in events[0]["why"]
    assert events[1]["last"] is None and events[1]["exposure"] == ["TCS"]


def test_reminder_digest_explains_economy():
    from marketmyna.services.calendar import digest

    text = digest([], [{"title": "US inflation (CPI)", "region": "US", "days_away": 0, "date": "2026-10-14",
                        "local_time": "18:00", "last": "3.7% YoY in Aug", "why": "Hot print delays cuts.",
                        "exposure": ["A", "B", "C", "D", "E"]}])
    assert "Last: 3.7% YoY in Aug" in text and "Why it matters: Hot print" in text
    assert "Your US stocks: A, B, C, D +1 more" in text


def test_covers_and_verdict():
    assert ec.covers("us_cpi", date(2026, 10, 14)) == date(2026, 9, 1)
    assert ec.covers("us_jobs", date(2027, 1, 8)) == date(2026, 12, 1)
    assert ec.covers("us_gdp", date(2026, 10, 29)) == date(2026, 7, 1)
    assert ec.covers("us_gdp", date(2027, 1, 28)) == date(2026, 10, 1)
    assert ec.verdict("us_cpi", 3.9, 3.7).startswith("Hotter")
    assert ec.verdict("us_cpi", 3.5, 3.7).startswith("Cooler")
    assert ec.verdict("us_jobs", 29, 133).startswith("Weak")


def test_results_only_after_release_and_new_period():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    cpi = {"key": "us_cpi", "title": "US inflation (CPI)", "region": "US", "date": "2026-10-14",
           "time": "07:30", "tz": "America/Chicago"}
    gdp_rev = {"key": "us_gdp", "title": "US GDP", "region": "US", "date": "2026-11-25",
               "time": "07:30", "tz": "America/Chicago"}
    old = {"us_cpi": {"text": "3.7% YoY in Aug", "period": "2026-08-01", "value": 3.7, "prev": 3.5}}
    new = {"us_cpi": {"text": "3.9% YoY in Sep", "period": "2026-09-01", "value": 3.9, "prev": 3.7},
           "us_gdp": {"text": "2.8% in Q3", "period": "2026-07-01", "value": 2.8, "prev": 2.2}}
    ct = ZoneInfo("America/Chicago")
    asked = []

    def pts(data):
        return lambda: asked.append(1) or data

    assert ec.results([cpi], datetime(2026, 10, 14, 7, 40, tzinfo=ct), pts(new)) == [] and not asked  # inside grace
    assert ec.results([cpi], datetime(2026, 10, 14, 8, 0, tzinfo=ct), pts(old)) == []  # FRED not updated yet
    out = ec.results([cpi], datetime(2026, 10, 14, 8, 0, tzinfo=ct), pts(new))
    assert out[0]["result"] == "3.9% YoY in Sep" and out[0]["verdict"].startswith("Hotter")
    assert ec.results([gdp_rev], datetime(2026, 11, 25, 9, 0, tzinfo=ct), pts(new)) == []  # revision, not news
