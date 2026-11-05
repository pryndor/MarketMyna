import pytest

from marketmyna.data import listings as lst
from marketmyna.services import live_quotes


def _q(symbol, currency, price, short="X", long=None, shares=1000.0, **kw):
    return {"symbol": symbol, "currency": currency, "regularMarketPrice": price, "shortName": short,
            "longName": long or short, "sharesOutstanding": shares, "regularMarketChange": 10.0,
            "regularMarketChangePercent": 1.0, "fiftyTwoWeekHigh": price * 2, "fiftyTwoWeekLow": price / 2,
            "regularMarketVolume": 5.0, **kw}


def test_pence_become_pounds():
    r = lst.world_row(_q("HSBA.L", "GBp", 1337.0, "HSBC HOLDINGS"), "uk")
    assert r["price"] == 13.37 and r["currency"] == "GBP"
    assert r["change"] == 0.1 and r["high_52w"] == 26.74
    assert r["market_cap"] == pytest.approx(13370.0)
    assert r["market"] == "uk" and r["type"] == "stock"


def test_agorot_become_shekels():
    r = lst.world_row(_q("TEVA.TA", "ILA", 13240.0), "israel")
    assert r["price"] == 132.4 and r["currency"] == "ILS"


def test_lines_in_another_currency_are_left_out():
    assert lst.world_row(_q("TYT.L", "JPY", 3533.0), "uk") is None


def test_depositary_lines_are_tagged_without_parent_market_cap():
    r = lst.world_row(_q("AAPL.TO", "CAD", 49.0, "APPLE CDR (CAD HEDGED)", "Apple Inc.", shares=1.5e10), "canada")
    assert r["name"] == "Apple Inc. (CDR)" and r["market_cap"] is None
    r = lst.world_row(_q("HTCD.SI", "SGD", 5.0, "h Tencent HK SDR 10to1", "Tencent Holdings Limited"), "singapore")
    assert r["name"].endswith("(SDR)")


def test_fetch_world_pages_until_total():
    pages = []

    def screen(offset):
        pages.append(offset)
        quotes = [_q(f"S{offset + i}.AX", "AUD", 1.0 + i) for i in range(lst.SCREEN_PAGE if offset == 0 else 3)]
        return {"total": lst.SCREEN_PAGE + 3, "quotes": quotes}

    rows = lst.fetch_world("australia", screen=screen, sectors={"S0.AX": "Energy"})
    assert pages == [0, lst.SCREEN_PAGE] and len(rows) == lst.SCREEN_PAGE + 3
    assert rows[0]["sector"] == "Energy" and rows[1]["sector"] is None


def test_world_sectors_from_sector_queries():
    lst._world_sectors.pop("uk", None)

    def screen_for(sector):
        return lambda offset: {"total": 1, "quotes": [{"symbol": f"{sector[:3].upper()}.L"}]} if sector in (
            "Energy", "Industrials") else {"total": 0, "quotes": []}

    got = lst.world_sectors("uk", screen_for=screen_for)
    assert got == {"ENE.L": "Energy", "IND.L": "Industrials"}
    lst._world_sectors.pop("uk", None)


def test_feed_sector_names_map_to_categories():
    from marketmyna.data.categories import classify

    for sector, category in (("Consumer Cyclical", "Consumer"), ("Communication Services", "Telecom & Media"),
                             ("Industrials", "Industrials"), ("Financial Services", "Financials")):
        assert classify({"sector": sector, "name": "Rolls-Royce Holdings plc", "type": "stock"}) == (category, False)


def test_world_markets_are_listing_markets():
    for m in lst.WORLD_MARKETS:
        assert m in lst.MARKET_LABELS and m in lst.PROVIDERS


def test_live_prices_scale_minor_units():
    assert live_quotes._minor_divisor("uk", "HSBA.L") == 100.0
    assert live_quotes._minor_divisor("israel", "TEVA.TA") == 100.0
    assert live_quotes._minor_divisor("canada", "SHOP.TO") == 1.0
    assert "uk" in live_quotes.REFRESH
