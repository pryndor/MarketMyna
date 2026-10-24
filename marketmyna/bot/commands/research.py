"""Stock research from chat: the same services the Analyze page shows
(quote, overview, valuation, financials, estimates, dividends, peers,
Shariah screen, compare), as short text replies.

Every command takes SYMBOL [market]; "us:AAPL" works too. Without a
market the symbol is looked up in the listings (see common.guess_market).
"""

from __future__ import annotations

from ...utils.deadline import call_with_deadline
from ..models import CommandResult, IncomingMessage
from .base import Command
from .common import big, num, parse_symbol, pct

GROUP = "Stock research"


class _SymbolCommand(Command):
    group = GROUP

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        symbol, market, rest = parse_symbol(args, self._config)
        if not symbol:
            return CommandResult(text=f"Usage: {self.usage}\nExample: {self.example}", success=False)
        try:
            return CommandResult(text=self.run(symbol, market, rest))
        except TimeoutError:
            return CommandResult(text=f"{symbol}: the data source took too long. Try again.", success=False)
        except Exception as exc:  # noqa: BLE001 - one bad source must not crash the chat
            return CommandResult(text=f"{symbol} ({market}): {exc}", success=False)

    def run(self, symbol: str, market: str, rest: list[str]) -> str:
        raise NotImplementedError


class QuoteCommand(_SymbolCommand):
    name = "quote"
    aliases = ["q", "price"]
    usage = "/quote SYMBOL [market]"
    description = "Live price, day change, day range, volume and market cap."
    example = "/quote RELIANCE india"

    def run(self, symbol, market, rest):
        from ...core.constants import Markets
        from ...data.china import ChinaAFetcher, HongKongFetcher
        from ...data.crypto import CryptoDataFetcher
        from ...data.india import IndiaDataFetcher
        from ...data.stocks import StockDataFetcher

        fetcher = {"india": IndiaDataFetcher, "crypto": CryptoDataFetcher, "china_a": ChinaAFetcher,
                   "hong_kong": HongKongFetcher}.get(Markets(market).value, StockDataFetcher)()
        q = call_with_deadline(fetcher.get_quote, 20, symbol) or {}
        # Exchange quotes can come back thin (e.g. NSE off-hours); fill gaps from the listings row.
        try:
            from ...data.listings import get_store

            found = get_store().lookup([(market, kind, symbol) for kind in ("stock", "etf")])
            row = next(iter(found.values()), {})
        except Exception:
            row = {}
        for key, alt in (("price", "price"), ("open", "open"), ("day_high", "high"), ("day_low", "low"),
                         ("volume", "volume"), ("market_cap", "market_cap"), ("change_percent", "change_percent")):
            if not q.get(key) and row.get(alt):
                q[key] = row[alt]
        if q.get("price") is None:
            return f"No quote for {symbol} ({market})."
        def pair(*items):
            return " · ".join(f"{label} {fmt(q[key])}" for label, key, fmt in items if q.get(key))

        lines = [f"{symbol} ({market})  {num(q['price'])}  {num(q.get('change'))} ({pct(q.get('change_percent'), 2)})",
                 pair(("Open", "open", num), ("Prev close", "previous_close", num)),
                 f"Day range {num(q['day_low'])} - {num(q['day_high'])}" if q.get("day_low") and q.get("day_high") else "",
                 pair(("Volume", "volume", big), ("Market cap", "market_cap", big))]
        return "\n".join(line for line in lines if line)


class OverviewCommand(_SymbolCommand):
    name = "overview"
    aliases = ["ov", "tech"]
    usage = "/overview SYMBOL [market]"
    description = "Technicals, trend, returns, risk, fundamentals, analyst consensus and upcoming events."
    example = "/overview AAPL us"

    def run(self, symbol, market, rest):
        from ...services.overview import build_overview

        d = call_with_deadline(build_overview, 60, symbol, market)
        t, r, f, a, e = (d.get(k) or {} for k in ("technical", "risk", "fundamentals", "analysts", "events"))
        lines = [f"{symbol} ({market}) overview"]
        if t:
            counts = t.get("counts")  # absent on a public deploy (no per-stock verdicts)
            lines.append(f"Trend: {t.get('trend', 'n/a')}" + (
                f" · indicators {counts.get('buy', 0)} up / {counts.get('sell', 0)} down / "
                f"{counts.get('neutral', 0)} neutral" if counts else ""))
            ret = t.get("returns") or {}
            lines.append("Returns: " + " · ".join(f"{k} {pct(v)}" for k, v in list(ret.items())[:6]))
            lines.append(f"52w range {num(t.get('low_52w'))} - {num(t.get('high_52w'))} "
                         f"({pct(t.get('from_high_pct'))} from high)")
            rsi = next((i for i in t.get("indicators") or [] if i.get("key") == "rsi"), None)
            if rsi:
                lines.append(f"RSI(14) {num(rsi.get('value'), 1)}")
        if r:
            lines.append(f"Risk: {r.get('level', 'n/a')} · volatility {pct(r.get('volatility_pct'), 1, False)} · "
                         f"max drawdown {pct(r.get('max_drawdown_pct'))} · beta {num(r.get('beta'))}")
        if f:
            lines.append(f"Fundamentals: score {f.get('score', 'n/a')}/100 · health {f.get('health_rating', 'n/a')}")
        if a.get("count"):
            # Third-party consensus as a direction (build_overview), without the price targets.
            lines.append(f"Broker consensus ({a['count']} analysts): {a.get('recommendation') or 'n/a'}")
        ev = [f"earnings {e['earnings_date']}" if e.get("earnings_date") else "",
              f"ex-dividend {e['ex_dividend_date']}" if e.get("ex_dividend_date") else ""]
        if any(ev):
            lines.append("Events: " + " · ".join(x for x in ev if x))
        return "\n".join(lines)


class ValuationCommand(_SymbolCommand):
    name = "valuation"
    aliases = ["val"]
    usage = "/valuation SYMBOL [market]"
    description = "Valuation meter: P/E, P/B and other multiples against the sector median, plus the growth-at-a-price check."
    example = "/valuation INFY india"

    def run(self, symbol, market, rest):
        from ...services.valuation import meter

        d = call_with_deadline(meter, 90, symbol, market)
        if d.get("status") != "ok":
            return f"{symbol}: {d.get('reason') or 'no valuation data'}"
        zone = {"below": "below its sector", "above": "above its sector", "in_line": "in line with its sector"}
        lines = [f"{symbol} ({market}) valuation vs {d.get('sector')} ({d.get('peers')} peers): "
                 f"priced {zone.get(d.get('zone'), d.get('zone'))}"]
        for m in d.get("multiples") or []:
            if m.get("value") is not None:
                lines.append(f"• {m['label']} {num(m['value'])} vs sector median {num(m.get('sector_median'))}")
        g = d.get("garp") or {}
        if g.get("total"):
            lines.append(f"Growth at a reasonable price: {g['passed']}/{g['total']} checks pass (PEG {num(g.get('peg'))})")
        return "\n".join(lines)


class FinancialsCommand(_SymbolCommand):
    name = "financials"
    aliases = ["fin"]
    usage = "/financials SYMBOL [market] [annual|quarterly]"
    description = "Income statement, balance sheet and cash flow health with the key findings."
    example = "/financials TCS india"

    def run(self, symbol, market, rest):
        from ...services.financials import build_financials

        period = "quarterly" if rest and rest[0].lower().startswith("q") else "annual"
        d = call_with_deadline(build_financials, 60, symbol, market, period)
        o = d.get("overall") or {}
        lines = [f"{d.get('name') or symbol} ({market}) {period}: {o.get('label', 'n/a')} ({o.get('score', 'n/a')}/100)"]
        for key, title in (("income", "Income statement"), ("balance", "Balance sheet"), ("cashflow", "Cash flow")):
            part = d.get(key) or {}
            v = part.get("verdict") or {}
            if not v:
                continue
            lines.append(f"{title}: {v.get('label')} ({v.get('score')}) as of {part.get('as_of')}")
            for f in (part.get("findings") or [])[:3]:
                lines.append(f"  {'+' if f.get('tone') == 'good' else '-' if f.get('tone') == 'bad' else '·'} {f['text']}")
        return "\n".join(lines)


class EstimatesCommand(_SymbolCommand):
    name = "estimates"
    aliases = ["est"]
    usage = "/estimates SYMBOL [market]"
    description = "Analyst EPS and revenue consensus, revisions and recent beats or misses."
    example = "/estimates MSFT us"

    def run(self, symbol, market, rest):
        from ...services.analysis_run import yahoo_symbol
        from ...services.estimates import build

        if market == "crypto":
            return "No analyst estimates for crypto."
        d = call_with_deadline(build, 45, yahoo_symbol(symbol, market))
        if not d.get("available"):
            return f"No analyst estimates for {symbol}."
        cur = d.get("currency") or ""
        lines = [f"{symbol} analyst estimates ({cur})"]
        for p in d.get("periods") or []:
            eps, rev, r = p.get("eps") or {}, p.get("revenue") or {}, p.get("revisions") or {}
            growth = eps.get("growth")
            lines.append(f"• {p['label']}: EPS {num(eps.get('avg'))}"
                         + (f" ({pct(growth * 100 if abs(growth) < 5 else growth)} y/y)" if growth is not None else "")
                         + (f", revenue {big(rev.get('avg'))}" if rev.get("avg") else "")
                         + (f", 30d revisions {int(r.get('up_30d') or 0)} up / {int(r.get('down_30d') or 0)} down" if r else ""))
        m, b = d.get("momentum") or {}, d.get("beats") or {}
        if m.get("label"):
            lines.append(f"Estimate trend (90d): {m['label']}")
        if b.get("total"):
            lines.append(f"Beat estimates in {b['beat']} of the last {b['total']} quarters")
        return "\n".join(lines)


class DividendsCommand(_SymbolCommand):
    name = "dividends"
    aliases = ["div"]
    usage = "/dividends SYMBOL [market]"
    description = "Dividend yield, payout ratio, growth, years without a cut and the last payment."
    example = "/dividends ITC india"

    def run(self, symbol, market, rest):
        from ...services.analysis_run import yahoo_symbol
        from ...services.dividends import build

        if market == "crypto":
            return "Crypto doesn't pay dividends."
        d = call_with_deadline(build, 45, yahoo_symbol(symbol, market))
        if not d.get("pays"):
            return f"{symbol} has no dividend history."
        last = d.get("last") or {}
        return "\n".join([
            f"{symbol} dividends ({d.get('currency')}) · {d.get('frequency') or 'irregular'}",
            f"Trailing yield {pct(d.get('ttm_yield'), 2, False)} ({num(d.get('ttm'))} in 12 months) · "
            f"forward {pct(d.get('forward_yield'), 2, False)}",
            f"Payout ratio {pct(d.get('payout_ratio'), 0, False)} · 5y growth {pct(d.get('growth_5y'))} · "
            f"{d.get('years_without_cut', 'n/a')} year{'' if d.get('years_without_cut') == 1 else 's'} without a cut",
            f"Last paid {num(last.get('amount'))} on {last.get('date', 'n/a')}"
            + (f" · next ex-date {d['next_ex_date']}" if d.get("next_ex_date") else ""),
        ])


class PeersCommand(_SymbolCommand):
    name = "peers"
    aliases = []
    usage = "/peers SYMBOL [market]"
    description = "Closest companies in the same sector by size, with P/E and day change."
    example = "/peers HDFCBANK india"

    def run(self, symbol, market, rest):
        from ...services.compare import peers

        d = call_with_deadline(peers, 60, symbol, market, 6)
        rows = d.get("peers") or []
        if not rows:
            return f"No peers found for {symbol}."
        lines = [f"{symbol} peers · {d.get('basis')}"]
        for p in rows:
            lines.append(f"• {p['symbol']} cap {big(p.get('market_cap'))} · P/E {num(p.get('pe'), 1)} · "
                         f"day {pct(p.get('change_percent'))}")
        lines.append(f"Compare: /compare {symbol}," + ",".join(p["symbol"] for p in rows[:3]) + f" {market}")
        return "\n".join(lines)


class ShariahCommand(_SymbolCommand):
    name = "ethical"
    aliases = ["shariah", "halal"]  # the old names keep working
    usage = "/ethical SYMBOL [market]"
    description = "Ethical screen: business activity and the debt, cash and interest-income ratios."
    example = "/ethical AAPL us"

    def run(self, symbol, market, rest):
        from ...services.shariah import build_shariah_profile

        d = call_with_deadline(build_shariah_profile, 60, symbol, market)
        lines = [f"{d.get('name') or symbol}: {d.get('verdict_label') or d.get('verdict') or 'no verdict'}"]
        b = d.get("business") or {}
        if b.get("reason"):
            lines.append(f"Business: {b['reason']}")
        for c in d.get("checks") or []:
            v = "n/a" if c.get("value") is None else f"{c['value']:.1f}%"
            lines.append(f"• {c['label']}: {v} (limit {c.get('limit')}%) {c.get('status', '')}")
        lines.append("A screening aid, not a fatwa.")
        return "\n".join(lines)


class CompareCommand(Command):
    name = "compare"
    aliases = ["vs"]
    usage = "/compare SYM1,SYM2[,SYM3] [market] [6mo|1y|3y|5y]"
    description = "2-5 stocks side by side: returns, volatility, drawdown, beta and correlation."
    example = "/compare TCS,INFY,WIPRO india 1y"
    group = GROUP

    def __init__(self, config):
        self._config = config

    def handle(self, message: IncomingMessage, args: str) -> CommandResult:
        from ...services.compare import compare
        from .common import guess_market, market_word

        parts = args.split()
        if not parts:
            return CommandResult(text=f"Usage: {self.usage}\nExample: {self.example}", success=False)
        market = next((market_word(p) for p in parts[1:] if market_word(p)), None)
        period = next((p.lower() for p in parts[1:] if p.lower() in ("6mo", "1y", "3y", "5y")), "1y")
        items = []
        for tok in parts[0].split(","):
            if not tok:
                continue
            m, _, s = tok.partition(":") if ":" in tok else ("", "", tok)
            sym = s.upper()
            items.append((sym, market_word(m) or market or guess_market(sym, self._config)))
        if not 2 <= len(items) <= 5:
            return CommandResult(text="Give 2 to 5 symbols, comma separated.", success=False)
        try:
            d = call_with_deadline(compare, 60, items, period)
        except (ValueError, TimeoutError) as exc:
            return CommandResult(text=str(exc), success=False)
        syms = [i["symbol"] for i in d.get("items") or []]
        lines = [f"Compare {', '.join(syms)} ({period})"]
        for row in d.get("returns") or []:
            lines.append(f"{row['window']}: " + " · ".join(f"{s} {pct(row['values'].get(s))}" for s in syms))
        risk = d.get("risk") or {}
        for s in syms:
            r = risk.get(s) or {}
            lines.append(f"{s}: volatility {pct(r.get('volatility'), 1, False)} · max drawdown {pct(r.get('max_drawdown'))} · "
                         f"beta {num(r.get('beta'))}")
        corr = d.get("correlation") or {}
        cs, mx = corr.get("symbols") or [], corr.get("matrix") or []
        pairs = [f"{cs[i]}/{cs[j]} {mx[i][j]:.2f}" for i in range(len(cs)) for j in range(i + 1, len(cs)) if mx[i][j] is not None]
        if pairs:
            lines.append("Correlation: " + " · ".join(pairs[:6]))
        return CommandResult(text="\n".join(lines))
