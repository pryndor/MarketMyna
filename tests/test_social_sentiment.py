"""Social sentiment - parsers, scoring, aggregation, Reddit fallback chain,
caching/snapshots and the API. No network: sources are fakes or parsers
fed recorded payload shapes."""

from datetime import datetime, timedelta, timezone

import pytest

from src.data.social import SocialPost, SocialQuery, SourceBlocked, SourceSkipped, hackernews, mentions, reddit
from src.data.social import stocktwits, valuepickr
from src.services import social_sentiment as ss

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def post(title, *, source="reddit", hours=1, score=10, comments=2, body="", label=None, pid=None):
    return SocialPost(
        source=source,
        id=pid or f"{source}:{title[:20]}:{hours}",
        title=title,
        body=body,
        url="https://example.com/" + str(abs(hash(title))),
        created_at=NOW - timedelta(hours=hours),
        community="r/stocks",
        score=score,
        comments=comments,
        label=label,
    )


@pytest.fixture(autouse=True)
def _fresh():
    ss.clear_cache()
    reddit.reset()
    yield
    ss.clear_cache()
    reddit.reset()


# ------------------------------------------------------------------ scoring


def test_score_text_bullish_bearish_and_neutral():
    assert ss.score_text("NVDA to the moon 🚀 buying calls")[0] > 0.5
    assert ss.score_text("total bagholder, this is tanking, buying puts")[0] < -0.5
    assert ss.score_text("What time is the earnings call?")[0] == 0


def test_negation_flips_side():
    score, terms = ss.score_text("I am not bullish on this at all")
    assert score < 0 and "not bullish" in terms
    assert ss.score_text("don't sell, hold")[0] > 0


def test_single_weak_word_is_mild():
    assert 0 < ss.score_text("I bought some")[0] <= 0.3


def test_stocktwits_label_outweighs_lexicon():
    p = post("this will crash", source="stocktwits", label="bullish")
    assert ss.post_sentiment(p) > 0.3
    assert ss.post_sentiment(post("nice", source="stocktwits", label="bearish")) < -0.3


def test_mood_bands():
    assert ss.mood(50) == "very bullish" and ss.mood(12) == "bullish" and ss.mood(0) == "neutral"
    assert ss.mood(-20) == "bearish" and ss.mood(-60) == "very bearish"


# ----------------------------------------------------------------- mentions


def test_mentions_cashtag_name_and_ambiguous_tickers():
    q = SocialQuery(symbol="F", market="us", name="Ford Motor")
    assert mentions(post("Loaded $F calls"), q)
    assert mentions(post("Ford Motor guidance cut"), q)
    assert not mentions(post("F this market"), q)

    nvda = SocialQuery(symbol="NVDA", market="us", name="NVIDIA")
    assert mentions(post("NVDA earnings play"), nvda)
    assert mentions(post("nvidia is cooked"), nvda)
    assert not mentions(post("look at nvdax token"), nvda)

    it = SocialQuery(symbol="IT", market="us", name="Gartner")
    assert not mentions(post("IT stocks are cheap"), it)


def test_build_query_names_and_aliases():
    q = ss.build_query("msft", "us", name="Microsoft Corporation")
    assert (q.symbol, q.name) == ("MSFT", "Microsoft")
    q = ss.build_query("META", "us", name="Meta Platforms, Inc.")
    assert q.name == "Meta Platforms" and q.aliases == ["Meta"]
    q = ss.build_query("GM", "us", name="General Motors Company")
    assert q.aliases == []  # "General" alone would match everything
    q = ss.build_query("BTC-USD", "crypto")
    assert (q.ticker, q.name) == ("BTC", "Bitcoin")
    assert ss.build_query("XYZ", "us", name="XYZ").name == ""


# ------------------------------------------------------------------ parsers


def test_parse_reddit_listing():
    payload = {"data": {"children": [
        {"data": {"id": "abc", "title": "AAPL &amp; earnings", "selftext": "beat", "permalink": "/r/stocks/comments/abc/x/",
                  "created_utc": 1791201600, "author": "u1", "subreddit": "stocks", "score": 42, "num_comments": 7}},
        {"data": {"id": "", "title": "skip"}},
    ]}}
    [p] = reddit.parse_listing(payload)
    assert p.id == "reddit:abc" and p.title == "AAPL & earnings" and p.community == "r/stocks"
    assert (p.score, p.comments) == (42, 7) and p.url.endswith("/comments/abc/x/")


def test_parse_reddit_search_units_and_feed():
    rows = [{"title": "NVDA calls printing", "href": "/r/wallstreetbets/comments/q1w2/nvda/", "sub": "r/wallstreetbets",
             "ts": "2026-10-05T10:00:00.000Z", "text": "r/wallstreetbets • 2h\nNVDA calls printing\n1.2k votes · 345 comments"},
            {"title": "", "href": "/r/x/comments/zz/", "ts": None, "text": ""}]
    [p] = reddit.parse_search_units(rows)
    assert (p.id, p.score, p.comments, p.community) == ("reddit:q1w2", 1200, 345, "r/wallstreetbets")

    feed = [{"id": "t3_k9", "title": "TSLA", "permalink": "/r/stocks/comments/k9/tsla/", "score": "15", "comments": "4",
             "ts": "2026-10-05T09:00:00+0000", "author": "a", "sub": "r/stocks", "body": "long"}]
    [f] = reddit.parse_feed_posts(feed)
    assert f.id == "reddit:k9" and f.score == 15 and f.created_at.tzinfo is not None


def test_parse_reddit_rss():
    xml = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><author><name>/u/bob</name></author><title>AMD looks undervalued</title>
        <link href="https://www.reddit.com/r/stocks/comments/r55/amd/"/><published>2026-10-05T08:00:00+00:00</published>
        <content type="html">&lt;p&gt;Buying more&lt;/p&gt; submitted by /u/bob [link]</content></entry>
    </feed>"""
    [p] = reddit.parse_rss(xml, "stocks")
    assert p.id == "reddit:r55" and p.author == "bob" and p.body == "Buying more" and p.score == 0


def test_parse_stocktwits_valuepickr_hn():
    st = {"messages": [{"id": 9, "body": "$AAPL breakout", "created_at": "2026-10-05T11:00:00Z", "user": {"username": "z"},
                        "likes": {"total": 3}, "entities": {"sentiment": {"basic": "Bullish"}}},
                       {"id": 10, "body": "meh", "created_at": "2026-10-05T11:00:00Z", "entities": {"sentiment": None}}]}
    a, b = stocktwits.parse_stream(st)
    assert a.label == "bullish" and a.score == 3 and a.url == "https://stocktwits.com/z/message/9"
    assert b.label is None
    assert stocktwits.stocktwits_symbol(SocialQuery("BTC-USD", "crypto")) == "BTC.X"
    assert stocktwits.stocktwits_symbol(SocialQuery("BRK-B", "us")) == "BRK.B"
    with pytest.raises(SourceSkipped):
        stocktwits.stocktwits_symbol(SocialQuery("RELIANCE", "india"))

    vp = {"posts": [{"id": 1, "topic_id": 7, "post_number": 3, "created_at": "2026-10-01T00:00:00Z", "username": "v",
                     "like_count": 5, "blurb": "Reliance  Industries   results"}],
          "topics": [{"id": 7, "title": "Reliance Industries", "slug": "reliance-industries", "reply_count": 99}]}
    [v] = valuepickr.parse_search(vp)
    assert v.url.endswith("/t/reliance-industries/7/3") and v.body == "Reliance Industries results" and v.comments == 0

    hn = {"hits": [{"objectID": "55", "title": "Nvidia ships", "created_at_i": 1791201600, "points": 80, "num_comments": 12}]}
    [h] = hackernews.parse_hits(hn)
    assert h.url.endswith("id=55") and h.score == 80


# -------------------------------------------------------------- aggregation


def test_select_posts_dedupes_filters_mentions_and_window():
    q = SocialQuery("AAPL", "us", name="Apple")
    posts = [
        post("AAPL up", pid="reddit:1"),
        post("AAPL up again", pid="reddit:1"),  # duplicate id
        post("unrelated stock talk", pid="reddit:2"),
        post("Apple too old", hours=24 * 9, pid="reddit:3"),
        post("no ticker but per-symbol stream", source="stocktwits", pid="st:1"),
        post("Apple on the forum", source="valuepickr", hours=24 * 20, pid="vp:1"),
    ]
    kept = {p.id for p in ss.select_posts(posts, q, NOW)}
    assert kept == {"reddit:1", "st:1", "vp:1"}


def test_aggregate_scores_counts_and_buzz_excludes_stocktwits():
    posts = [post(f"AAPL to the moon {i}", hours=2 + i) for i in range(4)]
    posts += [post(f"AAPL bagholder crash {i}", hours=30 + 24 * i, score=1) for i in range(4)]
    posts += [post(f"$AAPL st {i}", source="stocktwits", hours=1, label="bullish") for i in range(30)]
    data = ss.aggregate(posts, NOW)
    assert data["posts"] == 38 and data["counts"]["bullish"] == 34 and data["counts"]["bearish"] == 4
    assert data["score"] > 30 and data["mood"] in ("bullish", "very bullish")
    # 4 non-StockTwits posts in the last 24h vs 4 over the 6 days before.
    assert data["buzz"]["last_24h"] == 4
    assert sum(t["posts"] for t in data["timeline"]) == 8
    assert data["by_source"][0]["source"] == "stocktwits"
    assert len(data["top_posts"]) == 15 and "excerpt" in data["top_posts"][0]


def test_aggregate_empty():
    data = ss.aggregate([], NOW)
    assert data["posts"] == 0 and data["mood"] is None and data["score"] == 0 and data["buzz"] is None


def test_themes():
    scored = [(post("earnings beat, guidance raised"), 0.6), (post("Q3 earnings miss"), -0.6), (post("buying calls"), 0.5)]
    names = {t["theme"]: t for t in ss.themes(scored)}
    assert names["Earnings"]["posts"] == 2 and names["Options activity"]["tone"] == "bullish"


# ------------------------------------------------------------ build + cache


def _fake_sources(calls):
    def good(query, config):
        calls.append(query.symbol)
        return [post("AAPL to the moon", source="stocktwits", hours=1), post("$AAPL bagholder", source="stocktwits", hours=3)]

    def blocked(query, config):
        raise SourceBlocked("blocked by network security")

    def skipped(query, config):
        raise SourceSkipped("not for this market")

    def chain(query, config):
        return [post("Apple breakout", hours=2, pid="reddit:x")], "feeds"

    return {"stocktwits": good, "reddit": chain, "valuepickr": skipped, "hackernews": blocked}


def test_build_statuses_cache_and_snapshot(tmp_path, monkeypatch):
    from src.data import news_search
    from src.storage import DatabaseManager

    monkeypatch.setattr(news_search, "company_name", lambda symbol, market: "Apple Inc.")

    db = DatabaseManager(f"sqlite:///{tmp_path / 'social.db'}")
    calls: list = []
    data = ss.build("aapl", "us", None, db, sources=_fake_sources(calls))
    status = {s["source"]: s for s in data["sources"]}
    assert status["reddit"]["via"] == "feeds" and status["reddit"]["posts"] == 1
    assert status["hackernews"]["status"] == "blocked" and status["valuepickr"]["status"] == "skipped"
    assert data["posts"] == 3 and data["symbol"] == "AAPL"
    assert len(data["history"]) == 1 and data["history"][0]["posts"] == 3

    ss.build("AAPL", "us", None, db, sources=_fake_sources(calls))
    assert len(calls) == 1  # cached
    ss.build("AAPL", "us", None, db, refresh=True, sources=_fake_sources(calls))
    ss.clear_cache()
    ss.build("AAPL", "us", None, db, sources=_fake_sources(calls))
    assert len(calls) >= 2
    assert len(ss.history(db, "AAPL", "us")) == 1  # one row per day, updated in place


# ----------------------------------------------------- Reddit fallback chain


class _Cfg:
    social_reddit_mode = "auto"
    social_playwright = True
    reddit_client_id = None
    reddit_client_secret = None
    reddit_user_agent = None


def test_reddit_methods_order():
    cfg = _Cfg()
    assert [n for n, _ in reddit.methods(cfg)] == ["search", "feeds", "rss"]
    cfg.reddit_client_id, cfg.reddit_client_secret = "id", "secret"
    assert [n for n, _ in reddit.methods(cfg)] == ["api", "search", "feeds", "rss"]
    cfg.social_reddit_mode = "api"
    assert [n for n, _ in reddit.methods(cfg)] == ["api"]
    cfg.social_reddit_mode, cfg.social_playwright = "auto", False
    assert [n for n, _ in reddit.methods(cfg)] == ["api", "rss"]


def test_reddit_falls_back_and_backs_off(monkeypatch):
    q = SocialQuery("TSLA", "us", name="Tesla")
    hits = {"search": 0, "feeds": 0}

    def search(query):
        hits["search"] += 1
        raise SourceBlocked("blocked by network security")

    def feeds(query):
        hits["feeds"] += 1
        return [post("TSLA squeeze"), post("unrelated")]

    monkeypatch.setattr(reddit, "methods", lambda config: [("search", search), ("feeds", feeds)])
    posts, via = reddit.fetch(q, _Cfg())
    assert via == "feeds" and len(posts) == 1
    reddit.fetch(q, _Cfg())
    assert hits == {"search": 1, "feeds": 2}  # search skipped while its breaker is open


def test_reddit_all_blocked_raises_and_empty_is_ok(monkeypatch):
    q = SocialQuery("TSLA", "us", name="Tesla")

    def blocked(query):
        raise SourceBlocked("429")

    monkeypatch.setattr(reddit, "methods", lambda config: [("search", blocked)])
    with pytest.raises(SourceBlocked):
        reddit.fetch(q, _Cfg())

    reddit.reset()
    monkeypatch.setattr(reddit, "methods", lambda config: [("search", lambda query: [])])
    assert reddit.fetch(q, _Cfg()) == ([], "search")


# ---------------------------------------------------------------- AI + API


def test_parse_summary():
    text = '```json\n{"summary": "Mixed.", "bull_points": ["AI demand", ""], "bear_points": ["valuation"], "hype_risk": "EXTREME"}\n```'
    out = ss._parse_summary(text)
    assert out["bull_points"] == ["AI demand"] and out["hype_risk"] == "low"
    assert ss._parse_summary('{"summary": ""}') is None


def test_social_endpoint(app_client, monkeypatch):
    seen = {}

    def fake_build(symbol, market, config, db, refresh):
        seen.update(symbol=symbol, market=market, refresh=refresh)
        return {"symbol": symbol.upper(), "posts": 0}

    monkeypatch.setattr(ss, "build", fake_build)
    client = app_client()
    r = client.get("/api/v1/stocks/aapl/social", params={"market": "us", "refresh": "true"})
    assert r.status_code == 200 and r.json()["symbol"] == "AAPL"
    assert seen == {"symbol": "aapl", "market": "us", "refresh": True}
