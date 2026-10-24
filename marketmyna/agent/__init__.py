"""LLM-synthesis agent pipeline: technical/risk agents call MarketMyna's
own analysis modules as deterministic tools, an LLM backend narrates
each result, and a decision agent synthesizes everything into a report.

See orchestrator.py for the pipeline itself, context.py for the shared
state agents pass between each other, and dashboard.py for the final
report shape.
"""
