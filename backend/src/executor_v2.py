"""Step executor: runs a validated Plan DAG, one ToolResult per step.

* Steps run in topological order (``Plan.execution_order``).
* A step whose required dependency did not succeed is ``skipped`` with the
  reason; a failed **optional** dependency degrades the step instead of
  failing it (build-plan 3.6).
* The plan's engine-call and wall-clock budgets are enforced; the query
  budget is enforced by the warehouse on every statement.
* Every step emits ``plan_step_started`` / ``plan_step_finished``; engine
  steps also emit ``engine_running`` ("running model") when the engine runs
  live rather than being read from the precomputed tables.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from contracts.v2 import EngineProvenance, Plan, PlanStep, ToolProvenance, ToolResult
from engines.report import EngineReport, EngineRun, confidence_from
from tools.registry import StepContext, Warehouse, run_tool

Emit = Callable[..., None]
_OK = frozenset({"ok", "empty"})


@dataclass
class Execution:
    plan: Plan
    results: dict[str, ToolResult] = field(default_factory=dict)
    reports: dict[str, EngineReport] = field(default_factory=dict)
    frames: dict[str, dict[str, Any]] = field(default_factory=dict)
    engine_calls: int = 0
    duration_ms: int = 0

    def ordered(self) -> list[ToolResult]:
        return [self.results[step.step_id] for step in self.plan.steps if step.step_id in self.results]


def _skipped(step: PlanStep, reason: str) -> ToolResult:
    if step.is_engine:
        provenance = ToolProvenance(source="engine", engine=EngineProvenance(name=step.tool, version="not-run", method="skipped", seed=0),  # type: ignore[arg-type]
                                    input_step_ids=step.depends_on)
    else:
        provenance = ToolProvenance(source="catalog" if step.tool == "catalog" else "sql", input_step_ids=step.depends_on)
    return ToolResult(step_id=step.step_id, tool=step.tool, status="skipped", produces=step.produces, provenance=provenance,
                      reason=reason, duration_ms=0)


def _errored(step: PlanStep, reason: str, duration_ms: int) -> ToolResult:
    result = _skipped(step, reason)
    return result.model_copy(update={"status": "error", "duration_ms": duration_ms})


class PlanExecutor:
    def __init__(self, warehouse: Warehouse, *, emit: Emit | None = None, seed: int = 0, run_id: str = "run") -> None:
        self.warehouse = warehouse
        self.emit = emit or (lambda *args, **kwargs: None)
        self.seed = seed
        self.run_id = run_id

    def execute(self, plan: Plan) -> Execution:
        started = time.perf_counter()
        execution = Execution(plan=plan)
        by_id = {step.step_id: step for step in plan.steps}

        def on_engine(step: PlanStep) -> None:
            self.emit("engine_running", step_id=step.step_id, tool=step.tool,
                      summary=f"Running {step.tool} live: {step.purpose}")

        ctx = StepContext(warehouse=self.warehouse, results=execution.results, reports=execution.reports,
                          frames=execution.frames, seed=self.seed, run_id=self.run_id, on_engine=on_engine)
        for step_id in plan.execution_order():
            step = by_id[step_id]
            self.emit("plan_step_started", step_id=step.step_id, tool=step.tool, purpose=step.purpose,
                      depends_on=list(step.depends_on))
            step_started = time.perf_counter()
            failed = [dep for dep in step.depends_on if execution.results[dep].status not in _OK and not by_id[dep].optional]
            if failed:
                result = _skipped(step, f"Skipped because required step(s) {', '.join(failed)} did not succeed.")
                run = EngineRun(result, EngineReport(engine=step.tool, method="skipped", assumptions=(result.reason or "",),
                                                     confidence=confidence_from(basis="skipped").model_copy(update={"level": "insufficient", "score": 0.0})))
            elif step.is_engine and execution.engine_calls >= plan.budget.max_engine_calls:
                result = _skipped(step, f"Skipped: the plan's engine budget of {plan.budget.max_engine_calls} calls was reached.")
                run = EngineRun(result, EngineReport(engine=step.tool, method="skipped", assumptions=(result.reason or "",),
                                                     confidence=confidence_from(basis="budget").model_copy(update={"level": "insufficient", "score": 0.0})))
            elif (time.perf_counter() - started) * 1000 > plan.budget.max_wall_ms:
                result = _skipped(step, f"Skipped: the plan's wall-clock budget of {plan.budget.max_wall_ms} ms was reached.")
                run = EngineRun(result, EngineReport(engine=step.tool, method="skipped", assumptions=(result.reason or "",),
                                                     confidence=confidence_from(basis="budget").model_copy(update={"level": "insufficient", "score": 0.0})))
            else:
                if step.is_engine:
                    execution.engine_calls += 1
                try:
                    run = run_tool(step, ctx)
                except Exception as exc:  # a failed step is reported, never a crashed run
                    duration = int((time.perf_counter() - step_started) * 1000)
                    result = _errored(step, f"{type(exc).__name__}: {exc}"[:400], duration)
                    run = EngineRun(result, EngineReport(engine=step.tool, method="error", assumptions=(result.reason or "",),
                                                         confidence=confidence_from(basis="error").model_copy(update={"level": "insufficient", "score": 0.0})))
            execution.results[step.step_id] = run.result
            execution.reports[step.step_id] = run.report
            self.emit("plan_step_finished", step_id=step.step_id, tool=step.tool, status=run.result.status,
                      duration_ms=run.result.duration_ms,
                      summary=(run.result.reason if run.result.status not in _OK else _summary(step, run))[:300])
        execution.duration_ms = int((time.perf_counter() - started) * 1000)
        return execution


def _summary(step: PlanStep, run: EngineRun) -> str:
    result = run.result
    if result.rows is not None:
        return f"{step.tool} returned {result.rows.row_count} row(s)."
    if result.analyst_output is not None:
        return f"{step.tool} finished with method {run.report.method}."
    if result.catalog_facts is not None:
        return f"catalog returned {len(result.catalog_facts.facts)} fact(s)."
    return f"{step.tool} finished."


__all__ = ["Execution", "PlanExecutor"]
