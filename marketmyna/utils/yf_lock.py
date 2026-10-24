"""One process-wide lock for yfinance.download().

yf.download keeps its results in module-level state (yfinance.shared), so two
batch downloads running at once on different threads can hand each other's
rows back: a 1-year commodities fetch and a 2-year crude fetch overlapping
returned 1-year Brent to the 2-year caller. Every batch download goes through
this lock; single-ticker Ticker().history() calls do not need it.
"""

import threading

YF_DOWNLOAD_LOCK = threading.Lock()
