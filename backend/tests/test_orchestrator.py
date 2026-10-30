"""Stage 5 orchestration tests (RTE-1, RTE-3, OPS-2, ANA-1)."""

from __future__ import annotations

from datetime import date

from analysts.harness import AnalystHarness
from catalog import MetricRegistry
from catalog.metric_resolver import MetricResolver
from contracts.models import (
    AnomalyResult,
    ExecutionBudget,
    ExecutionColumn,
    ExecutionResult,
    GuardResult,
)
from orchestrator import Orchestrator
from router import Router
from schema_retriever.catalog import (
    CatalogColumn,
    CatalogForeignKey,
    CatalogTable,
    SchemaCatalog,
)
from sql.compiler import SQLCompiler
from sql.reconciler import Reconciler


class NoCallClient:
    def chat_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("stage-5 tests must not call the model")


class FakeExecutor:
    def __init__(self, series=None, scalar=123):
        self.series = series or _default_series()
        self.scalar = scalar
        self.sqls: list[str] = []
        self.query_ids: list[str] = []

    def execute(self, sql: str, *, query_id: str) -> ExecutionResult:
        self.sqls.append(sql)
        self.query_ids.append(query_id)
        if "strftime('%Y-%m'" in sql:
            columns = (
                ExecutionColumn(name="month", type="TEXT"),
                ExecutionColumn(name="order_count", type="INTEGER"),
            )
            rows = self.series
        else:
            columns = (ExecutionColumn(name="order_count", type="INTEGER"),)
            rows = ((self.scalar,),)
        return ExecutionResult(
            query_id=query_id,
            status="ok",
            columns=columns,
            row_count=len(rows),
            rows=tuple(rows),
            duration_ms=2,
        )


def _default_series():
    rows = []
    year, month = 2016, 9
    for _ in range(24):
        value = 20 if (year, month) == (2018, 8) else 100
        rows.append((f"{year:04d}-{month:02d}", value))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return tuple(rows)


def _catalog() -> SchemaCatalog:
    return SchemaCatalog(
        version="orchestrator-test",
        tables=(
            CatalogTable(
                name="orders",
                foreign_keys=(
                    CatalogForeignKey(
                        columns=("customer_id",),
                        referred_table="customers",
                        referred_columns=("customer_id",),
                    ),
                ),
                columns=(
                    CatalogColumn(name="order_id", data_type="TEXT"),
                    CatalogColumn(name="customer_id", data_type="TEXT"),
                    CatalogColumn(name="order_status", data_type="TEXT"),
                    CatalogColumn(
                        name="order_purchase_timestamp",
                        data_type="TEXT",
                    ),
                ),
            ),
            CatalogTable(
                name="customers",
                columns=(
                    CatalogColumn(name="customer_id", data_type="TEXT"),
                    CatalogColumn(name="customer_state", data_type="TEXT"),
                ),
            ),
            CatalogTable(
                name="order_payments",
                foreign_keys=(
                    CatalogForeignKey(
                        columns=("order_id",),
                        referred_table="orders",
                        referred_columns=("order_id",),
                    ),
                ),
                columns=(
                    CatalogColumn(name="order_id", data_type="TEXT"),
                    CatalogColumn(name="payment_value", data_type="REAL"),
                ),
            ),
        ),
    )


def _orchestrator(executor, budget=None) -> Orchestrator:
    catalog = _catalog()
    registry = MetricRegistry.default()
    router = Router(
        catalog=catalog,
        registry=registry,
        client=NoCallClient(),
        reference_date=date(2026, 10, 25),
    )
    return Orchestrator(
        executor=executor,
        router=router,
        registry=registry,
        metric_resolver=MetricResolver(
            registry,
            client=NoCallClient(),
            use_model=False,
        ),
        compiler=SQLCompiler(catalog),
        reconciler=Reconciler(),
        harness=AnalystHarness(),
        budget=budget,
    )


def test_diagnostic_run_executes_one_series_query_and_anomaly():
    executor = FakeExecutor()
    outcome = _orchestrator(executor).run(
        "Why did orders drop in August 2018?"
    )

    assert outcome.status == "ok", outcome.reason
    assert outcome.route_labels[0] == "anomaly"
    assert outcome.intent_label == "Diagnostic"
    assert len(outcome.queries) == 1
    assert outcome.queries[0].purpose == "series"
    assert "strftime('%Y-%m'" in outcome.queries[0].sql
    assert executor.query_ids == ["Q1"]
    assert outcome.execution is not None
    assert outcome.execution.rows == executor.series
    assert len(outcome.analyst_outputs) == 1
    assert isinstance(outcome.analyst_outputs[0].result, AnomalyResult)
    assert outcome.analyst_outputs[0].result.actual == 20.0
    assert outcome.budget.queries == 1
    assert outcome.budget.wall_ms >= 0
    assert [step.module for step in outcome.plan] == [
        "router",
        "query_series",
        "anomaly",
    ]
    assert all(step.status == "completed" for step in outcome.plan)
    assert outcome.latency_ms >= 0


def test_budget_blocks_the_first_query_before_it_reaches_the_database():
    executor = FakeExecutor()
    outcome = _orchestrator(
        executor,
        budget=ExecutionBudget(max_queries=0),
    ).run("Why did orders drop in August 2018?")

    assert outcome.status == "error"
    assert "budget" in outcome.reason.lower()
    assert outcome.queries == ()
    assert executor.sqls == []
    assert outcome.budget.queries == 0


def test_governed_lookup_is_routed_through_compiler_and_executed():
    executor = FakeExecutor(scalar=500)
    outcome = _orchestrator(executor).run("How many orders in August 2018?")

    assert outcome.status == "ok", outcome
    assert outcome.route_labels == ("lookup",)
    assert outcome.candidate is not None
    assert outcome.candidate.origin == "compiler"
    assert outcome.validation is not None
    assert outcome.validation.approved is True
    assert outcome.execution is not None
    assert outcome.execution.rows == ((500,),)
    assert len(outcome.queries) == 1
    assert outcome.analyst_outputs == ()
    assert [step.module for step in outcome.plan] == ["router", "lookup"]


def test_comparative_lookup_executes_two_queries_and_completes():
    executor = FakeExecutor(scalar=500)
    outcome = _orchestrator(executor).run("difference in total sales in 2018 compared to 2017")

    assert outcome.status == "ok", outcome.reason
    assert outcome.route_labels == ("lookup",)
    assert outcome.intent_label == "Comparative"
    assert len(outcome.queries) == 2
    assert outcome.queries[0].purpose == "current_lookup"
    assert outcome.queries[1].purpose == "comparison_lookup"
    assert len(outcome.executions) == 2


def test_low_confidence_question_stops_with_clarification_and_no_query():
    executor = FakeExecutor()
    outcome = _orchestrator(executor).run("How are sales doing?")

    assert outcome.status == "clarification"
    assert outcome.route_labels == ("clarify",)
    assert outcome.clarification is not None
    assert outcome.queries == ()
    assert executor.sqls == []
    assert outcome.plan[-1].status == "completed"


def test_blocked_guard_short_circuits_orchestration():
    executor = FakeExecutor()
    guard = GuardResult(
        passed=False,
        reason="write_attempt",
        matched_rule="delete_orders",
    )
    outcome = _orchestrator(executor).run(
        "Why did orders drop in August 2018?",
        guard_result=guard,
    )

    assert outcome.status == "blocked"
    assert outcome.route_labels == ("blocked",)
    assert outcome.queries == ()
    assert executor.sqls == []


def test_risk_route_returns_explicit_insufficient_evidence_not_fake_analysis():
    executor = FakeExecutor()
    outcome = _orchestrator(executor).run(
        "Which customers are likely to churn?"
    )

    assert outcome.status == "insufficient_evidence"
    assert outcome.route_labels == ("risk",)
    assert "risk" in outcome.reason.lower()
    assert outcome.queries == ()
    assert executor.sqls == []


def test_route_result_can_be_reused_to_avoid_routing_twice():
    executor = FakeExecutor()
    orchestrator = _orchestrator(executor)
    route = orchestrator.router.route("Why did orders drop in August 2018?")

    outcome = orchestrator.run(
        "Why did orders drop in August 2018?",
        route_result=route,
    )

    assert outcome.router == route
    assert outcome.status == "ok"
    assert len(executor.sqls) == 1


class DriverExecutor:
    """Returns dimensioned contribution rows for the driver path (DRV-2)."""

    def __init__(self, current_rows, comparison_rows):
        self.current_rows = current_rows
        self.comparison_rows = comparison_rows
        self.sqls: list[str] = []
        self.query_ids: list[str] = []

    def execute(self, sql: str, *, query_id: str) -> ExecutionResult:
        self.sqls.append(sql)
        self.query_ids.append(query_id)
        # The orchestrator compiles the current period first, then the
        # comparison period, so the call order identifies the window.
        rows = self.current_rows if len(self.sqls) == 1 else self.comparison_rows
        return ExecutionResult(
            query_id=query_id,
            status="ok",
            columns=(
                ExecutionColumn(name="customer_state", type="TEXT"),
                ExecutionColumn(name="order_count", type="INTEGER"),
            ),
            row_count=len(rows),
            rows=tuple(rows),
            duration_ms=2,
        )


def test_driver_route_completes_and_attributes_the_change():
    """V2-PRE-1: the driver path raised TypeError on every call.

    ``_contribution_table`` takes ``current_period``/``comparison_period``,
    but the call site passed ``current``/``comparison``, so ``current`` was
    supplied both positionally and by keyword. Every driver question returned
    ``status: "error"``, which is why only "what" questions ever worked.
    """

    executor = DriverExecutor(
        current_rows=(("SP", 60), ("RJ", 20), ("MG", 20)),
        comparison_rows=(("SP", 100), ("RJ", 20), ("MG", 20)),
    )
    outcome = _orchestrator(executor).run(
        "What drove the order count change by state in August 2018?"
    )

    assert outcome.status == "ok", outcome.reason
    assert outcome.route_labels == ("driver",)
    assert outcome.intent_label == "Diagnostic"

    # Two contribution queries, one per window.
    assert len(outcome.queries) == 2
    assert [query.purpose for query in outcome.queries] == [
        "current_contribution",
        "comparison_contribution",
    ]

    # The analyst ran and attributed the change rather than erroring.
    assert len(outcome.analyst_outputs) == 1
    output = outcome.analyst_outputs[0]
    assert output.module == "driver"
    assert output.status == "ok", output.reason
    result = output.result
    assert result is not None

    # SP is the only state that moved: -40 of a -40 total change.
    assert result.total_change == -40.0
    top = result.drivers[0]
    assert top.dimension == "customer_state"
    assert top.value == "SP"
    assert top.contribution == -40.0
    assert top.share == 1.0
    # DRV-2: contributions must reconcile to the total change exactly.
    assert result.reconciliation_error == 0.0

    assert [step.module for step in outcome.plan] == ["router", "driver"]
    assert all(step.status == "completed" for step in outcome.plan)


def test_driver_route_passes_distinct_periods_to_the_contribution_table():
    """The two windows must stay distinguishable, not collapse into one.

    The original defect passed one period twice. A fix that merely renamed the
    argument while sending the same window to both would still bin every row
    into one period and report a zero change, so assert the periods differ.
    """

    executor = DriverExecutor(
        current_rows=(("SP", 60),),
        comparison_rows=(("SP", 100),),
    )
    outcome = _orchestrator(executor).run(
        "What drove the order count change by state in August 2018?"
    )

    assert outcome.status == "ok", outcome.reason
    parameters = outcome.analyst_outputs[0].parameters
    assert parameters["current_period"] != parameters["comparison_period"]
    assert parameters["current_period"] == "2018-08-01/2018-09-01"
    assert parameters["comparison_period"] == "2018-07-01/2018-08-01"
