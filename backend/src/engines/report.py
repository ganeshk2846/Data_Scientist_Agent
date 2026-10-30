"""The uniform engine report: tables, key numbers, method, assumptions,
confidence and a chart hint (Track 2 output rule).

The frozen ``ToolResult`` has no field for these, so the report travels two
ways without a contract change:

* every engine returns it beside the result as :class:`EngineRun`;
* engine outputs also embed it under ``analyst_output.parameters["report"]``
  (``parameters`` is an open mapping in the contract), so a consumer holding
  only the ``ToolResult`` can recover it with :func:`report_of`.

Every number in a report is copied from the engine result or from the input
rows. A report never introduces a figure of its own (SAFE-8).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, field_validator

from contracts.models import ContractModel
from contracts.v2 import AnalystOutput, ToolResult, VizKind

ConfidenceLevel = Literal["high", "medium", "low", "insufficient"]

REPORT_KEY = "report"


class ReportTable(ContractModel):
    name: str = Field(min_length=1)
    columns: tuple[str, ...] = Field(min_length=1)
    rows: tuple[tuple[Any, ...], ...] = ()

    @field_validator("rows")
    @classmethod
    def _rows_are_clean(cls, rows: tuple[tuple[Any, ...], ...]) -> tuple[tuple[Any, ...], ...]:
        return tuple(tuple(_clean(value) for value in row) for row in rows)


class KeyNumber(ContractModel):
    name: str = Field(min_length=1)
    value: float | None = None
    unit: str = ""
    label: str = ""

    @field_validator("value")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("a key number must be finite or null")
        return value


class Confidence(ContractModel):
    level: ConfidenceLevel
    score: float = Field(ge=0.0, le=1.0)
    basis: str = Field(min_length=1)


class ChartHint(ContractModel):
    kind: VizKind
    table: str = Field(min_length=1)
    x: str = Field(min_length=1)
    y: tuple[str, ...] = Field(min_length=1)
    series: str | None = None
    title: str = Field(min_length=1)


class EngineReport(ContractModel):
    engine: str = Field(min_length=1)
    method: str = Field(min_length=1)
    tables: tuple[ReportTable, ...] = ()
    key_numbers: tuple[KeyNumber, ...] = ()
    assumptions: tuple[str, ...] = ()
    confidence: Confidence
    chart_hint: ChartHint | None = None

    def number(self, name: str) -> float | None:
        for item in self.key_numbers:
            if item.name == name:
                return item.value
        raise KeyError(name)

    def table(self, name: str) -> ReportTable:
        for item in self.tables:
            if item.name == name:
                return item
        raise KeyError(name)


@dataclass(frozen=True)
class EngineRun:
    """What every engine's ``execute`` returns."""

    result: ToolResult
    report: EngineReport


def _clean(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def confidence_from(
    *,
    p_value: float | None = None,
    interval: tuple[float, float] | None = None,
    sample_size: int | None = None,
    grade: int | None = None,
    basis: str,
) -> Confidence:
    """A deterministic confidence label from measured evidence quality.

    It is a rule over the result's own statistics, never a model judgement.
    """

    score = 0.5
    if p_value is not None:
        score += 0.25 if p_value < 0.01 else 0.15 if p_value < 0.05 else -0.15
    if interval is not None and (interval[0] > 0.0 or interval[1] < 0.0):
        score += 0.1
    if sample_size is not None:
        score += 0.1 if sample_size >= 30 else -0.1 if sample_size < 8 else 0.0
    if grade is not None:
        score += {0: -0.3, 1: -0.15, 2: 0.0, 3: 0.1, 4: 0.15}.get(grade, 0.0)
    score = min(1.0, max(0.0, score))
    level: ConfidenceLevel = "high" if score >= 0.75 else "medium" if score >= 0.5 else "low"
    return Confidence(level=level, score=round(score, 4), basis=basis)


def insufficient_report(engine: str, method: str, reason: str) -> EngineReport:
    return EngineReport(
        engine=engine,
        method=method,
        assumptions=(reason,),
        confidence=Confidence(level="insufficient", score=0.0, basis=reason),
    )


def attach_report(output: AnalystOutput, report: EngineReport) -> AnalystOutput:
    parameters = dict(output.parameters)
    parameters[REPORT_KEY] = report.model_dump(mode="json")
    return output.model_copy(update={"parameters": parameters})


def report_of(result: ToolResult) -> EngineReport | None:
    """Recover the report embedded in an engine ``ToolResult``."""
    if result.analyst_output is None:
        return None
    payload = result.analyst_output.parameters.get(REPORT_KEY)
    if payload is None:
        return None
    return EngineReport.model_validate(payload)


__all__ = [
    "ChartHint",
    "Confidence",
    "EngineReport",
    "EngineRun",
    "KeyNumber",
    "REPORT_KEY",
    "ReportTable",
    "attach_report",
    "confidence_from",
    "insufficient_report",
    "report_of",
]
