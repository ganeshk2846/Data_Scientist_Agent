"""Interactive Day-1 console for the query pipeline.

The console accepts read-only SELECT statements directly, runs them through the
guard, the AST validator and the read-only gateway, and renders the result with
Rich. Long-lived commands inspect tables and toggle the validation mode.
"""

from __future__ import annotations

import builtins
from typing import Callable, cast

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy.exc import SQLAlchemyError

from analysts.harness import AnalystHarness
from answerability import AnswerabilityChecker
from catalog import MetricRegistry
from catalog.metric_resolver import MetricResolver
from contracts.models import (
    AnswerabilityResult,
    AnomalyResult,
    ClarificationResult,
    DriverResult,
    ExecutionResult,
    GuardResult,
    MetricDefinition,
    MetricResolution,
    OrchestrationResult,
    ReconciliationResult,
    RepairOutcome,
    SqlCandidate,
    ValidationMode,
    ValidationResult,
)
from gateway.connection import ConnectionManager
from gateway.executor import QueryExecutor
from guard import Guard
from orchestrator import Orchestrator
from router import Router
from schema_retriever.catalog import SchemaCatalog
from schema_retriever.perceptor import SchemaPerceptor
from sql.compiler import MetricCompilationError, SQLCompiler
from sql.generator import SQLGenerationError, SQLGenerator
from sql.reconciler import Reconciler
from sql.repairer import SelfRepairer
from sql.validator import SQLValidator
from trace_logger import TraceLogger, TraceRecord, mask_sensitive

_MODES = frozenset({"enterprise", "benchmark"})


def _format_cell(value: object) -> str:
    value = mask_sensitive(value)
    if value is None:
        return "[dim]NULL[/dim]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        rendered = f"{value:,.4f}".rstrip("0").rstrip(".")
        return rendered or "0"
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "<binary>"
    return escape(str(value))


class CLI:
    """Rich REPL around guard -> validator -> gateway."""

    def __init__(
        self,
        *,
        manager: ConnectionManager,
        guard: Guard | None = None,
        logger: TraceLogger | None = None,
        console: Console | None = None,
        input_func: Callable[[str], str] | None = None,
        reasoning_client: object | None = None,
        mode: ValidationMode = "enterprise",
        max_rows: int = 50,
    ) -> None:
        if mode not in _MODES:
            raise ValueError("mode must be 'enterprise' or 'benchmark'")

        self._manager = manager
        self._guard = guard or Guard()
        self._logger = logger or TraceLogger()
        self._console = console or Console()
        self._read_input = input_func or builtins.input
        self._reasoning_client = reasoning_client
        self._mode: ValidationMode = mode
        self._tables = self._load_tables()
        self._validator = self._make_validator()
        self._executor = QueryExecutor(manager, max_rows=max_rows)
        self._query_counter = 0
        self._catalog: SchemaCatalog | None = None
        self._answerability: AnswerabilityChecker | None = None
        self._perceptor: SchemaPerceptor | None = None
        self._generator: SQLGenerator | None = None
        self._metric_resolver: MetricResolver | None = None
        self._compiler: SQLCompiler | None = None
        self._router: Router | None = None
        self._orchestrator: Orchestrator | None = None
        self._analyst_harness: AnalystHarness | None = None
        self._reconciler = Reconciler()

    @property
    def mode(self) -> ValidationMode:
        return self._mode

    def run(self) -> int:
        self._print_banner()

        while True:
            try:
                line = self._read_input("DS-Agent > ")
            except EOFError:
                self._console.print()
                return 0
            except KeyboardInterrupt:
                self._console.print("\n[dim]Interrupted. Type exit to quit.[/dim]")
                continue

            command = line.strip()
            if not command:
                continue

            lowered = command.lower()
            if lowered in {"exit", "quit"}:
                return 0
            if lowered in {"help", "?"}:
                self._print_help()
                continue
            if lowered == "tables":
                self._show_tables()
                continue
            if lowered == "mode" or lowered.startswith("mode "):
                self._change_mode(command)
                continue
            if lowered == "ask" or lowered.startswith("ask "):
                self._handle_ask(command[3:].strip())
                continue

            self._handle_statement(command)

    def close(self) -> None:
        self._manager.dispose()

    def _load_tables(self) -> tuple[str, ...]:
        try:
            inspector = sqlalchemy_inspect(self._manager.engine)
            return tuple(sorted(inspector.get_table_names()))
        except (SQLAlchemyError, ValueError):
            return ()

    def _make_validator(self) -> SQLValidator:
        return SQLValidator(self._tables, dialect="sqlite", mode=self._mode)

    def _refresh_tables(self) -> None:
        self._tables = self._load_tables()
        self._validator = self._make_validator()

    def _ensure_nl_pipeline(self) -> None:
        if self._catalog is not None:
            return
        catalog = SchemaCatalog.from_manager(self._manager)
        registry = MetricRegistry.default()
        self._catalog = catalog
        self._answerability = AnswerabilityChecker(catalog)
        self._perceptor = SchemaPerceptor(catalog)
        self._generator = SQLGenerator(catalog, dialect="sqlite")
        self._metric_resolver = MetricResolver(
            registry,
            client=self._reasoning_client,
        )
        self._compiler = SQLCompiler(catalog, dialect="sqlite")
        self._router = Router(
            catalog=catalog,
            registry=registry,
            client=self._reasoning_client,
        )
        self._analyst_harness = AnalystHarness()
        self._orchestrator = Orchestrator(
            executor=self._executor,
            router=self._router,
            registry=registry,
            metric_resolver=self._metric_resolver,
            compiler=self._compiler,
            reconciler=self._reconciler,
            harness=self._analyst_harness,
            guard=self._guard,
        )

    def _handle_ask(self, question: str) -> None:
        if not question:
            self._console.print("[yellow]Usage: ask <question>[/yellow]")
            return

        guard_result = self._guard.check(question)
        if not guard_result.passed:
            self._log(question=question, guard=guard_result)
            self._print_guard(guard_result)
            return

        try:
            self._ensure_nl_pipeline()
        except (OSError, ValueError, SQLAlchemyError) as exc:
            self._console.print(
                f"[red]Could not build the schema catalog: "
                f"{escape(str(mask_sensitive(str(exc))))}[/red]"
            )
            return

        assert self._answerability is not None
        assert self._perceptor is not None
        assert self._generator is not None
        assert self._catalog is not None
        assert self._metric_resolver is not None
        assert self._compiler is not None
        assert self._router is not None
        assert self._orchestrator is not None

        route_result = self._router.route(
            question,
            guard_result=guard_result,
        )
        if route_result.primary_route in {
            "anomaly",
            "driver",
            "risk",
            "clarify",
            "refused",
            "blocked",
        }:
            outcome = self._orchestrator.run(
                question,
                guard_result=guard_result,
                route_result=route_result,
            )
            self._log(
                question=question,
                guard=guard_result,
                validation=outcome.validation,
                execution=outcome.execution,
                candidate=outcome.candidate,
                reconciliation=outcome.reconciliation,
                orchestration=outcome,
            )
            self._print_orchestration(outcome)
            return

        metric_resolution = self._metric_resolver.resolve(question)
        if (
            metric_resolution.coverage == "full"
            and metric_resolution.definition is not None
        ):
            self._handle_governed_metric(
                question,
                guard_result,
                metric_resolution,
            )
            return

        answerability = self._answerability.check(question)
        if not answerability.answerable:
            self._log(
                question=question,
                guard=guard_result,
                answerability=answerability,
            )
            self._print_refusal(answerability)
            return

        perception = self._perceptor.perceive(question)
        if perception.requires_clarification:
            clarification = ClarificationResult(
                what_understood=f"I understood the request as: {question}",
                what_needs_clarification=(
                    perception.clarification_reason
                    or "The value match is ambiguous."
                ),
            )
            self._log(
                question=question,
                guard=guard_result,
                answerability=answerability,
            )
            self._print_clarification(clarification)
            return

        try:
            generation = self._generator.generate(
                question,
                linked_values=perception.linked_values,
            )
        except SQLGenerationError as exc:
            clarification = ClarificationResult(
                what_understood=exc.what_understood,
                what_needs_clarification=exc.what_needs_clarification,
            )
            self._log(
                question=question,
                guard=guard_result,
                answerability=answerability,
            )
            self._print_clarification(clarification)
            return

        validator = SQLValidator(
            generation.allowlist.tables,
            dialect="sqlite",
            mode=self._mode,
            columns=[
                f"{column.table}.{column.column}"
                for column in generation.allowlist.columns
            ],
        )
        repairer = SelfRepairer(
            validator=validator,
            executor=self._executor,
            catalog=self._catalog,
        )
        outcome = repairer.run(
            generation.candidate,
            allowlist=generation.allowlist,
            question=question,
            query_id=self._next_query_id(),
        )

        self._log(
            question=question,
            guard=guard_result,
            validation=outcome.validation,
            execution=outcome.execution,
            answerability=answerability,
            candidate=outcome.candidate or generation.candidate,
            repair=outcome,
        )
        self._print_generated(outcome.candidate or generation.candidate)
        if outcome.success and outcome.execution is not None:
            self._print_execution(outcome.execution)
        elif outcome.clarification is not None:
            self._print_clarification(outcome.clarification)

    def _handle_governed_metric(
        self,
        question: str,
        guard_result: GuardResult,
        metric_resolution: MetricResolution,
    ) -> None:
        assert metric_resolution.definition is not None
        assert self._compiler is not None
        definition = metric_resolution.definition
        dimensions = tuple(
            dimension.requested
            for dimension in metric_resolution.resolved_dimensions
            if dimension.allowed
        )
        try:
            compiled = self._compiler.compile(
                definition,
                dimensions=dimensions,
                filters=metric_resolution.filters,
                period=metric_resolution.period,
                time_grain=metric_resolution.time_grain,
            )
        except MetricCompilationError as exc:
            clarification = ClarificationResult(
                what_understood=f"I understood the governed metric as {definition.name}.",
                what_needs_clarification=str(exc),
            )
            self._log(
                question=question,
                guard=guard_result,
                metric_resolution=metric_resolution,
            )
            self._print_clarification(clarification)
            return

        query_id = self._next_query_id()
        execution = self._executor.execute(
            compiled.candidate.sql,
            query_id=query_id,
        )
        reconciliation = self._reconcile_governed(
            definition,
            metric_resolution,
            compiled.candidate,
            execution,
        )
        if (
            reconciliation is not None
            and reconciliation.registry_comparison is not None
            and not reconciliation.registry_comparison.within
        ):
            execution = self._executor.execute(
                compiled.candidate.sql,
                query_id=query_id,
            )
            reconciliation = self._reconcile_governed(
                definition,
                metric_resolution,
                compiled.candidate,
                execution,
                retry_used=True,
            )
        if (
            reconciliation is not None
            and reconciliation.status == "flags"
            and self._reasoning_client is not None
        ):
            diagnosis = self._reconciler.diagnose(
                reconciliation,
                question,
                client=self._reasoning_client,
            )
            if diagnosis is not None:
                reconciliation = reconciliation.model_copy(
                    update={"diagnosis": diagnosis}
                )

        self._log(
            question=question,
            guard=guard_result,
            validation=compiled.validation,
            execution=execution,
            candidate=compiled.candidate,
            metric_resolution=metric_resolution,
            reconciliation=reconciliation,
        )
        self._print_metric_resolution(metric_resolution)
        self._print_generated(compiled.candidate)
        self._print_execution(execution)
        self._print_reconciliation(reconciliation)

    def _reconcile_governed(
        self,
        definition: MetricDefinition,
        resolution: MetricResolution,
        candidate: SqlCandidate,
        execution: ExecutionResult,
        *,
        retry_used: bool = False,
    ) -> ReconciliationResult | None:
        if execution.status not in ("ok", "truncated"):
            return None

        grouped = bool(candidate.grain) or bool(resolution.resolved_dimensions)
        filters = bool(resolution.filters)
        compare_registry = (
            definition.reconciliation is not None
            and not grouped
            and not filters
            and resolution.period is None
            and resolution.time_grain is None
        )
        metric_column = next(
            (
                index
                for index, column in enumerate(execution.columns)
                if column.name.lower() == definition.metric_id.lower()
            ),
            None,
        )
        observed_value: float | None = None
        if (
            compare_registry
            and metric_column is not None
            and execution.rows
            and execution.rows[0][metric_column] is not None
        ):
            observed_value = float(execution.rows[0][metric_column])
        expected_value: float | None = None
        if compare_registry and observed_value is not None:
            expected_value = self._registry_expected(definition)

        return self._reconciler.reconcile(
            execution,
            expected_grain=candidate.grain,
            join_path=definition.join_path,
            mandatory_columns=tuple(
                column.name for column in execution.columns
            ),
            metric_id=definition.metric_id if compare_registry else None,
            observed_value=observed_value,
            registry_expected=expected_value,
            tolerance=(
                definition.reconciliation.tolerance
                if definition.reconciliation is not None
                else 0.0
            ),
            retry_used=retry_used,
        )

    def _registry_expected(self, definition: MetricDefinition) -> float | None:
        if definition.reconciliation is None:
            return None
        result = self._executor.execute(
            definition.reconciliation.sql,
            query_id="registry",
        )
        if result.status not in ("ok", "truncated"):
            return None
        if not result.rows or not result.rows[0]:
            return None
        value = result.rows[0][0]
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _next_query_id(self) -> str:
        self._query_counter += 1
        return f"Q{self._query_counter}"

    def _handle_statement(self, statement: str) -> None:
        guard_result = self._guard.check(statement)
        if not guard_result.passed:
            self._log(question=statement, guard=guard_result)
            self._print_guard(guard_result)
            return

        validation = self._validator.validate(statement)
        if not validation.approved:
            self._log(question=statement, guard=guard_result, validation=validation)
            self._print_validation(validation)
            return

        execution = self._executor.execute(
            statement, query_id=self._next_query_id()
        )
        self._log(
            question=statement,
            guard=guard_result,
            validation=validation,
            execution=execution,
        )
        self._print_execution(execution)

    def _log(
        self,
        *,
        question: str,
        guard: GuardResult,
        validation: ValidationResult | None = None,
        execution: ExecutionResult | None = None,
        answerability: AnswerabilityResult | None = None,
        candidate: SqlCandidate | None = None,
        repair: RepairOutcome | None = None,
        metric_resolution: MetricResolution | None = None,
        reconciliation: ReconciliationResult | None = None,
        orchestration: OrchestrationResult | None = None,
    ) -> TraceRecord | None:
        try:
            record = self._logger.log(
                question=question,
                guard=guard,
                validation=validation,
                execution=execution,
                answerability=answerability,
                candidate=candidate,
                repair=repair,
                metric_resolution=metric_resolution,
                reconciliation=reconciliation,
                orchestration=orchestration,
            )
        except (OSError, TypeError, ValueError) as exc:
            self._console.print(
                f"[yellow]trace logging failed: "
                f"{escape(str(mask_sensitive(str(exc))))}[/yellow]"
            )
            return None

        self._console.print(f"[dim]trace: {escape(str(record.path))}[/dim]")
        return record

    def _change_mode(self, command: str) -> None:
        parts = command.split()
        if len(parts) != 2 or parts[1].lower() not in _MODES:
            self._console.print(
                "[yellow]Usage: mode <benchmark|enterprise>[/yellow]"
            )
            return

        self._mode = cast(ValidationMode, parts[1].lower())
        self._validator = self._make_validator()
        self._console.print(
            f"[green]Validation mode set to {self._mode}.[/green]"
        )

    def _table_row_count(self, table: str, index: int) -> str:
        quoted = table.replace('"', '""')
        result = self._executor.execute(
            f'SELECT COUNT(*) FROM "{quoted}"', query_id=f"T{index + 1}"
        )
        if result.status == "ok" and result.rows and result.rows[0]:
            return _format_cell(result.rows[0][0])
        return "-"

    def _show_tables(self) -> None:
        self._refresh_tables()
        if not self._tables:
            self._console.print("[yellow]No tables found.[/yellow]")
            return

        table = Table(title=f"Tables ({len(self._tables)})")
        table.add_column("Table")
        table.add_column("Rows", justify="right")
        for index, name in enumerate(self._tables):
            table.add_row(escape(name), self._table_row_count(name, index))

        self._console.print(table)
        self._console.print(
            f"[dim]{len(self._tables)} tables allowlisted "
            f"(validation mode: {self._mode}).[/dim]"
        )

    def _print_banner(self) -> None:
        self._console.print(
            Panel(
                Text(
                    "DS-Agent console\n"
                    f"Datasource: {self._manager.datasource_id} | "
                    f"mode: {self._mode}\n"
                    "Enter a read-only SELECT statement or ask <question>.\n"
                    "Commands: ask, tables, mode <benchmark|enterprise>, "
                    "help, exit"
                ),
                title="DS-Agent",
                border_style="cyan",
            )
        )

    def _print_help(self) -> None:
        self._console.print(
            Panel(
                Text(
                    "ask <question>                 Generate, repair and run SQL\n"
                    "tables                         List tables and row counts\n"
                    "mode <benchmark|enterprise>    Switch validation rules\n"
                    "help                           Show this help\n"
                    "exit / quit                    Leave the console"
                ),
                title="Commands",
                border_style="blue",
            )
        )

    def _print_guard(self, result: GuardResult) -> None:
        lines = [f"Blocked: {result.reason}"]
        if result.matched_rule:
            lines.append(f"Rule: {result.matched_rule}")
        self._console.print(
            Panel(Text("\n".join(lines)), title="Guard", border_style="red")
        )

    def _print_validation(self, result: ValidationResult) -> None:
        table = Table(title=f"Validation failed ({result.validation_mode})")
        table.add_column("ID", justify="right")
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Reason")

        for check in result.checks:
            color = {"pass": "green", "fail": "red", "skipped": "dim"}.get(
                check.status, "white"
            )
            reason = check.reason or ""
            if check.offending:
                reason = f"{reason} ({', '.join(check.offending)})".strip()
            table.add_row(
                str(check.id),
                escape(check.name),
                f"[{color}]{check.status}[/{color}]",
                escape(reason),
            )

        self._console.print(table)

    def _print_refusal(self, result: AnswerabilityResult) -> None:
        lines = ["The catalog cannot answer this question."]
        if result.missing:
            lines.append(f"Missing: {', '.join(result.missing)}")
        if result.closest_answerable:
            lines.append(f"Closest answerable: {result.closest_answerable}")
        self._console.print(
            Panel(Text("\n".join(lines)), title="Refusal", border_style="yellow")
        )

    def _print_clarification(self, result: ClarificationResult) -> None:
        self._console.print(
            Panel(
                Text(
                    "What I understood:\n"
                    f"{result.what_understood}\n\n"
                    "What I need:\n"
                    f"{result.what_needs_clarification}"
                ),
                title="Clarification",
                border_style="yellow",
            )
        )

    def _print_orchestration(self, outcome: OrchestrationResult) -> None:
        labels = ", ".join(outcome.route_labels)
        self._console.print(
            Panel(
                Text(
                    f"Route labels: {labels}\n"
                    f"Confidence: {outcome.confidence:.2f}\n"
                    f"Intent: {outcome.intent_label}\n"
                    f"Reason: {outcome.reason}"
                ),
                title="Intent route",
                border_style="cyan",
            )
        )
        if outcome.status == "blocked":
            self._console.print(
                Panel(
                    Text(outcome.reason),
                    title="Blocked",
                    border_style="red",
                )
            )
            return
        if outcome.status == "clarification":
            clarification = outcome.clarification or outcome.router.clarification
            if clarification is not None:
                self._print_clarification(clarification)
            return
        if outcome.status == "refused":
            self._console.print(
                Panel(
                    Text(outcome.refusal or outcome.reason),
                    title="Refusal",
                    border_style="yellow",
                )
            )
            return

        if outcome.candidate is not None:
            self._print_generated(outcome.candidate)
        if outcome.execution is not None:
            self._print_execution(outcome.execution)
        self._print_analyst_outputs(outcome)
        if outcome.status in {"error", "insufficient_evidence"}:
            self._console.print(
                Panel(
                    Text(outcome.reason),
                    title=outcome.status.replace("_", " ").title(),
                    border_style="yellow",
                )
            )
        self._console.print(
            f"[dim]Budget: {outcome.budget.queries} queries, "
            f"{outcome.budget.tokens} tokens, "
            f"{outcome.budget.wall_ms} ms[/dim]"
        )

    def _print_analyst_outputs(self, outcome: OrchestrationResult) -> None:
        for output in outcome.analyst_outputs:
            if output.status != "ok" or output.result is None:
                self._console.print(
                    Panel(
                        Text(output.reason or ""),
                        title=f"{output.module.title()} analyst",
                        border_style="yellow",
                    )
                )
                continue
            if isinstance(output.result, AnomalyResult):
                result = output.result
                table = Table(title="Anomaly analysis")
                table.add_column("Field")
                table.add_column("Value")
                table.add_row("Verdict", result.verdict.replace("_", " "))
                table.add_row("Window", result.window)
                table.add_row("Actual", _format_cell(result.actual))
                table.add_row("Expected", _format_cell(result.expected))
                table.add_row(
                    "Expected range",
                    f"{_format_cell(result.expected_range[0])} to "
                    f"{_format_cell(result.expected_range[1])}",
                )
                table.add_row(
                    "Deviation",
                    f"{result.deviation_pct:+.2f}%",
                )
                table.add_row(
                    "Robust score",
                    f"{result.robust_score:+.2f}",
                )
                table.add_row("Persistence", result.persistence)
                table.add_row("Baseline", result.baseline_kind)
                self._console.print(table)
            elif isinstance(output.result, DriverResult):
                result = output.result
                table = Table(title="Driver analysis")
                table.add_column("Dimension")
                table.add_column("Value")
                table.add_column("Contribution", justify="right")
                table.add_column("Share", justify="right")
                table.add_column("Grade", justify="right")
                table.add_column("Stable")
                for contribution in result.drivers:
                    table.add_row(
                        escape(contribution.dimension),
                        escape(contribution.value),
                        _format_cell(contribution.contribution),
                        f"{contribution.share:.2%}",
                        str(contribution.grade),
                        "no" if contribution.unstable else "yes",
                    )
                self._console.print(table)
                boundary = next(
                    (
                        assumption
                        for assumption in output.assumptions
                        if "not causal" in assumption.lower()
                    ),
                    None,
                )
                if boundary:
                    self._console.print(
                        Panel(
                            Text(boundary),
                            title="Causal boundary",
                            border_style="yellow",
                        )
                    )

    def _print_metric_resolution(self, resolution: MetricResolution) -> None:
        if resolution.definition is None:
            return
        lines = [
            f"Metric: {resolution.definition.name} "
            f"({resolution.definition.metric_id})",
            f"Coverage: {resolution.coverage} | grain: {resolution.grain or '-'}",
        ]
        dimensions = [
            dimension.requested
            for dimension in resolution.resolved_dimensions
            if dimension.allowed
        ]
        if dimensions:
            lines.append(f"Dimensions: {', '.join(dimensions)}")
        if resolution.time_grain:
            lines.append(f"Time grain: {resolution.time_grain}")
        if resolution.period is not None:
            lines.append(
                f"Period: {resolution.period.start.isoformat()} to "
                f"{resolution.period.end.isoformat()}"
            )
        if resolution.model is not None:
            lines.append(f"Resolved by: {resolution.model.name}")
        else:
            lines.append("Resolved by: deterministic registry")
        for caveat in resolution.caveats:
            lines.append(f"Note: {caveat}")
        self._console.print(
            Panel(
                Text("\n".join(lines)),
                title="Governed metric",
                border_style="green",
            )
        )

    def _print_reconciliation(
        self, result: ReconciliationResult | None
    ) -> None:
        if result is None:
            return
        if result.status == "pass":
            suffix = " after retry" if result.retry_used else ""
            self._console.print(
                f"[green]Reconciliation passed{suffix} "
                f"({len(result.checks)} checks).[/green]"
            )
            return

        table = Table(title="Reconciliation flags")
        table.add_column("Check")
        table.add_column("Status")
        table.add_column("Detail")
        for check in result.checks:
            if check.status != "flag":
                continue
            table.add_row(
                escape(check.name),
                "[red]flag[/red]",
                escape(check.detail or ""),
            )
        self._console.print(table)
        if result.caveats:
            self._console.print(
                Panel(
                    Text("\n".join(result.caveats)),
                    title="Reconciliation caveats",
                    border_style="yellow",
                )
            )
        if result.diagnosis:
            self._console.print(
                Panel(
                    Text(result.diagnosis),
                    title="Diagnosis",
                    border_style="magenta",
                )
            )

    def _print_generated(self, candidate: SqlCandidate) -> None:
        self._console.print(
            Panel(
                Text(candidate.sql),
                title="Generated SQL",
                border_style="blue",
            )
        )

    def _print_execution(self, result: ExecutionResult) -> None:
        if result.error is not None:
            self._console.print(
                Panel(
                    Text(
                        f"{result.error.kind}: "
                        f"{mask_sensitive(result.error.message)}"
                    ),
                    title=f"{result.query_id} {result.status}",
                    border_style="red",
                )
            )
            return

        if not result.columns:
            self._console.print(
                f"[yellow]{result.query_id} returned no columns.[/yellow]"
            )
            return

        table = Table(
            title=(
                f"{result.query_id}: {result.status} | "
                f"{result.row_count} row(s) | {result.duration_ms} ms"
            )
        )
        for column in result.columns:
            table.add_column(
                f"{escape(column.name)}\n[dim]{escape(column.type)}[/dim]",
                overflow="fold",
            )
        safe_rows = mask_sensitive(
            {
                "columns": [column.model_dump(mode="json") for column in result.columns],
                "rows": result.rows or (),
            }
        )["rows"]
        for row in safe_rows:
            table.add_row(*(_format_cell(value) for value in row))

        self._console.print(table)
        if result.truncated:
            self._console.print(
                f"[yellow]Result truncated at {result.row_count} rows.[/yellow]"
            )


__all__ = ["CLI"]
