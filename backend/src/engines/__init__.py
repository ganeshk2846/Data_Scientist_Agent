"""V2 data-science engines behind one interface (Track 2).

    run(engine, params, data) -> contracts.v2.ToolResult
    execute(engine, params, data) -> EngineRun(result, report)

``engine`` names one of the six analytical intents. The mapping is closed:
there is no registration hook, no import-by-name and no code parameter
(ANA-2, B0). Each engine is deterministic Python over rows an upstream
``sql`` / ``analytical_table`` step produced; none opens a warehouse
connection or calls a language model (SAFE-8), so every engine works with no
model service available.

=============  ====================  ===========================================
engine         ToolResult.tool       reuses
=============  ====================  ===========================================
descriptive    sql                   SQL over the supplied rows (scope: "SQL only")
diagnostic     python.driver         analysts.driver (DriverAnalyst)
impact         python.impact /       analysts.impact, analysts.anomaly
               python.anomaly
forecast       python.forecast       analysts.forecast (Prophet / ETS) + ARIMA challenger
scenario       python.scenario       analysts.scenario + analysts.elasticity
prescriptive   python.segment        analysts.segment (k-means, rank_actions, budget LP)
=============  ====================  ===========================================

:func:`run_step` executes a planner ``PlanStep`` whose tool is a
``python.*`` engine, so the frozen tool registry maps onto these engines.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Literal

from contracts.v2 import ENGINE_NAMES, PlanStep, ToolResult

from . import descriptive, diagnostic, forecast, impact, prescriptive, scenario
from .base import EngineData
from .report import EngineReport, EngineRun, report_of

EngineName = Literal["descriptive", "diagnostic", "impact", "forecast", "scenario", "prescriptive"]

ENGINES: Mapping[str, Callable[[Mapping[str, Any], EngineData], EngineRun]] = MappingProxyType(
    {
        "descriptive": descriptive.execute,
        "diagnostic": diagnostic.execute,
        "impact": impact.execute,
        "forecast": forecast.execute,
        "scenario": scenario.execute,
        "prescriptive": prescriptive.execute,
    }
)

#: Which engine serves each frozen ``python.*`` tool name.
TOOL_ENGINES: Mapping[str, str] = MappingProxyType(
    {
        "python.anomaly": "impact",
        "python.driver": "diagnostic",
        "python.forecast": "forecast",
        "python.impact": "impact",
        "python.scenario": "scenario",
        "python.segment": "prescriptive",
    }
)

#: Which engine answers each analytical intent (``contracts.v2.IntentName``).
INTENT_ENGINES: Mapping[str, str] = MappingProxyType(
    {
        "descriptive": "descriptive",
        "diagnostic": "diagnostic",
        "impact": "impact",
        "forecast": "forecast",
        "scenario": "scenario",
        "prescriptive": "prescriptive",
    }
)


class UnknownEngineError(ValueError):
    """The caller named an engine outside the closed mapping."""


def execute(engine: str, params: Mapping[str, Any], data: EngineData) -> EngineRun:
    function = ENGINES.get(engine)
    if function is None:
        raise UnknownEngineError(f"unknown engine {engine!r}; choose one of {sorted(ENGINES)}")
    return function(params, data)


def run(engine: str, params: Mapping[str, Any], data: EngineData) -> ToolResult:
    return execute(engine, params, data).result


def run_step(step: PlanStep, data: EngineData) -> EngineRun:
    """Execute a planner step whose tool is a registered ``python.*`` engine."""
    if step.tool not in ENGINE_NAMES:
        raise UnknownEngineError(f"step {step.step_id!r} uses {step.tool!r}, which is not a python engine")
    params = dict(step.params)
    if step.tool == "python.anomaly":
        params["mode"] = "anomaly"
    elif step.tool == "python.impact":
        params.setdefault("mode", "change")
    bound = EngineData(
        tables=data.tables,
        source_tables=data.source_tables,
        seed=data.seed,
        run_id=data.run_id,
        step_id=step.step_id,
        input_step_ids=step.depends_on,
        analytical_rows_synthetic=data.analytical_rows_synthetic,
    )
    return execute(TOOL_ENGINES[step.tool], params, bound)


__all__ = [
    "ENGINES",
    "INTENT_ENGINES",
    "TOOL_ENGINES",
    "EngineData",
    "EngineName",
    "EngineReport",
    "EngineRun",
    "UnknownEngineError",
    "execute",
    "report_of",
    "run",
    "run_step",
]
