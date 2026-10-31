"""Deterministic chart-choice rules for a rows table (Track 5, item 1).

The frozen ``VizKind`` set is ``line | bar | grouped_bar | waterfall |
range_band | forecast_fan | scatter | table``. The requested families map onto
it without inventing a kind:

=================  ==========================================================
family             kind
=================  ==========================================================
time series        ``line`` (one line per series column when present)
category compare   ``bar``
share              ``grouped_bar`` with a series split, else ``bar`` in %
distribution       ``bar`` over bins the SQL already produced; never binned here
relationship       ``scatter``
single row         ``table`` (VZ-6: a one-point series is never a line)
forecast rows      ``forecast_fan`` when the rows carry yhat and its interval
flagged anomalies  ``table`` with spike / dip marks (only flagged points are
                   carried, so no line is drawn through them)
anomaly + series   ``line`` with the engine's spike / dip marked on it
=================  ==========================================================

Engine outputs (forecast, drivers, anomalies, scenario) are handled in
``viz.builder`` because their shape is fixed by the engine contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from contracts.v2 import RowsColumn

Family = Literal["forecast", "flagged", "time_series", "category", "share", "distribution", "relationship", "table"]

_BIN = re.compile(r"(^|_)(bin|bins|bucket|histogram|band|range)(_|$)", re.IGNORECASE)
_SHARE = re.compile(r"(^|_)(share|pct|percent|percentage|mix|proportion)(_|$)", re.IGNORECASE)
_MONEY = re.compile(r"(^|_)(revenue|gmv|aov|price|freight|freight_value|payment|spend|value_brl)(_|$)", re.IGNORECASE)


@dataclass(frozen=True)
class RowsChoice:
    family: Family
    x: RowsColumn
    y: RowsColumn
    series: RowsColumn | None = None
    lower: RowsColumn | None = None
    upper: RowsColumn | None = None


_ACRONYMS = {"gmv": "GMV", "aov": "AOV", "sla": "SLA", "ltv": "LTV", "kpi": "KPI", "mape": "MAPE"}


def label(name: str) -> str:
    text = " ".join(_ACRONYMS.get(part.lower(), part) for part in name.replace("_", " ").split())
    return f"{text[:1].upper()}{text[1:]}" if text else name


def unit_for(name: str) -> str | None:
    if _SHARE.search(name):
        return "%"
    if _MONEY.search(name):
        return "BRL"
    return None


def is_bin(column: RowsColumn) -> bool:
    return bool(_BIN.search(column.name))


def is_share(column: RowsColumn) -> bool:
    return bool(_SHARE.search(column.name))


_TIME_NAMES = ("ds", "date", "period", "month", "day", "week")


def _named(columns: tuple[RowsColumn, ...], *names: str) -> RowsColumn | None:
    return next((c for name in names for c in columns if c.name == name), None)


def choose(columns: tuple[RowsColumn, ...], row_count: int) -> RowsChoice | None:
    """Pick a chart family from column roles (and a few fixed engine names).

    Returns ``None`` when the table
    has nothing drawable; the existing evidence table still shows it.
    """

    time_col = next((c for c in columns if c.role == "time"), None) or _named(columns, *_TIME_NAMES)
    yhat, lower, upper = _named(columns, "yhat"), _named(columns, "yhat_lower"), _named(columns, "yhat_upper")
    if time_col is not None and yhat is not None and lower is not None and upper is not None:
        return RowsChoice("forecast", time_col, yhat, lower=lower, upper=upper)
    direction, value = _named(columns, "direction"), _named(columns, "value")
    if time_col is not None and direction is not None and value is not None:
        # Only the flagged points are carried, so joining them with a line
        # would draw a series that does not exist: they are listed, marked.
        return RowsChoice("flagged", time_col, value)

    bins = [c for c in columns if is_bin(c)]
    times = [c for c in columns if c.role == "time" and c not in bins]
    dims = [c for c in columns if c.role in ("dimension", "key") and c not in bins]
    measures = [c for c in columns if c.role == "measure" and c not in bins]
    if not measures:
        return None
    measure = measures[0]

    if row_count < 2:
        axis = (times or dims or bins or [None])[0]
        return RowsChoice("table", axis, measure) if axis is not None else None

    if bins:
        return RowsChoice("distribution", bins[0], measure)
    if times:
        return RowsChoice("time_series", times[0], measure, dims[0] if dims else None)
    share = next((c for c in measures if is_share(c)), None)
    if dims and share is not None:
        return RowsChoice("share", dims[0], share, dims[1] if len(dims) > 1 else None)
    if len(dims) >= 2:
        # Two categorical splits of one measure: compared side by side.
        return RowsChoice("category", dims[0], measure, dims[1])
    if dims:
        if len(measures) >= 2 and dims[0].role == "key":
            # One row per entity with two measures: how they move together.
            return RowsChoice("relationship", measures[0], measures[1])
        return RowsChoice("category", dims[0], measure)
    if len(measures) >= 2:
        return RowsChoice("relationship", measures[0], measures[1])
    return None


__all__ = ["Family", "RowsChoice", "choose", "is_bin", "is_share", "label", "unit_for"]
