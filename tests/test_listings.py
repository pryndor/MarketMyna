"""Tests for the market listing store, query engine and AMFI parser (offline)."""

import threading
import time
from datetime import timedelta

import pytest

from marketmyna.data import listings
from marketmyna.data.listings import ListingStore, _row, query


def _rows():
    return [
        _row("RELIANCE", "Reliance Industries Limited", "india", "stock", sector="Oil Gas", market_cap=1.9e13, price=1400.0),
        _row("TCS", "Tata Consultancy Services Limited", "india", "stock", sector="IT", market_cap=1.2e13, price=3000.0),
        _row("TATAMOTORS", "Tata Motors Limited", "india", "stock", sector="Automobile", market_cap=2.5e12, price=700.0),
        _row("NIFTYBEES", "Nifty 50 ETF", "india", "etf", sector="ETF", price=280.0),
        _row("120503", "Axis ELSS Tax Saver Fund - Direct Plan - Growth", "india", "mf",
             sector="ELSS", price=100.0, plan="Direct", option="Growth"),
        _row("120504", "Axis ELSS Tax Saver Fund - Regular Plan - IDCW", "india", "mf",
             sector="ELSS", price=20.0, plan="Regular", option="IDCW"),
    ]


class TestQuery:
    def test_default_lists_everything_by_market_cap(self):
        res = query(_rows())
        assert res["total"] == 6
        assert [r["symbol"] for r in res["rows"][:3]] == ["RELIANCE", "TCS", "TATAMOTORS"]

    def test_type_filter(self):
        res = query(_rows(), type_="mf")
        assert {r["symbol"] for r in res["rows"]} == {"120503", "120504"}

    def test_search_ranks_symbol_over_name(self):
        res = query(_rows(), q="tata")
        assert [r["symbol"] for r in res["rows"]] == ["TATAMOTORS", "TCS"]

    def test_multi_word_search(self):
        res = query(_rows(), q="axis direct")
        assert [r["symbol"] for r in res["rows"]] == ["120503"]

    def test_sector_filter_keeps_facets(self):
        res = query(_rows(), sector="IT")
        assert [r["symbol"] for r in res["rows"]] == ["TCS"]
        assert {f["value"] for f in res["facets"]["sectors"]} >= {"IT", "Oil Gas", "ELSS"}

    def test_sort_asc_puts_blanks_last(self):
        res = query(_rows(), sort="price", order="asc")
        prices = [r["price"] for r in res["rows"]]
        assert prices == sorted(prices)

    def test_pagination(self):
        res = query(_rows(), sort="symbol", order="asc", offset=2, limit=2)
        assert res["total"] == 6
        assert len(res["rows"]) == 2

    def test_mf_plan_option_filters(self):
        res = query(_rows(), type_="mf", plan="Direct", option="growth")
        assert [r["symbol"] for r in res["rows"]] == ["120503"]


class TestAmfiParser:
    SAMPLE = (
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date\r\n"
        " \r\n"
        "Open Ended Schemes(Equity Scheme - Large Cap Fund)\r\n"
        " \r\n"
        "Axis Mutual Fund\r\n"
        " \r\n"
        "120465;INF846K01EW2;-;Axis Large Cap Fund;Direct Plan;Growth Option;65.12;24-Sep-2026\r\n"
        "Close Ended Schemes(Income/Debt Oriented Schemes - Fixed Term Plan)\r\n"
        "UTI Mutual Fund\r\n"
        "100001;INF789F01AAA;-;UTI FTP Series 1;Regular Plan;IDCW;10.5;24-Sep-2026\r\n"
    )

    def test_parses_schemes_with_category_and_amc(self, monkeypatch):
        class Resp:
            content = self.SAMPLE.encode()

        monkeypatch.setattr(listings, "_get", lambda url, **kw: Resp())
        rows = listings.fetch_india_mutual_funds()
        assert len(rows) == 2
        first, second = rows
        assert first["symbol"] == "120465"
        assert first["name"] == "Axis Large Cap Fund - Direct Plan - Growth Option"
        assert first["sector"] == "Large Cap Fund"
        assert first["fund_group"] == "Equity"
        assert first["exchange"] == "Axis"
        assert first["plan"] == "Direct"
        assert first["price"] == 65.12
        assert second["fund_group"] == "Income/Debt Oriented"
        assert second["sector"] == "Fixed Term Plan (Close Ended)"


class TestStore:
    def _store(self, tmp_path, fetch):
        return ListingStore(
            cache_dir=tmp_path,
            providers={"x": ("india", fetch, timedelta(hours=1))},
        )

    def test_fetches_once_then_serves_from_memory_and_disk(self, tmp_path):
        calls = []

        def fetch():
            calls.append(1)
            return _rows()

        store = self._store(tmp_path, fetch)
        assert len(store.rows("india")) == 6
        assert len(store.rows("india")) == 6
        assert len(calls) == 1
        # A fresh store (new process) reads the disk cache without fetching.
        assert len(self._store(tmp_path, fetch).rows("india")) == 6
        assert len(calls) == 1

    def test_failure_backs_off(self, tmp_path):
        calls = []

        def fetch():
            calls.append(1)
            raise RuntimeError("offline")

        store = self._store(tmp_path, fetch)
        assert store.rows("india") == []
        assert store.rows("india") == []
        assert len(calls) == 1
        assert store.status()[0]["error"] == "offline"

    def test_forced_refresh_at_most_every_few_minutes(self, tmp_path, monkeypatch):
        import marketmyna.data.listings as L

        calls = []

        def fetch():
            calls.append(1)
            return _rows()

        store = self._store(tmp_path, fetch)
        store.rows("india", force=True)
        store.rows("india", force=True)  # a second click right away is served from cache
        assert len(calls) == 1
        monkeypatch.setattr(L, "_FORCE_GAP", 0.0)
        store.rows("india", force=True)
        assert len(calls) == 2

    def test_all_market_merges_providers(self, tmp_path):
        store = ListingStore(
            cache_dir=tmp_path,
            providers={
                "a": ("india", lambda: _rows()[:2], timedelta(hours=1)),
                "b": ("us", lambda: [_row("AAPL", "Apple", "us", "stock")], timedelta(hours=1)),
            },
        )
        assert len(store.rows("all")) == 3
        assert len(store.rows("us")) == 1

    def test_wait_skips_slow_providers_until_loaded(self, tmp_path):
        release = threading.Event()

        def slow():
            release.wait(10)
            return [_row("600519", "Kweichow Moutai", "china", "stock")]

        store = ListingStore(
            cache_dir=tmp_path,
            providers={
                "a": ("india", lambda: _rows()[:2], timedelta(hours=1)),
                "b": ("china", slow, timedelta(hours=1)),
            },
        )
        started = time.monotonic()
        assert len(store.rows("all", wait=0.2)) == 2
        assert time.monotonic() - started < 2
        release.set()
        for _ in range(50):  # the slow provider finishes in the background
            if len(store.rows("all", wait=0.2)) == 3:
                break
            time.sleep(0.1)
        assert len(store.rows("all", wait=0.2)) == 3


fastapi_testclient = pytest.importorskip("fastapi.testclient")


class TestListingsApi:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi import FastAPI

        from marketmyna.api.v1.endpoints import listings as endpoint

        store = ListingStore(
            cache_dir=tmp_path,
            providers={"india_stocks": ("india", _rows, timedelta(hours=1))},
        )
        monkeypatch.setattr(endpoint, "get_store", lambda: store)
        app = FastAPI()
        app.include_router(endpoint.router, prefix="/api/v1")
        return fastapi_testclient.TestClient(app)

    def test_list(self, client):
        res = client.get("/api/v1/listings", params={"market": "india", "type": "stock"})
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 3
        assert body["sources"][0]["count"] == 6

    def test_search(self, client):
        res = client.get("/api/v1/listings/search", params={"q": "rel", "market": "india"})
        assert res.status_code == 200
        assert res.json()[0]["symbol"] == "RELIANCE"

    def test_unknown_market(self, client):
        assert client.get("/api/v1/listings", params={"market": "mars"}).status_code == 400


def test_mixed_currency_market_cap_ranks_in_usd():
    rows = [
        _row("RELIANCE", "Reliance", "india", "stock", market_cap=1.6e13, currency="INR"),  # ~$180B
        _row("AAPL", "Apple", "us", "stock", market_cap=3.5e12, currency="USD"),
        _row("SMALL", "Small Co", "us", "stock", market_cap=1e9, currency="USD"),
    ]
    assert [r["symbol"] for r in query(rows)["rows"]] == ["AAPL", "RELIANCE", "SMALL"]


class TestAdvancedFilters:
    def _rows(self):
        from marketmyna.data.categories import enrich

        return enrich([
            _row("INFY", "Infosys Limited", "india", "stock", sector="Information Technology",
                 price=1500.0, change_percent=2.5, market_cap=6e12, volume=5e6, high_52w=1550.0, low_52w=1200.0, currency="INR"),
            _row("KRBL", "KRBL Limited", "india", "stock", sector="Fast Moving Consumer Goods",
                 price=40.0, change_percent=-1.0, market_cap=8e10, volume=1e5, high_52w=90.0, low_52w=38.0, currency="INR"),
            _row("DHANUKA", "Dhanuka Agritech Limited", "india", "stock", sector=None,
                 price=90.0, change_percent=6.0, market_cap=4e9, volume=2e4, currency="INR"),
            _row("NMDC", "NMDC Steel Limited", "india", "stock", sector=None, price=45.0, currency="INR"),
            _row("ADM", "Archer-Daniels-Midland", "us", "stock", sector="Consumer Staples",
                 industry="Farming/Seeds/Milling", price=60.0, market_cap=30e9, currency="USD"),
        ])

    def test_categories_resolved_from_sector_industry_and_name(self):
        cats = {r["symbol"]: (r["category"], r["category_inferred"]) for r in self._rows()}
        assert cats["INFY"] == ("Technology", False)
        assert cats["ADM"] == ("Agriculture", False)
        assert cats["DHANUKA"] == ("Agriculture", True)
        assert cats["NMDC"] == ("Natural Resources", True)

    def test_category_filter_and_facets(self):
        res = query(self._rows(), categories=["Agriculture"])
        assert {r["symbol"] for r in res["rows"]} == {"DHANUKA", "ADM"}
        facet = {f["value"] for f in res["facets"]["categories"]}
        assert {"Technology", "Agriculture", "Natural Resources"} <= facet

    def test_price_range(self):
        res = query(self._rows(), price_max=50)
        assert {r["symbol"] for r in res["rows"]} == {"KRBL", "NMDC"}
        res = query(self._rows(), price_min=100, price_max=5000)
        assert [r["symbol"] for r in res["rows"]] == ["INFY"]

    def test_cap_bands(self):
        res = query(self._rows(), cap_sizes=["large"])
        assert {r["symbol"] for r in res["rows"]} == {"INFY", "ADM"}
        res = query(self._rows(), cap_sizes=["micro"])
        assert [r["symbol"] for r in res["rows"]] == ["DHANUKA"]

    def test_change_volume_and_52w(self):
        assert [r["symbol"] for r in query(self._rows(), change_min=5)["rows"]] == ["DHANUKA"]
        assert [r["symbol"] for r in query(self._rows(), min_volume=1e6)["rows"]] == ["INFY"]
        assert [r["symbol"] for r in query(self._rows(), near_high=5)["rows"]] == ["INFY"]
        assert [r["symbol"] for r in query(self._rows(), near_low=10)["rows"]] == ["KRBL"]


def test_mega_cap_band():
    rows = [
        _row("NVDA", "Nvidia", "us", "stock", market_cap=4e12, currency="USD"),
        _row("IBM", "IBM", "us", "stock", market_cap=150e9, currency="USD"),
        _row("RELIANCE", "Reliance", "india", "stock", market_cap=1.6e13, currency="INR"),  # ~$180B
    ]
    assert [r["symbol"] for r in query(rows, cap_sizes=["mega"])["rows"]] == ["NVDA"]
    assert {r["symbol"] for r in query(rows, cap_sizes=["large"])["rows"]} == {"IBM", "RELIANCE"}


def test_chinese_industries_map_to_categories():
    from marketmyna.data.categories import enrich

    rows = enrich([
        _row("688825", "长鑫科技", "china_a", "stock", sector="半导体"),
        _row("601398", "工商银行", "china_a", "stock", sector="银行Ⅱ"),
        _row("601088", "中国神华", "china_a", "stock", sector="煤炭开采"),
        _row("300750", "宁德时代", "china_a", "stock", sector="电池"),
        _row("002714", "牧原股份", "china_a", "stock", sector="养殖业"),
        _row("600900", "长江电力", "china_a", "stock", sector="电力"),
    ])
    assert [r["category"] for r in rows] == [
        "Technology", "Financials", "Natural Resources", "Industrials", "Agriculture", "Energy",
    ]


def test_names_only_fetch_retries_soon(tmp_path):
    store = ListingStore(
        cache_dir=tmp_path,
        providers={"hk": ("hong_kong", lambda: [_row("00700", "Tencent", "hong_kong", "stock")], timedelta(hours=4))},
    )
    assert len(store.rows("hong_kong")) == 1
    status = store.status()[0]
    assert status["error"].startswith("Prices temporarily unavailable")
    assert status["stale"] is False


def test_china_hk_fallbacks(monkeypatch):
    from marketmyna.data import listings as L

    L._eastmoney_blocked_until = 0.0
    calls = {"em": 0}

    def blocked(fs, page, quick=False):
        calls["em"] += 1
        raise RuntimeError("blocked")

    monkeypatch.setattr(L, "_eastmoney_page", blocked)
    monkeypatch.setattr(L, "_sina_pages", lambda method, node, max_pages=80: [
        {"code": "601288", "name": "农业银行", "trade": "6.87", "pricechange": 0.04, "changepercent": 0.586,
         "volume": 1000, "mktcap": 240440000, "per": 7.1, "pb": 0.7},
    ])
    rows = L.enrich(L.fetch_china_a())
    assert rows[0]["price"] == 6.87 and rows[0]["market_cap"] == 2.4044e12
    assert rows[0]["category"] == "Financials"  # 农 in 农业银行 must not mean Agriculture
    # Eastmoney is now skipped without another network attempt.
    L.fetch_china_a()
    assert calls["em"] == 1

    monkeypatch.setattr(L, "_tencent_hk_quotes", lambda codes: {"00700": {"name": "腾讯控股", "price": 436.6,
                                                                          "market_cap": 3.97e12, "high_52w": 677.7}})
    quotes, source = L._hong_kong_quotes(["00700"])
    assert source == "Tencent" and quotes["00700"]["price"] == 436.6
    L._eastmoney_blocked_until = 0.0


def test_china_a_tencent_refresh_from_cache(monkeypatch):
    from marketmyna.data import listings as L

    monkeypatch.setattr(L, "_eastmoney_rows", lambda market: (_ for _ in ()).throw(RuntimeError("blocked")))
    monkeypatch.setattr(L, "_sina_china_a", lambda: (_ for _ in ()).throw(RuntimeError("timeout")))
    monkeypatch.setattr(L, "_sina_china_funds", lambda: (_ for _ in ()).throw(RuntimeError("timeout")))
    monkeypatch.setattr(L, "_cached_rows", lambda key: [{"symbol": "600519", "name": "贵州茅台"},
                                                        {"symbol": "510300", "name": "沪深300ETF", "type": "etf"}])
    fields = ["1", "贵州茅台", "600519", "1237.00", "1251.24", "1250.01", "31239"] + ["0"] * 24 + \
        ["-14.24", "-1.14", "1256.13", "1231.05"] + ["0"] * 4 + ["18.99"] + ["0"] * 4 + ["15463.51", "15463.51", "6.15"]
    monkeypatch.setattr(L, "_tencent_quote_lines", lambda symbols, batch_size=60: iter([fields]))
    rows = L.fetch_china_a()
    row = rows[0]
    assert [r["symbol"] for r in rows] == ["600519", "510300"]  # cached ETF kept, not re-quoted as a stock
    assert row["price"] == 1237.0 and row["volume"] == 3123900
    assert row["market_cap"] == 15463.51e8 and row["pe"] == 18.99 and row["pb"] == 6.15


def test_china_a_funds_join_stock_list(monkeypatch):
    from marketmyna.data import listings as L

    monkeypatch.setattr(L, "_fetch_china_a_stocks", lambda: [L._row("600519", "贵州茅台", "china_a", L.STOCK)])
    pages = {"etf_hq_fund": [{"code": "510300", "name": "沪深300ETF", "trade": "4.1", "mktcap": 100}],
             "lof_hq_fund": [{"code": "161129", "name": "原油基金", "trade": "1.9"}]}
    monkeypatch.setattr(L, "_sina_pages", lambda method, node, max_pages=80: pages[node])
    rows = {r["symbol"]: r for r in L.fetch_china_a()}
    assert rows["510300"]["type"] == "etf" and rows["510300"]["sector"] == "ETF" and rows["510300"]["exchange"] == "SSE"
    assert rows["161129"]["sector"] == "LOF" and rows["161129"]["exchange"] == "SZSE"
    assert rows["510300"]["market_cap"] == 1e6


def test_india_reits_and_invits_are_listed_as_units():
    import io
    import zipfile
    from datetime import datetime

    from marketmyna.data import listings as L

    pd_csv = ("SYMBOL,SERIES,SECURITY,CLOSE_PRICE,PREV_CL_PR,NET_TRDQTY,HI_52_WK,LO_52_WK\n"
              "EMBASSY,RR,EMBASSY OFFICE PARKS REIT,435.30,430.00,1000,462.00,350.00\n"
              "INDIGRID,IV,INDIGRID INFRASTRUCT TRST,168.96,169.00,500,180.90,140.00\n"
              "RELIANCE,EQ,RELIANCE INDUSTRIES,1178.00,1207.70,9000,1600,1100\n")
    mcap_csv = ("Symbol,Series,Security Name,Close Price/Paid up value(Rs.),Market Cap(Rs.)\n"
                "EMBASSY,RR,EMBASSY OFFICE PARKS REIT,435.30,412618146327.90\n"
                "INDIGRID,IV,INDIGRID INFRASTRUCT TRST,168.96,160945334922.25\n"
                "CUBEINVIT,IV,CUBE HIGHWAYS TRUST,154.85,200000000000\n"
                "RELIANCE,EQ,RELIANCE INDUSTRIES,1178.00,1\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("pd07102026.csv", pd_csv)
        z.writestr("mcap07102026.csv", mcap_csv)
    rows = {r["symbol"]: r for r in L._india_trusts(zipfile.ZipFile(buf), datetime(2026, 10, 7))}

    assert set(rows) == {"EMBASSY", "INDIGRID", "CUBEINVIT"}  # shares stay out; untraded trusts stay in
    assert rows["EMBASSY"]["name"] == "Embassy Office Parks REIT" and rows["EMBASSY"]["sector"] == "REIT"
    assert rows["EMBASSY"]["change_percent"] == 1.23 and rows["EMBASSY"]["type"] == "stock"
    assert rows["CUBEINVIT"]["name"] == "Cube Highways Trust" and rows["CUBEINVIT"]["price"] == 154.85
    assert rows["INDIGRID"]["sector"] == "InvIT"
