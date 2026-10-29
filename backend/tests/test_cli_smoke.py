"""End-to-end smoke test for the Day-1 terminal console."""

import json
import os
from io import StringIO
from pathlib import Path

from rich.console import Console

from cli import CLI
from contracts.models import GatewayConfig
from gateway.connection import ConnectionManager
from trace_logger import TraceLogger
from dataset_fixtures import requires_olist

BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_PATH = Path(
    os.environ.get("DS_AGENT_DATABASE", BACKEND_DIR / ".." / "brazil_ecommerce.sqlite")
).expanduser().resolve()


@requires_olist
def test_cli_runs_end_to_end_without_crashing(monkeypatch, tmp_path):
    responses = iter(
        [
            "SELECT count(*) FROM orders",
            "mode benchmark",
            "SELECT count(*) FROM orders",
            "SELECT * FROM orders",
            "tables",
            "DROP TABLE orders",
            "exit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=160,
    )
    manager = ConnectionManager(
        GatewayConfig(
            datasource_id="brazil-ecommerce",
            dialect="sqlite",
            connection_url=str(DB_PATH),
            timeout_ms=5_000,
        )
    )
    trace_dir = tmp_path / "traces"
    cli = CLI(
        manager=manager,
        logger=TraceLogger(trace_dir),
        console=console,
        max_rows=5,
    )

    try:
        exit_code = cli.run()
    finally:
        cli.close()

    rendered = output.getvalue()
    assert exit_code == 0
    assert "DS-Agent" in rendered
    assert "benchmark" in rendered.lower()
    assert "99,441" in rendered
    assert "orders" in rendered
    assert "truncated" in rendered.lower()

    traces = sorted(trace_dir.glob("run_*.json"))
    assert len(traces) == 4
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in traces]

    blocked = [payload for payload in payloads if not payload["guard"]["passed"]]
    assert len(blocked) == 1
    assert blocked[0]["execution"] is None
    assert blocked[0]["guard"]["reason"] == "write_attempt"

    failed_validation = [
        payload
        for payload in payloads
        if payload["validation"] is not None
        and not payload["validation"]["approved"]
    ]
    assert len(failed_validation) == 1
    assert failed_validation[0]["execution"] is None

    truncated = [
        payload
        for payload in payloads
        if payload["execution"] is not None
        and payload["execution"]["status"] == "truncated"
    ]
    assert len(truncated) == 1


class NoCallReasoningClient:
    def chat(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("governed questions must not call the model")

    def chat_json(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("governed questions must not call the model")


@requires_olist
def test_cli_uses_the_governed_metric_fast_path(monkeypatch, tmp_path):
    responses = iter(["ask What was revenue?", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )
    manager = ConnectionManager(
        GatewayConfig(
            datasource_id="brazil-ecommerce",
            dialect="sqlite",
            connection_url=str(DB_PATH),
            timeout_ms=5_000,
        )
    )
    trace_dir = tmp_path / "traces"
    cli = CLI(
        manager=manager,
        logger=TraceLogger(trace_dir),
        console=console,
        max_rows=5,
        reasoning_client=NoCallReasoningClient(),
    )

    try:
        exit_code = cli.run()
    finally:
        cli.close()

    rendered = output.getvalue()
    assert exit_code == 0
    assert "revenue" in rendered
    assert "Reconciliation passed" in rendered

    traces = sorted(trace_dir.glob("run_*.json"))
    assert len(traces) == 1
    payload = json.loads(traces[0].read_text(encoding="utf-8"))
    assert payload["candidate"]["origin"] == "compiler"
    assert payload["metric_resolution"]["coverage"] == "full"
    assert payload["metric_resolution"]["metric_id"] == "revenue"
    assert payload["metric_resolution"]["model"] is None
    assert payload["reconciliation"]["status"] == "pass"
    assert payload["reconciliation"]["caveats"] == []


@requires_olist
def test_cli_runs_an_anomaly_diagnostic_with_analyst_and_trace(monkeypatch, tmp_path):
    responses = iter(
        ["ask Why did orders drop in August 2018?", "exit"]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )
    manager = ConnectionManager(
        GatewayConfig(
            datasource_id="brazil-ecommerce",
            dialect="sqlite",
            connection_url=str(DB_PATH),
            timeout_ms=5_000,
        )
    )
    trace_dir = tmp_path / "traces"
    cli = CLI(
        manager=manager,
        logger=TraceLogger(trace_dir),
        console=console,
        max_rows=50,
    )

    try:
        exit_code = cli.run()
    finally:
        cli.close()

    rendered = output.getvalue()
    assert exit_code == 0
    assert "Intent route" in rendered
    assert "anomaly" in rendered
    assert "driver" in rendered
    assert "order_count" in rendered
    assert "Anomaly analysis" in rendered
    assert "within normal range" in rendered

    traces = sorted(trace_dir.glob("run_*.json"))
    assert len(traces) == 1
    payload = json.loads(traces[0].read_text(encoding="utf-8"))
    orchestration = payload["orchestration"]
    assert orchestration["route_labels"][0] == "anomaly"
    assert orchestration["status"] == "ok"
    assert len(orchestration["queries"]) == 1
    assert orchestration["queries"][0]["purpose"] == "series"
    assert orchestration["budget"]["queries"] == 1
    assert orchestration["analyst_outputs"][0]["module"] == "anomaly"
    assert orchestration["analyst_outputs"][0]["status"] == "ok"
    assert orchestration["analyst_outputs"][0]["result"]["verdict"] == (
        "within_normal_range"
    )
    assert payload["candidate"]["origin"] == "compiler"
    assert payload["execution"]["status"] == "ok"


@requires_olist
def test_cli_clarifies_vague_questions_and_refuses_out_of_scope_metrics(
    monkeypatch, tmp_path
):
    responses = iter(
        [
            "ask How are sales doing?",
            "ask What is NPS?",
            "exit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )
    manager = ConnectionManager(
        GatewayConfig(
            datasource_id="brazil-ecommerce",
            dialect="sqlite",
            connection_url=str(DB_PATH),
            timeout_ms=5_000,
        )
    )
    trace_dir = tmp_path / "traces"
    cli = CLI(
        manager=manager,
        logger=TraceLogger(trace_dir),
        console=console,
        max_rows=50,
    )

    try:
        exit_code = cli.run()
    finally:
        cli.close()

    rendered = output.getvalue()
    assert exit_code == 0
    assert "Clarification" in rendered
    assert "Refusal" in rendered
    assert "nps" in rendered.lower()

    traces = sorted(trace_dir.glob("run_*.json"))
    assert len(traces) == 2
    payloads = [json.loads(path.read_text(encoding="utf-8")) for path in traces]
    statuses = {
        payload["orchestration"]["status"] for payload in payloads
    }
    assert statuses == {"clarification", "refused"}
    assert all(
        payload["orchestration"]["queries"] == []
        for payload in payloads
    )


@requires_olist
def test_cli_answers_a_natural_language_question(monkeypatch, tmp_path):
    responses = iter(
        [
            "ask What is the average review score by customer state?",
            "exit",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(responses))

    output = StringIO()
    console = Console(
        file=output,
        force_terminal=False,
        color_system=None,
        width=180,
    )
    manager = ConnectionManager(
        GatewayConfig(
            datasource_id="brazil-ecommerce",
            dialect="sqlite",
            connection_url=str(DB_PATH),
            timeout_ms=5_000,
        )
    )
    trace_dir = tmp_path / "traces"
    cli = CLI(
        manager=manager,
        logger=TraceLogger(trace_dir),
        console=console,
        max_rows=5,
    )

    try:
        exit_code = cli.run()
    finally:
        cli.close()

    rendered = output.getvalue()
    assert exit_code == 0
    assert "avg_review_score" in rendered

    traces = sorted(trace_dir.glob("run_*.json"))
    assert len(traces) == 1
    payload = json.loads(traces[0].read_text(encoding="utf-8"))
    assert payload["guard"]["passed"] is True
    assert payload["validation"]["approved"] is True
    assert payload["execution"]["status"] in {"ok", "truncated"}
    assert payload["execution"]["row_count"] > 0
    assert payload["candidate"]["origin"] == "generator"
