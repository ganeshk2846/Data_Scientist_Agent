"""Structured, masked run traces (OPS-1, SAFE-5).

Every logged run gets its own UUID and a JSON document at
``traces/run_<run_id>.json``. The document records the original question, the
guard result, the SQL validation report, and the execution summary. Sensitive
keys and values are masked before the file is written.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from contracts.models import (
    AnswerabilityResult,
    ExecutionResult,
    FactCheckResult,
    GuardResult,
    Ledger,
    MetricResolution,
    OrchestrationResult,
    ReconciliationResult,
    RepairOutcome,
    SqlCandidate,
    ValidationResult,
)

MASK = "***MASKED***"

_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "connection_url",
    "credential",
    "ssn",
    "social_security",
    "credit_card",
    "card_number",
    "cvv",
    "email",
    "phone",
    "full_name",
    "first_name",
    "last_name",
    "customer_name",
    "username",
    "address",
    "birth",
    "passport",
    "tax_id",
    "bank_account",
    "ip_address",
)

_EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", re.IGNORECASE)
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d{4}[ -]?){3}\d{1,4}\b")
_PHONE_PATTERN = re.compile(
    r"(?<![\w.-])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?"
    r"\d{3}[\s.-]\d{3,4}[\s.-]\d{4}(?![\w.-])"
)
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_CONNECTION_PASSWORD_PATTERN = re.compile(
    r"(?P<prefix>[A-Za-z][A-Za-z0-9+.-]*://[^:/@\s]+:)"
    r"(?P<password>[^@\s]+)(?=@)"
)
_API_KEY_PATTERN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,}|"
    r"AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
)
_JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|secret|api[_-]?key|client[_-]?secret|"
    r"access[_-]?token|auth[_-]?token|credential|token)\s*[:=]\s*)"
    r"(['\"]?)([^\s,;\"']+)"
)


@dataclass(frozen=True, slots=True)
class TraceRecord:
    run_id: str
    path: Path
    payload: dict[str, Any]


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _mask_string(value: str) -> str:
    masked = _SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}{MASK}", value
    )
    masked = _API_KEY_PATTERN.sub(MASK, masked)
    masked = _JWT_PATTERN.sub(MASK, masked)
    masked = _EMAIL_PATTERN.sub(MASK, masked)
    masked = _SSN_PATTERN.sub(MASK, masked)
    masked = _CREDIT_CARD_PATTERN.sub(MASK, masked)
    masked = _PHONE_PATTERN.sub(MASK, masked)
    masked = _BEARER_PATTERN.sub(f"Bearer {MASK}", masked)
    masked = _CONNECTION_PASSWORD_PATTERN.sub(
        lambda match: f"{match.group('prefix')}{MASK}", masked
    )
    return masked


def mask_sensitive(value: Any) -> Any:
    """Recursively mask sensitive keys and common sensitive string patterns."""

    if isinstance(value, dict):
        sensitive_indexes: set[int] = set()
        columns = value.get("columns")
        if isinstance(columns, (list, tuple)):
            sensitive_indexes = {
                index
                for index, column in enumerate(columns)
                if isinstance(column, dict)
                and isinstance(column.get("name"), str)
                and _is_sensitive_key(column["name"])
            }
        masked: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_sensitive_key(key):
                masked[key] = MASK
            elif key == "rows" and sensitive_indexes and isinstance(item, (list, tuple)):
                masked[key] = [
                    [
                        MASK if index in sensitive_indexes else mask_sensitive(cell)
                        for index, cell in enumerate(row)
                    ]
                    if isinstance(row, (list, tuple))
                    else mask_sensitive(row)
                    for row in item
                ]
            else:
                masked[key] = mask_sensitive(item)
        return masked
    if isinstance(value, (list, tuple)):
        return [mask_sensitive(item) for item in value]
    if isinstance(value, str):
        return _mask_string(value)
    return value


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "<binary>"
    if isinstance(value, set):
        return sorted(value, key=str)
    return str(value)


class TraceLogger:
    """Writes one masked JSON document per run."""

    def __init__(
        self,
        trace_dir: str | Path = "traces",
        *,
        mask: bool = True,
    ) -> None:
        if mask is not True:
            raise ValueError("trace redaction cannot be disabled")
        self._trace_dir = Path(trace_dir).expanduser()
        self._mask = True

    @property
    def trace_dir(self) -> Path:
        return self._trace_dir

    def path_for(self, run_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
            raise ValueError("run_id contains invalid characters")
        return self._trace_dir / f"run_{run_id}.json"

    def log(
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
        ledger: Ledger | None = None,
        fact_check: FactCheckResult | None = None,
        run_id: str | None = None,
    ) -> TraceRecord:
        run_id = run_id or uuid.uuid4().hex
        payload: dict[str, Any] = {
            "contract_version": "1.0.0",
            "run_id": run_id,
            "created_at": _utc_now(),
            "question": question,
            "guard": guard.model_dump(mode="json"),
            "orchestration": (
                orchestration.model_dump(mode="json")
                if orchestration is not None
                else None
            ),
            "answerability": (
                answerability.model_dump(mode="json")
                if answerability is not None
                else None
            ),
            "metric_resolution": (
                metric_resolution.model_dump(mode="json")
                if metric_resolution is not None
                else None
            ),
            "candidate": (
                candidate.model_dump(mode="json") if candidate is not None else None
            ),
            "repair": (
                repair.model_dump(mode="json") if repair is not None else None
            ),
            "reconciliation": (
                reconciliation.model_dump(mode="json")
                if reconciliation is not None
                else None
            ),
            "validation": (
                validation.model_dump(mode="json") if validation is not None else None
            ),
            "execution": (
                execution.model_dump(mode="json") if execution is not None else None
            ),
            "ledger": (
                ledger.model_dump(mode="json") if ledger is not None else None
            ),
            "fact_check": (
                fact_check.model_dump(mode="json")
                if fact_check is not None
                else None
            ),
        }

        if self._mask:
            payload = mask_sensitive(payload)

        path = self.path_for(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default)
            + "\n",
            encoding="utf-8",
        )
        return TraceRecord(run_id=run_id, path=path, payload=payload)


__all__ = ["MASK", "TraceLogger", "TraceRecord", "mask_sensitive"]
