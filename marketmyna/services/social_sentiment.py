"""What people are saying about a stock on Reddit, StockTwits, ValuePickr
and Hacker News - scored, aggregated, and summarised for the Analyze page.

Pipeline: build_query -> each source (in parallel, each with its own
deadline and failure isolation) -> dedupe + mention filter + time window ->
score each post -> aggregate (engagement- and recency-weighted) -> themes,
daily timeline, buzz -> snapshot to the db for the trend line.

Scoring is a finance + retail-trader lexicon (moon, bagholder, puts, ...)
with negation; StockTwits' author-set Bullish/Bearish tag outweighs it.
No AI is needed for the numbers; ai_summary() adds an optional LLM read.
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Optional

from ..data.social import SocialPost, SocialQuery, SourceBlocked, SourceSkipped, mentions
from ..llm.json_reply import parse_object
from ..utils.deadline import call_with_deadline

logger = logging.getLogger(__name__)

CACHE_SECONDS = 20 * 60
WINDOW_DAYS = 7
SLOW_WINDOW_DAYS = 30  # forums (ValuePickr) move slower
HALF_LIFE_HOURS = 72
SOURCE_DEADLINE = 75

# Sources that return "the latest N" rather than everything in the window.
SNAPSHOT_SOURCES = {"stocktwits"}

SOURCE_LABELS = {"reddit": "Reddit", "stocktwits": "StockTwits", "valuepickr": "ValuePickr", "hackernews": "Hacker News"}

# ------------------------------------------------------------------ scoring

# Phrases first (multi-word), then words. Weights: 1 normal, 1.5 strong.
_BULL = {
    "to the moon": 1.5, "short squeeze": 1, "buy the dip": 1, "btfd": 1, "diamond hands": 1, "strong buy": 1.5,
    "all time high": 1, "loading up": 1, "load up": 1, "buying calls": 1.5, "bought calls": 1.5, "price target raised": 1.5,
    "beat estimates": 1.5, "beats estimates": 1.5, "going up": 1, "long term hold": 1, "holding strong": 1,
    "moon": 1, "mooning": 1.5, "rocket": 1, "calls": 0.5, "bullish": 1.5, "bull": 1, "undervalued": 1.5,
    "breakout": 1, "tendies": 1, "printing": 1, "rally": 1, "rallying": 1, "ripping": 1, "squeeze": 0.5,
    "upgrade": 1.5, "upgraded": 1.5, "outperform": 1, "beat": 1, "beats": 1, "crushed": 0.5, "surge": 1,
    "surging": 1, "soar": 1, "soaring": 1, "jump": 0.5, "gain": 0.5, "gains": 0.5, "green": 0.5, "buy": 0.5,
    "buying": 0.5, "bought": 0.5, "accumulate": 1, "accumulating": 1, "adding": 0.5, "multibagger": 1.5,
    "rerating": 1, "re-rating": 1, "strong": 0.5, "growth": 0.5, "record": 0.5, "profit": 0.5, "profitable": 0.5,
    "upside": 1, "conviction": 0.5, "winner": 1, "winning": 0.5, "love": 0.5, "great": 0.5, "excellent": 1,
    "recovery": 0.5, "turnaround": 1, "momentum": 0.5, "ath": 1, "lfg": 1,
}
_BEAR = {
    "rug pull": 1.5, "value trap": 1.5, "falling knife": 1.5, "stay away": 1.5, "bag holder": 1.5, "guidance cut": 1.5,
    "buying puts": 1.5, "bought puts": 1.5, "price target cut": 1.5, "going down": 1, "dead cat": 1.5,
    "missed estimates": 1.5, "sell off": 1, "selloff": 1,
    "puts": 0.5, "short": 0.5, "shorting": 1, "shorts": 0.5, "bearish": 1.5, "bear": 1, "overvalued": 1.5,
    "bubble": 1, "dump": 1, "dumping": 1, "dumped": 1, "tank": 1, "tanking": 1.5, "tanked": 1, "crash": 1,
    "crashing": 1.5, "bagholder": 1.5, "bagholders": 1.5, "bagholding": 1.5, "rug": 1, "scam": 1.5, "fraud": 1.5,
    "sell": 0.5, "selling": 0.5, "sold": 0.5, "exit": 0.5, "exited": 0.5, "red": 0.5, "bleeding": 1, "drilling": 1,
    "miss": 1, "missed": 1, "downgrade": 1.5, "downgraded": 1.5, "underperform": 1, "lawsuit": 1, "dilution": 1,
    "dilutive": 1, "dead": 1, "worthless": 1.5, "avoid": 1, "trap": 1, "overhyped": 1, "hype": 0.5, "lost": 0.5,
    "loss": 0.5, "losses": 0.5, "losing": 0.5, "decline": 0.5, "declining": 0.5, "drop": 0.5, "dropping": 0.5,
    "plunge": 1, "plunged": 1, "weak": 0.5, "concern": 0.5, "concerns": 0.5, "risky": 0.5, "debt": 0.5,
    "terrible": 1, "awful": 1, "disappointing": 1, "disappointed": 1, "regret": 1, "down bad": 1, "rekt": 1.5,
}
_EMOJI = {"🚀": ("bull", 1), "💎": ("bull", 0.5), "📈": ("bull", 1), "🐂": ("bull", 1), "🌙": ("bull", 0.5),
          "📉": ("bear", 1), "🐻": ("bear", 1), "🩸": ("bear", 0.5), "💀": ("bear", 0.5), "🤡": ("bear", 0.5)}
_NEGATORS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "wont", "won't", "cant", "can't", "aint",
             "ain't", "without", "hardly", "nothing", "neither", "nor", "stop", "didnt", "didn't"}
_TERMS = sorted(
    [(t, "bull", w) for t, w in _BULL.items()] + [(t, "bear", w) for t, w in _BEAR.items()],
    key=lambda x: -len(x[0]),
)
_TERM_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t, _, _ in _TERMS) + r")\b")
_TERM_INFO = {t: (side, w) for t, side, w in _TERMS}


def score_text(text: str) -> tuple[float, list[str]]:
    """-1..1 for one post, plus the terms that drove it.

    A term preceded (within 3 words) by a negator flips side: "not bullish"
    reads bearish, "don't sell" reads bullish."""
    low = re.sub(r"https?://\S+", " ", text.lower()).replace("’", "'")
    bull = bear = 0.0
    hits: list[str] = []
    for match in _TERM_RE.finditer(low):
        term = match.group(1)
        side, weight = _TERM_INFO[term]
        before = re.findall(r"[a-z']+", low[max(0, match.start() - 40):match.start()])[-3:]
        if any(w in _NEGATORS for w in before):
            side = "bear" if side == "bull" else "bull"
            term = f"not {term}"
        if side == "bull":
            bull += weight
        else:
            bear += weight
        hits.append(term)
    for emoji, (side, weight) in _EMOJI.items():
        n = min(text.count(emoji), 3)
        if n:
            bull, bear = (bull + weight * n, bear) if side == "bull" else (bull, bear + weight * n)
            hits.append(emoji)
    total = bull + bear
    if total == 0:
        return 0.0, hits
    # Direction from the balance, strength from how much evidence there is:
    # a single weak word gives a mild reading, several give a firm one.
    return round((bull - bear) / total * min(1.0, total / 2.0), 3), hits


def post_sentiment(post: SocialPost) -> float:
    lex, _ = score_text(post.text)
    if post.label == "bullish":
        return round(0.7 + 0.3 * lex, 3)
    if post.label == "bearish":
        return round(-0.7 + 0.3 * lex, 3)
    return lex


def classify(score: float) -> str:
    return "bullish" if score > 0.15 else "bearish" if score < -0.15 else "neutral"


def mood(score100: float) -> str:
    if score100 >= 35:
        return "very bullish"
    if score100 >= 10:
        return "bullish"
    if score100 <= -35:
        return "very bearish"
    if score100 <= -10:
        return "bearish"
    return "neutral"


def weight(post: SocialPost, now: datetime) -> float:
    engagement = 1 + math.log1p(max(post.score, 0)) + 0.5 * math.log1p(max(post.comments, 0))
    age_h = max(0.0, (now - post.created_at).total_seconds() / 3600)
    return engagement * 0.5 ** (age_h / HALF_LIFE_HOURS)


# ------------------------------------------------------------------- themes

THEMES: dict[str, re.Pattern] = {
    name: re.compile(rx, re.I)
    for name, rx in {
        "Earnings": r"\bearnings\b|\beps\b|\bq[1-4]\b|\bresults\b|\bquarter(ly)?\b",
        "Guidance": r"\bguidance\b|\boutlook\b|\bforecast\b",
        "Options activity": r"\bcalls?\b|\bputs?\b|\boptions?\b|\b0dte\b|\bstrike\b|\byolo\b",
        "Short squeeze": r"\bsqueeze\b|\bshort interest\b|\bshorts?\b",
        "Valuation": r"\bvaluation\b|\bovervalued\b|\bundervalued\b|\bp/?e\b|\bmultiple\b|\bcheap\b|\bexpensive\b",
        "Dividends": r"\bdividends?\b|\byield\b|\bpayout\b",
        "Buyback": r"\bbuybacks?\b|\brepurchase",
        "M&A": r"\bmerger\b|\bacquisition\b|\bacquir|\btakeover\b|\bbuyout\b",
        "Analyst ratings": r"\bupgrade|\bdowngrade|\bprice target\b|\banalysts?\b",
        "AI": r"\bai\b|\bartificial intelligence\b|\bgpus?\b|\bllms?\b|\bdata ?cent(er|re)s?\b",
        "Legal / regulation": r"\blawsuit\b|\bsec\b|\bsebi\b|\bprobe\b|\binvestigation\b|\bregulat|\bantitrust\b|\bfined?\b",
        "Management": r"\bceo\b|\bcfo\b|\bmanagement\b|\binsiders?\b|\bpromoters?\b",
        "Layoffs": r"\blayoffs?\b|\bjob cuts\b|\brestructur",
        "Debt": r"\bdebt\b|\bloans?\b|\bbonds?\b|\bdefault\b|\brefinanc",
        "Technical analysis": r"\bsupport\b|\bresistance\b|\bbreakout\b|\bchart\b|\brsi\b|\bmoving average\b|\b\d+ ?dma\b",
        "Products / orders": r"\blaunch(es|ed)?\b|\bproducts?\b|\border book\b|\bcontracts?\b|\bdeal\b",
        "Macro / rates": r"\bfed\b|\brbi\b|\brate (cut|hike)s?\b|\binflation\b|\btariffs?\b|\brecession\b",
    }.items()
}


def themes(scored: list[tuple[SocialPost, float]], limit: int = 8) -> list[dict]:
    counts: dict[str, list[float]] = {}
    for post, s in scored:
        for name, rx in THEMES.items():
            if rx.search(post.text):
                counts.setdefault(name, []).append(s)
    min_posts = 2 if len(scored) >= 10 else 1
    out = [
        {"theme": name, "posts": len(vals), "score": round(sum(vals) / len(vals) * 100), "tone": classify(sum(vals) / len(vals))}
        for name, vals in counts.items()
        if len(vals) >= min_posts
    ]
    return sorted(out, key=lambda t: -t["posts"])[:limit]


# ---------------------------------------------------------------- query

_GENERIC_FIRST = {
    "american", "general", "united", "first", "national", "global", "international", "bank", "india", "indian",
    "the", "new", "advanced", "applied", "western", "eastern", "southern", "northern", "royal", "capital", "energy",
    "tata", "adani", "bajaj", "mahindra", "hdfc", "icici", "state", "great", "china", "hong", "power", "digital",
}
_CRYPTO_NAMES = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "XRP": "Ripple", "DOGE": "Dogecoin", "ADA": "Cardano",
    "BNB": "Binance Coin", "AVAX": "Avalanche", "DOT": "Polkadot", "LINK": "Chainlink", "MATIC": "Polygon",
    "LTC": "Litecoin", "SHIB": "Shiba Inu", "TRX": "Tron", "TON": "Toncoin",
}


def clean_name(name: str) -> str:
    from ..data.news_search import _SUFFIXES

    name = _SUFFIXES.sub("", name or "")
    return " ".join(re.sub(r"[.,()&]+", " ", name).split())


def build_query(symbol: str, market: str, name: Optional[str] = None) -> SocialQuery:
    symbol, market = symbol.strip().upper(), market.strip().lower()
    query = SocialQuery(symbol=symbol, market=market)
    if market == "crypto":
        query.name = _CRYPTO_NAMES.get(query.ticker, "")
        return query
    if name is None:
        from ..data.news_search import company_name

        name = company_name(symbol, market)
    cleaned = clean_name(name)
    query.name = "" if cleaned.upper() == symbol else cleaned
    words = query.name.split()
    # "Nvidia" for "NVIDIA", "Microsoft" for "Microsoft" - a distinctive first
    # word is how people actually write the name.
    if market == "us" and len(words) >= 2 and len(words[0]) >= 4 and words[0].lower() not in _GENERIC_FIRST:
        query.aliases.append(words[0])
    return query


# ---------------------------------------------------------------- sources


def _sources() -> dict[str, Callable]:
    from ..data.social import hackernews, reddit, stocktwits, valuepickr

    return {
        "reddit": reddit.fetch,
        "stocktwits": stocktwits.fetch,
        "valuepickr": valuepickr.fetch,
        "hackernews": hackernews.fetch,
    }


def _run_source(name: str, fetcher: Callable, query: SocialQuery, config) -> tuple[list[SocialPost], dict]:
    status = {"source": name, "label": SOURCE_LABELS.get(name, name), "status": "ok", "posts": 0, "via": None, "message": None}
    try:
        result = call_with_deadline(fetcher, SOURCE_DEADLINE, query, config)
    except SourceSkipped as exc:
        status.update(status="skipped", message=str(exc))
        return [], status
    except SourceBlocked as exc:
        status.update(status="blocked", message=str(exc))
        return [], status
    except TimeoutError:
        status.update(status="error", message="timed out")
        return [], status
    except Exception as exc:
        logger.warning("Social source %s failed: %s", name, exc)
        status.update(status="error", message=str(exc)[:200])
        return [], status
    posts, via = result if isinstance(result, tuple) else (result, None)
    status["via"] = via
    return posts, status


def collect(query: SocialQuery, config=None, sources: Optional[dict[str, Callable]] = None) -> tuple[list[SocialPost], list[dict]]:
    sources = sources if sources is not None else _sources()
    with ThreadPoolExecutor(max_workers=len(sources) or 1) as pool:
        futures = {name: pool.submit(_run_source, name, fn, query, config) for name, fn in sources.items()}
        results = {name: f.result() for name, f in futures.items()}
    posts: list[SocialPost] = []
    statuses: list[dict] = []
    for name in sources:
        found, status = results[name]
        posts.extend(found)
        statuses.append(status)
    return posts, statuses


# ---------------------------------------------------------------- aggregate


def _window(post: SocialPost) -> int:
    return SLOW_WINDOW_DAYS if post.source == "valuepickr" else WINDOW_DAYS


def select_posts(posts: list[SocialPost], query: SocialQuery, now: datetime) -> list[SocialPost]:
    """Dedupe, keep posts about this stock, inside the time window."""
    seen: set[str] = set()
    out = []
    for p in sorted(posts, key=lambda p: p.created_at, reverse=True):
        if p.id in seen or p.created_at < now - timedelta(days=_window(p)) or p.created_at > now + timedelta(hours=1):
            continue
        # StockTwits streams are per-symbol already; everything else must mention the stock.
        if p.source != "stocktwits" and not mentions(p, query):
            continue
        seen.add(p.id)
        out.append(p)
    return out


def aggregate(posts: list[SocialPost], now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    scored = [(p, post_sentiment(p)) for p in posts]
    weights = [weight(p, now) for p, _ in scored]
    total_w = sum(weights)
    overall = sum(w * s for w, (_, s) in zip(weights, scored)) / total_w if total_w else 0.0
    score100 = round(overall * 100)
    tones = [classify(s) for _, s in scored]
    counts = {t: tones.count(t) for t in ("bullish", "neutral", "bearish")}

    by_source: dict[str, list[float]] = {}
    for p, s in scored:
        by_source.setdefault(p.source, []).append(s)

    # Volume (timeline counts, buzz) only from sources that return the whole
    # window; StockTwits always hands back its latest 30 messages, which
    # would read as a fake spike today.
    volume = [(p, s) for p, s in scored if p.source not in SNAPSHOT_SOURCES]

    # Daily buckets over the short window (unweighted mean per day).
    days = [(now - timedelta(days=i)).date() for i in range(WINDOW_DAYS - 1, -1, -1)]
    buckets: dict[date, list[float]] = {d: [] for d in days}
    for p, s in volume:
        d = p.created_at.date()
        if d in buckets:
            buckets[d].append(s)
    timeline = [
        {"day": d.isoformat(), "posts": len(v), "score": round(sum(v) / len(v) * 100) if v else None}
        for d, v in buckets.items()
    ]

    last_24h = sum(1 for p, _ in volume if p.created_at >= now - timedelta(hours=24))
    prior = [p for p, _ in volume if now - timedelta(days=WINDOW_DAYS) <= p.created_at < now - timedelta(hours=24)]
    prior_daily = len(prior) / (WINDOW_DAYS - 1)
    buzz = None
    if prior_daily >= 0.5:
        buzz = {"last_24h": last_24h, "daily_avg": round(prior_daily, 1), "ratio": round(last_24h / prior_daily, 2)}

    top = sorted(zip(scored, weights), key=lambda x: -x[1])[:15]
    return {
        "score": score100,
        "mood": mood(score100) if posts else None,
        "confidence": "high" if len(posts) >= 40 else "medium" if len(posts) >= 12 else "low",
        "posts": len(posts),
        "counts": counts,
        "by_source": [
            {"source": src, "label": SOURCE_LABELS.get(src, src), "posts": len(v), "score": round(sum(v) / len(v) * 100)}
            for src, v in sorted(by_source.items(), key=lambda kv: -len(kv[1]))
        ],
        "themes": themes(scored),
        "timeline": timeline,
        "buzz": buzz,
        "top_posts": [
            {
                **{k: v for k, v in p.to_dict().items() if k != "body"},
                "excerpt": (p.body[:240] + "…") if len(p.body) > 240 else p.body,
                "sentiment": round(s * 100),
                "tone": classify(s),
                "terms": score_text(p.text)[1][:6],
            }
            for (p, s), _w in top
        ],
    }


# --------------------------------------------------------- cache + history

_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_inflight: dict[tuple[str, str], threading.Lock] = {}


def _save_snapshot(db, data: dict) -> None:
    from ..storage import SocialSentimentRecord as R

    day = date.today().isoformat()
    with db.get_session() as session:
        row = session.query(R).filter(R.symbol == data["symbol"], R.market == data["market"], R.day == day).first()
        if row is None:
            row = R(symbol=data["symbol"], market=data["market"], day=day)
            session.add(row)
        row.score = data["score"]
        row.posts = data["posts"]
        row.bullish, row.bearish, row.neutral = (data["counts"][k] for k in ("bullish", "bearish", "neutral"))
        row.updated_at = datetime.now()


def history(db, symbol: str, market: str, days: int = 30) -> list[dict]:
    from ..storage import SocialSentimentRecord as R

    since = (date.today() - timedelta(days=days)).isoformat()
    with db.get_session() as session:
        rows = (
            session.query(R)
            .filter(R.symbol == symbol, R.market == market, R.day >= since)
            .order_by(R.day)
            .all()
        )
        return [{"day": r.day, "score": round(r.score), "posts": r.posts} for r in rows]


def build(symbol: str, market: str, config=None, db=None, refresh: bool = False,
          sources: Optional[dict[str, Callable]] = None) -> dict:
    """Social sentiment for one stock (cached CACHE_SECONDS)."""
    key = (symbol.strip().upper(), market.strip().lower())
    with _cache_lock:
        hit = _cache.get(key)
        if hit and not refresh and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        lock = _inflight.setdefault(key, threading.Lock())
    # One fetch per stock at a time: a second viewer waits for the first
    # instead of launching another browser at the same site.
    with lock:
        with _cache_lock:
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < (5 if refresh else CACHE_SECONDS):
                return hit[1]
        now = datetime.now(timezone.utc)
        query = build_query(*key)
        raw, statuses = collect(query, config, sources)
        posts = select_posts(raw, query, now)
        for status in statuses:
            status["posts"] = sum(1 for p in posts if p.source == status["source"])
            if status["status"] == "ok" and not status["posts"]:
                status["status"] = "empty"
        data = {
            "symbol": key[0],
            "market": key[1],
            "query": {"ticker": query.ticker, "name": query.name, "aliases": query.aliases},
            "fetched_at": now.isoformat(),
            "window_days": WINDOW_DAYS,
            "sources": statuses,
            **aggregate(posts, now),
            "history": [],
        }
        if db is not None:
            try:
                if posts:
                    _save_snapshot(db, data)
                data["history"] = history(db, key[0], key[1])
            except Exception as exc:
                logger.warning("Social sentiment history unavailable: %s", exc)
        with _cache_lock:
            _cache[key] = (time.time(), data)
        return data


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ------------------------------------------------------------- AI summary


def _parse_summary(text: str) -> Optional[dict]:
    data = parse_object(text)
    if data is None:
        return None

    def strings(value) -> list[str]:
        return [str(v).strip() for v in value if str(v).strip()] if isinstance(value, list) else []

    hype = str(data.get("hype_risk") or "").lower()
    out = {
        "summary": str(data.get("summary") or "").strip(),
        "bull_points": strings(data.get("bull_points"))[:5],
        "bear_points": strings(data.get("bear_points"))[:5],
        "hype_risk": hype if hype in ("low", "medium", "high") else "low",
        "hype_reason": str(data.get("hype_reason") or "").strip(),
    }
    return out if out["summary"] else None


def ai_summary(data: dict, config) -> Optional[dict]:
    """LLM digest of the top posts. None without an LLM or on a bad reply."""
    from ..llm.channels import llm_configured

    if config is None or not llm_configured(config) or not data.get("top_posts"):
        return None
    from ..llm.backend_factory import create_generation_backend
    from ..llm.protocol import GenerationConfig

    lines = [
        f"Stock: {data['query'].get('name') or data['symbol']} ({data['symbol']}, market {data['market']}).",
        f"Lexicon sentiment score: {data['score']} on -100..100 from {data['posts']} posts in the last "
        f"{data['window_days']} days ({data['counts']['bullish']} bullish, {data['counts']['bearish']} bearish).",
        "Most-engaged posts (source | community | upvotes | text):",
    ]
    for p in data["top_posts"][:25]:
        text = (p["title"] + " " + (p.get("excerpt") or "")).replace("\n", " ")[:400]
        lines.append(f"- {p['source']} | {p['community']} | {p['score']} | {text}")
    system = (
        "You summarise retail-investor chatter about one stock for other investors. Use ONLY the posts given. "
        "Reply with ONLY a JSON object, no prose around it:\n"
        '{"summary": "2-3 sentences: what people are discussing and the overall mood", '
        '"bull_points": ["2-4 short arguments bulls are making"], '
        '"bear_points": ["2-4 short arguments bears are making"], '
        '"hype_risk": "low | medium | high", '
        '"hype_reason": "1 sentence: signs of pump/meme hype or coordinated promotion, or why it looks organic"}\n'
        "Attribute claims to posters (\"posters argue...\"), never state them as fact. No buy/sell advice."
    )
    try:
        result = create_generation_backend(config).generate(
            "\n".join(lines), GenerationConfig(max_tokens=700, timeout=110), system_prompt=system
        )
    except Exception as exc:
        logger.warning("Social AI summary unavailable: %s", exc)
        return None
    return _parse_summary(result.text or "")
