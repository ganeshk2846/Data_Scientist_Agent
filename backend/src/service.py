"""Run service, answer assembly, and the in-memory SSE event store (Stage 6).

The HTTP layer submits a question and gets a run id immediately. A worker thread
executes the orchestrator, publishes ordered progress events, builds the final
``AnswerEnvelope``, and fact-checks its narrative against the evidence ledger.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from analysts.harness import AnalystHarness
from catalog import MetricRegistry
from catalog.metric_resolver import MetricResolver
from contracts.models import (
    AnomalyResult,
    AnswerEnvelope,
    BlockBlock,
    DriverResult,
    EnvelopeQueryRecord,
    EnvelopeScope,
    EvidenceBlock,
    FactCheckResult,
    GuardResult,
    Ledger,
    MethodStep,
    OrchestrationResult,
    Provenance,
    RefusalBlock,
    RouteSummary,
    RunMetrics,
    RunStatus,
)
from evidence.ledger import EvidenceLedger, FactChecker, format_number
from gateway.connection import ConnectionManager
from gateway.executor import QueryExecutor
from guard import Guard
from orchestrator import Orchestrator
from router import Router
from schema_retriever.catalog import SchemaCatalog
from sql.compiler import SQLCompiler
from sql.reconciler import Reconciler
from trace_logger import TraceLogger, mask_sensitive

_DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "brazil_ecommerce.sqlite"
_DATABASE_PATH = Path(
    os.environ.get("DS_AGENT_DATABASE", _DEFAULT_DATABASE_PATH)
).expanduser().resolve()
_TERMINAL_EVENTS = frozenset({"answer", "error"})
_GOVERNED_ROUTES = frozenset({"lookup", "anomaly", "driver"})


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


@dataclass(slots=True)
class AgentRuntime:
    """One initialized read-only agent pipeline."""

    manager: ConnectionManager
    executor: QueryExecutor
    guard: Guard
    router: Router
    orchestrator: Orchestrator
    catalog: SchemaCatalog

    @property
    def catalog_version(self) -> str:
        return self.catalog.version

    def close(self) -> None:
        self.manager.dispose()


def build_runtime(
    database_path: str | Path = _DATABASE_PATH,
    *,
    reasoning_client: object | None = None,
    timeout_ms: int = 5_000,
    max_rows: int = 500,
) -> AgentRuntime:
    from contracts.models import GatewayConfig

    config = GatewayConfig(
        datasource_id="brazil-ecommerce",
        dialect="sqlite",
        connection_url=str(database_path),
        timeout_ms=timeout_ms,
    )
    manager = ConnectionManager(config)
    try:
        catalog = SchemaCatalog.from_manager(manager)
        registry = MetricRegistry.default()
        resolver = MetricResolver(registry, client=reasoning_client)
        compiler = SQLCompiler(catalog, dialect="sqlite")
        router = Router(
            catalog=catalog,
            registry=registry,
            client=reasoning_client,
        )
        harness = AnalystHarness()
        executor = QueryExecutor(manager, max_rows=max_rows)
        return AgentRuntime(
            manager=manager,
            executor=executor,
            guard=Guard(),
            router=router,
            orchestrator=Orchestrator(
                executor=executor,
                router=router,
                registry=registry,
                metric_resolver=resolver,
                compiler=compiler,
                reconciler=Reconciler(),
                harness=harness,
                guard=Guard(),
            ),
            catalog=catalog,
        )
    except Exception:
        manager.dispose()
        raise


@dataclass(slots=True)
class _RunRecord:
    run_id: str
    owner_id: str
    question: str
    session_id: str
    clarification_of: str | None
    created_at: str
    events: list[dict[str, object]] = field(default_factory=list)
    envelope: AnswerEnvelope | None = None
    terminal: bool = False


class RunNotFoundError(KeyError):
    """The requested run id is unknown."""


class RunStore:
    """Thread-safe event log and result store for active and completed runs."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._runs: dict[str, _RunRecord] = {}

    def create(
        self,
        run_id: str,
        *,
        owner_id: str,
        question: str,
        session_id: str,
        clarification_of: str | None,
    ) -> None:
        with self._condition:
            if run_id in self._runs:
                raise ValueError(f"duplicate run id: {run_id}")
            self._runs[run_id] = _RunRecord(
                run_id=run_id,
                owner_id=owner_id,
                question=question,
                session_id=session_id,
                clarification_of=clarification_of,
                created_at=_utc_now(),
            )

    def exists(self, run_id: str) -> bool:
        with self._condition:
            return run_id in self._runs

    def owner_id(self, run_id: str) -> str:
        with self._condition:
            return self._require(run_id).owner_id

    def append(
        self,
        run_id: str,
        event_type: str,
        **fields: object,
    ) -> dict[str, object]:
        with self._condition:
            record = self._require(run_id)
            event: dict[str, object] = {
                "type": event_type,
                "seq": len(record.events) + 1,
                "run_id": run_id,
                **fields,
            }
            record.events.append(event)
            if event_type in _TERMINAL_EVENTS:
                record.terminal = True
            self._condition.notify_all()
            return event

    def complete(self, run_id: str, envelope: AnswerEnvelope) -> None:
        with self._condition:
            record = self._require(run_id)
            record.envelope = envelope
            record.terminal = True
            self._condition.notify_all()

    def wait_for_envelope(
        self,
        run_id: str,
        *,
        timeout: float = 15.0,
    ) -> AnswerEnvelope | None:
        deadline = time.monotonic() + timeout
        with self._condition:
            record = self._require(run_id)
            while record.envelope is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return record.envelope

    def events(self, run_id: str, *, after: int = 0) -> tuple[dict[str, object], ...]:
        with self._condition:
            record = self._require(run_id)
            return tuple(
                event for event in record.events if int(event["seq"]) > after
            )

    def stream(
        self,
        run_id: str,
        *,
        after: int = 0,
        keepalive_seconds: float = 15.0,
    ) -> Iterator[dict[str, object] | None]:
        last = after
        while True:
            with self._condition:
                record = self._require(run_id)
                while (
                    not any(int(event["seq"]) > last for event in record.events)
                    and not record.terminal
                ):
                    if not self._condition.wait(timeout=keepalive_seconds):
                        break
                pending = [
                    event
                    for event in record.events
                    if int(event["seq"]) > last
                ]
                terminal = record.terminal

            if pending:
                for event in pending:
                    last = int(event["seq"])
                    yield event
                continue
            if terminal:
                return
            yield None

    def _require(self, run_id: str) -> _RunRecord:
        record = self._runs.get(run_id)
        if record is None:
            raise RunNotFoundError(run_id)
        return record


class RunService:
    """Coordinates background runs, evidence, facts, and answer assembly."""

    def __init__(
        self,
        runtime_factory: Callable[[], AgentRuntime],
        *,
        store: RunStore | None = None,
        ledger: EvidenceLedger | None = None,
        fact_checker: FactChecker | None = None,
        narrator: Callable[[OrchestrationResult, Ledger], str | None] | None = None,
        logger: TraceLogger | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._runtime_factory = runtime_factory
        self._store = store or RunStore()
        self._ledger = ledger or EvidenceLedger()
        self._fact_checker = fact_checker or FactChecker()
        self._narrator = narrator or _default_narrative
        self._logger = logger
        self._clock = clock or time.monotonic
        self._runtime: AgentRuntime | None = None
        self._runtime_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._threads_lock = threading.Lock()

    @property
    def store(self) -> RunStore:
        return self._store

    def submit(
        self,
        question: str,
        *,
        owner_id: str,
        session_id: str = "anonymous",
        clarification_of: str | None = None,
    ) -> str:
        cleaned = question.strip()
        if not cleaned:
            raise ValueError("question must not be empty")
        if not owner_id.strip():
            raise ValueError("owner_id must not be empty")
        if clarification_of is not None:
            try:
                clarification_owner = self._store.owner_id(clarification_of)
            except RunNotFoundError:
                raise
            if clarification_owner != owner_id:
                raise RunNotFoundError(clarification_of)
        run_id = uuid.uuid4().hex
        self._store.create(
            run_id,
            owner_id=owner_id,
            question=cleaned,
            session_id=session_id,
            clarification_of=clarification_of,
        )
        thread = threading.Thread(
            target=self._execute,
            args=(run_id, cleaned),
            name=f"ds-agent-run-{run_id[:8]}",
            daemon=True,
        )
        with self._threads_lock:
            self._threads.append(thread)
        thread.start()
        return run_id

    def close(self) -> None:
        with self._threads_lock:
            threads = list(self._threads)
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=5.0)
        with self._runtime_lock:
            runtime = self._runtime
            self._runtime = None
        if runtime is not None:
            runtime.close()

    def _execute(self, run_id: str, question: str) -> None:
        started = self._clock()
        try:
            runtime = self._get_runtime()
            guard_started = self._clock()
            self._emit(
                run_id,
                "step_started",
                step="1",
                component="Guard",
                at=_utc_now(),
            )
            guard = runtime.guard.check(question)
            self._emit(
                run_id,
                "step_finished",
                step="1",
                component="Guard",
                status="ok" if guard.passed else "failed",
                duration_ms=_elapsed_ms(guard_started, self._clock()),
                summary=(
                    "The request passed the ingress guard."
                    if guard.passed
                    else "The request was blocked by the ingress guard."
                ),
            )

            route_started = self._clock()
            self._emit(
                run_id,
                "step_started",
                step="2",
                component="Router and Extractor",
                at=_utc_now(),
            )
            route = runtime.router.route(question, guard_result=guard)
            self._emit(
                run_id,
                "step_finished",
                step="2",
                component="Router and Extractor",
                status="ok",
                duration_ms=_elapsed_ms(route_started, self._clock()),
                summary=f"Routed as {route.primary_route} with confidence {route.confidence:.2f}.",
            )

            if route.primary_route in _GOVERNED_ROUTES:
                self._emit(
                    run_id,
                    "step_started",
                    step="7",
                    component="SQL Compiler",
                    at=_utc_now(),
                )
                outcome = runtime.orchestrator.run(
                    question,
                    guard_result=guard,
                    route_result=route,
                )
                query_status = "ok" if outcome.status != "error" else "failed"
                query_duration = sum(
                    query.duration_ms for query in outcome.queries
                )
                self._emit(
                    run_id,
                    "step_finished",
                    step="7",
                    component="SQL Compiler",
                    status=query_status,
                    duration_ms=query_duration,
                    summary="The governed SQL path finished.",
                )
                self._emit(
                    run_id,
                    "step_started",
                    step="9",
                    component="Executor",
                    at=_utc_now(),
                )
                self._emit(
                    run_id,
                    "step_finished",
                    step="9",
                    component="Executor",
                    status=query_status,
                    duration_ms=query_duration,
                    summary=(
                        f"Completed {len(outcome.queries)} query(s) and "
                        f"{len(outcome.analyst_outputs)} analyst module(s)."
                    ),
                )
            else:
                outcome = runtime.orchestrator.run(
                    question,
                    guard_result=guard,
                    route_result=route,
                )

            if outcome.analyst_outputs:
                self._emit(
                    run_id,
                    "step_started",
                    step="11",
                    component="Analysts",
                    at=_utc_now(),
                )
                self._emit(
                    run_id,
                    "step_finished",
                    step="11",
                    component="Analysts",
                    status="ok",
                    duration_ms=0,
                    summary=(
                        f"Completed {len(outcome.analyst_outputs)} typed "
                        "analyst module(s)."
                    ),
                )

            ledger_started = self._clock()
            self._emit(
                run_id,
                "step_started",
                step="12",
                component="Evidence Ledger",
                at=_utc_now(),
            )
            ledger = self._ledger.build(run_id, outcome)
            self._emit(
                run_id,
                "step_finished",
                step="12",
                component="Evidence Ledger",
                status="ok",
                duration_ms=_elapsed_ms(ledger_started, self._clock()),
                summary=f"Approved {len(ledger.claims)} evidence claim(s).",
            )

            fact_started = self._clock()
            self._emit(
                run_id,
                "step_started",
                step="14",
                component="Fact Checker",
                at=_utc_now(),
            )
            narrative = self._narrator(outcome, ledger)
            fact_check = self._fact_checker.verify(narrative, ledger)
            self._emit(
                run_id,
                "step_finished",
                step="14",
                component="Fact Checker",
                status="ok",
                duration_ms=_elapsed_ms(fact_started, self._clock()),
                summary=(
                    "The narrative passed numeric fact checking."
                    if fact_check.passed
                    else (
                        f"Removed {len(fact_check.violations)} sentence(s) "
                        "with unapproved numbers."
                    )
                ),
            )

            envelope = build_answer_envelope(
                run_id=run_id,
                outcome=outcome,
                guard=guard,
                ledger=ledger,
                fact_check=fact_check,
                catalog_version=runtime.catalog_version,
            )
            self._write_trace(run_id, question, guard, outcome, ledger, fact_check)

            if envelope.clarification is not None:
                self._emit(
                    run_id,
                    "clarify",
                    what_understood=envelope.clarification.what_understood,
                    what_needs_clarification=(
                        envelope.clarification.what_needs_clarification
                    ),
                )
            if envelope.status == "error":
                self._emit(
                    run_id,
                    "error",
                    error={
                        "code": "internal",
                        "message": outcome.reason,
                        "retriable": False,
                    },
                )
            else:
                self._emit(
                    run_id,
                    "answer",
                    status=envelope.status,
                )
            self._store.complete(run_id, envelope)
        except Exception as exc:  # pragma: no cover - defensive boundary
            envelope = _error_envelope(
                run_id, f"Run failed: {mask_sensitive(str(exc))}"
            )
            self._emit(
                run_id,
                "error",
                error={
                    "code": "internal",
                    "message": "The run failed inside the agent service.",
                    "retriable": False,
                },
            )
            self._store.complete(run_id, envelope)

    def _get_runtime(self) -> AgentRuntime:
        with self._runtime_lock:
            if self._runtime is None:
                self._runtime = self._runtime_factory()
            return self._runtime

    def _emit(
        self,
        run_id: str,
        event_type: str,
        **fields: object,
    ) -> dict[str, object]:
        return self._store.append(run_id, event_type, **fields)

    def _write_trace(
        self,
        run_id: str,
        question: str,
        guard: GuardResult,
        outcome: OrchestrationResult,
        ledger: Ledger,
        fact_check: FactCheckResult,
    ) -> None:
        if self._logger is None:
            return
        try:
            self._logger.log(
                question=question,
                guard=guard,
                validation=outcome.validation,
                execution=outcome.execution,
                candidate=outcome.candidate,
                reconciliation=outcome.reconciliation,
                orchestration=outcome,
                ledger=ledger,
                fact_check=fact_check,
                run_id=run_id,
            )
        except Exception:
            return


def build_answer_envelope(
    *,
    run_id: str,
    outcome: OrchestrationResult,
    guard: GuardResult,
    ledger: Ledger,
    fact_check: FactCheckResult,
    catalog_version: str,
) -> AnswerEnvelope:
    status = _run_status(outcome.status)
    conclusion = (
        fact_check.repaired_narrative or _fallback_narrative(outcome, ledger)
        if status == "answered"
        else (
            outcome.reason
            if status == "insufficient_evidence"
            else None
        )
    )
    return AnswerEnvelope(
        run_id=run_id,
        status=status,
        route=RouteSummary(
            labels=outcome.router.route_labels,
            confidence=outcome.confidence,
            reason=outcome.router.reason,
        ),
        conclusion=conclusion,
        scope=_scope(outcome),
        evidence=_evidence(outcome, ledger),
        claims=ledger.claims,
        method=_method(outcome),
        queries=_queries(outcome),
        caveats=_caveats(outcome),
        causal_boundary_note=_causal_boundary_note(outcome),
        next_actions=(),
        clarification=outcome.clarification,
        refusal=(
            RefusalBlock(missing=(outcome.reason,))
            if outcome.status == "refused"
            else None
        ),
        block=(
            BlockBlock(
                reason=guard.reason or "unsafe",
                detail=guard.matched_rule or guard.reason or "Blocked by guard.",
            )
            if outcome.status == "blocked"
            else None
        ),
        run_metrics=RunMetrics(
            latency_ms=outcome.latency_ms,
            tokens=outcome.budget.tokens,
            queries=outcome.budget.queries,
            rows=sum(execution.row_count for execution in outcome.executions),
            retries=0,
        ),
        provenance=Provenance(
            model_name="none" if not outcome.router.signals.model else "ollama",
            model_version="",
            commit=os.environ.get("GIT_COMMIT", ""),
            snapshot_id="brazil-ecommerce",
            catalog_version=catalog_version,
            timestamp=_utc_now(),
        ),
    )


def _fallback_narrative(
    outcome: OrchestrationResult,
    ledger: Ledger,
) -> str | None:
    narrative = _default_narrative(outcome, ledger)
    if narrative is not None:
        return narrative
    tokens = [
        number.token
        for claim in ledger.claims
        for number in claim.numbers
    ]
    if not tokens:
        return None
    return "The evidence ledger supports " + ", ".join(tokens[:4]) + "."


def _run_status(status: str) -> RunStatus:
    mapping: dict[str, RunStatus] = {
        "ok": "answered",
        "clarification": "clarify",
        "refused": "refused",
        "blocked": "blocked",
        "insufficient_evidence": "insufficient_evidence",
        "error": "error",
    }
    return mapping.get(status, "error")


def _scope(outcome: OrchestrationResult) -> EnvelopeScope:
    slots = outcome.router.slots
    period = slots.time.current
    return EnvelopeScope(
        metric=slots.metric_terms[0] if slots.metric_terms else None,
        window=(
            f"{period.start.isoformat()}/{period.end.isoformat()}"
            if period is not None
            else None
        ),
        filters=tuple(
            f"{item.term}={item.value_phrase}" for item in slots.filters
        ),
        grain=slots.time.grain,
        governed=(
            outcome.candidate is not None
            and outcome.candidate.origin == "compiler"
        ),
    )


def _evidence(outcome: OrchestrationResult, ledger: Ledger) -> tuple[EvidenceBlock, ...]:
    blocks: list[EvidenceBlock] = []
    for execution in outcome.executions:
        claim_ids = tuple(
            claim.claim_id
            for claim in ledger.claims
            if claim.source.id == execution.query_id
        )
        blocks.append(
            EvidenceBlock(
                module="lookup",
                output={
                    "query_id": execution.query_id,
                    "columns": [
                        {"name": column.name, "type": column.type}
                        for column in execution.columns
                    ],
                    "rows": execution.rows or (),
                    "row_count": execution.row_count,
                    "truncated": execution.truncated,
                },
                source_claims=claim_ids,
            )
        )
    for output in outcome.analyst_outputs:
        claim_ids = tuple(
            claim.claim_id
            for claim in ledger.claims
            if claim.source.id in output.sources
        )
        blocks.append(
            EvidenceBlock(
                module=output.module,
                output=output.model_dump(mode="json"),
                source_claims=claim_ids,
            )
        )
    return tuple(blocks)


def _method(outcome: OrchestrationResult) -> tuple[MethodStep, ...]:
    steps: list[MethodStep] = []
    if outcome.queries:
        steps.append(
            MethodStep(
                name="governed_sql",
                params={"queries": len(outcome.queries)},
            )
        )
    steps.extend(
        MethodStep(name=output.module, params=output.parameters)
        for output in outcome.analyst_outputs
    )
    return tuple(steps)


def _queries(outcome: OrchestrationResult) -> tuple[EnvelopeQueryRecord, ...]:
    rows_scanned = {
        execution.query_id: execution.rows_scanned
        for execution in outcome.executions
    }
    origin = outcome.candidate.origin if outcome.candidate is not None else "compiler"
    return tuple(
        EnvelopeQueryRecord(
            query_id=query.query_id,
            sql=query.sql,
            status=(
                "ok"
                if query.status in {"ok", "truncated"}
                else "error"
            ),
            duration_ms=query.duration_ms,
            rows_scanned=rows_scanned.get(query.query_id),
            origin=origin,
            validation_mode="enterprise",
        )
        for query in outcome.queries
    )


def _caveats(outcome: OrchestrationResult) -> tuple[str, ...]:
    caveats: list[str] = []
    if outcome.reconciliation is not None:
        caveats.extend(outcome.reconciliation.caveats)
    if outcome.status == "insufficient_evidence" and outcome.reason:
        caveats.append(outcome.reason)
    return tuple(dict.fromkeys(caveats))


def _causal_boundary_note(outcome: OrchestrationResult) -> str | None:
    for output in outcome.analyst_outputs:
        if output.module != "driver" or not isinstance(output.result, DriverResult):
            continue
        for assumption in output.assumptions:
            if "not causal" in assumption.lower():
                return assumption
        return (
            "Driver analysis is associational evidence, not proof that a "
            "dimension caused the change."
        )
    return None


def _default_narrative(
    outcome: OrchestrationResult,
    ledger: Ledger,
) -> str | None:
    if outcome.status != "ok":
        return None
    for output in outcome.analyst_outputs:
        if isinstance(output.result, AnomalyResult):
            result = output.result
            phrase = (
                "within the normal range"
                if result.verdict == "within_normal_range"
                else "outside the normal range"
            )
            return (
                f"The selected period recorded {format_number(result.actual)} "
                f"versus an expected {format_number(result.expected)}; the "
                f"result is {phrase}."
            )
        if isinstance(output.result, DriverResult) and output.result.drivers:
            top = output.result.drivers[0]
            return (
                f"The largest contributor was {top.value}, with an attributed "
                f"change of {format_number(top.contribution)}."
            )
    if len(outcome.executions) >= 2 and (
        getattr(outcome.router, "intent_label", None) == "Comparative"
        or any(
            getattr(q, "purpose", "") in ("current_lookup", "comparison_lookup")
            for q in getattr(outcome, "queries", ())
        )
    ):
        exec1 = outcome.executions[0]
        exec2 = outcome.executions[1]
        raw1 = exec1.rows[0][0] if exec1.rows and exec1.rows[0] else None
        raw2 = exec2.rows[0][0] if exec2.rows and exec2.rows[0] else None
        if (
            raw1 is not None
            and raw2 is not None
            and not isinstance(raw1, bool)
            and not isinstance(raw2, bool)
            and isinstance(raw1, (int, float))
            and isinstance(raw2, (int, float))
        ):
            val1 = float(raw1)
            val2 = float(raw2)
            diff = val1 - val2
            pct = (diff / val2 * 100.0) if val2 != 0 else 0.0
            slots = getattr(outcome.router, "slots", None)
            metric_term = (
                slots.metric_terms[0]
                if slots and slots.metric_terms
                else "metric"
            )
            metric_name = metric_term.replace("_", " ")
            t1 = slots.time.current if slots and slots.time else None
            t2 = slots.time.comparison if slots and slots.time else None
            period1_str = str(t1.start.year) if t1 else "the current period"
            period2_str = str(t2.start.year) if t2 else "the comparison period"
            change_word = "an increase" if diff >= 0 else "a decrease"
            return (
                f"The governed {metric_name} in {period1_str} was {format_number(val1)} "
                f"compared to {format_number(val2)} in {period2_str}, representing "
                f"{change_word} of {format_number(abs(diff))} ({format_number(abs(round(pct, 2)))}%)."
            )
    for execution in reversed(outcome.executions):
        for row in execution.rows or ():
            for value in row:
                if isinstance(value, bool):
                    continue
                if isinstance(value, (int, float)):
                    return f"The governed result is {format_number(float(value))}."
    return None


def _error_envelope(run_id: str, reason: str) -> AnswerEnvelope:
    return AnswerEnvelope(
        run_id=run_id,
        status="error",
        route=RouteSummary(
            labels=("blocked",),
            confidence=0.0,
            reason=reason,
        ),
        conclusion=None,
        caveats=(reason,),
        run_metrics=RunMetrics(
            latency_ms=0,
            tokens=0,
            queries=0,
            rows=0,
            retries=0,
        ),
        provenance=Provenance(
            snapshot_id="brazil-ecommerce",
            timestamp=_utc_now(),
        ),
    )


def _elapsed_ms(started: float, finished: float) -> int:
    return max(0, int(round((finished - started) * 1_000)))


def format_sse_event(event: dict[str, object]) -> str:
    import json

    body = json.dumps(event, ensure_ascii=False, default=str, separators=(",", ":"))
    lines = [
        f"id: {event['seq']}",
        f"event: {event['type']}",
        f"data: {body}",
    ]
    return "\n".join(lines) + "\n\n"


__all__ = [
    "AgentRuntime",
    "RunNotFoundError",
    "RunService",
    "RunStore",
    "build_answer_envelope",
    "build_runtime",
    "format_sse_event",
]
