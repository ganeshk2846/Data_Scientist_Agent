"""Shared plumbing for the V2 engine layer (TR-1..8, SY-1, SAFE-8).

An engine receives its rows as :class:`EngineData` - tables that an upstream
``sql`` or ``analytical_table`` step already produced - and returns one
:class:`contracts.v2.ToolResult`. Nothing here opens a warehouse connection,
calls a model or builds SQL against the warehouse. The data layer is derived
from the physical tables the rows came from (SY-2), never declared.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd

from contracts.models import AnalystColumn, AnalystInput, ColumnRole, TableRef
from contracts.v2 import (
    AnalystOutput,
    EngineProvenance,
    FitQuality,
    PythonEngineName,
    ToolProvenance,
    ToolResult,
)
from semantic.layers import data_layer_for, synthetic_caveat

from .report import EngineReport, EngineRun, attach_report, insufficient_report

ENGINE_LAYER_VERSION = "engines-2.0.0"


@dataclass(frozen=True)
class EngineData:
    """The rows an engine may read, plus where they came from.

    ``source_tables`` lists the physical warehouse tables the upstream steps
    read. It is the only input to the synthetic label (SY-1, SY-2).
    """

    tables: Mapping[str, TableRef]
    source_tables: tuple[str, ...] = ()
    seed: int = 0
    run_id: str = "engine-run"
    step_id: str = "P1"
    input_step_ids: tuple[str, ...] = ()
    analytical_rows_synthetic: bool | None = None

    def table(self, name: str) -> TableRef | None:
        return self.tables.get(name)

    def query_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(table.query_id for table in self.tables.values()))

    def layer(self) -> tuple[str, tuple[str, ...]]:
        if not self.source_tables:
            return "real", ()
        return data_layer_for(
            self.source_tables,
            analytical_rows_synthetic=self.analytical_rows_synthetic,
        )


@dataclass
class Timer:
    started: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> int:
        return max(0, int((time.perf_counter() - self.started) * 1000))


# --------------------------------------------------------------------------- #
# Table helpers
# --------------------------------------------------------------------------- #


def _column_type(values: list[Any]) -> str:
    sample = next((value for value in values if value is not None), None)
    if isinstance(sample, bool) or isinstance(sample, int):
        return "INTEGER"
    if isinstance(sample, float):
        return "REAL"
    return "TEXT"


def _cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def table_from_frame(
    frame: pd.DataFrame,
    *,
    query_id: str,
    roles: Mapping[str, ColumnRole] | None = None,
) -> TableRef:
    """Build a :class:`TableRef` from a frame; roles default by dtype."""

    roles = dict(roles or {})
    columns = []
    rows = [tuple(_cell(value) for value in row) for row in frame.itertuples(index=False, name=None)]
    for index, name in enumerate(frame.columns):
        values = [row[index] for row in rows]
        kind = _column_type(values)
        role = roles.get(str(name))
        if role is None:
            role = "measure" if kind in {"INTEGER", "REAL"} else "dimension"
        columns.append(AnalystColumn(name=str(name), type=kind, role=role))
    return TableRef(
        query_id=query_id,
        columns=tuple(columns),
        row_count=len(rows),
        uri=f"engine://{query_id}",
        rows=tuple(rows),
    )


def frame_from_table(table: TableRef) -> pd.DataFrame:
    return pd.DataFrame(list(table.rows), columns=[column.name for column in table.columns])


def derived_query_id(prefix: str, *parts: Any) -> str:
    """A stable id for an engine-shaped table, derived from its inputs."""
    payload = json.dumps(parts, sort_keys=True, default=str)
    return f"{prefix}-{hashlib.sha256(payload.encode()).hexdigest()[:12]}"


# --------------------------------------------------------------------------- #
# ToolResult construction
# --------------------------------------------------------------------------- #


def analyst_input(module: str, params: Mapping[str, Any], tables: Mapping[str, TableRef], data: EngineData) -> AnalystInput:
    return AnalystInput(
        module=module,  # type: ignore[arg-type]
        params=dict(params),
        tables=dict(tables),
        run_id=data.run_id,
        seed=data.seed,
    )


def engine_result(
    *,
    tool: PythonEngineName,
    output: AnalystOutput,
    report: EngineReport,
    data: EngineData,
    timer: Timer,
    method: str,
    engine_version: str,
    method_fallback_reason: str | None = None,
    library: str | None = None,
    fit_quality: FitQuality | None = None,
) -> EngineRun:
    """Wrap an analyst output and its report in a contract ``ToolResult``."""

    layer, synthetic = data.layer()
    caveats = [caveat for caveat in (synthetic_caveat(synthetic),) if caveat]
    if output.status != "ok":
        reason = output.reason or "The engine could not produce a supported answer."
        return EngineRun(ToolResult(
            step_id=data.step_id,
            tool=tool,
            status="insufficient_evidence",
            produces="analyst_output",
            provenance=_provenance(
                data, tool, engine_version, method, method_fallback_reason, library, fit_quality, layer, synthetic
            ),
            caveats=tuple(caveats),
            reason=reason,
            duration_ms=timer.elapsed_ms(),
        ), insufficient_report(tool, method, reason))
    return EngineRun(ToolResult(
        step_id=data.step_id,
        tool=tool,
        status="ok",
        produces="analyst_output",
        analyst_output=attach_report(output, report),
        provenance=_provenance(
            data, tool, engine_version, method, method_fallback_reason, library, fit_quality, layer, synthetic
        ),
        caveats=tuple(caveats),
        duration_ms=timer.elapsed_ms(),
    ), report)


def insufficient(
    *,
    tool: PythonEngineName,
    reason: str,
    data: EngineData,
    timer: Timer,
    engine_version: str,
    method: str,
) -> EngineRun:
    layer, synthetic = data.layer()
    return EngineRun(ToolResult(
        step_id=data.step_id,
        tool=tool,
        status="insufficient_evidence",
        produces="analyst_output",
        provenance=_provenance(data, tool, engine_version, method, None, None, None, layer, synthetic),
        caveats=tuple(caveat for caveat in (synthetic_caveat(synthetic),) if caveat),
        reason=reason,
        duration_ms=timer.elapsed_ms(),
    ), insufficient_report(tool, method, reason))


def _provenance(
    data: EngineData,
    tool: PythonEngineName,
    engine_version: str,
    method: str,
    fallback: str | None,
    library: str | None,
    fit_quality: FitQuality | None,
    layer: str,
    synthetic: tuple[str, ...],
) -> ToolProvenance:
    return ToolProvenance(
        source="engine",
        query_ids=data.query_ids(),
        engine=EngineProvenance(
            name=tool,
            version=engine_version,
            seed=data.seed,
            method=method,
            method_fallback_reason=fallback,
            library=library,
            fit_quality=fit_quality,
        ),
        input_step_ids=data.input_step_ids,
        deterministic=True,
        data_layer=layer,  # type: ignore[arg-type]
        synthetic_tables=synthetic,
    )


def guarded(tool: PythonEngineName, engine_version: str, method: str) -> Callable:
    """Turn an unexpected exception into ``insufficient_evidence`` (ANA-4).

    Engines return a reason rather than raising for data problems; this is
    the last line of that promise, so a bug never crashes a run.
    """

    def wrap(function: Callable[[Mapping[str, Any], EngineData], EngineRun]):
        def run(params: Mapping[str, Any], data: EngineData) -> EngineRun:
            timer = Timer()
            try:
                return function(params, data)
            except (ArithmeticError, KeyError, LookupError, TypeError, ValueError) as exc:
                return insufficient(
                    tool=tool,
                    reason=f"The {tool} engine could not use the supplied rows: {type(exc).__name__}: {exc}",
                    data=data,
                    timer=timer,
                    engine_version=engine_version,
                    method=method,
                )

        run.__name__ = getattr(function, "__name__", "run")
        run.__doc__ = function.__doc__
        return run

    return wrap


__all__ = [
    "ENGINE_LAYER_VERSION",
    "EngineData",
    "Timer",
    "analyst_input",
    "derived_query_id",
    "engine_result",
    "frame_from_table",
    "guarded",
    "insufficient",
    "table_from_frame",
]
