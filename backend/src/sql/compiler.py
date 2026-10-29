"""Deterministic governed-metric compiler (MET-3, SQL-10).

A governed definition carries its formula, required filters, allowed dimensions
and approved join path. The compiler renders those slots through fixed templates,
checks every table/column against the retrieved catalog, validates the resulting
candidate, and records an exact allowlist. No model is involved.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from jinja2 import Environment, StrictUndefined, TemplateError

from contracts.models import (
    AllowlistedColumn,
    IntendedColumn,
    MetricAllowedDimension,
    MetricDefinition,
    MetricFilter,
    Period,
    SchemaAllowlist,
    SqlCandidate,
    ValidationResult,
)
from schema_retriever.catalog import JoinEdge, JoinGraph, SchemaCatalog

from .validator import SQLValidator

_TABLE_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
_FORMULA_COLUMN = re.compile(
    r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}\.([A-Za-z_][A-Za-z0-9_]*)"
)
_ALIASES = {
    "orders": "o",
    "order_items": "oi",
    "order_payments": "op",
    "order_reviews": "r",
    "customers": "c",
    "products": "p",
    "sellers": "s",
}
_TEMPLATES = Environment(autoescape=False, undefined=StrictUndefined)


class MetricCompilationError(ValueError):
    """A governed metric cannot be compiled into a validated candidate."""


@dataclass(frozen=True, slots=True)
class CompiledMetric:
    candidate: SqlCandidate
    allowlist: SchemaAllowlist
    definition: MetricDefinition
    validation: ValidationResult


def _escape(value: str) -> str:
    return value.replace("'", "''")


def _candidate_id(sql: str, dialect: str) -> str:
    digest = hashlib.sha256(f"compiler\n{dialect}\n{sql}".encode("utf-8")).hexdigest()
    return f"compiler-{digest[:12]}"


class SQLCompiler:
    """Compiles one governed definition into deterministic, bounded SQL."""

    def __init__(
        self,
        catalog: SchemaCatalog,
        *,
        dialect: str = "sqlite",
        limit: int = 100,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self._catalog = catalog
        self._join_graph = JoinGraph.from_catalog(catalog)
        self._dialect = dialect
        self._limit = limit
        self._edge_by_id = {edge.edge_id: edge for edge in self._join_graph.edges}

    @property
    def catalog(self) -> SchemaCatalog:
        return self._catalog

    def compile(
        self,
        definition: MetricDefinition,
        *,
        dimensions: Iterable[str] = (),
        filters: Iterable[MetricFilter] = (),
        period: Period | None = None,
        time_grain: str | None = None,
    ) -> CompiledMetric:
        dimension_names = tuple(dict.fromkeys(dimensions))
        resolved_dimensions = tuple(
            self._dimension(definition, name) for name in dimension_names
        )
        if time_grain is not None and time_grain not in {
            "day",
            "week",
            "month",
            "quarter",
            "year",
        }:
            raise MetricCompilationError(f"unsupported time grain: {time_grain}")

        time_dimension = next(
            (
                dimension
                for dimension in resolved_dimensions
                if dimension.time_grain is not None
            ),
            None,
        )
        if time_grain is None and time_dimension is not None:
            time_grain = time_dimension.time_grain
        if time_grain is not None and time_dimension is not None:
            if time_dimension.time_grain != time_grain:
                raise MetricCompilationError(
                    "the requested dimension and time grain disagree"
                )
            resolved_dimensions = tuple(
                dimension
                for dimension in resolved_dimensions
                if dimension is not time_dimension
            )

        filter_list = list(dict.fromkeys(filters))
        required_tables = self._required_tables(
            definition,
            resolved_dimensions,
            filter_list,
            period,
            time_grain,
        )
        aliases = self._aliases(required_tables)
        joins = self._joins(
            definition,
            required_tables,
            resolved_dimensions,
        )
        columns: dict[str, set[str]] = {}

        def remember(table: str, column: str) -> None:
            self._require_column(table, column)
            columns.setdefault(table.lower(), set()).add(column)

        for edge in joins:
            for left_column, right_column in edge.column_pairs:
                remember(edge.left_table, left_column)
                remember(edge.right_table, right_column)

        projections: list[str] = []
        intended: list[IntendedColumn] = []
        group_by: list[str] = []
        for dimension in resolved_dimensions:
            expression = self._dimension_expression(
                dimension, aliases[dimension.table.lower()]
            )
            projections.append(f"{expression} AS {dimension.name}")
            intended.append(
                IntendedColumn(name=dimension.name, role="dimension")
            )
            group_by.append(expression)
            if not dimension.time_grain:
                remember(dimension.table, dimension.column)

        if time_grain is not None:
            date_table, date_column = self._date_parts(definition)
            expression = self._time_expression(
                time_grain, aliases[date_table.lower()], date_column
            )
            projections.append(f"{expression} AS {time_grain}")
            intended.append(IntendedColumn(name=time_grain, role="time"))
            group_by.append(expression)
            remember(date_table, date_column)

        formula = self._render_formula(definition, aliases)
        projections.append(f"{formula} AS {definition.metric_id}")
        intended.append(IntendedColumn(name=definition.metric_id, role="measure"))
        for table, column in _FORMULA_COLUMN.findall(definition.formula):
            remember(table, column)

        predicates: list[str] = []
        for required in definition.required_filters:
            rendered = self._render_required(required, aliases, remember)
            predicates.append(rendered)

        for item in filter_list:
            self._require_filter(definition, item)
            remember(item.table, item.column)
            predicates.append(self._render_filter(item, aliases[item.table.lower()]))

        if period is not None:
            date_table, date_column = self._date_parts(definition)
            alias = aliases[date_table.lower()]
            predicates.append(
                f"{alias}.{date_column} >= '{_escape(period.start.isoformat())}'"
            )
            predicates.append(
                f"{alias}.{date_column} < '{_escape(period.end.isoformat())}'"
            )
            remember(date_table, date_column)

        grain = tuple(dimension.name for dimension in resolved_dimensions)
        if time_grain is not None:
            grain = (*grain, time_grain)
        sql = self._sql(
            definition,
            aliases[definition.base_table.lower()],
            joins,
            projections,
            predicates,
            group_by,
        )

        allowlist = SchemaAllowlist(
            tables=tuple(
                sorted({table for table in required_tables}, key=str.lower)
            ),
            columns=tuple(
                AllowlistedColumn(table=table, column=column)
                for table in sorted(columns, key=str.lower)
                for column in sorted(columns[table], key=str.lower)
            ),
        )
        validation = SQLValidator(
            allowlist.tables,
            dialect=self._dialect,
            mode="enterprise",
            columns=[
                f"{column.table}.{column.column}" for column in allowlist.columns
            ],
        ).validate(sql)
        if not validation.approved:
            failed = "; ".join(
                f"{check.name}: {check.reason or check.status}"
                for check in validation.checks
                if check.status == "fail"
            )
            raise MetricCompilationError(
                f"compiled metric did not validate: {failed}"
            )

        candidate = SqlCandidate(
            candidate_id=_candidate_id(sql, self._dialect),
            sql=sql,
            dialect=self._dialect,
            origin="compiler",
            intended_columns=tuple(intended),
            grain=grain,
            uses_edges=tuple(sorted(edge.edge_id for edge in joins)),
        )
        return CompiledMetric(
            candidate=candidate,
            allowlist=allowlist,
            definition=definition,
            validation=validation,
        )

    def _dimension(
        self, definition: MetricDefinition, requested: str
    ) -> MetricAllowedDimension:
        lowered = requested.lower()
        for dimension in definition.allowed_dimensions:
            if dimension.name.lower() == lowered:
                return dimension
        raise MetricCompilationError(
            f"metric {definition.metric_id} does not allow dimension {requested}"
        )

    def _required_tables(
        self,
        definition: MetricDefinition,
        dimensions: tuple[MetricAllowedDimension, ...],
        filters: list[MetricFilter],
        period: Period | None,
        time_grain: str | None,
    ) -> tuple[str, ...]:
        tables = {
            definition.base_table,
            *(table for table, _ in _FORMULA_COLUMN.findall(definition.formula)),
            *(dimension.table for dimension in dimensions),
            *(item.table for item in filters),
        }
        for required in definition.required_filters:
            tables.update(_TABLE_PLACEHOLDER.findall(required))
        if period is not None or time_grain is not None:
            tables.add(self._date_parts(definition)[0])
        if not all(self._catalog.get_table(table) for table in tables):
            missing = sorted(
                table
                for table in tables
                if self._catalog.get_table(table) is None
            )
            raise MetricCompilationError(
                f"metric tables are missing from the catalog: {', '.join(missing)}"
            )
        return tuple(sorted(tables, key=str.lower))

    def _aliases(self, tables: tuple[str, ...]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        used: set[str] = set()
        for table in tables:
            base = _ALIASES.get(
                table.lower(), re.sub(r"[^a-z0-9]", "", table.lower())[:2] or "t"
            )
            alias = base
            suffix = 1
            while alias in used:
                suffix += 1
                alias = f"{base}{suffix}"
            aliases[table.lower()] = alias
            used.add(alias)
        return aliases

    def _joins(
        self,
        definition: MetricDefinition,
        required_tables: tuple[str, ...],
        dimensions: tuple[MetricAllowedDimension, ...],
    ) -> tuple[JoinEdge, ...]:
        allowed = {edge.edge_id for edge in definition.join_path}
        base = definition.base_table.lower()
        ordered: list[JoinEdge] = []
        seen: set[str] = set()
        for table in required_tables:
            target = table.lower()
            if target == base:
                continue
            path = self._join_graph.find_path(base, target)
            if path is None:
                raise MetricCompilationError(
                    f"no approved join path from {definition.base_table} to {table}"
                )
            path_ids = {edge.edge_id for edge in path}
            if not path_ids <= allowed:
                raise MetricCompilationError(
                    f"join path to {table} is not in the governed definition"
                )
            for dimension in dimensions:
                if dimension.table.lower() == target and dimension.join_edges:
                    if not path_ids <= set(dimension.join_edges):
                        raise MetricCompilationError(
                            f"join path to {table} is not approved for "
                            f"dimension {dimension.name}"
                        )
            for edge in path:
                if edge.status != "approved":
                    raise MetricCompilationError(
                        f"join edge {edge.edge_id} is not approved"
                    )
                if edge.edge_id not in seen:
                    seen.add(edge.edge_id)
                    ordered.append(edge)
        return tuple(ordered)

    def _date_parts(self, definition: MetricDefinition) -> tuple[str, str]:
        if "." not in definition.date_column:
            raise MetricCompilationError(
                "metric date_column must be written as table.column"
            )
        table, column = definition.date_column.split(".", 1)
        if not table or not column:
            raise MetricCompilationError(
                "metric date_column must be written as table.column"
            )
        return table, column

    def _require_column(self, table: str, column: str) -> None:
        if self._catalog.get_column(table, column) is None:
            raise MetricCompilationError(
                f"column {table}.{column} is missing from the catalog"
            )

    def _require_filter(
        self, definition: MetricDefinition, item: MetricFilter
    ) -> None:
        allowed = {
            (dimension.table.lower(), dimension.column.lower())
            for dimension in definition.allowed_dimensions
        }
        if "." in definition.date_column:
            date_table, date_column = definition.date_column.split(".", 1)
            allowed.add((date_table.lower(), date_column.lower()))
        if (item.table.lower(), item.column.lower()) not in allowed:
            raise MetricCompilationError(
                f"metric {definition.metric_id} does not allow a filter on "
                f"{item.table}.{item.column}"
            )

    def _render_formula(
        self, definition: MetricDefinition, aliases: dict[str, str]
    ) -> str:
        tables = set(_TABLE_PLACEHOLDER.findall(definition.formula))
        unknown = sorted(table for table in tables if table.lower() not in aliases)
        if unknown:
            raise MetricCompilationError(
                f"formula references unjoined tables: {', '.join(unknown)}"
            )
        return self._render_template(definition.formula, aliases)

    def _render_required(
        self,
        required: str,
        aliases: dict[str, str],
        remember,
    ) -> str:
        for table, column in _FORMULA_COLUMN.findall(required):
            remember(table, column)
        return self._render_template(required, aliases)

    def _render_template(
        self, template: str, aliases: dict[str, str]
    ) -> str:
        try:
            return _TEMPLATES.from_string(template).render(**aliases)
        except TemplateError as exc:
            raise MetricCompilationError(
                f"metric template could not be rendered: {exc}"
            ) from exc

    def _render_filter(
        self, item: MetricFilter, alias: str
    ) -> str:
        column = f"{alias}.{item.column}"
        if item.operator == "in":
            values = ", ".join(f"'{_escape(value)}'" for value in item.value)
            return f"{column} IN ({values})"
        return f"{column} {item.operator} '{_escape(item.value)}'"

    def _dimension_expression(
        self, dimension: MetricAllowedDimension, alias: str
    ) -> str:
        if dimension.time_grain is not None:
            return self._time_expression(
                dimension.time_grain, alias, dimension.column
            )
        return f"{alias}.{dimension.column}"

    def _time_expression(
        self, grain: str, alias: str, column: str
    ) -> str:
        value = f"{alias}.{column}"
        dialect = self._dialect.lower()
        if dialect == "sqlite":
            if grain == "day":
                return f"date({value})"
            if grain == "week":
                return f"strftime('%Y-%W', {value})"
            if grain == "month":
                return f"strftime('%Y-%m', {value})"
            if grain == "quarter":
                return (
                    f"strftime('%Y', {value}) || '-Q' || "
                    f"((CAST(strftime('%m', {value}) AS INTEGER) + 2) / 3)"
                )
            return f"strftime('%Y', {value})"
        if dialect in {"duckdb", "postgres", "postgresql"}:
            return f"date_trunc('{grain}', {value})"
        return f"date_trunc('{grain}', {value})"

    def _sql(
        self,
        definition: MetricDefinition,
        base_alias: str,
        joins: tuple[JoinEdge, ...],
        projections: list[str],
        predicates: list[str],
        group_by: list[str],
    ) -> str:
        select = ",\n  ".join(projections)
        lines = [
            "SELECT",
            f"  {select}",
            f'FROM "{definition.base_table}" AS {base_alias}',
        ]
        joined = {definition.base_table.lower()}
        remaining = list(joins)
        while remaining:
            progressed = False
            for edge in list(remaining):
                left = edge.left_table.lower()
                right = edge.right_table.lower()
                if left in joined and right not in joined:
                    new_table = edge.right_table
                    new_alias = self._table_alias(new_table)
                    join_predicates = " AND ".join(
                        f"{self._table_alias(edge.left_table)}.{left_column} "
                        f"= {new_alias}.{right_column}"
                        for left_column, right_column in edge.column_pairs
                    )
                    lines.append(
                        f'JOIN "{new_table}" AS {new_alias} '
                        f"ON {join_predicates}"
                    )
                    joined.add(right)
                    remaining.remove(edge)
                    progressed = True
                elif right in joined and left not in joined:
                    new_table = edge.left_table
                    new_alias = self._table_alias(new_table)
                    join_predicates = " AND ".join(
                        f"{new_alias}.{left_column} "
                        f"= {self._table_alias(edge.right_table)}.{right_column}"
                        for left_column, right_column in edge.column_pairs
                    )
                    lines.append(
                        f'JOIN "{new_table}" AS {new_alias} '
                        f"ON {join_predicates}"
                    )
                    joined.add(left)
                    remaining.remove(edge)
                    progressed = True
            if not progressed:
                raise MetricCompilationError("governed join path is disconnected")
        if predicates:
            lines.append("WHERE " + "\n  AND ".join(predicates))
        if group_by:
            lines.append("GROUP BY " + ", ".join(group_by))
            lines.append("ORDER BY 1 ASC")
        lines.append(f"LIMIT {self._limit if group_by else 1}")
        return "\n".join(lines)

    def _table_alias(self, table: str) -> str:
        lowered = table.lower()
        for candidate, alias in _ALIASES.items():
            if candidate == lowered:
                return alias
        return re.sub(r"[^a-z0-9]", "", lowered)[:2] or "t"


__all__ = ["CompiledMetric", "MetricCompilationError", "SQLCompiler"]
