"""Frozen V2 contracts for the 8-intent agent (``spec/v2/contracts.md``).

Every model here is frozen and rejects unknown fields, so a step cannot
quietly widen a contract its consumers depend on. V1 types that are already
correct are **re-exported** rather than redefined, so there is one definition
of ``Period``, ``AnalystOutput`` and the rest.

Two safety properties are held at the type level rather than by review:

* ``ToolProvenance.source`` has no ``"model"`` member, so a language model
  cannot construct a :class:`ToolResult`. Every figure that reaches a user
  therefore traces to SQL, a catalog read, or a registered engine (SAFE-8,
  SAFE-3).
* :data:`ToolName` is a closed union with no code-string parameter, so a
  planner cannot invent a step or smuggle code through params (ANA-2, B0).

Name collision with V1, deliberate and tested (``contracts.md`` section 0.1):
``contracts.models.PlanStep`` is the *trace record* of an executed step, while
:class:`contracts.v2.PlanStep` is an *instruction to execute*. Both appear in a
V2 envelope. Never star-import this module alongside ``contracts.models``.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from contracts.models import (
    ActionOption,
    AnalystOutput,
    AnswerEnvelope,
    ColumnRole,
    ContractModel,
    ExecutionResult,
    IntentLabel,
    LedgerClaim,
    MetricDefinition,
    MetricTimeGrain,
    Period,
    RouteLabel,
    RunStatus,
)

CONTRACT_VERSION = "2.0.0"

#: How many turns the context store keeps (CTX-1).
CONTEXT_WINDOW = 10

#: How many turns the question rewriter may read (CTX-1b).
#:
#: Deliberately smaller than :data:`CONTEXT_WINDOW`: ten stored turns keep a
#: claim reference resolvable several turns later, while a three-turn rewrite
#: window stops a stale filter leaking into an unrelated new question.
REWRITE_WINDOW = 3

#: Plan caps (PL-2).
MAX_PLAN_DEPTH = 5
MAX_PLAN_STEPS = 8

#: Routing confidence floor, matching V1's ``RouterResult`` (RQ-4, IR-3).
CONFIDENCE_FLOOR = 0.70


# --------------------------------------------------------------------------- #
# Intents
# --------------------------------------------------------------------------- #

IntentName = Literal[
    "discovery",
    "clarify",
    "descriptive",
    "diagnostic",
    "impact",
    "forecast",
    "scenario",
    "prescriptive",
]

INTENT_NAMES: tuple[IntentName, ...] = (
    "discovery",
    "clarify",
    "descriptive",
    "diagnostic",
    "impact",
    "forecast",
    "scenario",
    "prescriptive",
)

#: Lossy V2 intent to V1 route mapping, so a V1 client is not broken by a V2
#: run (``contracts.md`` section 9). ``IntentResult.intents`` stays the
#: authoritative field; this exists only to populate ``AnswerEnvelope.route``.
INTENT_TO_ROUTE: dict[IntentName, RouteLabel] = {
    "discovery": "lookup",
    "clarify": "clarify",
    "descriptive": "lookup",
    "diagnostic": "anomaly",
    "impact": "risk",
    "forecast": "risk",
    "scenario": "risk",
    "prescriptive": "risk",
}


def route_for_intent(intent: IntentName) -> RouteLabel:
    """Map a V2 intent onto the nearest V1 route label.

    The mapping is lossy by design and documented as such: four distinct V2
    intents collapse onto ``risk`` because V1 has no forward-looking route.
    """

    return INTENT_TO_ROUTE[intent]


# --------------------------------------------------------------------------- #
# Section 1 — ContextState and ConversationTurn
# --------------------------------------------------------------------------- #

_CLAIM_ID = re.compile(r"^C\d+$")


class ConversationTurn(ContractModel):
    """One answered turn of a session.

    ``claim_ids`` are **references**, never values (CTX-2). A follow-up that
    needs a prior figure re-reads it from that run's ledger or re-runs the
    engine over the stored rows; copying a number into a prompt and
    re-emitting it would detach it from its evidence and break SAFE-3.
    """

    turn_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    at: str = Field(min_length=1)
    question: str = Field(min_length=1)
    resolved: ResolvedQuestion | None = None
    intent: IntentName | None = None
    status: RunStatus
    claim_ids: tuple[str, ...] = ()
    scope_summary: str = ""

    @field_validator("claim_ids")
    @classmethod
    def _claim_ids_are_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for claim_id in value:
            if not _CLAIM_ID.match(claim_id):
                raise ValueError(
                    f"claim_ids must be ledger references like 'C1', got "
                    f"{claim_id!r}; a turn never stores the figure itself "
                    f"(CTX-2)"
                )
        return value

    @field_validator("scope_summary")
    @classmethod
    def _scope_summary_is_one_safe_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("scope_summary must be one safe-to-display line")
        return value

    @model_validator(mode="after")
    def _blocked_turn_cannot_seed_context(self) -> ConversationTurn:
        # CTX-4: an injection attempt records the question but resolves to
        # nothing, so it cannot seed the next turn (SAFE-4).
        if self.status == "blocked" and self.resolved is not None:
            raise ValueError(
                "a blocked turn must not carry a resolved question (CTX-4)"
            )
        return self


class ContextState(ContractModel):
    """Bounded, per-session conversation context.

    Held server-side per ``session_id``, never shared across users, scoped by
    permission like the plan cache (OPS-4), and void across a catalog change.
    """

    contract_version: str = CONTRACT_VERSION
    session_id: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    turns: tuple[ConversationTurn, ...] = ()
    pending_clarification: ClarificationRequest | None = None

    @model_validator(mode="after")
    def _window_is_bounded(self) -> ContextState:
        if len(self.turns) > CONTEXT_WINDOW:
            raise ValueError(
                f"context keeps at most {CONTEXT_WINDOW} turns, got "
                f"{len(self.turns)} (CTX-1)"
            )
        turn_ids = [turn.turn_id for turn in self.turns]
        if len(turn_ids) != len(set(turn_ids)):
            raise ValueError("turn_id must be unique within a session")
        return self

    def rewrite_turns(self) -> tuple[ConversationTurn, ...]:
        """The turns the question rewriter may read (CTX-1b).

        Only the most recent :data:`REWRITE_WINDOW`, so a filter from an older
        turn cannot silently survive into a new question.
        """

        if REWRITE_WINDOW <= 0:
            return ()
        return self.turns[-REWRITE_WINDOW:]

    def latest_resolved(self) -> ResolvedQuestion | None:
        """The most recent resolved question inside the rewrite window."""

        for turn in reversed(self.rewrite_turns()):
            if turn.resolved is not None:
                return turn.resolved
        return None

    def is_valid_for(self, catalog_version: str) -> bool:
        """Whether this context may still be used (CTX-3)."""

        return self.catalog_version == catalog_version


# --------------------------------------------------------------------------- #
# Section 2 — ResolvedQuestion
# --------------------------------------------------------------------------- #

ResolvedFilterOperator = Literal["=", "!=", "in", ">", ">=", "<", "<="]

ResolutionSource = Literal[
    "deterministic",
    "context",
    "model_proposed_code_validated",
]


class ResolvedFilter(ContractModel):
    """One grounded filter.

    ``values`` are literals produced by the Value Index, never by a model;
    ``link_confidence`` below threshold must trigger a clarification (GRD-8).
    """

    dimension: str = Field(min_length=1)
    operator: ResolvedFilterOperator
    values: tuple[str, ...] = Field(min_length=1)
    source_phrase: str = Field(min_length=1)
    link_confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _operator_matches_value_count(self) -> ResolvedFilter:
        if self.operator != "in" and len(self.values) != 1:
            raise ValueError(
                f"operator {self.operator!r} takes exactly one value; use 'in' "
                f"for a set"
            )
        return self


class ResolvedQuestion(ContractModel):
    """Exactly what question is being answered, after context and defaults.

    This is the object shown back to the user ("Revenue, 2018, SP — carried
    from your previous question") and the object the plan cache keys on
    (OPS-4).

    Allowlist validation of ``dimensions`` and ``filters[].dimension`` against
    the metric's ``allowed_dimensions`` (RQ-1) needs the registry, so it is
    enforced by the resolver before this object is built, and covered by a
    resolver test rather than by a field validator here.
    """

    contract_version: str = CONTRACT_VERSION
    text: str = Field(min_length=1)
    effective_text: str | None = None
    metric_id: str | None = None
    ungoverned_metric_term: str | None = None
    dimensions: tuple[str, ...] = ()
    filters: tuple[ResolvedFilter, ...] = ()
    period: Period | None = None
    comparison_period: Period | None = None
    grain: MetricTimeGrain | None = None
    inherited_fields: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    resolution_source: ResolutionSource = "deterministic"
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _resolution_is_coherent(self) -> ResolvedQuestion:
        # RQ-2: inheritance is never silent.
        if self.resolution_source == "context" and not self.inherited_fields:
            raise ValueError(
                "a context-resolved question must name its inherited fields "
                "so they can be shown to the user (RQ-2)"
            )
        if self.inherited_fields and self.resolution_source != "context":
            raise ValueError(
                "inherited_fields is only meaningful when resolution_source "
                "is 'context' (RQ-2)"
            )
        # RQ-5: an ungoverned metric must still name the term it came from, so
        # the answer can carry the ungoverned_metric badge (MET-4).
        if self.metric_id is None and self.ungoverned_metric_term is None:
            raise ValueError(
                "a question with no governed metric must record the raw term "
                "as ungoverned_metric_term (RQ-5)"
            )
        if self.metric_id is not None and self.ungoverned_metric_term is not None:
            raise ValueError(
                "ungoverned_metric_term must be empty when a governed metric "
                "resolved"
            )
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("dimensions must not repeat")
        unknown = [
            name
            for name in self.inherited_fields
            if name not in type(self).model_fields
        ]
        if unknown:
            raise ValueError(
                f"inherited_fields must name ResolvedQuestion fields; unknown: "
                f"{sorted(unknown)}"
            )
        return self

    def needs_clarification(self) -> bool:
        """Whether the caller must clarify instead of proceeding (RQ-4)."""

        return self.confidence < CONFIDENCE_FLOOR


# --------------------------------------------------------------------------- #
# Section 3 — IntentResult
# --------------------------------------------------------------------------- #


class ScoredIntent(ContractModel):
    intent: IntentName
    score: float = Field(ge=0.0, le=1.0)
    span: str | None = None


class Horizon(ContractModel):
    """A forecast horizon, anchored on a complete period (V2-DATA-2)."""

    periods: int = Field(ge=1)
    grain: MetricTimeGrain
    anchor: str = Field(min_length=1)


ScenarioKind = Literal[
    "multiplicative",
    "additive",
    "absolute",
    "remove",
    "mix_shift",
]


class ScenarioAppliesTo(ContractModel):
    dimension: str = Field(min_length=1)
    values: tuple[str, ...] = Field(min_length=1)


class ScenarioParam(ContractModel):
    """One stated change to an input.

    The engine perturbs a *fitted* relationship by this amount; it never
    invents the coefficient that turns the change into an outcome.
    """

    target: str = Field(min_length=1)
    kind: ScenarioKind
    value: float
    applies_to: ScenarioAppliesTo | None = None
    source_phrase: str = Field(min_length=1)

    @model_validator(mode="after")
    def _kind_matches_value(self) -> ScenarioParam:
        if self.kind == "multiplicative" and self.value <= 0:
            raise ValueError("a multiplicative scenario value must be positive")
        if self.kind == "remove" and self.applies_to is None:
            raise ValueError("a 'remove' scenario must name what it removes")
        return self


class Entities(ContractModel):
    metric_id: str | None = None
    secondary_metric_ids: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    filters: tuple[ResolvedFilter, ...] = ()
    period: Period | None = None
    comparison_period: Period | None = None
    grain: MetricTimeGrain | None = None
    horizon: Horizon | None = None
    scenario_params: tuple[ScenarioParam, ...] = ()
    action_intent: bool = False


class IntentRulesSignal(ContractModel):
    matched: tuple[str, ...] = ()
    intents: tuple[IntentName, ...] = ()


class IntentClassifierSignal(ContractModel):
    intents: tuple[ScoredIntent, ...] = ()


class IntentModelSignal(ContractModel):
    """What the model proposed. Code takes the final decision (RTE-2)."""

    proposed: tuple[IntentName, ...] = ()
    entities: Entities = Field(default_factory=Entities)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class IntentSignals(ContractModel):
    rules: IntentRulesSignal = Field(default_factory=IntentRulesSignal)
    classifier: IntentClassifierSignal = Field(
        default_factory=IntentClassifierSignal
    )
    model: IntentModelSignal | None = None
    agreement: bool = False


class IntentResult(ContractModel):
    """The 8-intent classification, replacing V1's 7-value ``RouteLabel``.

    A compound question carries several intents, ordered with the primary
    first, and the planner builds one step per intent.
    """

    contract_version: str = CONTRACT_VERSION
    intents: tuple[ScoredIntent, ...] = Field(min_length=1)
    entities: Entities = Field(default_factory=Entities)
    signals: IntentSignals = Field(default_factory=IntentSignals)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    clarification: ClarificationRequest | None = None
    prd_intent_label: IntentLabel

    @property
    def primary_intent(self) -> IntentName:
        return self.intents[0].intent

    @property
    def intent_names(self) -> tuple[IntentName, ...]:
        return tuple(scored.intent for scored in self.intents)

    @property
    def route_labels(self) -> tuple[RouteLabel, ...]:
        """The lossy V1 route labels for this result, de-duplicated in order."""

        labels: list[RouteLabel] = []
        for name in self.intent_names:
            label = route_for_intent(name)
            if label not in labels:
                labels.append(label)
        return tuple(labels)

    @model_validator(mode="after")
    def _intents_are_coherent(self) -> IntentResult:
        names = self.intent_names
        if len(set(names)) != len(names):
            raise ValueError("an intent must not appear twice")

        # IR-2: clarify is exclusive; discovery may be combined.
        if "clarify" in names and len(names) != 1:
            raise ValueError(
                "the clarify intent cannot be combined with another intent "
                "(IR-2)"
            )

        # IR-3: code decides; below the floor the only answer is a question.
        if self.confidence < CONFIDENCE_FLOOR:
            if names != ("clarify",):
                raise ValueError(
                    f"confidence below {CONFIDENCE_FLOOR} must resolve to the "
                    f"clarify intent, got {list(names)} (IR-3)"
                )
            if self.clarification is None:
                raise ValueError(
                    "a clarify intent needs a ClarificationRequest (IR-3)"
                )
        if names == ("clarify",) and self.clarification is None:
            raise ValueError("a clarify intent needs a ClarificationRequest")

        # IR-4 / IR-5: the entities an intent needs, and only those.
        has_forecast = "forecast" in names
        if has_forecast and self.entities.horizon is None:
            raise ValueError("the forecast intent requires a horizon (IR-4)")
        if not has_forecast and self.entities.horizon is not None:
            raise ValueError(
                "a horizon is only meaningful for the forecast intent (IR-4)"
            )

        has_scenario = "scenario" in names
        if has_scenario and not self.entities.scenario_params:
            raise ValueError(
                "the scenario intent requires at least one scenario parameter "
                "(IR-5)"
            )
        if not has_scenario and self.entities.scenario_params:
            raise ValueError(
                "scenario parameters are only meaningful for the scenario "
                "intent (IR-5)"
            )
        return self


# --------------------------------------------------------------------------- #
# Section 4 — ClarificationRequest
# --------------------------------------------------------------------------- #

ClarifiableSlot = Literal[
    "metric",
    "period",
    "comparison_period",
    "grain",
    "dimension",
    "filter_value",
    "horizon",
    "scenario_param",
    "intent",
]


class ClarificationOption(ContractModel):
    """One offered reading of the question.

    ``resolves_to`` is a *patch* over :class:`ResolvedQuestion`, so accepting
    an option is deterministic: the model does not re-interpret the reply
    (CL-6).
    """

    option_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    detail: str | None = None
    resolves_to: dict[str, Any] = Field(default_factory=dict)
    recommended: bool = False

    @model_validator(mode="after")
    def _patch_names_resolved_question_fields(self) -> ClarificationOption:
        if not self.resolves_to:
            raise ValueError(
                f"option {self.option_id!r} must resolve something; an option "
                f"that changes nothing is not a choice"
            )
        unknown = [
            key
            for key in self.resolves_to
            if key not in ResolvedQuestion.model_fields
        ]
        if unknown:
            raise ValueError(
                f"resolves_to must patch ResolvedQuestion fields; unknown: "
                f"{sorted(unknown)} (CL-6)"
            )
        return self


class DefaultAssumption(ContractModel):
    """What happens if the user says nothing (CL-3)."""

    option_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ClarificationRequest(ContractModel):
    """One question, 2-4 options, a stated default, bounded to 2 rounds.

    V1's ``ClarificationResult`` carried only two prose strings with no
    options and no default, so the frontend could render only a free-text
    reply box. Those two fields are retained here because the SSE ``clarify``
    event and the existing reply box depend on them.

    A clarification is HTTP 200 with ``status: "clarify"``, never an error,
    and the SSE event is not terminal (CL-7).
    """

    contract_version: str = CONTRACT_VERSION
    what_understood: str = Field(min_length=1)
    what_needs_clarification: str = Field(min_length=1)
    question: str = Field(min_length=1)
    options: tuple[ClarificationOption, ...] = Field(min_length=2, max_length=4)
    default_assumption: DefaultAssumption
    round: Literal[1, 2] = 1
    slot: ClarifiableSlot
    of_run_id: str | None = None

    @field_validator("question")
    @classmethod
    def _exactly_one_question(cls, value: str) -> str:
        # CL-1: asking two things at once is the behaviour V2 replaces.
        if value.count("?") > 1:
            raise ValueError(
                "a clarification asks exactly one question (CL-1)"
            )
        return value

    @model_validator(mode="after")
    def _options_are_coherent(self) -> ClarificationRequest:
        option_ids = [option.option_id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("option_id must be unique")

        # CL-3: there is always a default, and it is one of the options.
        if self.default_assumption.option_id not in option_ids:
            raise ValueError(
                f"default_assumption names {self.default_assumption.option_id!r}, "
                f"which is not one of {option_ids} (CL-3)"
            )

        # CL-5: at most one recommendation.
        recommended = [option for option in self.options if option.recommended]
        if len(recommended) > 1:
            raise ValueError("at most one option may be recommended (CL-5)")

        if self.round == 2 and self.of_run_id is None:
            raise ValueError(
                "a second-round clarification must name the run it clarifies"
            )
        return self


# --------------------------------------------------------------------------- #
# Section 5 — Plan and PlanStep
# --------------------------------------------------------------------------- #

PythonEngineName = Literal[
    "python.anomaly",
    "python.driver",
    "python.forecast",
    "python.impact",
    "python.scenario",
    "python.segment",
]

ToolName = Literal[
    "sql",
    "catalog",
    "analytical_table",
    "python.anomaly",
    "python.driver",
    "python.forecast",
    "python.impact",
    "python.scenario",
    "python.segment",
]

#: The closed tool registry. There is no ``python.custom``, no code-string
#: parameter and no eval path: a new engine is added by registering a module
#: with its contract, tests and eval cases (ANA-2, B0).
TOOL_NAMES: tuple[ToolName, ...] = (
    "sql",
    "catalog",
    "analytical_table",
    "python.anomaly",
    "python.driver",
    "python.forecast",
    "python.impact",
    "python.scenario",
    "python.segment",
)

ENGINE_NAMES: tuple[PythonEngineName, ...] = (
    "python.anomaly",
    "python.driver",
    "python.forecast",
    "python.impact",
    "python.scenario",
    "python.segment",
)

#: Tools that read data for an engine to consume. An engine may depend only on
#: these for its rows, never on another engine's rows (PL-5).
DATA_TOOLS: tuple[ToolName, ...] = ("sql", "analytical_table")

#: Engines that produce a fit a scenario may perturb (PL-4).
FIT_PRODUCING_ENGINES: tuple[PythonEngineName, ...] = (
    "python.forecast",
    "python.impact",
)

StepOutputKind = Literal[
    "rows",
    "catalog_facts",
    "analyst_output",
    "ranked_options",
]

ToolStatus = Literal[
    "ok",
    "empty",
    "insufficient_evidence",
    "refused",
    "skipped",
    "error",
]

PlanSource = Literal[
    "deterministic_template",
    "model_drafted_code_validated",
    "fallback_single_step",
]


class StepBudget(ContractModel):
    """The whole plan's budget, not one step's."""

    max_queries: int = Field(default=3, ge=0)
    max_engine_calls: int = Field(default=4, ge=0)
    max_tokens: int = Field(default=4096, ge=0)
    max_wall_ms: int = Field(default=10_000, ge=1)


class PlanStep(ContractModel):
    """An instruction to execute.

    Distinct from ``contracts.models.PlanStep``, which records a step that
    already ran. See the module docstring.
    """

    step_id: str = Field(min_length=1)
    tool: ToolName
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    produces: StepOutputKind
    optional: bool = False
    purpose: str = Field(min_length=1)

    @field_validator("purpose")
    @classmethod
    def _purpose_is_one_safe_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise ValueError("purpose must be one safe-to-display line")
        return value

    @model_validator(mode="after")
    def _step_does_not_depend_on_itself(self) -> PlanStep:
        if self.step_id in self.depends_on:
            raise ValueError(f"step {self.step_id!r} cannot depend on itself")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("depends_on must not repeat a step_id")
        return self

    @property
    def is_engine(self) -> bool:
        return self.tool in ENGINE_NAMES


class DroppedIntent(ContractModel):
    """An intent the plan accepted but could not serve, with the reason."""

    intent: IntentName
    reason: str = Field(min_length=1)


class Plan(ContractModel):
    """The validated executable DAG.

    A model may draft a plan; **code validates it** before a single step runs.
    An invalid plan falls back to the highest-value single intent and records
    the omission in ``intents_dropped`` (RTE-6).
    """

    contract_version: str = CONTRACT_VERSION
    plan_id: str = Field(min_length=1)
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=MAX_PLAN_STEPS)
    depth: int = Field(ge=1, le=MAX_PLAN_DEPTH)
    source: PlanSource
    intents_covered: tuple[IntentName, ...] = ()
    intents_dropped: tuple[DroppedIntent, ...] = ()
    budget: StepBudget = Field(default_factory=StepBudget)

    @model_validator(mode="after")
    def _plan_is_a_valid_dag(self) -> Plan:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id must be unique within a plan")
        known = set(step_ids)

        # PL-1: dependencies must exist.
        for step in self.steps:
            missing = [dep for dep in step.depends_on if dep not in known]
            if missing:
                raise ValueError(
                    f"step {step.step_id!r} depends on unknown step(s) "
                    f"{sorted(missing)} (PL-1)"
                )

        order = _topological_order(self.steps)
        if order is None:
            raise ValueError("the plan contains a dependency cycle (PL-1)")

        # PL-2: the declared depth must be the real longest chain, so it
        # cannot be understated to slip past the cap.
        computed = _plan_depth(self.steps)
        if computed != self.depth:
            raise ValueError(
                f"declared depth {self.depth} does not match the longest "
                f"dependency chain {computed} (PL-2)"
            )

        by_id = {step.step_id: step for step in self.steps}

        for step in self.steps:
            # PL-5: an engine consumes typed tables the orchestrator supplies;
            # it never reads another engine's rows, opens a connection, or
            # generates SQL (SAFE-8).
            if step.is_engine:
                for dep in step.depends_on:
                    parent = by_id[dep]
                    if parent.produces == "rows" and parent.tool not in DATA_TOOLS:
                        raise ValueError(
                            f"engine step {step.step_id!r} may take rows only "
                            f"from {list(DATA_TOOLS)}, not from "
                            f"{parent.tool!r} (PL-5)"
                        )

            # PL-4: a scenario perturbs a fit that was estimated from data. A
            # scenario with no fit behind it would be a fabricated number.
            if step.tool == "python.scenario":
                fits = [
                    by_id[dep]
                    for dep in step.depends_on
                    if by_id[dep].tool in FIT_PRODUCING_ENGINES
                ]
                if not fits:
                    raise ValueError(
                        f"scenario step {step.step_id!r} must depend on a fit "
                        f"from one of {list(FIT_PRODUCING_ENGINES)} (PL-4)"
                    )

        # PL-6: a compound question that cannot fit its budget drops an intent
        # explicitly rather than silently truncating at execution time.
        sql_steps = sum(1 for step in self.steps if step.tool == "sql")
        if sql_steps > self.budget.max_queries:
            raise ValueError(
                f"the plan needs {sql_steps} queries but the budget allows "
                f"{self.budget.max_queries} (PL-6)"
            )
        engine_steps = sum(1 for step in self.steps if step.is_engine)
        if engine_steps > self.budget.max_engine_calls:
            raise ValueError(
                f"the plan needs {engine_steps} engine calls but the budget "
                f"allows {self.budget.max_engine_calls} (PL-6)"
            )

        # PL-7: nothing vanishes without a stated reason.
        dropped = [item.intent for item in self.intents_dropped]
        overlap = set(self.intents_covered) & set(dropped)
        if overlap:
            raise ValueError(
                f"an intent cannot be both covered and dropped: "
                f"{sorted(overlap)} (PL-7)"
            )
        if len(set(dropped)) != len(dropped):
            raise ValueError("an intent cannot be dropped twice")
        if not self.intents_covered and not self.intents_dropped:
            raise ValueError(
                "a plan must either cover or explicitly drop at least one "
                "intent (PL-7)"
            )
        return self

    def execution_order(self) -> tuple[str, ...]:
        """Step ids in a valid execution order."""

        order = _topological_order(self.steps)
        if order is None:  # pragma: no cover - rejected by the validator
            raise ValueError("the plan contains a dependency cycle")
        return order


def _topological_order(steps: tuple[PlanStep, ...]) -> tuple[str, ...] | None:
    """Kahn's algorithm. ``None`` when the graph has a cycle."""

    remaining = {step.step_id: set(step.depends_on) for step in steps}
    declared = [step.step_id for step in steps]
    order: list[str] = []
    while remaining:
        ready = [
            step_id
            for step_id in declared
            if step_id in remaining and not remaining[step_id]
        ]
        if not ready:
            return None
        for step_id in ready:
            order.append(step_id)
            del remaining[step_id]
        for deps in remaining.values():
            deps.difference_update(ready)
    return tuple(order)


def _plan_depth(steps: tuple[PlanStep, ...]) -> int:
    """The longest dependency chain, counted in steps."""

    by_id = {step.step_id: step for step in steps}
    memo: dict[str, int] = {}

    def depth_of(step_id: str) -> int:
        if step_id in memo:
            return memo[step_id]
        step = by_id[step_id]
        if not step.depends_on:
            memo[step_id] = 1
        else:
            memo[step_id] = 1 + max(depth_of(dep) for dep in step.depends_on)
        return memo[step_id]

    return max(depth_of(step.step_id) for step in steps)


# --------------------------------------------------------------------------- #
# Section 5.1 — Precomputed analytical tables
# --------------------------------------------------------------------------- #

AnomalyDirection = Literal["spike", "dip"]
ForecastModelName = Literal["prophet", "ets"]


class AnomalyRow(ContractModel):
    """One row of ``analytical_anomalies``: engine output, cached.

    Reading this table must set ``ToolProvenance.source = "engine"`` with the
    row's ``engine_version``; the table is a cache of engine output, and
    reading it must not launder a figure out of its engine attribution
    (AT-1, SAFE-3).
    """

    kpi: str = Field(min_length=1)
    date: str = Field(min_length=1)
    grain: MetricTimeGrain
    dimension: str | None = None
    dimension_value: str | None = None
    value: float
    expected: float
    delta: float
    delta_pct: float
    direction: AnomalyDirection
    score: float
    flagged: bool
    correction: str = Field(min_length=1)
    computed_at: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    is_synthetic: bool = False

    @model_validator(mode="after")
    def _row_is_self_consistent(self) -> AnomalyRow:
        if (self.dimension is None) != (self.dimension_value is None):
            raise ValueError(
                "dimension and dimension_value must both be set, or both be "
                "null for the total series"
            )
        if abs((self.value - self.expected) - self.delta) > 1e-6:
            raise ValueError(
                "delta must equal value - expected; a restated delta would "
                "detach the figure from its evidence"
            )
        expected_direction = "spike" if self.delta >= 0 else "dip"
        if self.direction != expected_direction:
            raise ValueError(
                f"direction {self.direction!r} contradicts a delta of "
                f"{self.delta}"
            )
        return self


class ForecastRow(ContractModel):
    """One row of ``analytical_forecasts``: engine output, cached."""

    kpi: str = Field(min_length=1)
    dimension: str | None = None
    dimension_value: str | None = None
    grain: MetricTimeGrain
    anchor_period: str = Field(min_length=1)
    ds: str = Field(min_length=1)
    yhat: float
    yhat_lower: float
    yhat_upper: float
    model: ForecastModelName
    model_fallback_reason: str | None = None
    mape: float | None = Field(default=None, ge=0.0)
    computed_at: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    catalog_version: str = Field(min_length=1)
    is_synthetic: bool = False

    @model_validator(mode="after")
    def _forecast_row_is_coherent(self) -> ForecastRow:
        if not self.yhat_lower <= self.yhat <= self.yhat_upper:
            raise ValueError(
                "the forecast interval must bracket the central estimate"
            )
        # AT-3: a forecast period must lie beyond the period it was fitted on.
        if self.ds <= self.anchor_period:
            raise ValueError(
                f"forecast period {self.ds!r} must be after the anchor "
                f"{self.anchor_period!r} (AT-3)"
            )
        # TR-8: a fallback is never silent.
        if self.model == "ets" and not self.model_fallback_reason:
            raise ValueError(
                "an ETS forecast must state why it did not use the primary "
                "model (TR-8)"
            )
        if self.model == "prophet" and self.model_fallback_reason:
            raise ValueError(
                "model_fallback_reason is only meaningful for a fallback"
            )
        return self


# --------------------------------------------------------------------------- #
# Section 6 — ToolResult
# --------------------------------------------------------------------------- #

#: Where a figure may come from. **There is deliberately no "model" member**:
#: a language model cannot produce a ToolResult, which is the type-level
#: enforcement of SAFE-8 (TR-3).
ProvenanceSource = Literal["sql", "engine", "catalog"]

DataLayer = Literal["real", "synthetic", "mixed"]

FitMeasure = Literal["mape", "r_squared", "rmse"]


class RowsColumn(ContractModel):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    role: ColumnRole


class RowsPayload(ContractModel):
    """Rows from SQL or an analytical table.

    ``query_id`` links every cell back to the query that produced it (SAFE-3).
    Rows are masked before this object is constructed (SAFE-5).
    """

    query_id: str = Field(min_length=1)
    columns: tuple[RowsColumn, ...] = ()
    rows: tuple[tuple[Any, ...], ...] = ()
    row_count: int = Field(ge=0)
    truncated: bool = False
    result_ref: str | None = None

    @model_validator(mode="after")
    def _rows_match_their_shape(self) -> RowsPayload:
        if self.rows and self.columns:
            width = len(self.columns)
            for index, row in enumerate(self.rows):
                if len(row) != width:
                    raise ValueError(
                        f"row {index} has {len(row)} values but "
                        f"{width} columns are declared"
                    )
        if self.rows and len(self.rows) > self.row_count:
            raise ValueError(
                "row_count must not understate the rows actually carried"
            )
        if not self.rows and self.row_count and self.result_ref is None:
            raise ValueError(
                "a payload with rows held out of line must carry a result_ref"
            )
        return self


class CatalogFact(ContractModel):
    key: str = Field(min_length=1)
    value: Any = None
    source: str = Field(min_length=1)


class CatalogFactsPayload(ContractModel):
    catalog_version: str = Field(min_length=1)
    facts: tuple[CatalogFact, ...] = ()


class FitQuality(ContractModel):
    """How good the fit was.

    ``value`` is ``None`` when history was too short to hold out a tail. A
    null must be reported as "not backtested", never rendered as 0 (AT-4).
    """

    measure: FitMeasure
    value: float | None = None
    n_observations: int = Field(ge=0)
    holdout: Period | None = None


class EngineProvenance(ContractModel):
    """Which engine produced a figure, by which method.

    A silent method change is how a user ends up trusting a figure produced
    differently from how they were told, so a fallback always states why
    (TR-8).
    """

    name: PythonEngineName
    version: str = Field(min_length=1)
    seed: int | None = None
    method: str = Field(min_length=1)
    method_fallback_reason: str | None = None
    library: str | None = None
    fit_quality: FitQuality | None = None


class ToolProvenance(ContractModel):
    """Where a result's numbers came from.

    ``data_layer`` is computed from the tables actually read, never declared
    by a model (SY-2).
    """

    source: ProvenanceSource
    query_ids: tuple[str, ...] = ()
    engine: EngineProvenance | None = None
    input_step_ids: tuple[str, ...] = ()
    deterministic: bool = True
    data_layer: DataLayer = "real"
    synthetic_tables: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _provenance_is_coherent(self) -> ToolProvenance:
        if self.source == "engine" and self.engine is None:
            raise ValueError("an engine result must name its engine")
        if self.source != "engine" and self.engine is not None:
            raise ValueError(
                "engine provenance is only meaningful for an engine result"
            )
        # SY-1: the synthetic label cannot be lost.
        if self.data_layer == "real" and self.synthetic_tables:
            raise ValueError(
                "a result reading synthetic tables cannot claim data_layer "
                "'real' (SY-1)"
            )
        if self.data_layer in ("synthetic", "mixed") and not self.synthetic_tables:
            raise ValueError(
                f"data_layer {self.data_layer!r} must name the synthetic "
                f"tables it read (SY-1)"
            )
        return self


#: Which payload field carries each kind of step output (TR-1).
_PAYLOAD_FOR_KIND: dict[StepOutputKind, str] = {
    "rows": "rows",
    "catalog_facts": "catalog_facts",
    "analyst_output": "analyst_output",
    "ranked_options": "ranked_options",
}

_PAYLOAD_FIELDS: tuple[str, ...] = (
    "rows",
    "catalog_facts",
    "analyst_output",
    "ranked_options",
)


class ToolResult(ContractModel):
    """One step's output, whatever the tool, with the provenance that makes
    its numbers citable. This is the object the Evidence Ledger consumes.
    """

    contract_version: str = CONTRACT_VERSION
    step_id: str = Field(min_length=1)
    tool: ToolName
    status: ToolStatus
    produces: StepOutputKind
    rows: RowsPayload | None = None
    catalog_facts: CatalogFactsPayload | None = None
    analyst_output: AnalystOutput | None = None
    ranked_options: tuple[ActionOption, ...] | None = None
    provenance: ToolProvenance
    caveats: tuple[str, ...] = ()
    reason: str | None = None
    duration_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _result_is_coherent(self) -> ToolResult:
        present = [
            name for name in _PAYLOAD_FIELDS if getattr(self, name) is not None
        ]

        # TR-2: a non-ok status always says why.
        if self.status != "ok" and not self.reason:
            raise ValueError(
                f"status {self.status!r} needs a reason; an engine returns "
                f"insufficient_evidence with a reason rather than raising "
                f"(TR-2, ANA-4)"
            )

        # TR-1: exactly one payload, matching `produces`.
        if self.status in ("ok", "empty"):
            expected = _PAYLOAD_FOR_KIND[self.produces]
            if present != [expected]:
                raise ValueError(
                    f"a {self.status!r} result producing {self.produces!r} "
                    f"must set exactly the {expected!r} payload, got "
                    f"{present or 'none'} (TR-1)"
                )
        elif present:
            raise ValueError(
                f"status {self.status!r} carries no payload, got {present} "
                f"(TR-1)"
            )

        # TR-6: a true zero-row result is a finding, not a failure (SQL-12).
        if self.status == "empty":
            if self.produces != "rows" or self.rows is None:
                raise ValueError(
                    "status 'empty' applies to a rows payload (TR-6)"
                )
            if self.rows.row_count != 0:
                raise ValueError(
                    "status 'empty' requires row_count 0; use 'ok' for a "
                    "result that returned rows (TR-6)"
                )

        # TR-5: deterministic tools must say so.
        if self.tool in ("sql", "catalog", "analytical_table"):
            if not self.provenance.deterministic:
                raise ValueError(
                    f"{self.tool!r} is deterministic by construction (TR-5)"
                )

        # AT-1: a cached engine row keeps its engine attribution.
        if self.tool == "analytical_table" and self.produces == "analyst_output":
            if self.provenance.source != "engine":
                raise ValueError(
                    "an analytical table carrying engine output must keep "
                    "source 'engine' (AT-1)"
                )

        # An engine step must carry that engine's own output. Mislabelling one
        # engine's result as another's would misattribute every figure in it.
        if self.tool in ENGINE_NAMES and self.analyst_output is not None:
            expected_module = self.tool.removeprefix("python.")
            if self.analyst_output.module != expected_module:
                raise ValueError(
                    f"step {self.step_id!r} runs {self.tool!r} but carries a "
                    f"{self.analyst_output.module!r} output"
                )

        engine = self.provenance.engine
        if engine is not None:
            # TR-5: a seeded engine is reproducible; an unseeded one must not
            # claim to be.
            if engine.seed is not None and not self.provenance.deterministic:
                raise ValueError(
                    "a seeded engine run is reproducible and must be marked "
                    "deterministic (TR-5)"
                )
            if engine.seed is None and self.provenance.deterministic:
                raise ValueError(
                    "an unseeded engine run must not claim determinism; say "
                    "so in caveats instead (TR-5)"
                )
            # TR-8: a fitted estimate always reports its quality.
            if engine.fit_quality is None and engine.method_fallback_reason:
                raise ValueError(
                    "a fallback implies a fitted model, which must report "
                    "fit_quality (TR-8)"
                )

        # SY-1: the synthetic label reaches the user.
        if self.provenance.data_layer in ("synthetic", "mixed"):
            if not any(
                "synthetic" in caveat.lower() for caveat in self.caveats
            ):
                raise ValueError(
                    "a result derived from generated data must carry a "
                    "synthetic caveat (SY-1, V2-SYN-4)"
                )
        return self


# --------------------------------------------------------------------------- #
# Section 7 — VisualizationSpec
# --------------------------------------------------------------------------- #

VizKind = Literal[
    "line",
    "bar",
    "grouped_bar",
    "waterfall",
    "range_band",
    "forecast_fan",
    "scatter",
    "table",
]

VizEmphasis = Literal["normal", "attention"]
VizAnnotationKind = Literal["point", "band", "line", "label"]


class VizAxis(ContractModel):
    column: str = Field(min_length=1)
    role: Literal["time", "dimension", "measure"]
    label: str = Field(min_length=1)
    unit: str | None = None
    zero_baseline: bool | None = None


class VizSeries(ContractModel):
    column: str = Field(min_length=1)
    label: str = Field(min_length=1)


class VizBand(ContractModel):
    lower_column: str = Field(min_length=1)
    upper_column: str = Field(min_length=1)
    label: str = Field(min_length=1)


class VizSort(ContractModel):
    column: str = Field(min_length=1)
    direction: Literal["asc", "desc"] = "desc"


class VizEncoding(ContractModel):
    """What to draw, named by **column** and never by value (VZ-1)."""

    x: VizAxis
    y: VizAxis
    series: VizSeries | None = None
    band: VizBand | None = None
    sort: VizSort | None = None
    limit: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _axes_carry_their_roles(self) -> VizEncoding:
        if self.x.role == "measure":
            raise ValueError("the x axis carries time or a dimension, not a measure")
        if self.y.role != "measure":
            raise ValueError("the y axis carries the measure")
        # VZ-7: a truncated y axis overstates a change, so the choice is
        # always explicit rather than inherited from a chart library.
        if self.y.zero_baseline is None:
            raise ValueError(
                "y.zero_baseline must be stated explicitly (VZ-7)"
            )
        return self


class VizAnnotationAt(ContractModel):
    x: str | None = None
    x_start: str | None = None
    x_end: str | None = None
    y: float | None = None

    @model_validator(mode="after")
    def _position_is_given(self) -> VizAnnotationAt:
        if self.x is None and self.x_start is None and self.y is None:
            raise ValueError("an annotation must say where it sits")
        if (self.x_start is None) != (self.x_end is None):
            raise ValueError("a band annotation needs both x_start and x_end")
        return self


class VizAnnotation(ContractModel):
    """A mark on the chart.

    ``emphasis`` is semantic, never a colour name (VZ-4): the frontend owns
    its palette, which is also what keeps its colour rules enforceable.
    """

    kind: VizAnnotationKind
    at: VizAnnotationAt
    label: str = Field(min_length=1)
    emphasis: VizEmphasis = "normal"
    claim_id: str | None = None

    @model_validator(mode="after")
    def _a_number_needs_a_claim(self) -> VizAnnotation:
        # VZ-2: an annotation is not a place to introduce a figure.
        if self.at.y is not None and self.claim_id is None:
            raise ValueError(
                "an annotation that states a number must cite the claim it "
                "comes from (VZ-2, SAFE-3)"
            )
        return self


class VisualizationSpec(ContractModel):
    """What chart to draw, referencing data by step and column.

    The spec carries **no data array**: the data is the referenced
    :class:`ToolResult`. Top-N is applied by the backend, which re-reports the
    excluded remainder in ``caption`` — a frontend that hid rows would be
    computing a "top 5" of its own (VZ-3).
    """

    contract_version: str = CONTRACT_VERSION
    viz_id: str = Field(min_length=1)
    kind: VizKind
    title: str = Field(min_length=1)
    source_step_id: str = Field(min_length=1)
    source_query_id: str | None = None
    source_artifact_id: str | None = None
    encoding: VizEncoding
    annotations: tuple[VizAnnotation, ...] = ()
    caption: str = ""
    claim_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _spec_is_drawable(self) -> VisualizationSpec:
        # VZ-5: a forecast drawn without its interval misrepresents it.
        if self.kind == "forecast_fan" and self.encoding.band is None:
            raise ValueError(
                "a forecast_fan must encode its prediction interval (VZ-5)"
            )
        if self.kind == "range_band" and self.encoding.band is None:
            raise ValueError("a range_band must encode its band")
        if self.encoding.limit is not None and not self.caption:
            raise ValueError(
                "a top-N chart must report the excluded remainder in its "
                "caption (VZ-3)"
            )
        if self.source_query_id is None and self.source_artifact_id is None:
            raise ValueError(
                "a visualization must reference the data it draws"
            )
        return self


# --------------------------------------------------------------------------- #
# Section 8 — AnswerEnvelopeV2
# --------------------------------------------------------------------------- #


class StepResultSummary(ContractModel):
    """One planned step, as reported to the user.

    Every planned step appears, skipped ones included with a reason: a step
    that ran and is not reported is a reporting failure, not an optimisation
    (EN-2, EVID-7).
    """

    step_id: str = Field(min_length=1)
    tool: ToolName
    status: ToolStatus
    purpose: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    claim_ids: tuple[str, ...] = ()
    duration_ms: int = Field(ge=0)
    reason: str | None = None

    @model_validator(mode="after")
    def _non_ok_steps_say_why(self) -> StepResultSummary:
        if self.status not in ("ok", "empty") and not self.reason:
            raise ValueError(
                f"step {self.step_id!r} is {self.status!r} and must say why"
            )
        return self


class FollowUpSuggestion(ContractModel):
    """A question to offer next.

    ``answerable`` is ``Literal[True]``: a suggestion is only constructed
    after the backend has verified it resolves to a plannable intent, so there
    is no way to offer a question the backend cannot answer (EN-5).
    """

    text: str = Field(min_length=1)
    intent: IntentName
    rationale: str = Field(min_length=1)
    answerable: Literal[True] = True


class AnswerEnvelopeV2(AnswerEnvelope):
    """The V2 work product.

    Every V1 field keeps its current meaning, so the existing frontend renders
    a V2 envelope unchanged and gains features as it reads the new fields.
    ``route`` stays populated through the documented lossy intent mapping.
    """

    contract_version: Literal["2.0.0"] = CONTRACT_VERSION

    resolved_question: ResolvedQuestion | None = None
    intent: IntentResult | None = None
    plan: Plan | None = None
    step_results: tuple[StepResultSummary, ...] = ()
    visualizations: tuple[VisualizationSpec, ...] = ()
    assumptions: tuple[str, ...] = ()
    follow_ups: tuple[FollowUpSuggestion, ...] = ()

    # EN-1: the V2 clarification, which retains V1's two prose fields so the
    # SSE clarify event and the existing reply box are unaffected.
    clarification: ClarificationRequest | None = None  # type: ignore[assignment]

    @model_validator(mode="after")
    def _v2_envelope_is_coherent(self) -> AnswerEnvelopeV2:
        # EN-1
        if self.status == "clarify" and self.clarification is None:
            raise ValueError("a clarify answer must carry its clarification (EN-1)")

        # EN-2: one summary per planned step, in plan order.
        if self.plan is not None:
            planned = [step.step_id for step in self.plan.steps]
            reported = [summary.step_id for summary in self.step_results]
            if reported != planned:
                raise ValueError(
                    f"step_results must report every planned step in plan "
                    f"order; planned {planned}, reported {reported} (EN-2)"
                )
        elif self.step_results:
            raise ValueError(
                "step_results without a plan has nothing to report against "
                "(EN-2)"
            )

        # EN-4: an assumption the user cannot see is a trap.
        if self.resolved_question is not None:
            missing = [
                assumption
                for assumption in self.resolved_question.assumptions
                if assumption not in self.assumptions
            ]
            if missing:
                raise ValueError(
                    f"every resolved-question assumption must appear in the "
                    f"envelope's assumptions; missing {missing} (EN-4)"
                )

        # EN-6: next_actions is the prescriptive output and stays empty for
        # every other intent.
        if self.next_actions and self.intent is not None:
            if "prescriptive" not in self.intent.intent_names:
                raise ValueError(
                    "next_actions belongs to the prescriptive intent (EN-6)"
                )

        # Section 9: route stays populated through the lossy mapping, so a V1
        # client is not broken by a V2 run.
        if self.intent is not None:
            expected = self.intent.route_labels
            if tuple(self.route.labels) != expected:
                raise ValueError(
                    f"route.labels must follow the documented intent mapping; "
                    f"expected {list(expected)}, got {list(self.route.labels)}"
                )
        return self


__all__ = [
    # Constants
    "CONFIDENCE_FLOOR",
    "CONTEXT_WINDOW",
    "CONTRACT_VERSION",
    "DATA_TOOLS",
    "ENGINE_NAMES",
    "FIT_PRODUCING_ENGINES",
    "INTENT_NAMES",
    "INTENT_TO_ROUTE",
    "MAX_PLAN_DEPTH",
    "MAX_PLAN_STEPS",
    "REWRITE_WINDOW",
    "TOOL_NAMES",
    # Intents
    "Entities",
    "Horizon",
    "IntentClassifierSignal",
    "IntentModelSignal",
    "IntentName",
    "IntentResult",
    "IntentRulesSignal",
    "IntentSignals",
    "ScenarioAppliesTo",
    "ScenarioKind",
    "ScenarioParam",
    "ScoredIntent",
    "route_for_intent",
    # Context
    "ContextState",
    "ConversationTurn",
    # Resolution
    "ResolutionSource",
    "ResolvedFilter",
    "ResolvedFilterOperator",
    "ResolvedQuestion",
    # Clarification
    "ClarifiableSlot",
    "ClarificationOption",
    "ClarificationRequest",
    "DefaultAssumption",
    # Plan
    "DroppedIntent",
    "Plan",
    "PlanSource",
    "PlanStep",
    "PythonEngineName",
    "StepBudget",
    "StepOutputKind",
    "ToolName",
    # Analytical tables
    "AnomalyDirection",
    "AnomalyRow",
    "ForecastModelName",
    "ForecastRow",
    # Tool results
    "CatalogFact",
    "CatalogFactsPayload",
    "DataLayer",
    "EngineProvenance",
    "FitMeasure",
    "FitQuality",
    "ProvenanceSource",
    "RowsColumn",
    "RowsPayload",
    "ToolProvenance",
    "ToolResult",
    "ToolStatus",
    # Visualization
    "VisualizationSpec",
    "VizAnnotation",
    "VizAnnotationAt",
    "VizAnnotationKind",
    "VizAxis",
    "VizBand",
    "VizEmphasis",
    "VizEncoding",
    "VizKind",
    "VizSeries",
    "VizSort",
    # Envelope
    "AnswerEnvelopeV2",
    "FollowUpSuggestion",
    "StepResultSummary",
    # Re-exported V1 contracts (one definition, not two)
    "ActionOption",
    "AnalystOutput",
    "ColumnRole",
    "ContractModel",
    "ExecutionResult",
    "IntentLabel",
    "LedgerClaim",
    "MetricDefinition",
    "MetricTimeGrain",
    "Period",
    "RouteLabel",
    "RunStatus",
]
