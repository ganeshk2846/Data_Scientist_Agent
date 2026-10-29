"""Tests for the governed metric fast path (MET-2, MET-3, SQL-10)."""

from __future__ import annotations

import time

import pytest

from catalog import MetricRegistry
from catalog.metric_resolver import MetricResolver
from contracts.models import GatewayConfig, MetricFilter, Period
from gateway.connection import ConnectionManager
from gateway.executor import QueryExecutor
from schema_retriever.catalog import SchemaCatalog
from sql.compiler import MetricCompilationError, SQLCompiler
from sql.validator import SQLValidator
from dataset_fixtures import DB_PATH

class NoCallClient:
    """A client that fails the test if the governed path calls a model."""

    def chat_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("the metric fast path must not call the model")


@pytest.fixture(scope="module")
def manager():
    if not DB_PATH.is_file():
        pytest.skip("Olist SQLite fixture is not present; set DS_AGENT_DATABASE")
    connection = ConnectionManager(
        GatewayConfig(
            datasource_id="brazil-ecommerce",
            dialect="sqlite",
            connection_url=str(DB_PATH),
            timeout_ms=5_000,
        )
    )
    try:
        yield connection
    finally:
        connection.dispose()


@pytest.fixture(scope="module")
def catalog(manager):
    return SchemaCatalog.from_manager(manager)


@pytest.fixture(scope="module")
def executor(manager):
    return QueryExecutor(manager, max_rows=25)


def _validator_for(compiled) -> SQLValidator:
    return SQLValidator(
        compiled.allowlist.tables,
        dialect=compiled.candidate.dialect,
        mode="enterprise",
        columns=[
            f"{column.table}.{column.column}"
            for column in compiled.allowlist.columns
        ],
    )


def test_governed_questions_resolve_without_a_model():
    registry = MetricRegistry.default()
    resolver = MetricResolver(registry, client=NoCallClient())

    questions = (
        "What was GMV?",
        "What is revenue?",
        "How many orders?",
        "What is the average order value?",
    )

    for question in questions:
        resolution = resolver.resolve(question)
        assert resolution.coverage == "full", question
        assert resolution.metric_id is not None, question
        assert resolution.definition is not None, question


def test_each_governed_metric_compiles_executes_and_is_deterministic(
    catalog, executor
):
    registry = MetricRegistry.default()
    compiler = SQLCompiler(catalog, dialect="sqlite")

    for metric_id in ("gmv", "revenue", "order_count", "aov"):
        definition = registry.require(metric_id)
        started = time.perf_counter()
        compiled = compiler.compile(definition)
        validation = _validator_for(compiled).validate(compiled.candidate.sql)
        execution = executor.execute(compiled.candidate.sql, query_id="Q1")
        elapsed_ms = (time.perf_counter() - started) * 1_000

        assert validation.approved is True, validation
        assert execution.status == "ok", execution.error
        assert execution.rows, metric_id
        assert execution.rows[0][0] is not None, metric_id
        assert execution.rows[0][0] > 0, metric_id
        assert execution.columns[0].name == metric_id
        assert compiled.candidate.origin == "compiler"
        assert elapsed_ms < 1_000, (metric_id, elapsed_ms)

        again = compiler.compile(definition)
        assert again.candidate.sql == compiled.candidate.sql
        assert again.candidate.candidate_id == compiled.candidate.candidate_id

    count = compiler.compile(registry.require("order_count"))
    execution = executor.execute(count.candidate.sql, query_id="Q1")
    assert execution.rows == ((99_441,),)


def test_grouped_filtered_period_query_compiles_and_executes(catalog, executor):
    definition = MetricRegistry.default().require("revenue")
    compiler = SQLCompiler(catalog, dialect="sqlite")

    compiled = compiler.compile(
        definition,
        dimensions=("customer_state",),
        filters=(
            MetricFilter(
                table="customers",
                column="customer_state",
                operator="=",
                value="SP",
            ),
        ),
        period=Period(start="2018-01-01", end="2019-01-01"),
    )

    sql = compiled.candidate.sql
    assert "customer_state" in sql
    assert "'SP'" in sql
    assert "'2018-01-01'" in sql
    assert "'2019-01-01'" in sql
    assert "GROUP BY" in sql.upper()
    assert "LIMIT" in sql.upper()
    assert compiled.candidate.grain == ("customer_state",)
    assert _validator_for(compiled).validate(sql).approved is True

    execution = executor.execute(sql, query_id="Q2")
    assert execution.status == "ok", execution.error
    assert execution.rows
    assert execution.rows[0][0] == "SP"
    assert execution.rows[0][1] > 0


def test_monthly_grouping_is_dialect_aware(catalog):
    definition = MetricRegistry.default().require("revenue")
    compiler = SQLCompiler(catalog, dialect="sqlite")

    compiled = compiler.compile(definition, time_grain="month")

    sql = compiled.candidate.sql
    assert "strftime" in sql.lower()
    assert "month" in sql.lower()
    assert compiled.candidate.grain == ("month",)
    assert _validator_for(compiled).validate(sql).approved is True


def test_unknown_dimension_fails_closed(catalog):
    definition = MetricRegistry.default().require("gmv")
    compiler = SQLCompiler(catalog, dialect="sqlite")

    with pytest.raises(MetricCompilationError):
        compiler.compile(definition, dimensions=("warehouse_id",))
