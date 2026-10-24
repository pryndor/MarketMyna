"""Stock overview for the Analyze page: every computed fact about one
stock - technicals, trend, returns, risk, fundamentals, analysts, events,
profile and news - without any AI call.

Each section is built independently and best-effort: a missing source
(e.g. no fundamentals for crypto) yields {"error": ...} for that section
only, never a failed page.
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from ..core.numbers import finite as _num

logger = logging.getLogger(__name__)


def _pct_change(series, bars: int) -> Optional[float]:
    if len(series) <= bars:
        return None
    past = float(series.iloc[-bars - 1])
    return (float(series.iloc[-1]) / past - 1) * 100 if past else None


def _section(fn: Callable[[], dict]) -> dict:
    try:
        return fn()
    except Exception as exc:
        logger.info("Overview section failed: %s", exc)
        return {"error": str(exc) or type(exc).__name__}


def _technical(history) -> dict:
    from ..analysis.technical import TechnicalAnalyzer

    if history is None or len(history) < 30:
        raise ValueError("not enough price history for indicators")
    close = history["close"].astype(float)
    last = float(close.iloc[-1])
    summary = TechnicalAnalyzer(history).get_summary()

    notes = {
        "rsi": "Momentum 0-100: below 30 oversold, above 70 overbought",
        "macd": "Trend momentum; reads bullish or bearish as MACD crosses its signal line",
        "ma": "Price vs 20- and 50-day averages (value shown: 20-day average)",
        "bollinger": "Position inside the Bollinger band, % (0 = lower band, 100 = upper band)",
        "stochastic": "Where the close sits in the recent range: below 20 oversold, above 80 overbought",
    }
    indicators = [
        {"key": key, "name": {"rsi": "RSI (14)", "macd": "MACD", "ma": "Moving averages",
                              "bollinger": "Bollinger bands", "stochastic": "Stochastic %K"}.get(key, key),
         "value": _num(info["value"]), "signal": info["signal"], "note": notes.get(key, "")}
        for key, info in summary["indicators"].items()
    ]

    extra, patterns = _extra_technicals(history)
    indicators += extra
    counts = {"buy": sum(i["signal"] in ("buy", "strong_buy") for i in indicators),
              "sell": sum(i["signal"] in ("sell", "strong_sell") for i in indicators)}
    counts["neutral"] = len(indicators) - counts["buy"] - counts["sell"]
    if counts["buy"] > counts["sell"] + counts["neutral"]:
        overall = "buy"
    elif counts["sell"] > counts["buy"] + counts["neutral"]:
        overall = "sell"
    else:
        overall = "neutral"

    averages = []
    for period in (20, 50, 100, 200):
        if len(close) >= period:
            value = float(close.tail(period).mean())
            averages.append({"period": period, "value": value, "above": last > value,
                             "distance_pct": (last / value - 1) * 100})
    above = [a for a in averages if a["period"] in (50, 200)]
    if len(above) == 2 and all(a["above"] for a in above):
        trend = "uptrend"
    elif len(above) == 2 and not any(a["above"] for a in above):
        trend = "downtrend"
    else:
        trend = "sideways / mixed"

    returns = {label: _pct_change(close, bars) for label, bars in
               (("1W", 5), ("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 250))}
    window = close.tail(252)
    return {
        "overall": overall,
        "counts": counts,
        "indicators": indicators,
        "patterns": patterns,
        "averages": averages,
        "trend": trend,
        "returns": returns,
        "high_52w": float(window.max()),
        "low_52w": float(window.min()),
        "from_high_pct": (last / float(window.max()) - 1) * 100,
        "as_of": str(history.index[-1])[:10],
    }


def _extra_technicals(history) -> tuple[list[dict], list[dict]]:
    """Oscillators and trend gauges from src/trading/indicators.py, plus the
    candlestick patterns and divergences showing on the latest bar."""
    from ..trading import indicators as ind

    df = history.rename(columns=str.lower).astype(float)
    out: list[dict] = []

    def add(key, name, value, signal, note):
        value = _num(value)
        if value is not None:
            out.append({"key": key, "name": name, "value": value, "signal": signal, "note": note})

    band = lambda v, lo, hi: "neutral" if v is None else "buy" if v <= lo else "sell" if v >= hi else "neutral"  # noqa: E731
    c = _num(ind.cci(df).iloc[-1]) if len(df) >= 20 else None
    add("cci", "CCI (20)", c, band(c, -100, 100), "Distance from the average price: below -100 oversold, above +100 overbought")
    if "volume" in df and df["volume"].fillna(0).sum() > 0 and len(df) >= 15:
        m = _num(ind.mfi(df).iloc[-1])
        add("mfi", "Money flow index", m, band(m, 20, 80), "Volume-weighted RSI: below 20 oversold, above 80 overbought")
    w = _num(ind.williams_r(df).iloc[-1]) if len(df) >= 14 else None
    add("williams_r", "Williams %R", w, band(w, -80, -20), "Close vs 14-day range: below -80 oversold, above -20 overbought")
    if len(df) >= 30:
        a = ind.adx(df).iloc[-1]
        strength = _num(a["adx"])
        sig = "neutral" if strength is None or strength < 25 else "buy" if a["plus_di"] > a["minus_di"] else "sell"
        add("adx", "ADX (14)", strength, sig, "Trend strength: above 25 is a trending market; direction from +DI vs -DI")
        ar = _num(ind.aroon(df)["osc"].iloc[-1])
        add("aroon", "Aroon oscillator", ar, "neutral" if ar is None else "buy" if ar >= 50 else "sell" if ar <= -50 else "neutral",
            "Recency of 25-day highs vs lows: above +50 uptrend, below -50 downtrend")
    if len(df) >= 80:
        ich = ind.ichimoku(df).iloc[-1]
        last = float(df["close"].iloc[-1])
        top, bottom = max(ich["span_a"], ich["span_b"]), min(ich["span_a"], ich["span_b"])
        sig = "buy" if last > top else "sell" if last < bottom else "neutral"
        add("ichimoku", "Ichimoku cloud", (last / top - 1) * 100 if last > top else (last / bottom - 1) * 100 if last < bottom else 0.0,
            sig, "Price vs the cloud, % outside it: above = bullish, inside = undecided, below = bearish")

    patterns = [{"key": k, "name": ind.CANDLE_PATTERNS[k][0], "bias": ind.CANDLE_PATTERNS[k][1]}
                for k in ind.candle_patterns(df)]
    if len(df) >= 40:
        for label, osc in (("RSI", ind.rsi(df["close"])), ("MACD", ind.macd(df["close"])["macd"])):
            kind = ind.divergence(df, osc)
            if kind:
                patterns.append({"key": f"{label.lower()}_{kind}_div", "name": f"{label} {kind} divergence", "bias": kind})
    return out, patterns


def _risk(history, info: dict) -> dict:
    if history is None or len(history) < 30:
        raise ValueError("not enough price history for risk")
    close = history["close"].astype(float)
    returns = close.pct_change().dropna()
    volatility = float(returns.std() * math.sqrt(252))
    drawdown = float(((close - close.cummax()) / close.cummax()).min())
    level = "high" if volatility > 0.5 or drawdown < -0.35 else "medium" if volatility > 0.25 or drawdown < -0.2 else "low"
    return {
        "level": level,
        "volatility_pct": volatility * 100,
        "max_drawdown_pct": drawdown * 100,
        "beta": _num(info.get("beta")),
        "worst_day_pct": float(returns.min() * 100),
        "best_day_pct": float(returns.max() * 100),
        "realized": _realized(history),
    }


def _realized(history) -> Optional[dict]:
    from ..trading.volatility import summary

    try:
        return summary(history.rename(columns=str.lower))
    except Exception as exc:
        logger.info("Realized volatility unavailable: %s", exc)
        return None


def _fundamentals(info: dict) -> dict:
    from ..analysis.fundamental import FundamentalAnalyzer, yfinance_fundamentals

    if not info or not (info.get("marketCap") or info.get("trailingPE") or info.get("totalRevenue")):
        raise ValueError("no fundamentals published for this instrument")
    norm = yfinance_fundamentals(info)
    summary = FundamentalAnalyzer(norm).get_summary()

    def pct(key):
        v = norm.get(key)
        return v * 100 if v is not None else None

    return {
        "score": summary.get("overall_score"),
        "valuation_status": (summary.get("valuation") or {}).get("status"),
        "health_rating": (summary.get("financial_health") or {}).get("rating"),
        "currency": info.get("financialCurrency") or info.get("currency"),
        "groups": [
            {"title": "Valuation", "items": [
                {"label": "Market cap", "value": _num(info.get("marketCap")), "kind": "money"},
                {"label": "P/E (trailing)", "value": norm.get("pe_ratio"), "kind": "ratio"},
                {"label": "P/E (forward)", "value": norm.get("forward_pe"), "kind": "ratio"},
                {"label": "PEG", "value": norm.get("peg_ratio"), "kind": "ratio"},
                {"label": "Price / book", "value": norm.get("price_to_book"), "kind": "ratio"},
                {"label": "Price / sales", "value": norm.get("price_to_sales"), "kind": "ratio"},
                {"label": "EV / EBITDA", "value": _num(info.get("enterpriseToEbitda")), "kind": "ratio"},
            ]},
            {"title": "Profitability", "items": [
                {"label": "Return on equity", "value": pct("return_on_equity"), "kind": "pct"},
                {"label": "Return on assets", "value": pct("return_on_assets"), "kind": "pct"},
                {"label": "Profit margin", "value": pct("profit_margin"), "kind": "pct"},
                {"label": "Operating margin", "value": _num(info.get("operatingMargins")) and info["operatingMargins"] * 100, "kind": "pct"},
                {"label": "EPS (trailing)", "value": _num(info.get("trailingEps")), "kind": "ratio"},
            ]},
            {"title": "Growth", "items": [
                {"label": "Revenue growth (YoY)", "value": pct("revenue_growth"), "kind": "pct"},
                {"label": "Earnings growth (YoY)", "value": pct("earnings_growth"), "kind": "pct"},
                {"label": "Revenue (TTM)", "value": _num(info.get("totalRevenue")), "kind": "money"},
            ]},
            {"title": "Financial health", "items": [
                {"label": "Debt / equity", "value": norm.get("debt_to_equity"), "kind": "ratio"},
                {"label": "Current ratio", "value": norm.get("current_ratio"), "kind": "ratio"},
                {"label": "Total cash", "value": _num(info.get("totalCash")), "kind": "money"},
                {"label": "Total debt", "value": _num(info.get("totalDebt")), "kind": "money"},
                {"label": "Free cash flow", "value": _num(info.get("freeCashflow")), "kind": "money"},
            ]},
            {"title": "Dividend", "items": [
                {"label": "Dividend yield", "value": pct("dividend_yield"), "kind": "pct"},
                {"label": "Payout ratio", "value": pct("payout_ratio"), "kind": "pct"},
                {"label": "Dividend per share", "value": _num(info.get("dividendRate")), "kind": "ratio"},
            ]},
        ],
    }


def _analysts(info: dict) -> dict:
    if not info.get("recommendationKey") and not info.get("targetMeanPrice"):
        raise ValueError("no analyst coverage published")
    return {
        "recommendation": info.get("recommendationKey"),
        "mean_score": _num(info.get("recommendationMean")),  # 1 = strong buy ... 5 = sell
        "count": info.get("numberOfAnalystOpinions"),
        "target_mean": _num(info.get("targetMeanPrice")),
        "target_high": _num(info.get("targetHighPrice")),
        "target_low": _num(info.get("targetLowPrice")),
    }


def _events(yf_symbol: str) -> dict:
    import yfinance as yf

    from .analysis_run import _to_str_date

    cal = yf.Ticker(yf_symbol).calendar or {}
    out = {
        "earnings_date": _to_str_date(cal.get("Earnings Date")),
        "ex_dividend_date": _to_str_date(cal.get("Ex-Dividend Date")),
        "dividend_date": _to_str_date(cal.get("Dividend Date")),
        "eps_estimate": _num(cal.get("Earnings Average")),
        "revenue_estimate": _num(cal.get("Revenue Average")),
    }
    if not any(out.values()):
        raise ValueError("no upcoming events published")
    return out


def _profile(info: dict, market: str) -> dict:
    if not info:
        raise ValueError("no company profile available")
    return {
        "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "employees": info.get("fullTimeEmployees"),
        "website": info.get("website"),
        "summary": info.get("longBusinessSummary"),
        "exchange": info.get("exchange") or info.get("fullExchangeName"),
        "currency": info.get("currency"),
    }


def build_overview(symbol: str, market: str) -> dict:
    """Technicals, risk, fundamentals, analysts, events and news for one
    stock, without per-stock verdicts (public_view)."""
    return public_view(_build_overview(symbol, market))


def public_view(out: dict) -> dict:
    """What each indicator reads (bullish / bearish / neutral) instead of a
    buy / sell call, the overall reading and its counts, and the pattern
    lean; no "overvalued / undervalued" label (docs/future/sebi-compliance-mode.md,
    step 10). Trend, moving averages and returns stay; the attributed broker
    consensus is shown as bullish / neutral / bearish, without price targets."""
    tech = dict(out.get("technical") or {})
    if "indicators" in tech:
        tech["indicators"] = [{**i, "signal": reading(i.get("signal"))} for i in tech["indicators"]]
    if "overall" in tech:
        tech["overall"] = reading(tech["overall"])
    fund = dict(out.get("fundamentals") or {})
    fund.pop("valuation_status", None)
    # Third-party consensus as a direction, not a call, and without the brokers' price targets.
    analysts = {k: v for k, v in (out.get("analysts") or {}).items() if k not in ("target_mean", "target_high", "target_low")}
    if analysts.get("recommendation"):
        analysts["recommendation"] = reading(analysts["recommendation"]) or analysts["recommendation"]
    return {**out, "technical": tech, "fundamentals": fund, "analysts": analysts, "compliance": "analytics"}


_READINGS = {"strong_buy": "bullish", "buy": "bullish", "bullish": "bullish", "outperform": "bullish",
             "strong_sell": "bearish", "sell": "bearish", "bearish": "bearish", "underperform": "bearish",
             "hold": "neutral", "neutral": "neutral"}


def reading(signal):
    """A buy / sell signal as what the indicator reads, not a call."""
    return _READINGS.get(str(signal).lower()) if signal else None


def _build_overview(symbol: str, market: str) -> dict:
    from ..agent.agents import _resolve_fetcher
    from ..data.news_search import stock_news
    from .analysis_run import yahoo_symbol

    yf_symbol = yahoo_symbol(symbol, market)

    def load_history():
        return _resolve_fetcher(market).get_history(symbol, period="1y")

    def load_info():
        if market == "crypto":
            return {}
        import yfinance as yf

        return yf.Ticker(yf_symbol).info or {}

    # History, company info and news are independent network calls.
    with ThreadPoolExecutor(max_workers=3) as pool:
        history_f = pool.submit(load_history)
        info_f = pool.submit(load_info)
        news_f = pool.submit(lambda: stock_news(symbol, market, limit=8))
        try:
            history = history_f.result()
        except Exception as exc:
            logger.info("Overview history for %s failed: %s", symbol, exc)
            history = None
        try:
            info = info_f.result()
        except Exception as exc:
            logger.info("Overview info for %s failed: %s", symbol, exc)
            info = {}
        try:
            news = news_f.result()
        except Exception as exc:
            news = {"error": str(exc)}

    not_applicable = {"error": "not applicable to crypto"}
    return {
        "symbol": symbol,
        "market": market,
        "technical": _section(lambda: _technical(history)),
        "risk": _section(lambda: _risk(history, info)),
        "fundamentals": not_applicable if market == "crypto" else _section(lambda: _fundamentals(info)),
        "analysts": not_applicable if market == "crypto" else _section(lambda: _analysts(info)),
        "events": not_applicable if market == "crypto" else _section(lambda: _events(yf_symbol)),
        "profile": not_applicable if market == "crypto" else _section(lambda: _profile(info, market)),
        "news": news if isinstance(news, dict) else {"items": news},
    }
