"""Temperature fusion helpers."""

from __future__ import annotations

from collections.abc import Iterable
from math import isfinite


def fused_temperature(values: Iterable[object]) -> float | None:
    """Return the arithmetic mean of all finite numeric values."""
    valid: list[float] = []
    for value in values:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(numeric):
            valid.append(numeric)
    if not valid:
        return None
    return round(sum(valid) / len(valid), 2)
