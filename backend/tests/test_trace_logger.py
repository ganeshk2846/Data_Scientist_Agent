"""Tests for structured, masked run traces (OPS-1, SAFE-5)."""

import json

import pytest

from contracts.models import (
    ExecutionColumn,
    ExecutionResult,
    GuardResult,
    ValidationCheck,
    ValidationResult,
)
from trace_logger import MASK, TraceLogger, mask_sensitive


def passed_guard() -> GuardResult:
    return GuardResult(passed=True)


def passed_validation() -> ValidationResult:
    return ValidationResult(
        approved=True,
        validation_mode="enterprise",
        checks=(ValidationCheck(id=1, name="parse", status="pass"),),
    )


def ok_execution() -> ExecutionResult:
    return ExecutionResult(
        query_id="Q1",
        datasource_id="brazil-ecommerce",
        status="ok",
        columns=(ExecutionColumn(name="count", type="integer"),),
        row_count=1,
        rows=((99_441,),),
        duration_ms=4,
    )


def test_writes_structured_trace_with_unique_run_ids(tmp_path):
    logger = TraceLogger(tmp_path)

    first = logger.log(
        question="SELECT count(*) FROM orders LIMIT 1",
        guard=passed_guard(),
        validation=passed_validation(),
        execution=ok_execution(),
    )
    second = logger.log(
        question="SELECT count(*) FROM orders LIMIT 1",
        guard=passed_guard(),
        validation=passed_validation(),
        execution=ok_execution(),
    )

    assert first.run_id != second.run_id
    path = tmp_path / f"run_{first.run_id}.json"
    assert path == first.path
    assert path.is_file()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == first.run_id
    assert payload["created_at"].endswith("Z")
    assert payload["question"] == "SELECT count(*) FROM orders LIMIT 1"
    assert payload["guard"]["passed"] is True
    assert payload["validation"]["approved"] is True
    assert payload["validation"]["validation_mode"] == "enterprise"
    assert payload["execution"]["status"] == "ok"
    assert payload["execution"]["duration_ms"] == 4
    assert payload["execution"]["row_count"] == 1
    assert payload["execution"]["rows"] == [[99_441]]


def test_masks_sensitive_values_in_question_and_rows(tmp_path):
    logger = TraceLogger(tmp_path)
    question = (
        "Email jane@example.com or call +1 555-123-4567 "
        "about card 4111 1111 1111 1111"
    )
    execution = ExecutionResult(
        query_id="Q1",
        status="ok",
        columns=(
            ExecutionColumn(name="email", type="text"),
            ExecutionColumn(name="phone", type="text"),
            ExecutionColumn(name="card", type="text"),
        ),
        row_count=1,
        rows=(("jane@example.com", "+1 555-123-4567", "4111 1111 1111 1111"),),
        duration_ms=1,
    )

    record = logger.log(
        question=question,
        guard=passed_guard(),
        validation=passed_validation(),
        execution=execution,
    )

    raw = (tmp_path / f"run_{record.run_id}.json").read_text(encoding="utf-8")
    assert "jane@example.com" not in raw
    assert "555-123-4567" not in raw
    assert "4111 1111 1111 1111" not in raw
    assert "4111111111111111" not in raw
    assert MASK in raw


def test_masks_sensitive_fields_by_key():
    masked = mask_sensitive(
        {
            "password": "hunter2",
            "nested": {"api_key": "abc123", "note": "keep me"},
            "items": [{"token": "t-123"}],
        }
    )

    assert masked["password"] == MASK
    assert masked["nested"]["api_key"] == MASK
    assert masked["nested"]["note"] == "keep me"
    assert masked["items"][0]["token"] == MASK


def test_masks_credentials_and_jwts_in_free_text():
    from trace_logger import mask_sensitive

    canaries = (
        "sk-testcredential1234567890",
        "AKIA1234567890ABCDEF",
        "ghp_abcdefghijklmnopqrstuvwxyz123456",
        "xoxb-" + "1234567890" + "-" + "abcdefghijklmnop",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.signature123456",
    )
    masked = mask_sensitive(" ".join(canaries) + " password=hunter2")

    for canary in canaries:
        assert canary not in masked
    assert "hunter2" not in masked
    assert masked.count(MASK) >= len(canaries) + 1


def test_masks_values_under_sensitive_result_columns():
    masked = mask_sensitive(
        {
            "columns": [
                {"name": "customer_name", "type": "text"},
                {"name": "order_count", "type": "integer"},
            ],
            "rows": [["Ada Lovelace", 4]],
        }
    )

    assert masked["rows"] == [[MASK, 4]]


def test_persisted_trace_redacts_credentials_and_sensitive_rows(tmp_path):
    credential = "sk-testcredential1234567890"
    execution = ExecutionResult(
        query_id="Q1",
        status="ok",
        columns=(
            ExecutionColumn(name="customer_name", type="text"),
            ExecutionColumn(name="llm_api_key", type="text"),
            ExecutionColumn(name="amount", type="integer"),
        ),
        row_count=1,
        rows=(("Ada Lovelace", credential, 10),),
        duration_ms=1,
    )

    record = TraceLogger(tmp_path).log(
        question=f"password=hunter2 {credential}",
        guard=passed_guard(),
        execution=execution,
    )
    raw = record.path.read_text(encoding="utf-8")

    assert "Ada Lovelace" not in raw
    assert credential not in raw
    assert "hunter2" not in raw
    assert "10" in raw


def test_trace_redaction_cannot_be_disabled(tmp_path):
    with pytest.raises(ValueError, match="cannot be disabled"):
        TraceLogger(tmp_path, mask=False)


def test_logs_a_guard_block_without_validation_or_execution(tmp_path):
    logger = TraceLogger(tmp_path)

    record = logger.log(
        question="DROP TABLE orders",
        guard=GuardResult(
            passed=False, reason="write_attempt", matched_rule="guard.ddl"
        ),
    )

    payload = json.loads(record.path.read_text(encoding="utf-8"))
    assert payload["guard"]["passed"] is False
    assert payload["guard"]["matched_rule"] == "guard.ddl"
    assert payload["validation"] is None
    assert payload["execution"] is None


def test_path_for_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError):
        TraceLogger(tmp_path).path_for("../escape")
