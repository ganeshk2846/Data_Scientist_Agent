"""Master orchestration DAG for Stage 5 (RTE-1, RTE-3, OPS-2, ANA-1).

The orchestrator owns the execution budget, prepares bounded time-series or
contribution inputs, and hands copied rows to the pure analyst harness. It never
lets an analyst open a connection or generate SQL.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Mapping

from analysts.harness import AnalystHarness
from catalog import MetricRegistry
from catalog.metric_resolver import MetricResolver
from contracts.models import (
    AnalystColumn,
    AnalystOutput,
    AnomalyParams,
    BudgetUsage,
    ClarificationResult,
    ExecutionBudget,
    ExecutionResult,
    MetricDefinition,
    OrchestrationResult,
    Period,
    PlanStep,
    QueryRecord,
    ReconciliationResult,
    RouterResult,
    SqlCandidate,
    TableRef,
    ValidationResult,
)
from guard import Guard
from router import Router
from sql.compiler import SQLCompiler
from sql.reconciler import Reconciler


class BudgetExceeded(RuntimeError):
    """A run tried to exceed its query, token or wall-clock budget."""


@dataclass(slots=True)
class _RunState:
    started: float
    queries: list[QueryRecord] = field(default_factory=list)
    tokens: int = 0
    plan: list[PlanStep] = field(default_factory=list)
    analyst_outputs: list[AnalystOutput] = field(default_factory=list)
    candidate: SqlCandidate | None = None
    validation: ValidationResult | None = None
    execution: ExecutionResult | None = None
    executions: list[ExecutionResult] = field(default_factory=list)
    reconciliation: ReconciliationResult | None = None


class Orchestrator:
    """Routes, plans, queries and invokes analysts under a hard budget."""

    def __init__(
        self,
        *,
        executor: object,
        router: Router,
        registry: MetricRegistry,
        metric_resolver: MetricResolver,
        compiler: SQLCompiler,
        reconciler: Reconciler,
        harness: AnalystHarness,
        budget: ExecutionBudget | None = None,
        guard: Guard | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._executor = executor
        self._router = router
        self._registry = registry
        self._resolver = metric_resolver
        self._compiler = compiler
        self._reconciler = reconciler
        self._harness = harness
        self._budget = budget or ExecutionBudget()
        self._guard = guard or Guard()
        self._clock = clock or time.monotonic

    @property
    def router(self) -> Router:
        return self._router

    def run(
        self,
        question: str,
        *,
        guard_result=None,
        route_result: RouterResult | None = None,
    ) -> OrchestrationResult:
        state = _RunState(started=self._clock())
        guard = guard_result or self._guard.check(question)
        route = route_result or self._router.route(
            question,
            guard_result=guard,
        )
        state.tokens = _route_tokens(route)
        state.plan.append(
            PlanStep(
                step_id="route",
                module="router",
                status="completed",
                detail=f"{route.primary_route} at {route.confidence:.2f}",
            )
        )

        if not guard.passed:
            return self._finish(
                state,
                route,
                status="blocked",
                reason=route.reason,
            )

        if route.primary_route == "blocked":
            return self._finish(
                state,
                route,
                status="blocked",
                reason=route.reason,
            )
        if route.primary_route == "clarify":
            return self._finish(
                state,
                route,
                status="clarification",
                reason=route.reason,
                clarification=route.clarification,
            )
        if route.primary_route == "refused":
            return self._finish(
                state,
                route,
                status="refused",
                reason=route.reason,
                refusal=route.reason,
            )
        if route.primary_route == "risk":
            state.plan.append(
                PlanStep(
                    step_id="risk",
                    module="risk",
                    depends_on=("route",),
                    status="skipped",
                    detail="No risk model is enabled in this slice.",
                )
            )
            return self._finish(
                state,
                route,
                status="insufficient_evidence",
                reason=(
                    "Risk analysis is not enabled in this slice; no customer-"
                    "level risk score was fabricated."
                ),
            )

        try:
            if not guard.passed:
                raise BudgetExceeded("the request failed the guard")
            self._check_token_budget(state, route)
            self._check_wall_budget(state)
            if route.primary_route == "lookup":
                self._lookup(question, route, state)
                return self._finish(
                    state,
                    route,
                    status="ok",
                    reason=route.reason,
                )
            if route.primary_route == "anomaly":
                output = self._anomaly(question, route, state)
                status = (
                    "ok"
                    if output is not None and output.status == "ok"
                    else "insufficient_evidence"
                )
                return self._finish(
                    state,
                    route,
                    status=status,
                    reason=(
                        output.reason
                        if output is not None and output.reason
                        else route.reason
                    ),
                )
            if route.primary_route == "driver":
                clarification, output = self._driver(question, route, state)
                if clarification is not None:
                    return self._finish(
                        state,
                        route,
                        status="clarification",
                        reason=clarification.what_needs_clarification,
                        clarification=clarification,
                    )
                status = (
                    "ok"
                    if output is not None and output.status == "ok"
                    else "insufficient_evidence"
                )
                return self._finish(
                    state,
                    route,
                    status=status,
                    reason=(
                        output.reason
                        if output is not None and output.reason
                        else route.reason
                    ),
                )
        except BudgetExceeded as exc:
            return self._finish(
                state,
                route,
                status="error",
                reason=f"Execution budget exceeded: {exc}",
            )
        except Exception as exc:
            return self._finish(
                state,
                route,
                status="error",
                reason=f"Orchestration failed: {exc}",
            )

        return self._finish(
            state,
            route,
            status="error",
            reason=f"Unsupported route: {route.primary_route}",
        )

    def _lookup(
        self,
        question: str,
        route: RouterResult,
        state: _RunState,
    ) -> None:
        resolution = self._resolver.resolve(question, use_model=False)
        if resolution.coverage != "full" or resolution.definition is None:
            raise ValueError(
                "The governed lookup did not resolve every slot; the Stage 3 "
                "NL2SQL fallback is required."
            )
        definition = resolution.definition
        dimensions = tuple(
            item.requested
            for item in resolution.resolved_dimensions
            if item.allowed
        )

        is_comparative = (
            route.intent_label == "Comparative"
            or any(
                _contains(_normalize(question), word)
                for word in ("difference", "differences", "compared", "compare", "versus", "vs")
            )
        )
        current_period = route.slots.time.current or resolution.period
        comparison_period = route.slots.time.comparison

        if is_comparative and current_period is not None and comparison_period is not None:
            current_compiled = self._compiler.compile(
                definition,
                dimensions=dimensions,
                filters=resolution.filters,
                period=current_period,
                time_grain=resolution.time_grain,
            )
            current_execution, _ = self._execute(
                current_compiled.candidate.sql,
                purpose="current_lookup",
                state=state,
            )
            if current_execution.status not in ("ok", "truncated"):
                raise RuntimeError(
                    f"The lookup query returned {current_execution.status}: "
                    f"{current_execution.error.message if current_execution.error else 'unknown'}"
                )
            current_reconciliation = self._reconciler.reconcile(
                current_execution,
                expected_grain=current_compiled.candidate.grain,
                join_path=definition.join_path,
            )

            comparison_compiled = self._compiler.compile(
                definition,
                dimensions=dimensions,
                filters=resolution.filters,
                period=comparison_period,
                time_grain=resolution.time_grain,
            )
            comparison_execution, _ = self._execute(
                comparison_compiled.candidate.sql,
                purpose="comparison_lookup",
                state=state,
            )
            if comparison_execution.status not in ("ok", "truncated"):
                raise RuntimeError(
                    f"The comparison lookup query returned {comparison_execution.status}: "
                    f"{comparison_execution.error.message if comparison_execution.error else 'unknown'}"
                )
            self._reconciler.reconcile(
                comparison_execution,
                expected_grain=comparison_compiled.candidate.grain,
                join_path=definition.join_path,
            )

            state.candidate = current_compiled.candidate
            state.validation = current_compiled.validation
            state.execution = current_execution
            state.reconciliation = current_reconciliation
            state.plan.append(
                PlanStep(
                    step_id="lookup",
                    module="lookup",
                    depends_on=("route",),
                    status="completed",
                )
            )
        else:
            compiled = self._compiler.compile(
                definition,
                dimensions=dimensions,
                filters=resolution.filters,
                period=resolution.period,
                time_grain=resolution.time_grain,
            )
            execution, _ = self._execute(
                compiled.candidate.sql,
                purpose="lookup",
                state=state,
            )
            if execution.status not in ("ok", "truncated"):
                raise RuntimeError(
                    f"The lookup query returned {execution.status}: "
                    f"{execution.error.message if execution.error else 'unknown'}"
                )
            reconciliation = self._reconciler.reconcile(
                execution,
                expected_grain=compiled.candidate.grain,
                join_path=definition.join_path,
            )
            state.candidate = compiled.candidate
            state.validation = compiled.validation
            state.execution = execution
            state.reconciliation = reconciliation
            state.plan.append(
                PlanStep(
                    step_id="lookup",
                    module="lookup",
                    depends_on=("route",),
                    status="completed",
                )
            )

    def _anomaly(
        self,
        question: str,
        route: RouterResult,
        state: _RunState,
    ) -> AnalystOutput | None:
        definition = self._diagnostic_metric(question, route)
        period = route.slots.time.current
        if definition is None or period is None:
            state.analyst_outputs.append(
                AnalystOutput(
                    module="anomaly",
                    status="insufficient_evidence",
                    reason="The anomaly route needs a governed metric and a "
                    "complete time window.",
                )
            )
            return state.analyst_outputs[-1]
        grain = route.slots.time.grain or "month"
        history_start = _history_start(period.start, grain)
        history_period = Period(start=history_start, end=period.start)
        resolution = self._resolver.resolve(question, use_model=False)
        try:
            compiled = self._compiler.compile(
                definition,
                filters=resolution.filters,
                period=Period(start=history_start, end=period.end),
                time_grain=grain,
            )
        except Exception as exc:
            raise RuntimeError(f"The anomaly query could not be compiled: {exc}")
        execution, _ = self._execute(
            compiled.candidate.sql,
            purpose="series",
            state=state,
        )
        if execution.status not in ("ok", "truncated"):
            raise RuntimeError(
                f"The series query returned {execution.status}: "
                f"{execution.error.message if execution.error else 'unknown'}"
            )
        state.candidate = compiled.candidate
        state.validation = compiled.validation
        state.execution = execution
        state.plan.append(
            PlanStep(
                step_id="series",
                module="query_series",
                depends_on=("route",),
                status="completed",
            )
        )
        params = AnomalyParams(
            metric=definition.metric_id,
            grain=grain,
            test_window=period,
            history_window=history_period,
        )
        analyst_input = self._harness.build_input(
            "anomaly",
            params=params.model_dump(),
            tables={"series": execution},
            metric=definition,
            run_id=f"{execution.query_id}-anomaly",
            seed=0,
        )
        output = self._harness.run(analyst_input)
        state.analyst_outputs.append(output)
        state.plan.append(
            PlanStep(
                step_id="anomaly",
                module="anomaly",
                depends_on=("series",),
                status="completed",
                detail=output.reason,
            )
        )
        return output

    def _driver(
        self,
        question: str,
        route: RouterResult,
        state: _RunState,
    ) -> tuple[ClarificationResult | None, AnalystOutput | None]:
        definition = self._diagnostic_metric(question, route)
        current = route.slots.time.current
        comparison = route.slots.time.comparison
        dimensions = route.slots.dimensions
        if definition is None or current is None:
            return (
                ClarificationResult(
                    what_understood="The question asks for driver attribution.",
                    what_needs_clarification=(
                        "Please name the governed metric and time window to "
                        "attribute."
                    ),
                ),
                None,
            )
        if not dimensions:
            return (
                ClarificationResult(
                    what_understood=(
                        f"You want to attribute {definition.name} in "
                        f"{current.start.isoformat()}."
                    ),
                    what_needs_clarification=(
                        "Please specify the dimension to compare, such as "
                        "customer state, order status or payment type."
                    ),
                ),
                None,
            )
        if comparison is None:
            comparison = _previous_period(current)
        resolution = self._resolver.resolve(question, use_model=False)
        current_compiled = self._compiler.compile(
            definition,
            dimensions=dimensions,
            filters=resolution.filters,
            period=current,
        )
        comparison_compiled = self._compiler.compile(
            definition,
            dimensions=dimensions,
            filters=resolution.filters,
            period=comparison,
        )
        current_execution, _ = self._execute(
            current_compiled.candidate.sql,
            purpose="current_contribution",
            state=state,
        )
        comparison_execution, _ = self._execute(
            comparison_compiled.candidate.sql,
            purpose="comparison_contribution",
            state=state,
        )
        for execution in (current_execution, comparison_execution):
            if execution.status not in ("ok", "truncated"):
                raise RuntimeError(
                    f"A contribution query returned {execution.status}: "
                    f"{execution.error.message if execution.error else 'unknown'}"
                )
        state.candidate = current_compiled.candidate
        state.validation = current_compiled.validation
        state.execution = current_execution

        contribution = _contribution_table(
            current_execution,
            comparison_execution,
            dimensions=dimensions,
            current_period=current,
            comparison_period=comparison,
        )
        params = {
            "metric": definition.metric_id,
            "current_period": current.model_dump(),
            "comparison_period": comparison.model_dump(),
            "dimensions": dimensions,
            "aggregation": "sum",
            "value_decomposition": False,
        }
        analyst_input = self._harness.build_input(
            "driver",
            params=params,
            tables={"contrib": contribution},
            metric=definition,
            run_id=f"{current_execution.query_id}-driver",
            seed=0,
        )
        output = self._harness.run(analyst_input)
        state.analyst_outputs.append(output)
        state.plan.append(
            PlanStep(
                step_id="driver",
                module="driver",
                depends_on=("route",),
                status="completed",
                detail=output.reason,
            )
        )
        return None, output

    def _diagnostic_metric(
        self,
        question: str,
        route: RouterResult,
    ) -> MetricDefinition | None:
        for term in route.slots.metric_terms:
            metric = self._registry.get(term)
            if metric is not None:
                return metric
        resolution = self._resolver.resolve(question, use_model=False)
        return resolution.definition

    def _execute(
        self,
        sql: str,
        *,
        purpose: str,
        state: _RunState,
    ) -> tuple[ExecutionResult, str]:
        if len(state.queries) >= self._budget.max_queries:
            raise BudgetExceeded(
                f"query limit {self._budget.max_queries} reached"
            )
        self._check_wall_budget(state)
        query_id = f"Q{len(state.queries) + 1}"
        execution = self._executor.execute(sql, query_id=query_id)
        if not isinstance(execution, ExecutionResult):
            raise TypeError("the executor must return ExecutionResult")
        state.queries.append(
            QueryRecord(
                query_id=query_id,
                purpose=purpose,
                sql=sql,
                status=execution.status,
                row_count=execution.row_count,
                duration_ms=execution.duration_ms,
            )
        )
        state.execution = execution
        state.executions.append(execution)
        self._check_wall_budget(state)
        return execution, query_id

    def _check_token_budget(
        self,
        state: _RunState,
        route: RouterResult,
    ) -> None:
        if state.tokens > self._budget.max_tokens:
            raise BudgetExceeded(
                f"token limit {self._budget.max_tokens} exceeded by "
                f"{state.tokens}"
            )
        if route.primary_route == "blocked":
            raise BudgetExceeded("the request was blocked")

    def _check_wall_budget(self, state: _RunState) -> None:
        elapsed_ms = (self._clock() - state.started) * 1_000
        if elapsed_ms > self._budget.max_wall_ms:
            raise BudgetExceeded(
                f"wall-clock limit {self._budget.max_wall_ms}ms exceeded"
            )

    def _finish(
        self,
        state: _RunState,
        route: RouterResult,
        *,
        status: str,
        reason: str,
        clarification: ClarificationResult | None = None,
        refusal: str | None = None,
    ) -> OrchestrationResult:
        latency_ms = max(
            int(round((self._clock() - state.started) * 1_000)),
            0,
        )
        return OrchestrationResult(
            status=status,  # type: ignore[arg-type]
            route_labels=route.route_labels,
            confidence=route.confidence,
            intent_label=route.intent_label,
            reason=reason,
            router=route,
            clarification=clarification,
            refusal=refusal,
            candidate=state.candidate,
            validation=state.validation,
            execution=state.execution,
            executions=tuple(state.executions),
            reconciliation=state.reconciliation,
            analyst_outputs=tuple(state.analyst_outputs),
            queries=tuple(state.queries),
            budget=BudgetUsage(
                queries=len(state.queries),
                tokens=state.tokens,
                wall_ms=latency_ms,
            ),
            plan=tuple(state.plan),
            latency_ms=latency_ms,
        )


def _route_tokens(route: RouterResult) -> int:
    model = route.signals.model
    if model is None or model.usage is None:
        return 0
    return model.usage.tokens_in + model.usage.tokens_out


def _history_start(test_start, grain: str):
    if grain in ("month", "quarter"):
        index = test_start.year * 12 + test_start.month - 1 - 24
        return date(index // 12, index % 12 + 1, 1)
    if grain == "year":
        return date(test_start.year - 4, 1, 1)
    if grain == "week":
        return test_start - timedelta(weeks=104)
    return test_start - timedelta(days=90)


def _previous_period(period: Period) -> Period:
    length = period.end - period.start
    return Period(start=period.start - length, end=period.start)


def _contribution_table(
    current: ExecutionResult,
    comparison: ExecutionResult,
    *,
    dimensions: tuple[str, ...],
    current_period: Period,
    comparison_period: Period,
) -> TableRef:
    columns = (
        AnalystColumn(name="period", type="TEXT", role="time"),
        *(
            AnalystColumn(name=name, type="TEXT", role="dimension")
            for name in dimensions
        ),
        AnalystColumn(name="value", type="REAL", role="measure"),
    )
    rows: list[tuple[object, ...]] = []
    for execution, period in (
        (current, current_period),
        (comparison, comparison_period),
    ):
        for row in execution.rows or ():
            if len(row) < len(dimensions) + 1:
                continue
            rows.append(
                (
                    period.start.isoformat(),
                    *row[: len(dimensions)],
                    row[len(dimensions)],
                )
            )
    query_id = f"{current.query_id}+{comparison.query_id}"
    return TableRef(
        query_id=query_id,
        columns=columns,
        row_count=len(rows),
        uri=f"inline://{query_id}",
        rows=tuple(rows),
    )


def _normalize(text: str) -> str:
    lowered = text.lower().replace("&", " and ")
    lowered = re.sub(r"[_\-/]+", " ", lowered)
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(lowered.split())


def _contains(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


__all__ = ["BudgetExceeded", "Orchestrator"]
