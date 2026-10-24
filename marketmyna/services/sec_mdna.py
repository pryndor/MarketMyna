"""AI summary of Management's Discussion and Analysis (MD&A) from a US
company's latest 10-K or 10-Q on SEC EDGAR (free, no key).

SEC's fair-access policy requires a User-Agent naming the caller with a
contact email, so the feature is off until SEC_USER_AGENT is set, e.g.
"MarketMyna you@example.com". Stands in for OpenBB's
equity.fundamental.management_discussion_analysis (Apache 2.0).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time

logger = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
MAX_CHARS = 24000
CACHE_SECONDS = 24 * 3600

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


class SecNotConfigured(RuntimeError):
    pass


def user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if "@" not in ua:
        raise SecNotConfigured("Set SEC_USER_AGENT (a name and contact email, e.g. 'MarketMyna you@example.com') "
                               "to read SEC filings - SEC requires it.")
    return ua


def _get(url: str):
    import requests

    resp = requests.get(url, headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}, timeout=30)
    resp.raise_for_status()
    return resp


def _cached(key: str, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def cik_for(symbol: str) -> int:
    table = _cached("tickers", lambda: {v["ticker"].upper(): int(v["cik_str"]) for v in _get(TICKERS_URL).json().values()})
    cik = table.get(symbol.upper().replace(".", "-"))
    if cik is None:
        raise ValueError(f"{symbol} is not an SEC filer")
    return cik


def latest_filing(cik: int) -> dict:
    recent = _get(SUBMISSIONS_URL.format(cik=cik)).json()["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form in ("10-K", "10-Q"):
            return {"form": form, "filed": recent["filingDate"][i], "period": recent["reportDate"][i],
                    "accession": recent["accessionNumber"][i], "document": recent["primaryDocument"][i]}
    raise ValueError("No 10-K or 10-Q on file")


def html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for hidden in soup.select('[style*="display:none"], [style*="display: none"]'):
        hidden.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\xa0", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


_START = {"10-K": r"item\s*7\.?\s*[-–—:]?\s*management[’'`s]*\s+discussion",
          "10-Q": r"item\s*2\.?\s*[-–—:]?\s*management[’'`s]*\s+discussion"}
_END = {"10-K": r"item\s*7a\.?|item\s*8\.?\s*[-–—:]?\s*financial\s+statements",
        "10-Q": r"item\s*3\.?\s*[-–—:]?\s*quantitative|item\s*4\.?\s*[-–—:]?\s*controls"}


def extract_mdna(text: str, form: str) -> str:
    """The MD&A section. The heading also appears in the table of contents, so
    take the candidate that yields the longest section."""
    best = ""
    for m in re.finditer(_START[form], text, flags=re.I):
        end = re.search(_END[form], text[m.end():], flags=re.I)
        section = text[m.start(): m.end() + end.start()] if end else text[m.start(): m.start() + MAX_CHARS * 2]
        if len(section) > len(best):
            best = section
    if len(best) < 1500:
        best = _fallback(text)
    if len(best) < 1500:
        raise ValueError("Could not find the MD&A section in the filing")
    return best.strip()


def _fallback(text: str) -> str:
    """Banks and some others open with MD&A without an 'Item' heading: take the
    bare heading followed by the longest stretch before it repeats."""
    hits = [m.start() for m in re.finditer(r"management[’'`s]*\s+discussion\s+and\s+analysis", text, flags=re.I)]
    best = ""
    for i, start in enumerate(hits):
        stop = hits[i + 1] if i + 1 < len(hits) else len(text)
        chunk = text[start:min(stop, start + MAX_CHARS * 2)]
        if len(chunk) > len(best):
            best = chunk
    return best


def mdna(symbol: str) -> dict:
    cik = cik_for(symbol)
    filing = latest_filing(cik)

    def load():
        acc = filing["accession"].replace("-", "")
        html = _get(DOC_URL.format(cik=cik, acc=acc, doc=filing["document"])).text
        return extract_mdna(html_to_text(html), filing["form"])

    section = _cached(f"mdna:{filing['accession']}", load)
    acc = filing["accession"].replace("-", "")
    return {**filing, "cik": cik, "url": DOC_URL.format(cik=cik, acc=acc, doc=filing["document"]),
            "chars": len(section), "text": section}


SYSTEM = (
    "You are an equity analyst summarising the Management's Discussion and Analysis section of an SEC filing "
    "for a retail investor. Use ONLY the text given. Write Markdown with these sections: '### What happened' "
    "(results vs the prior period, with the key numbers), '### Why' (the drivers management gives), "
    "'### Outlook' (guidance, plans, capital spending, buybacks - say so if none is given), "
    "'### Risks management flagged', '### Watch next' (2-3 bullets). Keep each section to 2-4 sentences or "
    "bullets. Quote numbers exactly. No price targets, no buy/sell advice, no disclaimers."
)


def ai_summary(symbol: str, config) -> dict:
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig

    doc = mdna(symbol)
    key = f"ai:{doc['accession']}"
    with _lock:
        hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        summary = hit[1]
    else:
        text = doc["text"][:MAX_CHARS]
        prompt = (f"Company: {symbol}. Filing: {doc['form']} for the period ending {doc['period']}, filed {doc['filed']}."
                  f"{' (Section truncated.)' if doc['chars'] > MAX_CHARS else ''}\n\n{text}")
        result = create_generation_backend(config).generate(
            prompt, GenerationConfig(max_tokens=1100, timeout=110), system_prompt=SYSTEM)
        summary = (result.text or "").strip()
        if not summary:
            raise RuntimeError("The AI model returned an empty summary")
        with _lock:
            _cache[key] = (time.time(), summary)
    return {k: doc[k] for k in ("form", "filed", "period", "url", "chars")} | {"symbol": symbol, "summary": summary}
