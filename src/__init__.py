"""
MarketMyna - Investment Analysis Platform
A comprehensive tool for stock market analysis, portfolio management,
and investment insights across US, Global, Indian markets, and Crypto.
"""

__version__ = "0.1.0"
__author__ = "MarketMyna Team"

# Every process that imports the app (API, scheduled run, report workers) masks
# secrets such as the Telegram bot token in its logs.
from .utils import log_redact as _log_redact  # noqa: E402

_log_redact.install()
