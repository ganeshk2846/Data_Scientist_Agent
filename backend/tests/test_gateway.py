"""Integration tests for the read-only local gateway (SAFE-2, SQL-9).

The fixture database is configured by ``DS_AGENT_DATABASE`` or defaults to the
workspace's ``brazil_ecommerce.sqlite``. ``orders`` holds 99,441 rows, so
``count(*)`` must return that single scalar in one result row.
"""

import time

import pytest

from contracts.models import ExecutionResult, GatewayConfig
from gateway.connection import ConnectionManager, UnsupportedDialectError
from gateway.executor import QueryExecutor
from dataset_fixtures import BACKEND_DIR, DB_PATH, requires_olist

ORDERS_TOTAL = 99_441

SLOW_QUERY = (
    "WITH RECURSIVE cnt(x) AS ("
    "  SELECT 1 UNION ALL SELECT x + 1 FROM cnt WHERE x < 100000000"
    ") SELECT count(*) FROM cnt"
)


def gateway_config(*, timeout_ms: int = 5_000, connection_url: str | None = None):
    return GatewayConfig(
        datasource_id="brazil-ecommerce",
        dialect="sqlite",
        connection_url=connection_url or str(DB_PATH),
        timeout_ms=timeout_ms,
    )


@pytest.fixture
def manager():
    if not DB_PATH.is_file():
        pytest.skip("Olist SQLite fixture is not present; set DS_AGENT_DATABASE")
    manager = ConnectionManager(gateway_config())
    try:
        yield manager
    finally:
        manager.dispose()


@pytest.fixture
def executor(manager):
    return QueryExecutor(manager, max_rows=100)


def test_connection_is_opened_read_only(manager):
    assert "mode=ro" in str(manager.engine.url)


@requires_olist
def test_relative_path_targets_the_workspace_database(monkeypatch):
    monkeypatch.chdir(BACKEND_DIR)
    manager = ConnectionManager(
        gateway_config(connection_url="../brazil_ecommerce.sqlite")
    )
    try:
        with manager.connect() as connection:
            total = connection.exec_driver_sql(
                "SELECT count(*) FROM orders"
            ).scalar_one()
        assert total == ORDERS_TOTAL
    finally:
        manager.dispose()


def test_count_query_returns_the_brazil_orders_total(executor):
    result = executor.execute("SELECT count(*) FROM orders", query_id="Q1")

    assert isinstance(result, ExecutionResult)
    assert result.query_id == "Q1"
    assert result.datasource_id == "brazil-ecommerce"
    assert result.status == "ok"
    assert result.truncated is False
    assert result.row_count == 1
    assert result.rows == ((ORDERS_TOTAL,),)
    assert "count" in result.columns[0].name.lower()
    assert result.columns[0].type == "integer"
    assert result.duration_ms >= 0
    assert result.error is None


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE gateway_should_not_exist (id INTEGER)",
        "INSERT INTO orders (order_id) VALUES ('forbidden')",
        "UPDATE orders SET order_status = 'forbidden'",
        "DELETE FROM orders",
        "DROP TABLE orders",
    ],
)
def test_write_attempts_are_blocked_by_the_driver(executor, sql):
    result = executor.execute(sql)

    assert result.status == "error"
    assert result.error is not None
    assert result.error.kind == "permission"
    assert "readonly" in result.error.message.lower()


def test_failed_writes_leave_the_database_intact(executor):
    executor.execute("CREATE TABLE gateway_should_not_exist (id INTEGER)")

    created = executor.execute(
        "SELECT count(*) FROM sqlite_master "
        "WHERE type = 'table' AND name = 'gateway_should_not_exist'"
    )
    orders = executor.execute("SELECT count(*) FROM orders")

    assert created.rows == ((0,),)
    assert orders.rows == ((ORDERS_TOTAL,),)


@requires_olist
def test_timeout_terminates_the_query_cleanly():
    manager = ConnectionManager(gateway_config(timeout_ms=50))
    executor = QueryExecutor(manager, max_rows=100)
    try:
        started = time.monotonic()
        result = executor.execute(SLOW_QUERY)
        elapsed = time.monotonic() - started

        assert result.status == "timeout"
        assert result.error is not None
        assert result.error.kind == "timeout"
        assert elapsed < 3.0

        recovery = executor.execute("SELECT count(*) FROM orders")
        assert recovery.status == "ok"
        assert recovery.rows == ((ORDERS_TOTAL,),)
    finally:
        manager.dispose()


def test_row_limit_truncates_and_sets_the_flag(manager):
    executor = QueryExecutor(manager, max_rows=5)

    result = executor.execute("SELECT order_id FROM orders")

    assert result.status == "truncated"
    assert result.truncated is True
    assert result.row_count == 5
    assert len(result.rows) == 5


def test_exactly_the_row_cap_is_not_truncated(manager):
    executor = QueryExecutor(manager, max_rows=5)

    result = executor.execute("SELECT order_id FROM orders LIMIT 5")

    assert result.status == "ok"
    assert result.truncated is False
    assert result.row_count == 5
    assert len(result.rows) == 5


def test_missing_table_is_reported_as_a_catalog_error(executor):
    result = executor.execute("SELECT * FROM missing_orders")

    assert result.status == "error"
    assert result.error is not None
    assert result.error.kind == "catalog"
    assert "no such table" in result.error.message.lower()


def test_unsupported_dialects_are_rejected():
    config = GatewayConfig(
        datasource_id="pg",
        dialect="postgres",
        connection_url="postgresql://user:pass@localhost/retail",
    )

    with pytest.raises(UnsupportedDialectError):
        ConnectionManager(config)
