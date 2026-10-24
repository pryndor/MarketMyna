"""Hot stocks per login area: trader boards from today's prices, investor
boards from fundamentals plus where price sits in its yearly range."""

from src.services import hot_stocks as hot


def _stock(symbol, change, price=100.0, volume=1_000, cap=1e6, hi=120.0, lo=80.0, **extra):
    return {"symbol": symbol, "name": symbol, "type": "stock", "price": price, "change_percent": change,
            "volume": volume, "market_cap": cap, "high_52w": hi, "low_52w": lo, "category": "Tech", **extra}


def _board(out, key):
    return [r["symbol"] for r in next(b for b in out["boards"] if b["key"] == key)["rows"]]


def test_trader_boards():
    rows = [_stock(f"F{i}", 0.1) for i in range(30)]  # quiet filler sets the typical activity
    rows += [
        _stock("MOVE", 5.0, volume=3_000),
        _stock("HIGH", 1.2, price=121, hi=121),
        _stock("BUSY", 0.5, volume=10_000),
        _stock("BOUNCE", 3.0, price=84, lo=80, volume=2_000),
        _stock("BREAK", -2.0, price=80, lo=80.5, volume=2_000),
    ]
    out = hot.trader("us", rows=rows)
    assert "MOVE" in _board(out, "momentum") and "F0" not in _board(out, "momentum")
    assert _board(out, "breakouts")[0] == "HIGH"
    assert _board(out, "activity")[0] == "BUSY"
    assert "BOUNCE" in _board(out, "bounces")
    assert _board(out, "breakdowns") == ["BREAK"]
    row = next(b for b in out["boards"] if b["key"] == "activity")["rows"][0]
    assert "usual activity" in row["why"] and "buy" not in row["why"].lower()


def test_investor_boards():
    infos = {
        "DIP": {"returnOnEquity": 0.25, "debtToEquity": 40, "earningsGrowth": 0.1},
        "GROW": {"returnOnEquity": 0.12, "earningsGrowth": 0.4, "revenueGrowth": 0.2},
        "JUNK": {"returnOnEquity": -0.05, "earningsGrowth": -0.3},
    }
    rows = [
        _stock("DIP", -1, price=90, hi=120),     # 25% off the high
        _stock("GROW", 2, price=115, hi=120),    # 4% off the high
        _stock("JUNK", -3, price=81, hi=120),
    ]
    out = hot.investor("us", rows=rows, info_fetch=lambda sym: {**infos[sym], "longName": sym}, use_cache=False)
    assert _board(out, "quality_dip") == ["DIP"]
    assert _board(out, "earnings") == ["GROW"]
    assert all("JUNK" not in b["rows"] for b in out["boards"])


def test_crypto_investor_uses_price_range():
    rows = [{"symbol": "AAA", "type": "crypto", "price": 50, "volume": 10, "change_percent": 1, "high_52w": 100, "low_52w": 40},
            {"symbol": "BBB", "type": "crypto", "price": 95, "volume": 10, "change_percent": 1, "high_52w": 100, "low_52w": 40}]
    out = hot.investor("crypto", rows=rows, use_cache=False)
    assert _board(out, "crypto_dips") == ["AAA"] and _board(out, "crypto_strong") == ["BBB"]
