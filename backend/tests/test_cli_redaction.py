from __future__ import annotations

from io import StringIO
import sqlite3

from rich.console import Console

from cli import CLI
from contracts.models import ExecutionColumn, ExecutionResult, GatewayConfig
from gateway.connection import ConnectionManager


def test_cli_redacts_sensitive_result_columns_and_error_text(tmp_path):
    database = tmp_path / "empty.sqlite"
    sqlite3.connect(database).close()
    manager = ConnectionManager(
        GatewayConfig(
            datasource_id="test",
            dialect="sqlite",
            connection_url=str(database),
        )
    )
    output = StringIO()
    cli = CLI(manager=manager, console=Console(file=output, color_system=None))

    try:
        cli._print_execution(
            ExecutionResult(
                query_id="Q1",
                status="ok",
                columns=(
                    ExecutionColumn(name="customer_name", type="text"),
                    ExecutionColumn(name="api_key", type="text"),
                    ExecutionColumn(name="count", type="integer"),
                ),
                row_count=1,
                rows=(("Ada Lovelace", "sk-testcredential1234567890", 3),),
                duration_ms=1,
            )
        )
        cli._print_execution(
            ExecutionResult(
                query_id="Q2",
                status="error",
                columns=(),
                row_count=0,
                duration_ms=1,
                error={"kind": "other", "message": "password=hunter2"},
            )
        )
    finally:
        cli.close()

    rendered = output.getvalue()
    assert "Ada Lovelace" not in rendered
    assert "sk-testcredential1234567890" not in rendered
    assert "hunter2" not in rendered
    assert "3" in rendered
