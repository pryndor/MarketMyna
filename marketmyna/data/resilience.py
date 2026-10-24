"""Circuit-breaker-protected fallback chains for data fetchers.

Mechanics borrowed from daily_stock_analysis's data_provider circuit
breaker (closed -> open -> half_open state machine, per-source failure
count + cooldown), reimplemented here against MarketMyna's own,
differently-shaped DataFetcher interface rather than copied verbatim.

Key design choice: state is keyed by an arbitrary string, not just the
source name, so callers can compose "{source}:{method}" keys. A source
failing on get_quote should not necessarily open the circuit for that
same source's get_history - the two calls can have very different
failure modes (e.g. a quote endpoint rate-limited while history is
fine), so isolating per-method avoids over-tripping the breaker.
"""

from __future__ import annotations

import logging
import time
from threading import RLock
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class DataSourceUnavailable(Exception):
    """Every source in a FallbackChain failed or is circuit-open."""


class CircuitBreaker:
    """Per-key closed/open/half_open state machine.

    - CLOSED: normal, calls go through.
    - OPEN: skip calls for `cooldown_seconds` after `failure_threshold`
      consecutive failures.
    - HALF_OPEN: after cooldown, allow `half_open_max_calls` probe(s);
      success fully recovers, failure re-opens for another cooldown.
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 300.0,
        half_open_max_calls: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_calls = half_open_max_calls
        self._states: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    def _state(self, key: str) -> dict[str, Any]:
        if key not in self._states:
            self._states[key] = {
                "state": self.CLOSED,
                "failures": 0,
                "last_failure_time": 0.0,
                "half_open_calls": 0,
            }
        return self._states[key]

    def is_available(self, key: str) -> bool:
        """True if a call should be attempted for this key."""
        with self._lock:
            state = self._state(key)
            now = time.time()

            if state["state"] == self.CLOSED:
                return True

            if state["state"] == self.OPEN:
                elapsed = now - state["last_failure_time"]
                if elapsed < self.cooldown_seconds:
                    return False
                state["state"] = self.HALF_OPEN
                state["half_open_calls"] = 0
                logger.info("Circuit breaker %s: cooldown elapsed, half-opening", key)

            # HALF_OPEN
            if state["half_open_calls"] < self.half_open_max_calls:
                state["half_open_calls"] += 1
                return True
            return False

    def record_success(self, key: str) -> None:
        with self._lock:
            state = self._state(key)
            if state["state"] == self.HALF_OPEN:
                logger.info("Circuit breaker %s: probe succeeded, closing", key)
            state["state"] = self.CLOSED
            state["failures"] = 0
            state["half_open_calls"] = 0

    def record_failure(self, key: str, error: Optional[str] = None) -> None:
        with self._lock:
            state = self._state(key)
            state["failures"] += 1
            state["last_failure_time"] = time.time()

            if state["state"] == self.HALF_OPEN:
                state["state"] = self.OPEN
                state["half_open_calls"] = 0
                logger.warning("Circuit breaker %s: probe failed, re-opening", key)
            elif state["failures"] >= self.failure_threshold:
                state["state"] = self.OPEN
                logger.warning(
                    "Circuit breaker %s: %d consecutive failures, opening for %.0fs (%s)",
                    key, state["failures"], self.cooldown_seconds, error or "",
                )

    def record_inconclusive(self, key: str) -> None:
        """An empty/unusable (but non-exception) result - only matters in
        HALF_OPEN, where it re-opens the breaker rather than fully closing."""
        with self._lock:
            state = self._state(key)
            if state["state"] == self.HALF_OPEN:
                state["state"] = self.OPEN
                state["half_open_calls"] = 0
                state["last_failure_time"] = time.time()

    def status(self) -> dict[str, str]:
        with self._lock:
            return {key: info["state"] for key, info in self._states.items()}


# Shared default breaker: fetcher instances come and go (a new
# PortfolioManager/StockDataFetcher per API request, per Phase 0's
# get_portfolio_manager pattern) but failure history should persist
# across those instances for the breaker to mean anything.
default_breaker = CircuitBreaker()


class FallbackChain:
    """An ordered list of named callables for one logical operation
    (e.g. "get_quote"), tried in order with circuit-breaker protection."""

    def __init__(self, method: str, breaker: Optional[CircuitBreaker] = None):
        self.method = method
        self.breaker = breaker or default_breaker
        self._sources: list[tuple[str, Callable[..., Any]]] = []

    def add(self, name: str, func: Callable[..., Any]) -> "FallbackChain":
        self._sources.append((name, func))
        return self

    def call(self, *args: Any, is_empty: Optional[Callable[[Any], bool]] = None, **kwargs: Any) -> Any:
        last_exc: Optional[Exception] = None
        for name, func in self._sources:
            key = f"{name}:{self.method}"
            if not self.breaker.is_available(key):
                continue
            try:
                result = func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - deliberately broad, this is the fallback boundary
                self.breaker.record_failure(key, str(exc))
                last_exc = exc
                continue

            if is_empty is not None and is_empty(result):
                self.breaker.record_inconclusive(key)
                last_exc = last_exc or RuntimeError(f"{name} returned an empty result")
                continue

            self.breaker.record_success(key)
            return result

        raise DataSourceUnavailable(
            f"All sources exhausted for {self.method}"
        ) from last_exc
