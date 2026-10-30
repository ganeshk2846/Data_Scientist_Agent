"""``last_complete_period`` per metric and grain (V2-DATA-1, V2-PRE-3).

A snapshot's newest month is not its last real month. On the Olist snapshot
2018-09 holds 16 orders and 2018-10 holds 4: they are collection artefacts,
and an engine fitted on them reports a collapse that never happened. This
module decides which periods are complete from a **completeness rule**, never
from ``max(date)``.

The rule, for the month grain:

* Every month between the first and last observed month is assessed. A month
  with no rows at all is a gap and is incomplete.
* A month is complete when its observed volume is at least
  ``rule.factor`` times the median of up to ``rule.window`` preceding
  *complete* months. Incomplete months are excluded from the reference, so
  2018-10 is compared with 2018-08, not with 2018-09's 16 orders.
* A month with no complete month before it (the head of the snapshot) is
  compared with the median of the ``rule.window`` months that follow it,
  using the looser ``rule.head_factor``. A snapshot's head is a collection
  edge just as its tail is, but a young marketplace also ramps up, so only a
  near-total shortfall against what follows is an artefact: 2016-09 (4
  orders) is flagged, the 2016-10 ramp (324 orders) is not.

The default factor is deliberately low (0.2): it flags volumes that collapse
by 80% or more, which on real business data is a collection problem, while a
genuine 40% drop - the kind a diagnostic question asks about - stays a
complete period that must be explained, not hidden.

Coarser grains are derived, not re-measured: a quarter or year is complete
only when every one of its months is complete. 2018 is therefore an
incomplete year, which is exactly why "2018" is read as 2018-01 to 2018-08
with the assumption stated (``contracts.md`` section 1, example).

Volume is a plain ``COUNT(*)`` over the metric's date-column table, grouped by
period, read through a read-only connection. The rule itself is pure and
testable without a database (:func:`assess_monthly_volumes`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from statistics import median
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import text
from sqlalchemy.engine import Connection

from contracts.models import ContractModel, MetricDefinition

CompletenessGrain = Literal["month", "quarter", "year"]

_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CompletenessRule(ContractModel):
    """The configured completeness rule; versioned with the report."""

    rule_id: str = "trailing_median_v1"
    factor: float = Field(default=0.2, gt=0.0, le=1.0)
    head_factor: float = Field(default=0.05, gt=0.0, le=1.0)
    window: int = Field(default=6, ge=1, le=24)


class PeriodCoverage(ContractModel):
    """One assessed period."""

    period: str = Field(min_length=1)
    observed: int = Field(ge=0)
    complete: bool
    reason: str | None = None

    @model_validator(mode="after")
    def _incomplete_needs_reason(self) -> PeriodCoverage:
        if not self.complete and not self.reason:
            raise ValueError(f"incomplete period {self.period!r} needs a reason")
        return self


class CompletenessReport(ContractModel):
    """Completeness of one metric at one grain, under one catalog version."""

    metric_id: str = Field(min_length=1)
    grain: CompletenessGrain
    catalog_version: str = Field(min_length=1)
    volume_unit: str = Field(min_length=1)
    rule: CompletenessRule
    periods: tuple[PeriodCoverage, ...]

    @property
    def last_complete_period(self) -> str | None:
        complete = [item.period for item in self.periods if item.complete]
        return complete[-1] if complete else None

    @property
    def incomplete_periods(self) -> tuple[PeriodCoverage, ...]:
        return tuple(item for item in self.periods if not item.complete)

    def is_complete(self, period: str) -> bool:
        for item in self.periods:
            if item.period == period:
                return item.complete
        raise KeyError(f"period {period!r} is outside the assessed range")

    def complete_run(self) -> tuple[str, ...]:
        """The latest contiguous run of complete periods, oldest first.

        This is what a forecast may fit on (V2-DATA-2): history that ends at
        the last complete period and contains no gap or truncated period.
        """
        run: list[str] = []
        for item in reversed(self.periods):
            if item.complete:
                run.append(item.period)
            elif run:
                break
        return tuple(reversed(run))

    def caveat_for_window(self, start: str, end: str) -> str | None:
        """A visible caveat when ``[start, end]`` includes an incomplete period.

        Satisfies V2-DATA-3: the caveat names each incomplete period and its
        observed volume. Periods are compared as ISO strings of this grain.
        """
        if start > end:
            raise ValueError("window start must not be after its end")
        hits = [
            item
            for item in self.incomplete_periods
            if start <= item.period <= end
        ]
        if not hits:
            return None
        named = ", ".join(
            f"{item.period} ({item.observed:,} {self.volume_unit})" for item in hits
        )
        last = self.last_complete_period
        tail = f" The last complete {self.grain} is {last}." if last else ""
        return (
            f"The window includes incomplete {self.grain}s: {named}. Their "
            f"figures reflect partial data collection, not business activity."
            f"{tail}"
        )


# --------------------------------------------------------------------------- #
# The rule - pure
# --------------------------------------------------------------------------- #


def _month_index(period: str) -> int:
    match = _MONTH.match(period)
    if match is None:
        raise ValueError(f"expected a YYYY-MM month, got {period!r}")
    return int(match.group(1)) * 12 + int(match.group(2)) - 1


def _month_label(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def assess_monthly_volumes(
    volumes: Mapping[str, int],
    rule: CompletenessRule | None = None,
) -> tuple[PeriodCoverage, ...]:
    """Apply the completeness rule to observed monthly volumes.

    ``volumes`` maps ``YYYY-MM`` to a row count. Months missing from the
    mapping but inside the observed range are gaps with volume 0.
    """
    rule = rule or CompletenessRule()
    if not volumes:
        return ()
    if any(count < 0 for count in volumes.values()):
        raise ValueError("volumes must be non-negative counts")

    indices = sorted(_month_index(period) for period in volumes)
    by_index = {_month_index(period): int(count) for period, count in volumes.items()}
    months = list(range(indices[0], indices[-1] + 1))
    observed = [by_index.get(index, 0) for index in months]

    results: list[PeriodCoverage] = []
    complete_history: list[int] = []
    for position, (index, count) in enumerate(zip(months, observed, strict=True)):
        label = _month_label(index)
        if count == 0:
            results.append(
                PeriodCoverage(
                    period=label,
                    observed=0,
                    complete=False,
                    reason="no rows recorded in this period (a collection gap)",
                )
            )
            continue

        if complete_history:
            reference = median(complete_history[-rule.window :])
            factor = rule.factor
            basis = "the median of the preceding complete periods"
        else:
            following = [value for value in observed[position + 1 :] if value > 0]
            following = following[: rule.window]
            if not following:
                # A single observed period: nothing to compare it with.
                reference = count
            else:
                reference = median(following)
            factor = rule.head_factor
            basis = "the median of the following periods (head of the snapshot)"

        if count >= factor * reference:
            results.append(PeriodCoverage(period=label, observed=count, complete=True))
            complete_history.append(count)
        else:
            results.append(
                PeriodCoverage(
                    period=label,
                    observed=count,
                    complete=False,
                    reason=(
                        f"volume is below {factor:g} times {basis}"
                    ),
                )
            )
    return tuple(results)


def _quarter_of(month: str) -> str:
    index = _month_index(month)
    return f"{index // 12:04d}-Q{(index % 12) // 3 + 1}"


def _year_of(month: str) -> str:
    return month[:4]


def roll_up(
    months: Iterable[PeriodCoverage],
    grain: Literal["quarter", "year"],
) -> tuple[PeriodCoverage, ...]:
    """Derive quarter or year completeness: complete only if every month is.

    A quarter or year whose months are not all inside the assessed range is
    incomplete too: it was only partly observed.
    """
    key = _quarter_of if grain == "quarter" else _year_of
    expected = 3 if grain == "quarter" else 12
    buckets: dict[str, list[PeriodCoverage]] = {}
    for month in months:
        buckets.setdefault(key(month.period), []).append(month)

    results: list[PeriodCoverage] = []
    for label, members in buckets.items():
        observed = sum(member.observed for member in members)
        broken = [member.period for member in members if not member.complete]
        if broken:
            reason = "contains incomplete months: " + ", ".join(broken)
        elif len(members) < expected:
            reason = (
                f"only {len(members)} of its {expected} months fall inside "
                "the observed range"
            )
        else:
            reason = None
        results.append(
            PeriodCoverage(
                period=label,
                observed=observed,
                complete=reason is None,
                reason=reason,
            )
        )
    return tuple(results)


# --------------------------------------------------------------------------- #
# Reading volumes - one fixed, read-only query
# --------------------------------------------------------------------------- #


def _split_date_column(date_column: str) -> tuple[str, str]:
    parts = date_column.split(".")
    if len(parts) != 2 or not all(_IDENTIFIER.match(part) for part in parts):
        raise ValueError(f"date_column must be 'table.column', got {date_column!r}")
    return parts[0], parts[1]


def read_monthly_volumes(connection: Connection, date_column: str) -> dict[str, int]:
    """Row count per ``YYYY-MM`` of ``table.column``.

    Identifiers come from the governed registry and are checked against a
    strict identifier pattern before being quoted into the statement; no
    user or model text reaches this query.
    """
    table, column = _split_date_column(date_column)
    statement = text(
        f'SELECT strftime(\'%Y-%m\', "{table}"."{column}") AS period, '
        f'COUNT(*) AS volume FROM "{table}" '
        f'WHERE "{table}"."{column}" IS NOT NULL '
        "GROUP BY period ORDER BY period"
    )
    rows = connection.execute(statement).all()
    return {str(period): int(volume) for period, volume in rows if period}


def assess_metric(
    connection: Connection,
    metric: MetricDefinition,
    *,
    grain: CompletenessGrain = "month",
    catalog_version: str,
    rule: CompletenessRule | None = None,
) -> CompletenessReport:
    """Publish the completeness report for one metric at one grain."""
    rule = rule or CompletenessRule()
    table, _ = _split_date_column(metric.date_column)
    months = assess_monthly_volumes(
        read_monthly_volumes(connection, metric.date_column), rule
    )
    periods = months if grain == "month" else roll_up(months, grain)
    return CompletenessReport(
        metric_id=metric.metric_id,
        grain=grain,
        catalog_version=catalog_version,
        volume_unit="orders" if table == "orders" else f"{table} rows",
        rule=rule,
        periods=periods,
    )


__all__ = [
    "CompletenessGrain",
    "CompletenessReport",
    "CompletenessRule",
    "PeriodCoverage",
    "assess_metric",
    "assess_monthly_volumes",
    "read_monthly_volumes",
    "roll_up",
]
