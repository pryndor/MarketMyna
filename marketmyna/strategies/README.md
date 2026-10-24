# Strategy / skill library

These 15 YAML files are adapted from daily_stock_analysis's own `strategies/`
directory. Each describes one trading-analysis strategy as a schema
(`name`, `display_name`, `description`, `category`, `core_rules`,
`required_tools`, `aliases`, `default_priority`, `market_regimes`) plus an
`instructions:` markdown block meant to be injected verbatim as an LLM
system-prompt fragment for a `SkillAgent` (see `src/agent/skills.py`).

## What changed from the source files

Only `required_tools` was remapped — every other field, and the entire
`instructions` block, is unchanged from the original (the instructions are
domain knowledge about reading a golden cross, Chan theory pivots, etc, not
code; rewriting that prose from scratch would be worse than adapting it).

The source project's `required_tools` names its own tool-calling agent
runtime's tools. MarketMyna doesn't have a tool-calling runtime yet — the
technical/risk agents call analysis modules directly (see
`src/agent/agents.py`). So each tool name was mapped to the closest thing
that actually exists today, or marked `pending:` when nothing does:

| Source tool name      | Mapped to             | Why |
|------------------------|------------------------|-----|
| `get_daily_history`    | `fetch_history`        | `DataFetcher.get_history` — real, already called by `TechnicalAgent`/`RiskAgent` |
| `analyze_trend`        | `technical_summary`    | `TechnicalAnalyzer.get_summary()` — real, lands on `ctx.technical_summary` |
| `get_realtime_quote`   | `fetch_quote`          | `DataFetcher.get_quote` — real |
| `get_stock_info`       | `fetch_info`           | `DataFetcher.get_info` + `FundamentalAnalyzer` — real |
| `search_stock_news`    | `pending:search_stock_news`   | No news-search API/tool configured (same scope cut as Phase 3b's missing IntelAgent) |
| `get_sector_rankings`  | `pending:get_sector_rankings` | No sector-ranking data source exists in `src/data/` yet |

A `pending:` prefix means: this strategy's full instructions assume a
capability MarketMyna doesn't have wired up yet. The strategy still loads
and can still run — `SkillAgent` hands the LLM whatever real context is
available (price history, technical summary, quote, fundamentals) plus the
skill's instructions; the LLM just won't have a real news/sector feed to
draw on for strategies that call for one. It is not silently pretending to
have that data.

Two files (`bull_trend.yaml`, `shrink_pullback.yaml`) also carry
`default_active`/`default_router` flags from the source project (marking
that strategy as the fallback default route there) — preserved as-is on
the `Skill` dataclass, not currently used for any routing decision in
`select_skills()`.

Inline tool-name mentions inside the `instructions:` prose itself (e.g.
"使用 `analyze_trend` 判断...") were **not** rewritten — only the structured
`required_tools:` list was remapped. Renaming names inside expert
trading-strategy prose would require rewriting that prose, which is out of
scope here; a human reading the instructions will still understand the
intent.
