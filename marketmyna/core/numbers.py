"""Small number helpers shared by the data services."""

from __future__ import annotations

import math
from typing import Optional


def finite(value) -> Optional[float]:
    """A float, or None for missing, non-numeric, NaN and infinite values."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def ratio(a, b) -> Optional[float]:
    """a / b, or None when either is missing or b is zero."""
    return a / b if a is not None and b not in (None, 0) else None


def median(values: list[float]) -> Optional[float]:
    v = sorted(values)
    if not v:
        return None
    mid = len(v) // 2
    return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2
