"""Descriptive (WHAT): aggregate, rank and trend summaries, in SQL.

``scope.md`` routes ``descriptive`` to ``sql`` with zero engines, and the
frozen tool registry has no ``python.descriptive``. So this engine computes
every figure with SQL: the input rows (already produced by an upstream
``sql`` / ``analytical_table`` step) are loaded into a private in-memory
SQLite database and summarised there. The result is a contract-valid
``tool="sql"`` rows result whose ``query_id`` hashes the exact SQL text and
the input query ids, so every cell links back to the query that produced it
(SAFE-3, SAFE-8).

Only ``:memory:`` is ever opened. Identifiers are checked against the input
table's declared columns and quoted; every value is a bound parameter.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from contracts.models import ColumnRole, ContractModel, TableRef
from contracts.v2 import RowsColumn, RowsPayload, ToolProvenance, ToolResult
from semantic.layers import synthetic_caveat

from .base import EngineData, Timer, derived_query_id
from .report import (
    ChartHint,
    EngineReport,
    EngineRun,
    KeyNumber,
    ReportTable,
    confidence_from,
    insufficient_report,
)

ENGINE = "descriptive"
ENGINE_VERSION = "descriptive-2.0.0"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GRAIN_WIDTH = {"day": 10, "month": 7, "year": 4}
_AGGREGATES = {"sum": "SUM", "avg": "AVG", "mean": "AVG", "count": "COUNT", "min": "MIN", "max": "MAX"}
_REMAINDER = "All remaining"


class DescriptiveParams(ContractModel):
    operation: Literal["aggregate", "rank", "trend"]
    table: str | None = None
    measure: str = Field(min_length=1)
    aggregation: Literal["sum", "avg", "mean", "count", "min", "max"] = "sum"
    dimensions: tuple[str, ...] = ()
    period_column: str | None = None
    grain: Literal["day", "month", "year"] = "month"
    start: str | None = None
    end: str | None = None
    comparison_start: str | None = None
    comparison_end: str | None = None
    filters: dict[str, str | float | int | tuple[str | float | int, ...]] = Field(default_factory=dict)
    top_n: int = Field(default=10, ge=1, le=100)
    order: Literal["desc", "asc"] = "desc"
    unit: str = ""

    @model_validator(mode="after")
    def _operation_needs(self) -> DescriptiveParams:
        if self.operation == "trend" and self.period_column is None:
            raise ValueError("a trend summary needs a period_column")
        if self.operation == "rank" and not self.dimensions:
            raise ValueError("a ranking needs at least one dimension")
        if (self.comparison_start is None) != (self.comparison_end is None):
            raise ValueError("a comparison window needs both start and end")
        if self.comparison_start is not None and self.period_column is None:
            raise ValueError("a period comparison needs a period_column")
        return self


def _quote(name: str) -> str:
    return '"' + name + '"'


def _check(name: str, available: set[str]) -> str:
    if not _IDENTIFIER.match(name) or name not in available:
        raise ValueError(f"column {name!r} is not a declared column of the input table")
    return _quote(name)


def _sqlite_type(kind: str) -> str:
    upper = kind.upper()
    if "INT" in upper:
        return "INTEGER"
    if upper in {"REAL", "FLOAT", "DOUBLE", "NUMERIC"} or "REAL" in upper:
        return "REAL"
    return "TEXT"


def _load(table: TableRef) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    columns = ", ".join(f"{_quote(column.name)} {_sqlite_type(column.type)}" for column in table.columns)
    connection.execute(f"CREATE TABLE input_rows ({columns})")
    placeholders = ", ".join("?" for _ in table.columns)
    connection.executemany(f"INSERT INTO input_rows VALUES ({placeholders})", table.rows)
    return connection


def _where(params: DescriptiveParams, available: set[str], window: tuple[str | None, str | None]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    values: list[Any] = []
    for column, value in sorted(params.filters.items()):
        quoted = _check(column, available)
        if isinstance(value, tuple):
            clauses.append(f"{quoted} IN ({', '.join('?' for _ in value)})")
            values.extend(value)
        else:
            clauses.append(f"{quoted} = ?")
            values.append(value)
    start, end = window
    if params.period_column is not None:
        period = _check(params.period_column, available)
        if start is not None:
            clauses.append(f"{period} >= ?")
            values.append(start)
        if end is not None:
            clauses.append(f"{period} < ?")
            values.append(end)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", values


def _aggregate_sql(params: DescriptiveParams, available: set[str]) -> str:
    function = _AGGREGATES[params.aggregation]
    measure = _check(params.measure, available)
    return f"{function}({measure})"


def _aggregate(params: DescriptiveParams, available: set[str]) -> tuple[str, list[Any], tuple[str, ...]]:
    dims = [_check(name, available) for name in params.dimensions]
    value = _aggregate_sql(params, available)
    where, values = _where(params, available, (params.start, params.end))
    select_dims = "".join(f"{dim} AS {dim}, " for dim in dims)
    group = f" GROUP BY {', '.join(dims)}" if dims else ""
    if params.comparison_start is None:
        sql = f"SELECT {select_dims}{value} AS value FROM input_rows{where}{group}"
        if dims:
            sql += f" ORDER BY value {params.order.upper()}, {', '.join(dims)}"
        return sql, values, (*params.dimensions, "value")
    comparison_where, comparison_values = _where(
        params, available, (params.comparison_start, params.comparison_end)
    )
    join = " AND ".join(f"c.{dim} IS b.{dim}" for dim in dims) or "1 = 1"
    keys = "".join(f"COALESCE(c.{dim}, b.{dim}) AS {dim}, " for dim in dims)
    sql = (
        f"WITH c AS (SELECT {select_dims}{value} AS value FROM input_rows{where}{group}), "
        f"b AS (SELECT {select_dims}{value} AS value FROM input_rows{comparison_where}{group}) "
        f"SELECT {keys}c.value AS value, b.value AS comparison_value, "
        f"c.value - b.value AS change, "
        f"CASE WHEN b.value IS NULL OR b.value = 0 THEN NULL "
        f"ELSE 100.0 * (c.value - b.value) / b.value END AS change_pct "
        f"FROM c FULL OUTER JOIN b ON {join} "
        f"ORDER BY change IS NULL, change {params.order.upper()}" + "".join(f", {dim}" for dim in dims)
    )
    return sql, values + comparison_values, (*params.dimensions, "value", "comparison_value", "change", "change_pct")


def _rank(params: DescriptiveParams, available: set[str]) -> tuple[str, list[Any], tuple[str, ...]]:
    dims = [_check(name, available) for name in params.dimensions]
    value = _aggregate_sql(params, available)
    where, values = _where(params, available, (params.start, params.end))
    direction = params.order.upper()
    tie = ", ".join(dims)
    remainder = ", ".join("?" for _ in dims)
    sql = (
        f"WITH a AS (SELECT {', '.join(f'{dim} AS {dim}' for dim in dims)}, {value} AS value "
        f"FROM input_rows{where} GROUP BY {tie}), "
        f"r AS (SELECT a.*, ROW_NUMBER() OVER (ORDER BY value {direction}, {tie}) AS rank, "
        f"CASE WHEN SUM(value) OVER () = 0 THEN NULL ELSE value * 1.0 / SUM(value) OVER () END AS share FROM a) "
        f"SELECT * FROM (SELECT {tie}, value, share, rank FROM r WHERE rank <= ? "
        f"UNION ALL SELECT {remainder}, SUM(value), SUM(share), NULL FROM r WHERE rank > ? HAVING COUNT(*) > 0) "
        f"ORDER BY rank IS NULL, rank"
    )
    return sql, values + [params.top_n] + [_REMAINDER] * len(dims) + [params.top_n], (
        *params.dimensions,
        "value",
        "share",
        "rank",
    )


def _trend(params: DescriptiveParams, available: set[str]) -> tuple[str, list[Any], tuple[str, ...], str]:
    period = _check(params.period_column or "", available)
    value = _aggregate_sql(params, available)
    width = _GRAIN_WIDTH[params.grain]
    where, values = _where(params, available, (params.start, params.end))
    series = (
        f"SELECT substr({period}, 1, {width}) AS period, {value} AS value "
        f"FROM input_rows{where} GROUP BY 1 ORDER BY 1"
    )
    summary = (
        f"WITH s AS ({series}), n AS (SELECT period, value, ROW_NUMBER() OVER (ORDER BY period) - 1 AS x FROM s) "
        "SELECT COUNT(*) AS periods, "
        "(SELECT period FROM n ORDER BY x LIMIT 1) AS first_period, "
        "(SELECT value FROM n ORDER BY x LIMIT 1) AS first_value, "
        "(SELECT period FROM n ORDER BY x DESC LIMIT 1) AS last_period, "
        "(SELECT value FROM n ORDER BY x DESC LIMIT 1) AS last_value, "
        "CASE WHEN (SELECT value FROM n ORDER BY x LIMIT 1) = 0 THEN NULL ELSE "
        "100.0 * ((SELECT value FROM n ORDER BY x DESC LIMIT 1) - (SELECT value FROM n ORDER BY x LIMIT 1)) "
        "/ (SELECT value FROM n ORDER BY x LIMIT 1) END AS change_pct, "
        "CASE WHEN COUNT(*) * SUM(x * x) - SUM(x) * SUM(x) = 0 THEN NULL ELSE "
        "(COUNT(*) * SUM(x * value) - SUM(x) * SUM(value)) * 1.0 / (COUNT(*) * SUM(x * x) - SUM(x) * SUM(x)) "
        "END AS slope_per_period, "
        "AVG(value) AS mean_value, MIN(value) AS min_value, MAX(value) AS max_value, "
        "(SELECT period FROM n ORDER BY value DESC, x LIMIT 1) AS peak_period, "
        "(SELECT period FROM n ORDER BY value ASC, x LIMIT 1) AS trough_period "
        "FROM n"
    )
    return series, values, ("period", "value"), summary


def _rows_payload(query_id: str, names: tuple[str, ...], rows: list[tuple[Any, ...]], roles: Mapping[str, ColumnRole]) -> RowsPayload:
    columns = []
    for index, name in enumerate(names):
        sample = next((row[index] for row in rows if row[index] is not None), None)
        kind = "INTEGER" if isinstance(sample, int) else "REAL" if isinstance(sample, float) else "TEXT"
        columns.append(RowsColumn(name=name, type=kind, role=roles.get(name, "measure" if kind != "TEXT" else "dimension")))
    return RowsPayload(query_id=query_id, columns=tuple(columns), rows=tuple(rows), row_count=len(rows))


def _insufficient(reason: str, data: EngineData, timer: Timer) -> EngineRun:
    layer, synthetic = data.layer()
    result = ToolResult(
        step_id=data.step_id,
        tool="sql",
        status="insufficient_evidence",
        produces="rows",
        provenance=ToolProvenance(
            source="sql",
            query_ids=data.query_ids(),
            input_step_ids=data.input_step_ids,
            deterministic=True,
            data_layer=layer,  # type: ignore[arg-type]
            synthetic_tables=synthetic,
        ),
        caveats=tuple(caveat for caveat in (synthetic_caveat(synthetic),) if caveat),
        reason=reason,
        duration_ms=timer.elapsed_ms(),
    )
    return EngineRun(result, insufficient_report(ENGINE, "sql", reason))


def execute(params: Mapping[str, Any], data: EngineData) -> EngineRun:
    """Run one descriptive operation in SQL over the supplied rows."""

    timer = Timer()
    try:
        parsed = DescriptiveParams.model_validate(dict(params))
    except ValidationError as exc:
        return _insufficient(f"Invalid descriptive parameters: {exc}", data, timer)
    name = parsed.table or next(iter(sorted(data.tables)), None)
    table = data.tables.get(name) if name is not None else None
    if table is None:
        return _insufficient("A descriptive summary needs an input table.", data, timer)
    if not table.rows:
        return _empty(parsed, table, data, timer)
    available = {column.name for column in table.columns}
    summary_sql: str | None = None
    try:
        if parsed.operation == "aggregate":
            sql, values, names = _aggregate(parsed, available)
        elif parsed.operation == "rank":
            sql, values, names = _rank(parsed, available)
        else:
            sql, values, names, summary_sql = _trend(parsed, available)
    except ValueError as exc:
        return _insufficient(str(exc), data, timer)

    connection = _load(table)
    try:
        rows = [tuple(row) for row in connection.execute(sql, values).fetchall()]
        summary_row: tuple[Any, ...] | None = None
        summary_names: tuple[str, ...] = ()
        if summary_sql is not None:
            cursor = connection.execute(summary_sql, values)
            summary_names = tuple(item[0] for item in cursor.description)
            summary_row = tuple(cursor.fetchone())
    except sqlite3.Error as exc:
        return _insufficient(f"The descriptive SQL could not run: {exc}", data, timer)
    finally:
        connection.close()

    query_id = derived_query_id("DESC", sql, values, table.query_id)
    query_ids = [query_id, table.query_id]
    if summary_sql is not None:
        query_ids.insert(1, derived_query_id("DESC", summary_sql, values, table.query_id))
    if not rows:
        return _empty(parsed, table, data, timer, query_id=query_id, names=names)

    roles: dict[str, ColumnRole] = {dimension: "dimension" for dimension in parsed.dimensions}
    roles["period"] = "time"
    roles["rank"] = "key"
    payload = _rows_payload(query_id, names, rows, roles)
    layer, synthetic = data.layer()
    result = ToolResult(
        step_id=data.step_id,
        tool="sql",
        status="ok",
        produces="rows",
        rows=payload,
        provenance=ToolProvenance(
            source="sql",
            query_ids=tuple(dict.fromkeys(query_ids)),
            input_step_ids=data.input_step_ids,
            deterministic=True,
            data_layer=layer,  # type: ignore[arg-type]
            synthetic_tables=synthetic,
        ),
        caveats=tuple(caveat for caveat in (synthetic_caveat(synthetic),) if caveat),
        duration_ms=timer.elapsed_ms(),
    )
    report = _report(parsed, names, rows, summary_names, summary_row)
    return EngineRun(result, report)


def run(params: Mapping[str, Any], data: EngineData) -> ToolResult:
    return execute(params, data).result


def _empty(
    params: DescriptiveParams,
    table: TableRef,
    data: EngineData,
    timer: Timer,
    *,
    query_id: str | None = None,
    names: tuple[str, ...] = ("value",),
) -> EngineRun:
    """A true zero-row result is a finding, not a failure (TR-6, SQL-12)."""
    layer, synthetic = data.layer()
    payload = RowsPayload(
        query_id=query_id or derived_query_id("DESC", "empty", table.query_id),
        columns=tuple(RowsColumn(name=name, type="REAL", role="measure") for name in names),
        rows=(),
        row_count=0,
    )
    result = ToolResult(
        step_id=data.step_id,
        tool="sql",
        status="empty",
        produces="rows",
        rows=payload,
        reason="No rows matched the requested window and filters.",
        provenance=ToolProvenance(
            source="sql",
            query_ids=(payload.query_id, table.query_id),
            input_step_ids=data.input_step_ids,
            deterministic=True,
            data_layer=layer,  # type: ignore[arg-type]
            synthetic_tables=synthetic,
        ),
        caveats=tuple(caveat for caveat in (synthetic_caveat(synthetic),) if caveat),
        duration_ms=timer.elapsed_ms(),
    )
    report = EngineReport(
        engine=ENGINE,
        method=f"sql.{params.operation}",
        assumptions=("No rows matched the requested window and filters; zero rows is reported as a finding.",),
        confidence=confidence_from(sample_size=0, basis="No matching rows."),
    )
    return EngineRun(result, report)


def _report(
    params: DescriptiveParams,
    names: tuple[str, ...],
    rows: list[tuple[Any, ...]],
    summary_names: tuple[str, ...],
    summary_row: tuple[Any, ...] | None,
) -> EngineReport:
    unit = params.unit
    tables = [ReportTable(name=params.operation, columns=names, rows=tuple(rows))]
    key_numbers: list[KeyNumber] = []
    assumptions = [
        f"Every figure is computed by SQL ({params.aggregation.upper()} of {params.measure}) over the supplied rows.",
        "Windows are half-open: start inclusive, end exclusive.",
    ]
    value_index = names.index("value")
    chart: ChartHint
    if params.operation == "trend" and summary_row is not None:
        summary = dict(zip(summary_names, summary_row, strict=True))
        tables.append(ReportTable(name="trend_summary", columns=summary_names, rows=(summary_row,)))
        for key in ("first_value", "last_value", "change_pct", "slope_per_period", "mean_value", "min_value", "max_value"):
            value = summary.get(key)
            key_numbers.append(
                KeyNumber(
                    name=key,
                    value=float(value) if value is not None else None,
                    unit="%" if key == "change_pct" else unit,
                    label=key.replace("_", " "),
                )
            )
        key_numbers.append(KeyNumber(name="periods", value=float(summary["periods"]), label="periods"))
        assumptions.append(
            "The trend slope is an ordinary least-squares slope over period index, computed in SQL; "
            "it describes the window and is not a forecast."
        )
        chart = ChartHint(kind="line", table="trend", x="period", y=("value",), title=f"{params.measure} by {params.grain}")
        confidence = confidence_from(sample_size=int(summary["periods"]), basis="Measured values from SQL; no estimation.")
    elif params.operation == "rank":
        top = [row for row in rows if row[names.index("rank")] is not None]
        remainder = [row for row in rows if row[names.index("rank")] is None]
        for row in top[:3]:
            label = " / ".join(str(row[index]) for index in range(len(params.dimensions)))
            key_numbers.append(KeyNumber(name=f"rank_{row[names.index('rank')]}", value=float(row[value_index]), unit=unit, label=label))
        if remainder:
            key_numbers.append(KeyNumber(name="remainder", value=float(remainder[0][value_index]), unit=unit, label=_REMAINDER))
            assumptions.append(f"Only the top {params.top_n} are listed; the remainder is reported as one aggregate row.")
        chart = ChartHint(kind="bar", table="rank", x=params.dimensions[0], y=("value",), title=f"{params.measure} ranked by {', '.join(params.dimensions)}")
        confidence = confidence_from(sample_size=len(rows), basis="Measured values from SQL; no estimation.")
    else:
        for row in rows[:5]:
            label = " / ".join(str(row[index]) for index in range(len(params.dimensions))) or "total"
            key_numbers.append(KeyNumber(name=f"value:{label}", value=_number(row[value_index]), unit=unit, label=label))
            if "change_pct" in names:
                key_numbers.append(KeyNumber(name=f"change_pct:{label}", value=_number(row[names.index("change_pct")]), unit="%", label=label))
        chart = (
            ChartHint(kind="grouped_bar" if "comparison_value" in names else "bar", table="aggregate", x=params.dimensions[0],
                      y=("value", "comparison_value") if "comparison_value" in names else ("value",), title=f"{params.measure} by {', '.join(params.dimensions)}")
            if params.dimensions
            else ChartHint(kind="table", table="aggregate", x="value", y=("value",), title=params.measure)
        )
        confidence = confidence_from(sample_size=len(rows), basis="Measured values from SQL; no estimation.")
    return EngineReport(
        engine=ENGINE,
        method=f"sql.{params.operation}",
        tables=tuple(tables),
        key_numbers=tuple(key_numbers),
        assumptions=tuple(assumptions),
        confidence=confidence,
        chart_hint=chart,
    )


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


__all__ = ["DescriptiveParams", "ENGINE_VERSION", "execute", "run"]
