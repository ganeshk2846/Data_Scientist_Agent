"""The V2 understanding-and-planning pipeline (Track 3).

    guard -> intent + entities -> grounding -> (clarify | plan)
          -> execute -> sanity check / re-plan (<= 2) -> compose

The guard, the SQL validator and the read-only gateway stay in the path for
every query. Every stage emits an SSE event; the V1 ``step_started`` /
``step_finished`` events are emitted too, with the V1 step ids and component
names, so the existing frontend keeps rendering a V2 run unchanged.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import clarify
import followup
from composer import compose
from contracts.models import BlockBlock, Period
from contracts.v2 import (
    AnswerEnvelopeV2,
    ClarificationRequest,
    ContextState,
    Entities,
    IntentResult,
    IntentSignals,
    ResolvedQuestion,
    ScoredIntent,
)
from executor_v2 import Execution, PlanExecutor
from gateway.executor import QueryExecutor
from grounding import Grounded, Grounder
from intent import DEFAULT_ANCHOR, EntityExtractor, IntentExtractor, ValueIndex
from planner import Capabilities, Planner, PlanValidationError
from sanity import MAX_REPLANS, actionable, check
from semantic.metrics_v2 import all_metrics
from semantic.versioning import catalog_version as current_catalog_version
from sql.compiler import SQLCompiler
from tools.registry import Warehouse

Emit = Callable[..., None]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class ClarificationReply:
    """A reply to an earlier V2 clarification (CL-6: an option id is applied deterministically)."""

    original_question: str
    request: ClarificationRequest
    of_run_id: str
    option_id: str | None = None
    text: str | None = None


@dataclass
class PipelineOutcome:
    envelope: AnswerEnvelopeV2
    question: str
    clarification: ClarificationRequest | None
    replans: int = 0
    issues: list[str] = field(default_factory=list)
    #: Track 4: how the message was read against the session context.
    rewrite: followup.Rewrite | None = None
    reset: bool = False


class PipelineV2:
    def __init__(self, *, guard, catalog, manager=None, executor=None, client: object | None = None,
                 anchor: str | None = None, max_rows: int = 200_000) -> None:
        self.guard = guard
        self.catalog = catalog
        self.manager = manager
        self.client = client
        self.registry = all_metrics()
        self.catalog_version = current_catalog_version()
        query_executor = executor or QueryExecutor(manager, max_rows=max_rows)
        self._executor = query_executor
        self.compiler = SQLCompiler(catalog, dialect="sqlite")
        tables = frozenset(catalog.table_names)
        self.anchor = anchor or self._last_complete(tables) or DEFAULT_ANCHOR
        values = ValueIndex()
        if "product_category_translation" in tables:
            try:
                rows = self._warehouse().run(
                    "SELECT product_category_name, product_category_name_english FROM product_category_translation LIMIT 500",
                    purpose="value index", tables=("product_category_translation",))
                values.add_categories(rows.rows or ())
            except Exception:  # the static index still applies
                pass
        self.extractor = IntentExtractor(entities=EntityExtractor(self.registry, values=values, anchor=self.anchor), client=client, anchor=self.anchor)
        self.grounder = Grounder(self.registry, anchor=self.anchor, available_tables=tables)
        self.capabilities = self._capabilities(tables)
        self.planner = Planner(self.capabilities)

    # ------------------------------------------------------------------ #

    def _warehouse(self) -> Warehouse:
        factory = self.manager.engine.connect if self.manager is not None else None
        return Warehouse(executor=self._executor, compiler=self.compiler, catalog=self.catalog, connection_factory=factory,
                         catalog_version=self.catalog_version, anchor=self.anchor, registry=self.registry)

    def _last_complete(self, tables: frozenset[str]) -> str | None:
        if self.manager is None or "orders" not in tables:
            return None
        try:
            from semantic.completeness import assess_metric

            with self.manager.engine.connect() as connection:
                report = assess_metric(connection, self.registry.require("order_count"), catalog_version=self.catalog_version)
            return report.last_complete_period
        except Exception:
            return None

    def _capabilities(self, tables: frozenset[str]) -> Capabilities:
        analytical = {"analytical_series", "analytical_anomalies", "analytical_forecasts"} <= tables
        kpis: frozenset[str] = frozenset()
        horizon = 6
        if analytical:
            try:
                warehouse = self._warehouse()
                rows = warehouse.run("SELECT DISTINCT kpi FROM analytical_series LIMIT 500", purpose="capabilities", tables=("analytical_series",))
                kpis = frozenset(str(row[0]) for row in rows.rows or ())
                count = warehouse.run("SELECT COUNT(*) FROM analytical_forecasts WHERE kpi = 'revenue' AND dimension IS NULL LIMIT 1",
                                      purpose="capabilities", tables=("analytical_forecasts",))
                horizon = int(count.rows[0][0]) if count.rows else 6
            except Exception:
                analytical = False
        synthetic = {"marketing_spend", "delivery_sla", "price_history", "customer_segments", "inventory_daily"} <= tables
        return Capabilities(analytical=analytical, synthetic=synthetic, analytical_kpis=kpis, forecast_horizon=horizon or 6,
                            anchor=self.anchor, history_start="2016-10")

    # ------------------------------------------------------------------ #

    def run(self, question: str, *, run_id: str | None = None, emit: Emit | None = None,
            reply: ClarificationReply | None = None, context: ContextState | None = None) -> PipelineOutcome:
        """Run one turn. ``context`` is the session's stored context; without it every question is cold."""
        run_id = run_id or uuid.uuid4().hex
        emit = emit or (lambda *args, **kwargs: None)
        started = time.perf_counter()
        warehouse = self._warehouse()

        # Step 1 - the existing ingress guard (unchanged).
        emit("step_started", step="1", component="Guard", at=_now())
        guard = self.guard.check(question)
        emit("step_finished", step="1", component="Guard", status="ok" if guard.passed else "failed", duration_ms=0,
             summary="The request passed the ingress guard." if guard.passed else "The request was blocked by the ingress guard.")
        if not guard.passed:
            return self._blocked(run_id, question, guard, started)

        # Track 4 - read the message against the last turns of the session (deterministic, no model).
        rewrite: followup.Rewrite | None = None
        if reply is None:
            try:
                rewrite = followup.rewrite(question, context, extractor=self.extractor, registry=self.registry, anchor=self.anchor)
            except Exception:  # context must never break a run: fall back to a cold question
                rewrite = None
        if rewrite is not None and rewrite.kind != "cold":
            emit("context", mode=rewrite.kind, shape=rewrite.shape, interpreted_as=rewrite.effective_text,
                 inherited_fields=list(rewrite.inherited_fields), prior_turn_id=rewrite.prior_turn_id)
        reset = rewrite is not None and rewrite.kind == "reset"
        if reset and not rewrite.text:
            outcome = self._reset_ack(run_id, question, started, emit)
            outcome.rewrite, outcome.reset = rewrite, True
            return outcome

        # Step 2 - intent, entities and grounding.
        emit("step_started", step="2", component="Router and Extractor", at=_now())
        patch: dict[str, Any] = {}
        round_number = 1
        of_run_id = None
        notes: list[str] = []
        text = rewrite.text if reset else question
        if rewrite is not None and rewrite.kind == "followup":
            text = rewrite.effective_text or question
            patch = dict(rewrite.patch)
        if reply is not None:
            round_number = reply.request.round + 1
            of_run_id = reply.of_run_id
            option_id = reply.option_id or (clarify.option_by_label(reply.request, reply.text) if reply.text else None)
            if option_id is not None or reply.text is None:
                patch, note = clarify.patch_for(reply.request, option_id)
                notes.append(note)
                text = patch.pop("effective_text", None) or reply.original_question
            else:
                text = f"{reply.original_question} {reply.text}"
        extraction = followup.promote_bare_metric(self.extractor.extract(text))
        emit("intent", intents=[{"intent": item.intent, "score": item.score, "span": item.span} for item in extraction.intents],
             confidence=extraction.confidence, reason=extraction.reason,
             entities=extraction.entities.model_dump(mode="json", exclude_none=True),
             model_consulted=extraction.signals.model is not None)
        if rewrite is not None and rewrite.kind == "clarify" and rewrite.clarification is not None:
            # Ambiguous even with context (scope.md U2, U4, V10): one question with complete options.
            grounded = Grounded(self.grounder._clarify_intent(extraction, rewrite.clarification), None, rewrite.clarification, (), ())
        else:
            grounded = self.grounder.ground(extraction, patch=patch, round_number=round_number, of_run_id=of_run_id)
        if grounded.clarification is not None and round_number > clarify.MAX_ROUNDS:
            default_patch, note = clarify.patch_for(grounded.clarification, None)
            if "effective_text" in default_patch:
                notes.append(note)
                extraction = self.extractor.extract(default_patch["effective_text"])
                grounded = self.grounder.ground(extraction, force_defaults=True)
        if notes and grounded.resolved is not None:
            grounded = Grounded(grounded.intent, grounded.resolved.model_copy(update={"assumptions": (*grounded.resolved.assumptions, *notes)}),
                                None, grounded.special, (*grounded.assumptions, *notes))
        if rewrite is not None and rewrite.kind == "followup" and grounded.resolved is not None and rewrite.inherited_fields:
            # RQ-2: inheritance is never silent - the fields and the rewritten question are on the envelope.
            resolved_followup = followup.apply_to_resolved(grounded.resolved, rewrite, raw_text=question)
            grounded = Grounded(grounded.intent, resolved_followup, None, grounded.special,
                                (*grounded.assumptions, *([rewrite.note] if rewrite.note else ())))
        emit("grounding", status="clarify" if grounded.needs_clarification else "grounded",
             metric_id=grounded.resolved.metric_id if grounded.resolved else None,
             assumptions=list(grounded.assumptions),
             slot=grounded.clarification.slot if grounded.clarification else None)
        emit("step_finished", step="2", component="Router and Extractor", status="ok", duration_ms=_ms(started),
             summary=f"Intent {' + '.join(grounded.intent.intent_names)} with confidence {grounded.intent.confidence:.2f}.")

        if grounded.needs_clarification:
            request = grounded.clarification
            emit("clarify", what_understood=request.what_understood, what_needs_clarification=request.what_needs_clarification,
                 question=request.question, slot=request.slot, round=request.round,
                 options=[{"option_id": option.option_id, "label": option.label, "detail": option.detail} for option in request.options],
                 default_option_id=request.default_assumption.option_id)
            envelope, _ = compose(run_id=run_id, intent=grounded.intent, resolved=None, plan=None, results={}, reports={}, queries=[],
                                  clarification=request, catalog_version=self.catalog_version, latency_ms=_ms(started))
            emit("compose", status=envelope.status, claims=0)
            return PipelineOutcome(envelope, text if rewrite is None or rewrite.kind != "clarify" else question, request,
                                   rewrite=rewrite, reset=reset)

        intent, resolved = grounded.intent, grounded.resolved
        assert resolved is not None
        execution, plan_issues, replans, resolved = self._plan_and_execute(intent, resolved, grounded.special, warehouse, run_id, emit)
        outcome = self._compose(run_id, text, intent, resolved, execution, warehouse, plan_issues, replans, started, emit)
        outcome.rewrite, outcome.reset = rewrite, reset
        return outcome

    # ------------------------------------------------------------------ #

    def _plan_and_execute(self, intent: IntentResult, resolved: ResolvedQuestion, special: tuple[str, ...], warehouse: Warehouse,
                          run_id: str, emit: Emit) -> tuple[Execution | None, list[str], int, ResolvedQuestion]:
        avoid_analytical = False
        replans = 0
        leftover: list[str] = []
        execution: Execution | None = None
        current = resolved
        for attempt in range(MAX_REPLANS + 1):
            try:
                plan = self.planner.plan(intent, current, special=special, attempt=attempt, avoid_analytical=avoid_analytical)
            except (PlanValidationError, ValueError) as exc:
                leftover.append(f"The plan could not be built: {exc}")
                return execution, leftover, replans, current
            emit("plan", plan_id=plan.plan_id, attempt=attempt, source=plan.source,
                 steps=[{"step_id": step.step_id, "tool": step.tool, "depends_on": list(step.depends_on), "purpose": step.purpose,
                         "optional": step.optional} for step in plan.steps],
                 intents_covered=list(plan.intents_covered),
                 intents_dropped=[item.model_dump() for item in plan.intents_dropped])
            emit("step_started", step="9", component="Executor", at=_now())
            execution = PlanExecutor(warehouse, emit=emit, seed=0, run_id=run_id).execute(plan)
            emit("step_finished", step="9", component="Executor", status="ok" if execution.results else "failed",
                 duration_ms=execution.duration_ms,
                 summary=f"Completed {len(execution.results)} plan step(s) and {execution.engine_calls} engine call(s).")
            if execution.engine_calls:
                emit("step_started", step="11", component="Analysts", at=_now())
                emit("step_finished", step="11", component="Analysts", status="ok", duration_ms=0,
                     summary=f"Completed {execution.engine_calls} typed engine step(s).")
            issues = check(execution, metric=current.metric_id)
            fixable = actionable(issues)
            if not fixable or attempt == MAX_REPLANS:
                leftover = [f"Sanity check ({issue.kind}) on {issue.step_id}: {issue.message}" for issue in issues]
                break
            replans += 1
            fixes = {issue.fix for issue in fixable}
            if "live_engine" in fixes:
                avoid_analytical = True
            if "widen_window" in fixes and current.period is not None:
                anchor = _month(self.anchor)
                widened = Period(start=_add_months(anchor, -11), end=_add_months(anchor, 1))
                note = f"The first plan found no usable rows for {current.period.start:%Y-%m}; it was re-run on the last 12 complete months."
                if widened != current.period:
                    current = current.model_copy(update={"period": widened, "assumptions": (*current.assumptions, note)})
                else:
                    avoid_analytical = True
            if "drop_dimension" in fixes and current.dimensions:
                current = current.model_copy(update={"dimensions": (), "assumptions": (*current.assumptions,
                                                                                         "The breakdown was too large and was dropped to the total.")})
            emit("replan", attempt=attempt + 1, issues=[{"step_id": issue.step_id, "kind": issue.kind, "fix": issue.fix} for issue in fixable])
        return execution, leftover, replans, current

    def _compose(self, run_id, text, intent, resolved, execution, warehouse, issues, replans, started, emit) -> PipelineOutcome:
        emit("step_started", step="12", component="Evidence Ledger", at=_now())
        envelope, ledger = compose(
            run_id=run_id, intent=intent, resolved=resolved, plan=execution.plan if execution else None,
            results=execution.results if execution else {}, reports=execution.reports if execution else {},
            queries=warehouse.queries, clarification=None, catalog_version=self.catalog_version, latency_ms=_ms(started),
            extra_caveats=tuple(issues), model_used=bool(intent.signals.model and intent.signals.model.proposed),
        )
        emit("step_finished", step="12", component="Evidence Ledger", status="ok", duration_ms=0,
             summary=f"Approved {len(ledger.claims)} evidence claim(s).")
        emit("step_started", step="14", component="Fact Checker", at=_now())
        emit("step_finished", step="14", component="Fact Checker", status="ok", duration_ms=0,
             summary="The narrative passed numeric fact checking." if envelope.conclusion else "No narrative was produced.")
        emit("compose", status=envelope.status, claims=len(ledger.claims), replans=replans)
        return PipelineOutcome(envelope, text, None, replans=replans, issues=issues)

    def _reset_ack(self, run_id: str, question: str, started: float, emit: Emit) -> PipelineOutcome:
        """A bare "new topic": the context is cleared by the caller; offer fresh starting points."""
        request = clarify.build(slot="intent", understood="You started a new topic, so earlier questions in this session are no longer used.",
                                needs="What would you like to ask?", question="Context cleared. What would you like to look at",
                                choices=clarify.question_choices([("What data do you have?", "What data do you have?"),
                                                                  ("Revenue trend", "How does revenue trend look today?"),
                                                                  ("Forecast revenue", "Forecast revenue for the next 3 months")]),
                                rationale="Listing the data held is always a safe starting point.")
        intent = IntentResult(intents=(ScoredIntent(intent="clarify", score=1.0, span=question[:200]),), entities=Entities(),
                              signals=IntentSignals(), confidence=1.0, reason="Topic reset: the session context was cleared.",
                              clarification=request, prd_intent_label="Descriptive")
        emit("clarify", what_understood=request.what_understood, what_needs_clarification=request.what_needs_clarification,
             question=request.question, slot=request.slot, round=request.round,
             options=[{"option_id": option.option_id, "label": option.label, "detail": option.detail} for option in request.options],
             default_option_id=request.default_assumption.option_id)
        envelope, _ = compose(run_id=run_id, intent=intent, resolved=None, plan=None, results={}, reports={}, queries=[],
                              clarification=request, catalog_version=self.catalog_version, latency_ms=_ms(started))
        emit("compose", status=envelope.status, claims=0)
        return PipelineOutcome(envelope, question, request)

    def _blocked(self, run_id: str, question: str, guard, started: float) -> PipelineOutcome:
        request = clarify.build(slot="intent", understood="The request was blocked by the ingress guard.",
                                needs="Ask an analytics question instead.", question="Would one of these help",
                                choices=clarify.question_choices([("What data do you have?", "What data do you have?"),
                                                                  ("Revenue trend", "How does revenue trend look today?")]),
                                rationale="Listing the data held is always safe.")
        intent = IntentResult(intents=(ScoredIntent(intent="clarify", score=0.0),), entities=Entities(), signals=IntentSignals(),
                              confidence=0.0, reason="Blocked by the ingress guard.", clarification=request, prd_intent_label="Descriptive")
        envelope, _ = compose(run_id=run_id, intent=intent, resolved=None, plan=None, results={}, reports={}, queries=[],
                              clarification=None, catalog_version=self.catalog_version, latency_ms=_ms(started),
                              blocked=BlockBlock(reason=guard.reason or "unsafe", detail=guard.matched_rule or guard.reason or "Blocked by guard."))
        return PipelineOutcome(envelope, question, None)


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _month(text: str):
    from datetime import date

    year, month = (int(part) for part in text[:7].split("-"))
    return date(year, month, 1)


def _add_months(start, months: int):
    from datetime import date

    index = start.year * 12 + start.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


__all__ = ["ClarificationReply", "PipelineOutcome", "PipelineV2"]
