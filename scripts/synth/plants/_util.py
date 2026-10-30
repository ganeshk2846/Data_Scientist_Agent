"""Small helpers shared by the plants."""

from __future__ import annotations

import pandas as pd


def in_window(dates: pd.Series, start: str, end: str) -> pd.Series:
    """Inclusive ISO-date window mask over a ``YYYY-MM-DD`` string column."""
    return (dates >= start) & (dates <= end)


def realised(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return round((after - before) / before, 6)


def require_values(present: list[str], wanted: tuple[str, ...], what: str) -> None:
    missing = [value for value in wanted if value not in present]
    if missing:
        raise ValueError(f"the source has no {what} {', '.join(missing)}; cannot plant")
