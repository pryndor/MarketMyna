"""Tests for market holidays / sessions and the exchange's stock events (offline)."""

from datetime import date

from marketmyna.services import calendar, nse_events
from marketmyna.services import market_calendar as mc

NSE = {"CM": [
    {"tradingDate": "20-Oct-2026", "description": "Dussehra"},
    {"tradingDate": "08-Nov-2026", "description": "Diwali Laxmi Pujan*"},
    {"tradingDate": "10-Nov-2026", "description": "Diwali-Balipratipada"},
    {"tradingDate": "24-Nov-2026", "description": "Prakash Gurpurb Sri Guru Nanak Dev"},
    {"tradingDate": "15-Aug-2026", "description": "Independence Day"},  # a Saturday
]}
HK = {"vcalendar": [{"vevent": [
    {"dtstart": ["20261019", {"value": "DATE"}], "summary": "The day following Chung Yeung Festival"},
    {"dtstart": ["20261225", {"value": "DATE"}], "summary": "Christmas Day"},
    {"dtstart": ["20270206", {"value": "DATE"}], "summary": "Lunar New Year's Day"},
    {"dtstart": ["20270208", {"value": "DATE"}], "summary": "The third day of Lunar New Year"},
    {"dtstart": ["20270209", {"value": "DATE"}], "summary": "The fourth day of Lunar New Year"},
]}]}
CN = {"days": [{"name": "国庆节、中秋节", "date": f"2026-10-0{d}", "isOffDay": True} for d in range(1, 8)]
      + [{"name": "国庆节、中秋节", "date": "2026-10-10", "isOffDay": False}]}


def test_nyse_rules():
    h = {r["date"]: r["name"] for r in mc.nyse_holidays(2026)}
    assert h["2026-07-03"] == "Independence Day" and h["2026-04-03"] == "Good Friday"
    assert h["2026-11-26"] == "Thanksgiving" and len(h) == 10
    assert "2027-12-31" not in {r["date"] for r in mc.nyse_holidays(2028)}  # Sat New Year's Day isn't made up
    early = [r["date"] for r in mc.nyse_early_closes(2026)]
    assert early == ["2026-11-27", "2026-12-24"]  # 3 Jul 2026 is the holiday itself


def test_india_closures_muhurat_and_expiry():
    closed, ev = mc.india_events(mc.parse_nse(NSE), date(2026, 10, 19), date(2026, 11, 30), [2026])
    got = {(e["date"], e["key"]): e for e in ev}
    assert "Dussehra" in got[("2026-10-20", "market_holiday")]["title"]
    assert "reopens Wed 21 Oct" in got[("2026-10-20", "market_holiday")]["note"]
    assert got[("2026-11-08", "special_session")]["title"] == "Muhurat trading (Diwali)"
    assert ("2026-08-15", "market_holiday") not in got  # weekend rows aren't closures
    # last Tuesday of Nov is a holiday: Nifty expiry moves to Monday
    nifty = [e["date"] for e in ev if e["title"] == "Nifty F&O monthly expiry"]
    assert nifty == ["2026-10-27", "2026-11-23"]


def test_china_golden_week_is_one_event():
    _, ev = mc.cn_events(mc.parse_cn(CN), date(2026, 9, 28), date(2026, 10, 12), [2026])
    closed = [e for e in ev if e["key"] == "market_holiday"]
    assert len(closed) == 1 and closed[0]["date"] == "2026-10-01"
    assert "Golden Week" in closed[0]["title"]
    assert "Closed Thu 1 Oct - Wed 7 Oct" in closed[0]["note"] and "reopens Thu 8 Oct" in closed[0]["note"]


def test_hong_kong_half_days_and_window_start():
    _, ev = mc.hk_events(mc.parse_hk(HK), date(2026, 10, 19), date(2027, 2, 10), [2026, 2027])
    halves = [(e["date"], e["title"]) for e in ev if e["key"] == "short_day"]
    assert halves == [("2026-12-24", "Hong Kong half day: Christmas Eve"),
                      ("2026-12-31", "Hong Kong half day: New Year's Eve"),
                      ("2027-02-05", "Hong Kong half day: Lunar New Year's Eve")]
    lny = next(e for e in ev if e["date"] == "2027-02-08" and e["key"] == "market_holiday")
    assert "reopens Wed 10 Feb" in lny["note"]


def test_collect_survives_a_dead_source(tmp_path, monkeypatch):
    from marketmyna.services import econ_calendar as ec

    monkeypatch.setattr(ec.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(ec, "_cache", {})

    def fetch(url):
        if "nseindia" in url:
            return NSE
        raise RuntimeError("blocked")

    out = mc.collect(date(2026, 10, 19), 45, fetch)
    keys = {(e["region"], e["key"]) for e in out["events"]}
    assert ("India", "market_holiday") in keys and ("US", "market_holiday") in keys  # US is computed
    assert ("US", "clock_change") in keys and ("Global", "index_rebalance") in keys
    assert any("hk_holidays" in w for w in out["warnings"])
    assert [e["days_away"] for e in out["events"]] == sorted(e["days_away"] for e in out["events"])


def test_nse_meetings_and_actions_parse():
    rows = [{"bm_symbol": "HINDUNILVR", "bm_date": "28-Oct-2026", "bm_purpose": "Board Meeting Intimation",
             "bm_desc": "to consider the Financial results ... and Dividend."},
            {"bm_symbol": "HINDUNILVR", "bm_date": "28-Oct-2026", "bm_purpose": "Financial Results/Dividend"},
            {"bm_symbol": "ABC", "bm_date": "02-Nov-2026", "bm_purpose": "Fund Raising/Other business matters"}]
    meetings = {m["symbol"]: m for m in nse_events.parse_meetings(rows)}
    assert meetings["HINDUNILVR"]["topics"] == ["results", "dividend"]
    assert meetings["ABC"]["topics"] == ["fund raising"]
    acts = nse_events.parse_actions([
        {"symbol": "MRPL", "exDate": "21-Oct-2026", "subject": "Interim Dividend - Rs 3 Per Share"},
        {"symbol": "XYZ", "exDate": "05-Nov-2026", "subject": "Face Value Split (Sub-Division) - From Rs 10 To Re 1"},
        {"symbol": "XYZ", "exDate": "-", "subject": "Bonus 1:1"}])
    assert [(a["symbol"], a["label"]) for a in acts] == [("MRPL", "Dividend"), ("XYZ", "Stock split")]


def test_exchange_dates_replace_yahoo_for_indian_stocks():
    cals = {"TATASTEEL.NS": {"earnings": date(2026, 11, 11), "eps_estimate": 2.78},
            "MRPL.NS": {"ex_dividend": date(2026, 10, 22)}, "AAPL": {"earnings": date(2026, 10, 30)}}
    data = {"meetings": [{"symbol": "TATASTEEL", "date": "2026-10-27", "topics": ["results"]},
                         {"symbol": "ABC", "date": "2026-10-28", "topics": ["fund raising"]},
                         {"symbol": "NOTMINE", "date": "2026-10-28", "topics": ["results"]}],
            "actions": [{"symbol": "MRPL", "date": "2026-10-21", "label": "Dividend",
                         "subject": "Interim Dividend - Rs 3 Per Share"},
                        {"symbol": "ABC", "date": "2026-11-05", "label": "Bonus issue", "subject": "Bonus 1:1"}]}
    symbols = {("TATASTEEL", "india"): ["P"], ("MRPL", "india"): ["W"], ("ABC", "india"): ["W"], ("AAPL", "us"): ["W"]}
    ev = calendar.collect(symbols, date(2026, 10, 19), 30, lambda t: cals.get(t, {}), exchange=lambda: data)
    got = [(e["symbol"], e["kind"], e["date"]) for e in ev]
    assert got == [("MRPL", "ex_dividend", "2026-10-21"), ("TATASTEEL", "earnings", "2026-10-27"),
                   ("ABC", "board_meeting", "2026-10-28"), ("AAPL", "earnings", "2026-10-30"),
                   ("ABC", "corporate_action", "2026-11-05")]
    tata = ev[1]
    assert tata["confirmed"] and tata["eps_estimate"] == 2.78 and tata["detail"] == "Board meeting: results"
    assert ev[4]["label"] == "Bonus issue"


def test_digest_has_markets_section():
    text = calendar.digest([], [
        {"kind": "market", "key": "market_holiday", "title": "India market closed: Dussehra", "days_away": 1,
         "date": "2026-10-20", "note": "Closed Tue 20 Oct (NSE / BSE); reopens Wed 21 Oct.", "exposure": ["TCS"]},
        {"kind": "central_bank", "title": "Fed rate decision", "region": "US", "days_away": 9, "date": "2026-10-28"}])
    assert "🏛 Markets\n• India market closed: Dussehra: tomorrow" in text
    assert "Your stocks there: TCS" in text
    assert "🌐 Economic calendar\n• Fed rate decision (US)" in text
