"""Economic calendar: the macro dates that move whole markets.

- US Fed rate decisions: federalreserve.gov FOMC calendar (decision on the last
  meeting day; "*" meetings come with economic projections).
- US data releases: FRED's release calendar (CPI, PPI, jobs report, GDP, PCE,
  retail sales), times in US Central time.
- RBI rate decisions: the MPC meeting schedule on rbi.org.in.
- India CPI and GDP: MoSPI's standing schedule (CPI on the 12th, GDP on the
  last working day of Feb / May / Aug / Nov, both 4 pm IST), shifted off
  weekends. Public holidays are not known here, so these are marked estimated.

Modeled on OpenBB's economy.calendar. Each source is cached for 12 hours and
its last good result is saved under ~/.marketmyna/econ/, served if a later
fetch fails (same pattern as india_rates).
"""

from __future__ import annotations

import html as htmllib
import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from marketmyna.core.home import app_home

logger = logging.getLogger(__name__)

FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
RBI_URL = "https://www.rbi.org.in/Scripts/Annualpolicy.aspx"
FRED_URL = "https://fred.stlouisfed.org/releases/calendar?rid={rid}&y={year}"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
CACHE_SECONDS = 12 * 3600

# FRED release id -> (key, short title, kind, importance, what it tells you)
FRED_RELEASES = {
    10: ("us_cpi", "US inflation (CPI)", "inflation", "high", "Consumer prices; drives Fed rate expectations"),
    50: ("us_jobs", "US jobs report", "jobs", "high", "Payrolls and unemployment rate"),
    53: ("us_gdp", "US GDP", "growth", "high", "Quarterly growth estimate"),
    54: ("us_pce", "US PCE inflation", "inflation", "high", "The Fed's preferred inflation gauge, with spending"),
    46: ("us_ppi", "US producer prices (PPI)", "inflation", "medium", "Pipeline inflation at the wholesale level"),
    9: ("us_retail", "US retail sales", "spending", "medium", "Consumer spending momentum"),
}

# key -> how a surprise usually moves stocks (shown with the event and in the reminder)
WHY = {
    "fed": "A cut or a softer tone usually lifts stocks and foreign flows into India; a hawkish hold firms the dollar "
           "and weighs on tech and the rupee.",
    "rbi": "A repo cut lowers loan rates, good for banks, NBFCs, autos and real estate; a hawkish hold weighs on "
           "those rate-sensitive stocks.",
    "us_cpi": "Hotter than last month pushes Fed cuts back, lifting bond yields and pressuring tech / growth stocks; "
              "cooler supports a rally.",
    "us_pce": "The Fed's own inflation gauge: a hot print means fewer rate cuts, a soft one backs them.",
    "us_ppi": "Wholesale prices feed into CPI a few months later; a jump hints at stickier inflation.",
    "us_jobs": "Strong hiring means fewer Fed cuts; a weak print raises recession worries but also cut hopes.",
    "us_gdp": "Shows whether the US economy is slowing; a weak number hits cyclicals and IT exporters' demand outlook.",
    "us_retail": "Consumer spending is ~70% of US GDP; a miss points to slowing growth.",
    "in_cpi": "Sets up the next RBI decision: inside RBI's 2-6% band leaves room for cuts, above 6% rules them out.",
    "in_gdp": "Confirms India's growth pace; a miss hits banks, capital goods and other domestic cyclicals.",
}

Fetch = Callable[[str], str]

_cache: dict[str, tuple[float, list]] = {}
_lock = threading.Lock()


def _http(url: str) -> str:
    import requests

    # FRED stalls requests with an unknown custom User-Agent; the default works there.
    headers = {} if "stlouisfed" in url else {"User-Agent": UA}
    r = requests.get(url, headers=headers, timeout=25)
    r.raise_for_status()
    return r.text


def _event(key: str, day: date, title: str, region: str, kind: str, importance: str, note: str, source: str,
           time_str: Optional[str] = None, tz: Optional[str] = None, estimated: bool = False) -> dict:
    return {"key": key, "date": day.isoformat(), "time": time_str, "tz": tz, "title": title, "region": region,
            "kind": kind, "importance": importance, "note": note, "source": source, "estimated": estimated}


MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                         "september", "october", "november", "december"], 1)}
MON3 = {k[:3]: v for k, v in MONTHS.items()}


def parse_fed(page: str) -> list[dict]:
    """FOMC meetings per year section; decision on the last day."""
    out = []
    parts = re.split(r"(\d{4}) FOMC Meetings", page)
    for i in range(1, len(parts) - 1, 2):
        year, body = int(parts[i]), parts[i + 1]
        for month, days in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<',
                                      body, re.S):
            month, days = month.strip(), htmllib.unescape(days).strip()
            if "notation" in days.lower() or "cancel" in days.lower():
                continue
            sep = "*" in days
            nums = re.findall(r"\d+", days)
            months = [MON3.get(m.strip()[:3].lower()) for m in month.split("/")]
            if not nums or not months[0]:
                continue
            end_month = months[-1] if len(months) > 1 else months[0]
            try:
                day = date(year, end_month, int(nums[-1]))
            except ValueError:
                continue
            out.append(_event("fed", day, "Fed rate decision" + (" + projections" if sep else ""), "US", "central_bank", "high",
                              "FOMC statement 2:00 pm ET; press conference follows", "Federal Reserve",
                              "14:00", "America/New_York"))
    return out


def parse_rbi(page: str) -> list[dict]:
    """'October 5, 6 and 7, 2026' rows of the MPC schedule; decision on the last day."""
    text = htmllib.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", page)))
    out, seen = [], set()
    for month, days, year in re.findall(r"(January|February|March|April|May|June|July|August|September|October|November|December)"
                                        r"\s+((?:\d{1,2}(?:,|\s+and|\s+to|\s*-)?\s*)+),\s*(\d{4})", text):
        nums = re.findall(r"\d{1,2}", days)
        if len(nums) < 2:  # a single date is a press conference line, not a meeting range
            continue
        try:
            day = date(int(year), MONTHS[month.lower()], int(nums[-1]))
        except ValueError:
            continue
        if day in seen:
            continue
        seen.add(day)
        out.append(_event("rbi", day, "RBI rate decision", "India", "central_bank", "high",
                          "MPC resolution around 10:00 am IST, governor's statement", "Reserve Bank of India",
                          "10:00", "Asia/Kolkata"))
    return out


def parse_fred(page: str, rid: int) -> list[dict]:
    key, title, kind, importance, note = FRED_RELEASES[rid]
    out = []
    for day_s, time_s, row_rid in re.findall(
            r'font-weight: bold;">[A-Za-z]+ ([A-Za-z]+ \d{1,2}, \d{4})</span>.*?<td nowrap[^>]*>\s*([^<]*?)\s*</td>\s*'
            r'<td[^>]*>\s*<a href="/release\?rid=(\d+)">', page, re.S):
        if int(row_rid) != rid:
            continue
        try:
            day = datetime.strptime(day_s, "%B %d, %Y").date()
        except ValueError:
            continue
        hhmm = None
        if m := re.match(r"(\d{1,2}):(\d{2})\s*([ap]m)", time_s.lower()):
            h = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
            hhmm = f"{h:02d}:{m.group(2)}"
        out.append(_event(key, day, title, "US", kind, importance, note, "US official statistics",
                          hhmm, "America/Chicago"))
    return out


def _workday_on_or_after(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _last_workday(year: int, month: int) -> date:
    d = (date(year, month % 12 + 1, 1) if month < 12 else date(year + 1, 1, 1)) - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def india_releases(start: date, end: date) -> list[dict]:
    out = []
    d = date(start.year, start.month, 1)
    while d <= end:
        cpi = _workday_on_or_after(date(d.year, d.month, 12))
        out.append(_event("in_cpi", cpi, "India inflation (CPI)", "India", "inflation", "high",
                          "Retail inflation for the previous month (MoSPI)", "MoSPI schedule",
                          "16:00", "Asia/Kolkata", estimated=True))
        if d.month in (2, 5, 8, 11):
            out.append(_event("in_gdp", _last_workday(d.year, d.month), "India GDP", "India", "growth", "high",
                              "Quarterly growth estimate (MoSPI)", "MoSPI schedule",
                              "16:00", "Asia/Kolkata", estimated=True))
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return [e for e in out if start.isoformat() <= e["date"] <= end.isoformat()]


def _dir() -> Path:
    p = app_home() / "econ"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _source(name: str, loader: Callable[[], list[dict]], ttl: float = CACHE_SECONDS) -> tuple[list[dict], Optional[str]]:
    """Cached per source; last good copy on disk when a fetch fails."""
    with _lock:
        hit = _cache.get(name)
    if hit and time.time() - hit[0] < ttl:
        return hit[1], None
    path = _dir() / f"{name}.json"
    try:
        events = loader()
        if not events:
            raise ValueError("no dates found (page layout changed?)")
        with _lock:
            _cache[name] = (time.time(), events)
        try:
            path.write_text(json.dumps(events), encoding="utf-8")
        except OSError:
            pass
        return events, None
    except Exception as exc:
        logger.warning("Economic calendar source %s failed: %s", name, exc)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")), f"{name}: live fetch failed, using the last saved schedule"
        return [], f"{name}: unavailable right now"


def collect(start: date, days: int, fetch: Fetch = _http, regions: tuple[str, ...] = ("US", "India")) -> dict:
    end = start + timedelta(days=days)
    years = sorted({start.year, end.year})
    events, warnings = [], []
    if "US" in regions:
        ev, w = _source("fed", lambda: parse_fed(fetch(FED_URL)))
        events += ev
        warnings += [w] if w else []
        for rid in FRED_RELEASES:
            ev, w = _source(f"fred_{rid}_{'_'.join(map(str, years))}",
                            lambda rid=rid: [e for y in years for e in parse_fred(fetch(FRED_URL.format(rid=rid, year=y)), rid)])
            events += ev
            warnings += [w] if w else []
    if "India" in regions:
        ev, w = _source("rbi", lambda: parse_rbi(fetch(RBI_URL)))
        events += ev
        warnings += [w] if w else []
        events += india_releases(start, end)
    picked = [dict(e, days_away=(date.fromisoformat(e["date"]) - start).days)
              for e in events if start.isoformat() <= e["date"] <= end.isoformat()]
    picked.sort(key=lambda e: (e["date"], e["time"] or "", e["title"]))
    return {"events": picked, "warnings": warnings}


def local_time(e: dict, tz_name: str) -> Optional[str]:
    """Event time converted to the viewer's timezone, 'HH:MM'."""
    if not e.get("time") or not e.get("tz"):
        return None
    try:
        dt = datetime.combine(date.fromisoformat(e["date"]), datetime.strptime(e["time"], "%H:%M").time(),
                              tzinfo=ZoneInfo(e["tz"]))
        loc = dt.astimezone(ZoneInfo(tz_name))
        day_shift = (loc.date() - dt.date()).days
        return loc.strftime("%H:%M") + (" (+1d)" if day_shift > 0 else "")
    except Exception:
        return None


# ------------------------------------------------------------------ last readings

READINGS_SECONDS = 6 * 3600
SeriesFetch = Callable[[str, date], "object"]  # macro._fred: id, start -> pandas Series


def _pct_yoy(s) -> "object":
    monthly = s.resample("MS").last().dropna()
    return ((monthly / monthly.shift(12) - 1) * 100).dropna()


def _mon(ts) -> str:
    return ts.strftime("%b")


def _qtr(ts) -> str:
    return f"Q{(ts.month - 1) // 3 + 1} {ts.year}"


def _trend(now: float, prev: float, unit: str = "%") -> str:
    if round(now, 1) == round(prev, 1):
        return f"same as {prev:.1f}{unit} before"
    return f"{'up' if now > prev else 'down'} from {prev:.1f}{unit}"


def _point(text: str, period, value: float, prev: Optional[float]) -> dict:
    return {"text": text, "period": period.date().isoformat(), "value": float(value),
            "prev": None if prev is None else float(prev)}


def _yoy_point(series: dict, main: str, core: Optional[str] = None) -> Optional[dict]:
    if main not in series:
        return None
    y = _pct_yoy(series[main])
    if len(y) < 2:
        return None
    text = f"{y.iloc[-1]:.1f}% YoY in {_mon(y.index[-1])}, {_trend(y.iloc[-1], y.iloc[-2])}"
    if core and core in series and len(c := _pct_yoy(series[core])):
        text += f"; core {c.iloc[-1]:.1f}%"
    return _point(text, y.index[-1], y.iloc[-1], y.iloc[-2])


def _fred_points(series: dict) -> dict[str, dict]:
    """key -> {text, period (first day of the month / quarter it covers), value, prev}."""
    out: dict[str, dict] = {}
    for key, main, core in (("us_cpi", "CPIAUCSL", "CPILFESL"), ("us_pce", "PCEPI", "PCEPILFE"), ("us_ppi", "PPIFIS", None)):
        if pt := _yoy_point(series, main, core):
            out[key] = pt
    if "PAYEMS" in series and len(p := series["PAYEMS"].dropna()) >= 3:
        adds = p.diff().dropna()
        line = f"{adds.iloc[-1]:+,.0f}k jobs in {_mon(adds.index[-1])} (before: {adds.iloc[-2]:+,.0f}k)"
        if "UNRATE" in series and len(u := series["UNRATE"].dropna()):
            line += f", unemployment {u.iloc[-1]:.1f}%"
        out["us_jobs"] = _point(line, adds.index[-1], adds.iloc[-1], adds.iloc[-2])
    if "A191RL1Q225SBEA" in series and len(g := series["A191RL1Q225SBEA"].dropna()) >= 2:
        out["us_gdp"] = _point(f"{g.iloc[-1]:.1f}% annualised in {_qtr(g.index[-1])} (before: {g.iloc[-2]:.1f}%)",
                               g.index[-1], g.iloc[-1], g.iloc[-2])
    if "RSAFS" in series and len(r := series["RSAFS"].dropna()) >= 3:
        mom = (r.pct_change() * 100).dropna()
        out["us_retail"] = _point(f"{mom.iloc[-1]:+.1f}% month on month in {_mon(mom.index[-1])} (before: {mom.iloc[-2]:+.1f}%)",
                                  mom.index[-1], mom.iloc[-1], mom.iloc[-2])
    if "DFEDTARL" in series and "DFEDTARU" in series and len(series["DFEDTARL"]) and len(series["DFEDTARU"]):
        lo, hi = series["DFEDTARL"], series["DFEDTARU"]
        out["fed"] = _point(f"Target range now {lo.iloc[-1]:.2f}-{hi.iloc[-1]:.2f}%", hi.index[-1], hi.iloc[-1], None)
    return out


READING_SERIES = ["CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "PPIFIS", "PAYEMS", "UNRATE",
                  "A191RL1Q225SBEA", "RSAFS", "DFEDTARL", "DFEDTARU"]


def _rbi_line() -> Optional[str]:
    from . import india_rates

    for p in india_rates.build().get("rbi", {}).get("policy", []):
        if p["key"] == "repo" and p["value"] is not None:
            return f"Repo rate now {p['value']:.2f}%"
    return None


def points(fetch: Optional[SeriesFetch] = None, max_age: float = READINGS_SECONDS) -> dict[str, dict]:
    """Latest FRED reading per event key; cached for `max_age` seconds, never raises."""
    with _lock:
        hit = _cache.get("points")
    if max_age and hit and time.time() - hit[0] < max_age:
        return hit[1]
    from concurrent.futures import ThreadPoolExecutor

    if fetch is None:
        from .macro import _fred as fetch
    start = date.today() - timedelta(days=800)

    def one(sid):
        try:
            return sid, fetch(sid, start)
        except Exception as exc:
            logger.info("Reading %s unavailable: %s", sid, exc)
            return sid, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        series = {sid: s for sid, s in pool.map(one, READING_SERIES) if s is not None and len(s)}
    try:
        out = _fred_points(series)
    except Exception as exc:
        logger.warning("Economic readings failed: %s", exc)
        out = {}
    if max_age and out:
        with _lock:
            _cache["points"] = (time.time(), out)
    return out


def readings(fetch: Optional[SeriesFetch] = None, rbi: Optional[Callable[[], Optional[str]]] = _rbi_line,
             use_cache: bool = True) -> dict[str, str]:
    """key -> the last published reading ("2.9% YoY in Aug, up from 2.7%; core 3.1%").
    Cached; a missing series just leaves its key out, never raises."""
    if use_cache:
        with _lock:
            hit = _cache.get("readings")
        if hit and time.time() - hit[0] < READINGS_SECONDS:
            return hit[1]
    out = {k: v["text"] for k, v in points(fetch, READINGS_SECONDS if use_cache else 0).items()}
    if rbi:
        try:
            if line := rbi():
                out["rbi"] = line
        except Exception as exc:
            logger.info("RBI repo reading unavailable: %s", exc)
    if use_cache and out:
        with _lock:
            _cache["readings"] = (time.time(), out)
    return out


# ------------------------------------------------------------------ results after a release

# Data releases we can read back from FRED once they are out (central bank
# decisions and India's MoSPI numbers have no reliable same-day feed here).
RESULT_KEYS = {"us_cpi", "us_pce", "us_ppi", "us_jobs", "us_gdp", "us_retail"}
RESULT_GRACE = timedelta(minutes=20)  # FRED usually posts within minutes of the release
RESULT_GIVE_UP = timedelta(hours=10)  # stop looking if FRED has not posted by then


def _month_start(d: date, back: int = 0) -> date:
    m = d.year * 12 + d.month - 1 - back
    return date(m // 12, m % 12 + 1, 1)


def covers(key: str, release_day: date) -> date:
    """The earliest period a release on `release_day` reports: last month for the
    monthly ones, last quarter for GDP. A FRED value at or after it is the new print."""
    if key == "us_gdp":
        q = _month_start(release_day)
        return _month_start(date(q.year, (q.month - 1) // 3 * 3 + 1, 1), 3)
    return _month_start(release_day, 1)


def release_moment(e: dict) -> Optional[datetime]:
    if not e.get("time") or not e.get("tz"):
        return None
    return datetime.combine(date.fromisoformat(e["date"]), datetime.strptime(e["time"], "%H:%M").time(),
                            tzinfo=ZoneInfo(e["tz"]))


def verdict(key: str, value: float, prev: Optional[float]) -> str:
    """Plain words on the new print against the one before (no consensus forecast here)."""
    if prev is None:
        return ""
    if key in ("us_cpi", "us_pce", "us_ppi"):
        if round(value, 1) == round(prev, 1):
            return "Same as the month before: no change to the rate-cut picture."
        if value > prev:
            return "Hotter than the month before: Fed cuts look less likely, usually a drag on tech / growth stocks and the rupee."
        return "Cooler than the month before: supports Fed rate cuts, usually good for stocks."
    if key == "us_jobs":
        if value >= 150:
            return "Strong hiring: the economy is holding up, but it gives the Fed less reason to cut."
        if value < 50:
            return "Weak hiring: raises slowdown worries, and the odds of Fed cuts."
        return "Moderate hiring: neither hot nor weak."
    if key in ("us_gdp", "us_retail"):
        if round(value, 1) == round(prev, 1):
            return "Same pace as before."
        return ("Faster than before: the US economy is holding up." if value > prev
                else "Slower than before: a sign the US economy is cooling.")
    return ""


def results(events: list[dict], now: datetime, fetch_points: Callable[[], dict]) -> list[dict]:
    """Of today's `events`, the ones whose new number is out: each gets `result`
    (text) and `verdict`. FRED is only asked when a release time has passed."""
    due = []
    for e in events:
        key = e.get("key") or TITLE_KEYS.get(e["title"], "")
        at = release_moment(e)
        # GDP's later estimates revise a quarter FRED already has; only the first one is news.
        advance_only = key != "us_gdp" or date.fromisoformat(e["date"]).month in (1, 4, 7, 10)
        if key in RESULT_KEYS and advance_only and at and at + RESULT_GRACE <= now <= at + RESULT_GIVE_UP:
            due.append((key, e))
    if not due:
        return []
    pts = fetch_points()
    out = []
    for key, e in due:
        pt = pts.get(key)
        if pt and date.fromisoformat(pt["period"]) >= covers(key, date.fromisoformat(e["date"])):
            out.append(dict(e, key=key, result=pt["text"], verdict=verdict(key, pt["value"], pt["prev"])))
    return out


# region -> the markets of the stocks it moves ("global" listings trade in the US)
REGION_MARKETS = {"US": ("us", "global"), "India": ("india",), "Hong Kong": ("hong_kong",), "China": ("china_a",)}
# schedules saved before events carried a key
TITLE_KEYS = {"Fed rate decision": "fed", "RBI rate decision": "rbi", "India inflation (CPI)": "in_cpi",
              "India GDP": "in_gdp", **{t: k for k, t, *_ in FRED_RELEASES.values()}}


def enrich(events: list[dict], followed: Optional[dict] = None, read: Optional[Callable[[], dict]] = None) -> list[dict]:
    """Add `last` (latest reading), `why` (what a surprise does) and `exposure`
    (the followed stocks listed in that event's country) to each event, in place."""
    try:
        last = (read or readings)()
    except Exception as exc:
        logger.warning("Economic readings failed: %s", exc)
        last = {}
    mine: dict[str, list[str]] = {}
    for symbol, market in followed or {}:
        mine.setdefault(market, []).append(symbol)
    for e in events:
        e["key"] = key = e.get("key") or TITLE_KEYS.get(e["title"].replace(" + projections", ""), "")
        e["last"] = last.get(key)
        e["why"] = e.get("why") or WHY.get(key)
        e["exposure"] = sorted({s for m in REGION_MARKETS.get(e["region"], ()) for s in mine.get(m, [])})
    return events
