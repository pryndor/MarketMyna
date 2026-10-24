"""Market-insight tabs for US / Hong Kong / China A / crypto: oil sensitivity,
rates, crypto screens, ETF and crypto rotation, big trades. No network:
every fetcher is faked."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from marketmyna.services import (
    big_trades,
    crude_sensitivity,
    crypto_screens,
    etf_rotation,
    rates,
    rotation,
)

DAYS = pd.bdate_range(end=pd.Timestamp(date.today()), periods=520)


def walk(seed: int, drift: float = 0.0, n: int = len(DAYS), start: float = 100.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(start * np.exp(np.cumsum(rng.normal(drift, 0.01, n))), index=DAYS[-n:])


# ---------------------------------------------------------------- oil


def test_crude_sensitivity_us_uses_index_and_wti_without_fx():
    crude = walk(1)
    index = walk(2)

    def fetch(tickers):
        assert "CL=F" in tickers and "^GSPC" in tickers and "USDINR=X" not in tickers
        out = {"CL=F": crude, "^GSPC": index}
        for i, t in enumerate(tickers):
            if t not in out:
                out[t] = index * 0.5 + crude * (0.6 if t in ("XOM", "COP") else -0.4) + walk(10 + i) * 0.1
        return out

    data = crude_sensitivity.build(fetch, use_cache=False, market="us")
    assert data["crude_label"] == "WTI" and data["index_name"] == "S&P 500" and data["groups"]
    betas = {s["symbol"]: s["beta_crude"] for g in data["groups"] for s in g["stocks"]}
    assert betas["XOM"] > 0 > betas["DAL"]
    assert "brent_inr" not in data


def test_crude_sensitivity_hk_symbols_map_to_yahoo():
    seen = []

    def fetch(tickers):
        seen.extend(tickers)
        return {}

    out = crude_sensitivity.build(fetch, use_cache=False, market="hong_kong")
    assert "0857.HK" in seen and "HKD=X" in seen and out["groups"] == []
    assert "error" in crude_sensitivity.build(fetch, use_cache=False, market="crypto")


# ---------------------------------------------------------------- rates


def test_rate_item_changes():
    s = pd.Series([1.0] * 300 + [2.0] * 100, index=pd.date_range(end=pd.Timestamp(date.today()), periods=400))
    i = rates.item("x", s, "%")
    assert i["value"] == 2.0 and i["change_1y"] == pytest.approx(1.0) and i["change_1m"] == 0
    p = rates.item("p", s, "$", change="pct")
    assert p["change_1y"] == pytest.approx(100.0)
    assert rates.item("none", None, "%") is None


def test_rates_crypto_funding_falls_back_and_annualises():
    def binance():
        raise RuntimeError("451 restricted location")

    def bybit():
        return [{"coin": "BTC", "rate_8h": 0.0001, "mark": 1.0, "next": 0}]

    def yahoo(tickers):
        return {"BTC-USD": walk(3, start=80000), "GC=F": walk(4, start=4000)}

    out = rates._crypto(yahoo=yahoo, funding_sources=(binance, bybit))
    funding = next(s for s in out["sections"] if s["title"].startswith("Perpetual"))
    assert funding["items"][0]["value"] == pytest.approx(10.95, abs=0.1) and "Crypto exchange" in funding["source"]  # the fallback exchange's value (Bybit mock)
    assert any(s["title"] == "Bitcoin vs gold" for s in out["sections"])


def test_rates_unknown_market():
    assert rates.build("mars", use_cache=False)["sections"] == []


# ------------------------------------------------------- crypto screens


def test_crypto_universe_drops_stables_and_ranks_by_volume():
    rows = [{"symbol": "USDT-USD", "volume": 9e12}, {"symbol": "PAXG-USD", "volume": 9e11},
            {"symbol": "ETH-USD", "volume": 5}, {"symbol": "DOGE-USD", "volume": 9}, {"symbol": "X-EUR", "volume": 99}]
    assert [c["symbol"] for c in crypto_screens.universe(rows)] == ["DOGE-USD", "ETH-USD", "BTC-USD"]


def test_crypto_metrics_and_presets():
    up = pd.Series(np.linspace(100, 200, 120), index=DAYS[-120:])
    down = pd.Series(np.linspace(200, 90, 120), index=DAYS[-120:])
    m_up = crypto_screens.metrics(up, btc_30d=5.0)
    assert m_up["ret_30d"] > 10 and m_up["above_ma50"] > 0 and m_up["vs_btc_30d"] > 0 and m_up["from_high_90d"] == 0
    assert crypto_screens.metrics(down, None)["rsi14"] < 35

    rows = [{"symbol": "AAA-USD", "volume": 10, "price": 2}, {"symbol": "BBB-USD", "volume": 5, "price": 1}]
    flat = pd.Series(np.full(120, 50000.0), index=DAYS[-120:])
    fetch = lambda t: {"AAA-USD": up, "BBB-USD": down, "BTC-USD": flat}  # noqa: E731
    res = crypto_screens.run("momentum", fetch=fetch, rows=rows, use_cache=False)
    assert [r["symbol"] for r in res["results"]] == ["AAA-USD"]
    assert [r["symbol"] for r in crypto_screens.run("oversold", fetch=fetch, rows=rows, use_cache=False)["results"]] == ["BBB-USD"]
    with pytest.raises(ValueError):
        crypto_screens.run("nope", fetch=fetch, rows=rows, use_cache=False)


# ------------------------------------------------------------ rotation


def test_etf_rotation_views_and_app_symbols():
    def fetch(tickers):
        return {t: walk(i, drift=0.0005 * (i % 3)) for i, t in enumerate(tickers)}

    out = etf_rotation.build("hong_kong", "Global", fetch=fetch, use_cache=False)
    assert out["groups"] == ["Hong Kong & China", "Global"] and len(out["items"]) == 4
    assert {i["symbol"] for i in out["items"]} >= {"02834", "02840"}
    assert etf_rotation.app_symbol("510300.SS", "china_a") == "510300"
    with pytest.raises(ValueError):
        etf_rotation.build("crypto", fetch=fetch, use_cache=False)
    with pytest.raises(ValueError):
        etf_rotation.build("us", "Nope", fetch=fetch, use_cache=False)


def test_crypto_rotation_groups_vs_btc():
    def fetch(tickers):
        return {t: walk(i, n=300) for i, t in enumerate(tickers)}

    out = rotation.build_crypto(fetch=fetch, use_cache=False)
    assert out["benchmark"]["name"] == "Bitcoin"
    assert {s["sector"] for s in out["sectors"]} == set(rotation.CRYPTO_GROUPS)
    assert all(s["quadrant"] in ("leading", "weakening", "lagging", "improving") for s in out["sectors"])


# ---------------------------------------------------------- big trades

FORM4 = """<?xml version="1.0"?><ownershipDocument>
 <issuer><issuerName>Acme Corp</issuerName><issuerTradingSymbol>acme</issuerTradingSymbol></issuer>
 <reportingOwner><reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
  <reportingOwnerRelationship><isDirector>1</isDirector><isOfficer>1</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship>
 </reportingOwner>
 <nonDerivativeTable>
  <nonDerivativeTransaction><transactionDate><value>2026-10-01</value></transactionDate>
   <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
   <transactionAmounts><transactionShares><value>100</value></transactionShares><transactionPricePerShare><value>10</value></transactionPricePerShare></transactionAmounts>
  </nonDerivativeTransaction>
  <nonDerivativeTransaction><transactionDate><value>2026-10-01</value></transactionDate>
   <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
   <transactionAmounts><transactionShares><value>300</value></transactionShares><transactionPricePerShare><value>20</value></transactionPricePerShare></transactionAmounts>
  </nonDerivativeTransaction>
  <nonDerivativeTransaction><transactionDate><value>2026-10-01</value></transactionDate>
   <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
   <transactionAmounts><transactionShares><value>5000</value></transactionShares></transactionAmounts>
  </nonDerivativeTransaction>
 </nonDerivativeTable></ownershipDocument>"""


def test_parse_form4_keeps_open_market_trades_only():
    [row] = big_trades.parse_form4(FORM4)
    assert (row["symbol"], row["side"], row["qty"], row["value"]) == ("ACME", "sell", 400, 7000)
    assert row["price"] == pytest.approx(17.5) and row["client"] == "Doe Jane" and row["remarks"] == "Director, CEO"


def test_parse_feed_dedupes_accessions():
    feed = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><link href="https://www.sec.gov/Archives/edgar/data/111/000111222333444555/x-index.htm"/></entry>
      <entry><link href="https://www.sec.gov/Archives/edgar/data/999/000111222333444555/x-index.htm"/></entry>
      <entry><link href="https://www.sec.gov/Archives/edgar/data/222/000999888777666555/y-index.htm"/></entry></feed>"""
    assert big_trades.parse_feed(feed) == [("111", "000111222333444555"), ("222", "000999888777666555")]


def test_us_big_trades_need_sec_user_agent(monkeypatch):
    from marketmyna.services.sec_mdna import SecNotConfigured

    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(SecNotConfigured):
        big_trades.build("us", use_cache=False)


def test_china_blocks_and_hk_southbound():
    blocks = [
        {"SECURITY_TYPE_WEB": "1", "TRADE_DATE": "2026-09-30 00:00:00", "SECURITY_CODE": "600000", "SECURITY_NAME_ABBR": "X",
         "BUYER_NAME": "A", "SELLER_NAME": "B", "PREMIUM_RATIO": -0.05, "DEAL_VOLUME": 10, "DEAL_PRICE": 2, "DEAL_AMT": 20},
        {"SECURITY_TYPE_WEB": "3", "TRADE_DATE": "2026-09-30 00:00:00", "SECURITY_CODE": "510300"},
    ]
    [b] = big_trades.parse_blocks(blocks)
    assert b["side"] == "discount" and b["remarks"] == "-5.0% vs close" and b["client"] == "A ← B"

    def fetch(url, params):
        return {"result": {"data": [
            {"TRADE_DATE": "2026-09-30 00:00:00", "SECURITY_CODE": "00700", "SECURITY_NAME": "T", "NET_BUY_AMT": -5e8,
             "BUY_AMT": 1e8, "SELL_AMT": 6e8, "CLOSE_PRICE": 400},
            {"TRADE_DATE": "2026-09-20 00:00:00", "SECURITY_CODE": "00001", "SECURITY_NAME": "old", "NET_BUY_AMT": 9e9},
        ]}}

    out = big_trades._hong_kong(1, fetch=fetch, names={"00700": "Tencent"})
    assert [d["symbol"] for d in out["deals"]] == ["00700", "00700"]  # both links, old day dropped
    assert out["deals"][0]["side"] == "net sell" and out["deals"][0]["value"] == 5e8


def test_crypto_positioning():
    def fetch(url, params):
        if "topLongShort" in url:
            return [{"longAccount": "0.6", "longShortRatio": "1.5"}, {"longAccount": "0.65", "longShortRatio": "1.86"}]
        if "openInterestHist" in url:
            return [{"sumOpenInterestValue": "100"}, {"sumOpenInterestValue": "110"}, {"sumOpenInterestValue": "121"}]
        return [{"buySellRatio": "1.07"}]

    row = big_trades._coin_positioning("BTC", fetch)
    assert row["top_long_pct"] == 65.0 and row["top_ratio_change"] == pytest.approx(0.36)
    assert row["oi_change_1d"] == pytest.approx(10.0) and row["oi_change_7d"] == pytest.approx(21.0)
    with pytest.raises(ValueError):
        big_trades.build("mars", use_cache=False)
