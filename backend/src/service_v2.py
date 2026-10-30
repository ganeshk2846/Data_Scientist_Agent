"""The V2 run path beside the V1 path (build-plan 5, decision 2A).

``POST /api/v2/ask`` submits here. Runs share V1's ``RunStore``, so the
existing ``/api/runs/{run_id}/events`` stream serves V2 runs unchanged and
ends on the same terminal ``answer`` / ``error`` events; ``GET
/api/v2/runs/{run_id}`` returns the full ``AnswerEnvelopeV2``. V1's
``RunService.submit`` and ``/api/ask`` are not touched.

A clarification is stored per run, so a reply naming ``clarification_of`` and
an ``option_id`` is applied deterministically (CL-6), and a third round is
never asked (CL-4).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

from contracts.models import ContractModel
from contracts.v2 import AnswerEnvelopeV2, ClarificationRequest
from pipeline_v2 import ClarificationReply, PipelineV2
from pydantic import Field, field_validator
from service import RunNotFoundError, RunService, _error_envelope
from trace_logger import mask_sensitive


class AskV2Request(ContractModel):
    question: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    clarification_of: str | None = None
    option_id: str | None = None

    @field_validator("question")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned


@dataclass(frozen=True)
class _Pending:
    question: str
    request: ClarificationRequest


class V2Runner:
    def __init__(self, service: RunService) -> None:
        self._service = service
        self._pipeline: PipelineV2 | None = None
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._threads: list[threading.Thread] = []

    def pipeline(self) -> PipelineV2:
        with self._lock:
            if self._pipeline is None:
                runtime = self._service._get_runtime()
                self._pipeline = PipelineV2(guard=runtime.guard, catalog=runtime.catalog, manager=runtime.manager,
                                            client=getattr(runtime.router, "_client", None))
            return self._pipeline

    def submit(self, request: AskV2Request, *, owner_id: str) -> str:
        reply: ClarificationReply | None = None
        if request.clarification_of is not None:
            if self._service.store.owner_id(request.clarification_of) != owner_id:
                raise RunNotFoundError(request.clarification_of)
            pending = self._pending.get(request.clarification_of)
            if pending is not None:
                reply = ClarificationReply(original_question=pending.question, request=pending.request,
                                           of_run_id=request.clarification_of, option_id=request.option_id,
                                           text=None if request.option_id else request.question)
        run_id = uuid.uuid4().hex
        self._service.store.create(run_id, owner_id=owner_id, question=request.question, session_id=request.session_id,
                                   clarification_of=request.clarification_of)
        thread = threading.Thread(target=self._execute, args=(run_id, request.question, reply), name=f"ds-agent-v2-{run_id[:8]}", daemon=True)
        self._threads.append(thread)
        thread.start()
        return run_id

    def envelope(self, run_id: str, *, timeout: float = 15.0) -> AnswerEnvelopeV2 | None:
        return self._service.store.wait_for_envelope(run_id, timeout=timeout)  # type: ignore[return-value]

    def run_sync(self, question: str, *, owner_id: str = "local", option_id: str | None = None,
                 clarification_of: str | None = None) -> tuple[str, AnswerEnvelopeV2]:
        """Submit and wait; used by tests and the CLI."""
        run_id = self.submit(AskV2Request(question=question, session_id="local", clarification_of=clarification_of, option_id=option_id),
                             owner_id=owner_id)
        envelope = self._service.store.wait_for_envelope(run_id, timeout=120.0)
        return run_id, envelope  # type: ignore[return-value]

    def _execute(self, run_id: str, question: str, reply: ClarificationReply | None) -> None:
        emit = lambda event_type, **fields: self._service.store.append(run_id, event_type, **fields)
        try:
            outcome = self.pipeline().run(question, run_id=run_id, emit=emit, reply=reply)
            envelope = outcome.envelope
            if outcome.clarification is not None:
                self._pending[run_id] = _Pending(outcome.question if reply is None else reply.original_question, outcome.clarification)
            if envelope.status == "error":
                emit("error", error={"code": "internal", "message": "; ".join(envelope.caveats[:1]) or "The V2 run failed.", "retriable": False})
            else:
                emit("answer", status=envelope.status)
            self._service.store.complete(run_id, envelope)
        except Exception as exc:  # pragma: no cover - defensive boundary
            envelope = _error_envelope(run_id, f"Run failed: {mask_sensitive(str(exc))}")
            emit("error", error={"code": "internal", "message": "The V2 run failed inside the agent service.", "retriable": False})
            self._service.store.complete(run_id, envelope)

    def close(self) -> None:
        for thread in list(self._threads):
            if thread.is_alive():
                thread.join(timeout=5.0)


__all__ = ["AskV2Request", "V2Runner"]
