"""Market calendar: the days the exchanges we cover are shut, trade short or
hold a special session, plus the market-wide dates that move everything
(derivatives expiry, index reviews, US clock changes).

- India: NSE's trading holiday list (the official one, for the current
  year); a "*" on Diwali Laxmi Pujan marks the Muhurat trading session.
  Monthly expiries follow the exchange rules (Nifty: last Tuesday, Sensex:
  last Thursday, a day earlier if that is a holiday).
- US: NYSE holiday and early-close rules, computed.
- Hong Kong: the government's general holiday list (HKEX shuts on every one),
  half-day sessions on the eves of Christmas, New Year and Lunar New Year.
- China A: the State Council holiday schedule; Shanghai / Shenzhen shut on
  every weekday off day (make-up working weekends don't trade).

Consecutive closed days become one event ("closed Thu 1 - Wed 7 Oct,
reopens Thu 8 Oct"). Each source goes through econ_calendar's cache with a
saved copy on disk, so a failed fetch serves the last good list.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Callable, Optional

logger = logging.getLogger(__name__)

NSE_HOLIDAYS_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
HK_HOLIDAYS_URL = "https://www.1823.gov.hk/common/ical/en.json"
CN_HOLIDAYS_URL = "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Referer": "https://www.nseindia.com/",
    "Accept": "application/json, text/plain, */*",
}

# region -> its exchanges
MARKETS = {
    "India": "NSE / BSE",
    "US": "NYSE / Nasdaq",
    "Hong Kong": "HKEX",
    "China": "Shanghai / Shenzhen",
}

CLOSED_WHY = {
    "India": "NSE and BSE are shut: no trading or settlement, and anything due that day (F&O expiry, SIP "
             "purchases) moves to a nearby working day.",
    "US": "NYSE and Nasdaq are shut, so US prices don't move; global markets often trade thin and quiet.",
    "Hong Kong": "HKEX is shut, and Stock Connect trading between Hong Kong and the mainland is off too.",
    "China": "Shanghai and Shenzhen are shut and Stock Connect pauses. Hong Kong often moves for the mainland "
             "while it is away, and the mainland catches up when it reopens.",
}

# State Council holiday names -> English
CN_NAMES = {"元旦": "New Year", "春节": "Spring Festival", "清明": "Qingming", "劳动": "Labour Day",
            "端午": "Dragon Boat Festival", "中秋": "Mid-Autumn Festival", "国庆": "National Day (Golden Week)"}

FetchJson = Callable[[str], object]


def _get_json(url: str) -> object:
    import requests

    r = requests.get(url, headers=NSE_HEADERS if "nseindia" in url else {"User-Agent": NSE_HEADERS["User-Agent"]},
                     timeout=25)
    r.raise_for_status()
    return json.loads(r.content.decode("utf-8-sig"))


# ------------------------------------------------------------------ sources


def parse_nse(data: dict) -> list[dict]:
    """[{date, name, muhurat}] from NSE's holiday master (cash market list)."""
    out = []
    for row in (data or {}).get("CM", []):
        try:
            day = datetime.strptime(row["tradingDate"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        name = (row.get("description") or "").strip()
        out.append({"date": day.isoformat(), "name": name.rstrip("*").strip(),
                    "muhurat": name.endswith("*") or "laxmi pujan" in name.lower()})
    return out


def parse_hk(data: dict) -> list[dict]:
    out = []
    for cal in (data or {}).get("vcalendar", []):
        for e in cal.get("vevent", []):
            try:
                day = datetime.strptime(str(e["dtstart"][0]), "%Y%m%d").date()
            except (KeyError, IndexError, ValueError):
                continue
            out.append({"date": day.isoformat(), "name": e.get("summary") or "Public holiday"})
    return out


def parse_cn(data: dict) -> list[dict]:
    out = []
    for row in (data or {}).get("days", []):
        if row.get("isOffDay"):
            raw = row.get("name") or ""
            name = next((en for cn, en in CN_NAMES.items() if cn in raw), raw or "Public holiday")
            if "国庆" in raw and "中秋" in raw:
                name = "National Day / Mid-Autumn (Golden Week)"
            out.append({"date": row["date"], "name": name})
    return out


def _easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    return date(year, month, (h + l_ - 7 * m + 114) % 31 + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday (0 = Monday) of the month; n = -1 for the last one."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    d = _month_end(year, month)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _month_end(year: int, month: int) -> date:
    return (date(year + (month == 12), month % 12 + 1, 1)) - timedelta(days=1)


def _observed(d: date) -> date:
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


def nyse_holidays(year: int) -> list[dict]:
    """NYSE full-day closures (Rule 7.2: a Saturday holiday moves to Friday,
    a Sunday one to Monday; New Year's Day on a Saturday isn't made up)."""
    days = [
        (date(year, 1, 1), "New Year's Day"),
        (_nth_weekday(year, 1, 0, 3), "Martin Luther King Jr. Day"),
        (_nth_weekday(year, 2, 0, 3), "Washington's Birthday"),
        (_easter(year) - timedelta(days=2), "Good Friday"),
        (_nth_weekday(year, 5, 0, -1), "Memorial Day"),
        (date(year, 6, 19), "Juneteenth"),
        (date(year, 7, 4), "Independence Day"),
        (_nth_weekday(year, 9, 0, 1), "Labor Day"),
        (_nth_weekday(year, 11, 3, 4), "Thanksgiving"),
        (date(year, 12, 25), "Christmas"),
    ]
    out = []
    for d, name in days:
        if d.month == 1 and d.day == 1 and d.weekday() == 5:
            continue
        out.append({"date": _observed(d).isoformat(), "name": name})
    return out


def nyse_early_closes(year: int) -> list[dict]:
    """1 pm closes: 3 July (when the 4th is a Tuesday-Friday), the day after
    Thanksgiving and Christmas Eve (Monday-Thursday)."""
    out = []
    jul3 = date(year, 7, 3)
    if jul3.weekday() <= 3:
        out.append({"date": jul3.isoformat(), "name": "Independence Day eve"})
    out.append({"date": (_nth_weekday(year, 11, 3, 4) + timedelta(days=1)).isoformat(), "name": "Day after Thanksgiving"})
    eve = date(year, 12, 24)
    if eve.weekday() <= 3:
        out.append({"date": eve.isoformat(), "name": "Christmas Eve"})
    return out


# ------------------------------------------------------------------ building events


class Closed:
    """Which weekdays a market is shut, with the holiday names."""

    def __init__(self, days: dict[date, str]):
        self.days = days

    def trading(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.days

    def next_open(self, d: date) -> date:
        d += timedelta(days=1)
        while not self.trading(d):
            d += timedelta(days=1)
        return d

    def on_or_before(self, d: date) -> date:
        while not self.trading(d):
            d -= timedelta(days=1)
        return d

    def on_or_after(self, d: date) -> date:
        while not self.trading(d):
            d += timedelta(days=1)
        return d

    def runs(self) -> list[tuple[date, date, list[str]]]:
        """Consecutive closures (weekends in between don't break a run)."""
        out: list[tuple[date, date, list[str]]] = []
        for d in sorted(self.days):
            if out and self.next_open(out[-1][1]) > d:
                first, _, names = out[-1]
                out[-1] = (first, d, names + ([self.days[d]] if self.days[d] not in names else []))
            else:
                out.append((d, d, [self.days[d]]))
        return out


def _fmt(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _event(key: str, day: date, title: str, region: str, note: str, why: str, source: str,
           importance: str = "high", time_str: Optional[str] = None, tz: Optional[str] = None,
           estimated: bool = False) -> dict:
    from .econ_calendar import _event as base

    return {**base(key, day, title, region, "market", importance, note, source, time_str, tz, estimated), "why": why}


def closure_events(region: str, closed: Closed, start: date, end: date, source: str) -> list[dict]:
    out = []
    for first, last, names in closed.runs():
        if last < start or first > end:
            continue
        span = f"Closed {_fmt(first)}" + (f" - {_fmt(last)}" if last != first else "")
        out.append(_event("market_holiday", max(first, start), f"{region} market closed: {' / '.join(names)}", region,
                          f"{span} ({MARKETS[region]}); reopens {_fmt(closed.next_open(last))}.",
                          CLOSED_WHY[region], source))
    return out


def india_events(rows: list[dict], start: date, end: date, years: list[int]) -> tuple[Closed, list[dict]]:
    closed = Closed({date.fromisoformat(r["date"]): r["name"] for r in rows
                     if date.fromisoformat(r["date"]).weekday() < 5})
    out = closure_events("India", closed, start, end, "NSE holiday list")
    for r in rows:
        d = date.fromisoformat(r["date"])
        if r.get("muhurat") and start <= d <= end:
            out.append(_event("special_session", d, "Muhurat trading (Diwali)", "India",
                              "A one-hour evening session for the new Samvat year; NSE and BSE give the exact time "
                              "in a circular a few weeks before.",
                              "A token, usually upbeat session: many investors buy a few shares for luck. Volumes are "
                              "thin, so moves are small and rarely say much about the year ahead.",
                              "NSE holiday list"))
    for y in years:
        budget = date(y, 2, 1)
        if start <= budget <= end:
            out.append(_event("special_session", budget, "Union Budget", "India",
                              "The Finance Minister presents the budget around 11:00 IST; when it falls on a weekend "
                              "the exchanges usually hold a special session.",
                              "Tax, spending and borrowing plans for the year: the biggest scheduled day for "
                              "Indian stocks, with big swings in PSU, infra, defence, rail and consumer names.",
                              "Usual schedule (1 February)", time_str="11:00", tz="Asia/Kolkata", estimated=True))
        for m in range(1, 13):
            nifty = closed.on_or_before(_nth_weekday(y, m, 1, -1))
            sensex = closed.on_or_before(_nth_weekday(y, m, 3, -1))
            for d, title, note in ((nifty, "Nifty F&O monthly expiry", "NSE monthly futures and options (Nifty, Bank "
                                    "Nifty, stock F&O) expire at 15:30 IST."),
                                   (sensex, "Sensex F&O monthly expiry", "BSE monthly Sensex / Bankex contracts expire "
                                    "at 15:30 IST.")):
                if start <= d <= end:
                    out.append(_event("expiry", d, title, "India", note,
                                      "Traders roll or close positions, so the last hour can swing hard, especially "
                                      "in stocks with big F&O open interest.", "Exchange expiry rules",
                                      importance="medium", time_str="15:30", tz="Asia/Kolkata"))
    return closed, out


def us_events(start: date, end: date, years: list[int]) -> tuple[Closed, list[dict]]:
    rows = [r for y in years for r in nyse_holidays(y)]
    closed = Closed({date.fromisoformat(r["date"]): r["name"] for r in rows})
    out = closure_events("US", closed, start, end, "NYSE holiday rules")
    for y in years:
        for r in nyse_early_closes(y):
            d = date.fromisoformat(r["date"])
            if start <= d <= end and closed.trading(d):
                out.append(_event("short_day", d, f"US early close: {r['name']}", "US",
                                  "NYSE and Nasdaq close at 13:00 New York time (bond market at 14:00).",
                                  "Half a session with light volume; the time shown is the close in your timezone.",
                                  "NYSE holiday rules", importance="medium", time_str="13:00", tz="America/New_York"))
        for m in range(1, 13):
            d = closed.on_or_before(_nth_weekday(y, m, 4, 3))
            if not (start <= d <= end):
                continue
            if m in (3, 6, 9, 12):
                out.append(_event("expiry", d, "US quad witching + S&P rebalance", "US",
                                  "Quarterly stock and index futures and options expire; S&P 500 and Nasdaq-100 "
                                  "index changes take effect at the close.",
                                  "One of the heaviest volume days of the year: index funds buy added stocks and "
                                  "sell removed ones at the close, and prices can jump around the expiry.",
                                  "Exchange expiry rules", time_str="16:00", tz="America/New_York"))
            else:
                out.append(_event("expiry", d, "US monthly options expiry", "US",
                                  "Monthly stock and index options expire (third Friday).",
                                  "Big option positions can pin prices near popular strikes and lift volume.",
                                  "Exchange expiry rules", importance="medium", time_str="16:00", tz="America/New_York"))
        for m in (2, 5, 8, 11):
            d = closed.on_or_before(_month_end(y, m))
            if start <= d <= end:
                out.append(_event("index_rebalance", d, "MSCI index review takes effect", "Global",
                                  "MSCI's quarterly index changes take effect at the close of each market today.",
                                  "Passive funds tracking MSCI buy added stocks and sell removed ones at the close, "
                                  "often heavy foreign flows in India, China and Hong Kong in the last minutes.",
                                  "MSCI review schedule", importance="medium", estimated=True))
        for m, n, word in ((3, 2, "start"), (11, 1, "end")):
            switch = _nth_weekday(y, m, 6, n)
            d = closed.on_or_after(switch + timedelta(days=1))
            if start <= d <= end:
                earlier = word == "start"
                out.append(_event("clock_change", d, f"US clocks {'forward' if earlier else 'back'} (daylight saving "
                                  f"{word}s)", "US",
                                  f"US clocks changed on Sunday {switch.day} {switch:%b}. The US session still opens at "
                                  f"09:30 New York time, which is an hour {'earlier' if earlier else 'later'} for India "
                                  "and most of Asia; the time shown is the new open in your timezone.",
                                  "Plan alerts, orders and evening routines around the new US hours.",
                                  "US daylight saving rules", importance="medium", time_str="09:30", tz="America/New_York"))
    return closed, out


def hk_events(rows: list[dict], start: date, end: date, years: list[int]) -> tuple[Closed, list[dict]]:
    closed = Closed({date.fromisoformat(r["date"]): r["name"] for r in rows
                     if date.fromisoformat(r["date"]).weekday() < 5})
    out = closure_events("Hong Kong", closed, start, end, "Hong Kong government holiday list")
    eves = [(date(y, 12, 24), "Christmas Eve") for y in years] + [(date(y, 12, 31), "New Year's Eve") for y in years]
    eves += [(date.fromisoformat(r["date"]) - timedelta(days=1), "Lunar New Year's Eve")
             for r in rows if r["name"].lower() == "lunar new year's day"]
    for d, name in eves:  # an eve on a weekend has no session to shorten
        if start <= d <= end and closed.trading(d):
            out.append(_event("short_day", d, f"Hong Kong half day: {name}", "Hong Kong",
                              "HKEX trades the morning session only, closing at 12:00 Hong Kong time.",
                              "Light, holiday-thinned trade; Stock Connect also stops at midday.",
                              "HKEX half-day rules", importance="medium", time_str="12:00", tz="Asia/Hong_Kong"))
    for y in years:
        for m in range(1, 13):
            d = closed.on_or_before(closed.on_or_before(_month_end(y, m)) - timedelta(days=1))  # second-last business day
            if start <= d <= end:
                out.append(_event("expiry", d, "Hang Seng futures & options expiry", "Hong Kong",
                                  "Monthly Hang Seng Index futures and options expire (second-last business day).",
                                  "Settlement is on the average price through the day, which can add volatility.",
                                  "HKEX expiry rules", importance="medium"))
    return closed, out


def cn_events(rows: list[dict], start: date, end: date, years: list[int]) -> tuple[Closed, list[dict]]:
    closed = Closed({date.fromisoformat(r["date"]): r["name"] for r in rows
                     if date.fromisoformat(r["date"]).weekday() < 5})
    out = closure_events("China", closed, start, end, "China State Council holiday schedule")
    for y in years:
        for m in range(1, 13):
            d = closed.on_or_after(_nth_weekday(y, m, 4, 3))
            if start <= d <= end:
                out.append(_event("expiry", d, "CSI 300 index futures expiry", "China",
                                  "China's stock index futures (CSI 300, SSE 50, CSI 500) expire (third Friday).",
                                  "Settlement on the last two hours' average price; large-cap A-shares can swing.",
                                  "CFFEX expiry rules", importance="medium"))
    return closed, out


def collect(start: date, days: int, fetch: FetchJson = _get_json) -> dict:
    """{"events": market events dated start..start+days, soonest first, "warnings": [...]}."""
    from .econ_calendar import _source

    end = start + timedelta(days=days)
    # a little past the window, so "reopens" and expiries shifted off a holiday are right
    years = sorted({start.year, end.year, (end + timedelta(days=20)).year})
    warnings: list[str] = []

    def source(name: str, loader: Callable[[], list[dict]], future: bool = False) -> list[dict]:
        rows, w = _source(name, loader)
        if w and not future:  # next year's lists are often not published yet
            warnings.append(w)
        return rows

    nse = source("nse_holidays", lambda: parse_nse(fetch(NSE_HOLIDAYS_URL)))
    hk = source("hk_holidays", lambda: parse_hk(fetch(HK_HOLIDAYS_URL)))
    cn = [r for y in years for r in source(f"cn_holidays_{y}", lambda y=y: parse_cn(fetch(CN_HOLIDAYS_URL.format(year=y))),
                                           future=y > start.year)]
    events: list[dict] = []
    for build, args in ((india_events, (nse,)), (us_events, ()), (hk_events, (hk,)), (cn_events, (cn,))):
        try:
            events += build(*args, start, end, years)[1]
        except Exception as exc:  # one bad list must not hide the others
            logger.warning("Market calendar %s failed: %s", build.__name__, exc)
    for e in events:
        e["days_away"] = (date.fromisoformat(e["date"]) - start).days
    events.sort(key=lambda e: (e["date"], e["time"] or "", e["title"]))
    return {"events": events, "warnings": warnings}
