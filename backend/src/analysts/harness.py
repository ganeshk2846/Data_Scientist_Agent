"""Typed analyst harness (ANA-1, ANA-2, SAFE-8).

Analysts receive table references and parameters, never a connection. They run
as ordinary in-process functions over the copied rows and return a validated
``AnalystOutput``. There is deliberately no code execution or SQL generation in
this boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from contracts.models import (
    AnalystColumn,
    AnalystColumnRole,
    AnalystInput,
    AnalystOutput as V1AnalystOutput,
    ExecutionColumn,
    ExecutionResult,
    MetricDefinition,
    TableRef,
)
from contracts.v2 import AnalystOutput

from .anomaly import AnomalyAnalyst
from .driver import DriverAnalyst
from .forecast import ForecastAnalyst
from .impact import ImpactAnalyst
from .scenario import ScenarioAnalyst
from .segment import SegmentAnalyst


class UnsupportedAnalystError(ValueError):
    """The requested analyst module is not registered."""


class AnalystModule(Protocol):
    def run(self, analyst_input: AnalystInput) -> V1AnalystOutput | AnalystOutput:
        ...


class AnalystHarness:
    """Converts query rows into typed tables and dispatches a pure analyst."""

    def __init__(
        self,
        modules: Mapping[str, AnalystModule] | None = None,
    ) -> None:
        if modules is None:
            modules = {
                "anomaly": AnomalyAnalyst(),
                "driver": DriverAnalyst(),
                "forecast": ForecastAnalyst(),
                "impact": ImpactAnalyst(),
                "scenario": ScenarioAnalyst(),
                "segment": SegmentAnalyst(),
            }
        self._modules = dict(modules)

    @property
    def modules(self) -> tuple[str, ...]:
        return tuple(sorted(self._modules))

    def table_from_execution(
        self,
        execution: ExecutionResult,
        *,
        roles: Mapping[str, AnalystColumnRole] | None = None,
    ) -> TableRef:
        role_overrides = {
            key.lower(): value for key, value in (roles or {}).items()
        }
        columns = tuple(
            AnalystColumn(
                name=column.name,
                type=column.type,
                role=role_overrides.get(column.name.lower())
                or _infer_role(column),
            )
            for column in execution.columns
        )
        rows = tuple(execution.rows or ())
        return TableRef(
            query_id=execution.query_id,
            columns=columns,
            row_count=len(rows),
            uri=f"inline://{execution.query_id}",
            rows=rows,
        )

    def build_input(
        self,
        module: str,
        params: Mapping[str, object],
        tables: Mapping[str, ExecutionResult | TableRef],
        *,
        metric: MetricDefinition | None = None,
        run_id: str,
        seed: int | None = None,
    ) -> AnalystInput:
        if module not in self._modules:
            raise UnsupportedAnalystError(
                f"unsupported analyst module: {module}"
            )
        normalized_tables: dict[str, TableRef] = {}
        for name, table in tables.items():
            if isinstance(table, TableRef):
                normalized_tables[name] = table
            elif isinstance(table, ExecutionResult):
                normalized_tables[name] = self.table_from_execution(table)
            else:
                raise TypeError(
                    f"table {name!r} must be an ExecutionResult or TableRef"
                )
        return AnalystInput(
            module=module,  # type: ignore[arg-type]
            params=dict(params),
            tables=normalized_tables,
            metric=metric,
            run_id=run_id,
            seed=seed,
        )

    def run(self, analyst_input: AnalystInput) -> V1AnalystOutput | AnalystOutput:
        module = self._modules.get(analyst_input.module)
        if module is None:
            raise UnsupportedAnalystError(
                f"unsupported analyst module: {analyst_input.module}"
            )
        output = module.run(analyst_input)
        if not isinstance(output, V1AnalystOutput):
            raise TypeError("an analyst must return AnalystOutput")
        if output.module != analyst_input.module:
            raise ValueError("analyst output module does not match its input")
        return output


def _infer_role(column: ExecutionColumn) -> AnalystColumnRole:
    name = column.name.lower()
    data_type = column.type.upper()
    if column.role is not None:
        return column.role  # type: ignore[return-value]
    if name == "id" or name.endswith("_id"):
        return "key"
    if (
        "DATE" in data_type
        or "TIME" in data_type
        or name in {"month", "period", "date", "week", "quarter", "year"}
        or name.endswith("_date")
        or name.endswith("_month")
    ):
        return "time"
    if any(
        token in data_type
        for token in ("INT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE", "REAL")
    ):
        return "measure"
    return "dimension"


__all__ = [
    "AnalystHarness",
    "AnalystModule",
    "UnsupportedAnalystError",
]
