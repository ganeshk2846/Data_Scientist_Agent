"""V2 contract tests (``spec/v2/contracts.md`` section 10).

Two kinds of test here, and the second kind matters more: every numbered
invariant must *reject* its violation. A contract that only accepts valid
input is a suggestion.
"""

from __future__ import annotations

import importlib
import inspect
from datetime import date

import pytest
from pydantic import ValidationError

import contracts.models as v1
import contracts.v2 as v2
from contracts.models import (
    AnalystOutput,
    AnomalyResult,
    Period,
    Provenance,
    RouteSummary,
    RunMetrics,
)
from contracts.v2 import (
    CONFIDENCE_FLOOR,
    CONTEXT_WINDOW,
    CONTRACT_VERSION,
    MAX_PLAN_DEPTH,
    REWRITE_WINDOW,
    TOOL_NAMES,
    AnomalyRow,
    AnswerEnvelopeV2,
    CatalogFact,
    CatalogFactsPayload,
    ClarificationOption,
    ClarificationRequest,
    ContextState,
    ConversationTurn,
    DefaultAssumption,
    DroppedIntent,
    EngineProvenance,
    Entities,
    FitQuality,
    FollowUpSuggestion,
    ForecastRow,
    Horizon,
    IntentResult,
    Plan,
    PlanStep,
    ResolvedFilter,
    ResolvedQuestion,
    RowsColumn,
    RowsPayload,
    ScenarioAppliesTo,
    ScenarioParam,
    ScoredIntent,
    StepBudget,
    StepResultSummary,
    ToolProvenance,
    ToolResult,
    VisualizationSpec,
    VizAnnotation,
    VizAnnotationAt,
    VizAxis,
    VizBand,
    VizEncoding,
    route_for_intent,
)

AUG_2018 = Period(start=date(2018, 8, 1), end=date(2018, 9, 1))
JUL_2018 = Period(start=date(2018, 7, 1), end=date(2018, 8, 1))
YEAR_2018 = Period(start=date(2018, 1, 1), end=date(2018, 9, 1))


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _resolved(**overrides) -> ResolvedQuestion:
    payload = {
        "text": "What was revenue in 2018?",
        "metric_id": "revenue",
        "period": YEAR_2018,
        "grain": "month",
        "confidence": 0.93,
    }
    payload.update(overrides)
    return ResolvedQuestion(**payload)


def _clarification(**overrides) -> ClarificationRequest:
    payload = {
        "what_understood": "You are asking for a summary of Revenue.",
        "what_needs_clarification": "Which time window should it cover?",
        "question": "Which time window should I summarise revenue over?",
        "options": (
            ClarificationOption(
                option_id="O1",
                label="Last 12 complete months",
                detail="2017-09 to 2018-08",
                resolves_to={"period": YEAR_2018.model_dump(mode="json")},
                recommended=True,
            ),
            ClarificationOption(
                option_id="O2",
                label="2018 to date",
                resolves_to={"grain": "month"},
            ),
        ),
        "default_assumption": DefaultAssumption(
            option_id="O1",
            rationale="Twelve complete months covers a full seasonal cycle.",
        ),
        "slot": "period",
    }
    payload.update(overrides)
    return ClarificationRequest(**payload)


def _intent(**overrides) -> IntentResult:
    payload = {
        "intents": (ScoredIntent(intent="descriptive", score=0.94),),
        "entities": Entities(metric_id="revenue", period=YEAR_2018, grain="month"),
        "confidence": 0.92,
        "reason": "Treated as a measured lookup of revenue for 2018.",
        "prd_intent_label": "Descriptive",
    }
    payload.update(overrides)
    return IntentResult(**payload)


def _sql_step(step_id: str = "P1", **overrides) -> PlanStep:
    payload = {
        "step_id": step_id,
        "tool": "sql",
        "params": {"metric_id": "revenue"},
        "produces": "rows",
        "purpose": "Monthly revenue series through the last complete month.",
    }
    payload.update(overrides)
    return PlanStep(**payload)


def _engine_step(step_id: str, tool: str, depends_on: tuple[str, ...]) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        tool=tool,  # type: ignore[arg-type]
        depends_on=depends_on,
        produces="analyst_output",
        purpose=f"Run {tool}.",
    )


def _plan(**overrides) -> Plan:
    payload = {
        "plan_id": "pl_1",
        "steps": (
            _sql_step("P1"),
            _engine_step("P2", "python.forecast", ("P1",)),
        ),
        "depth": 2,
        "source": "model_drafted_code_validated",
        "intents_covered": ("forecast",),
    }
    payload.update(overrides)
    return Plan(**payload)


def _rows_payload(**overrides) -> RowsPayload:
    payload = {
        "query_id": "Q1",
        "columns": (
            RowsColumn(name="month", type="TEXT", role="time"),
            RowsColumn(name="revenue", type="REAL", role="measure"),
        ),
        "rows": (("2018-08", 1_053_182.44),),
        "row_count": 1,
    }
    payload.update(overrides)
    return RowsPayload(**payload)


def _sql_result(**overrides) -> ToolResult:
    payload = {
        "step_id": "P1",
        "tool": "sql",
        "status": "ok",
        "produces": "rows",
        "rows": _rows_payload(),
        "provenance": ToolProvenance(source="sql", query_ids=("Q1",)),
        "duration_ms": 184,
    }
    payload.update(overrides)
    return ToolResult(**payload)


def _engine_provenance(**overrides) -> EngineProvenance:
    payload = {
        "name": "python.anomaly",
        "version": "2.0.0",
        "seed": 0,
        "method": "ets",
        "method_fallback_reason": "Prophet needs >= 24 monthly periods.",
        "library": "statsmodels 0.14.2",
        "fit_quality": FitQuality(measure="mape", value=0.118, n_observations=23),
    }
    payload.update(overrides)
    return EngineProvenance(**payload)


def _analyst_output(module: str = "anomaly") -> AnalystOutput:
    """An engine output carrying a typed result.

    Deliberately an anomaly result: the per-engine result payloads for the V2
    engines (ForecastResult and friends) are a track-2 deliverable, and
    inventing their shape here would pin them before the engines exist. What
    is under test is the ToolResult envelope, not the engine payload.
    """

    return AnalystOutput(
        module=module,  # type: ignore[arg-type]
        status="ok",
        result=AnomalyResult(
            verdict="unusual",
            window="2018-08",
            actual=900_000.0,
            expected=1_000_000.0,
            expected_range=(950_000.0, 1_050_000.0),
            deviation_pct=-10.0,
            robust_score=-3.4,
            persistence="sustained",
            threshold=3.0,
            baseline_kind="robust_trailing",
        ),
        parameters={"metric": "revenue", "grain": "month"},
        assumptions=("Fitted on 2016-10 through 2018-08.",),
        sources=("Q1",),
    )


def _encoding(**overrides) -> VizEncoding:
    payload = {
        "x": VizAxis(column="period", role="time", label="Month"),
        "y": VizAxis(
            column="value",
            role="measure",
            label="Revenue",
            unit="BRL",
            zero_baseline=True,
        ),
    }
    payload.update(overrides)
    return VizEncoding(**payload)


def _viz(**overrides) -> VisualizationSpec:
    payload = {
        "viz_id": "vz_1",
        "kind": "line",
        "title": "Monthly revenue",
        "source_step_id": "P1",
        "source_query_id": "Q1",
        "encoding": _encoding(),
    }
    payload.update(overrides)
    return VisualizationSpec(**payload)


def _envelope(**overrides) -> AnswerEnvelopeV2:
    payload = {
        "run_id": "b7e2d4a1",
        "status": "answered",
        "route": RouteSummary(
            labels=("lookup",),
            confidence=0.92,
            reason="Treated as a measured lookup.",
        ),
        "run_metrics": RunMetrics(latency_ms=225, tokens=0, queries=1, rows=1),
        "provenance": Provenance(timestamp="2026-10-30T09:14:22Z"),
    }
    payload.update(overrides)
    return AnswerEnvelopeV2(**payload)


# --------------------------------------------------------------------------- #
# Section 0.1 — the namespace rule
# --------------------------------------------------------------------------- #


def test_v2_plan_step_is_deliberately_distinct_from_the_v1_one():
    """V1's PlanStep records an executed step; V2's instructs one to run.

    Both appear in a V2 envelope, so the shadowing must stay visible rather
    than become an accident.
    """

    assert v2.PlanStep is not v1.PlanStep
    assert "tool" in v2.PlanStep.model_fields
    assert "tool" not in v1.PlanStep.model_fields
    assert "module" in v1.PlanStep.model_fields
    assert "module" not in v2.PlanStep.model_fields


def test_v1_types_are_reexported_rather_than_redefined():
    """One definition of Period, not two that can drift apart."""

    for name in (
        "Period",
        "MetricDefinition",
        "ExecutionResult",
        "LedgerClaim",
        "ActionOption",
        "RunStatus",
        "IntentLabel",
        "MetricTimeGrain",
        "ColumnRole",
    ):
        assert getattr(v2, name) is getattr(v1, name), name
    assert issubclass(v2.AnalystOutput, v1.AnalystOutput)
    result_annotation = v2.AnalystOutput.model_fields["result"].annotation
    assert v2.ForecastResult in result_annotation.__args__
    assert v2.ImpactResult in result_annotation.__args__
    assert v2.ScenarioResult in result_annotation.__args__
    assert v2.SegmentResult in result_annotation.__args__


def test_every_v2_model_is_frozen_and_rejects_unknown_fields():
    for name in v2.__all__:
        obj = getattr(v2, name)
        if inspect.isclass(obj) and issubclass(obj, v1.ContractModel):
            assert obj.model_config.get("frozen") is True, name
            assert obj.model_config.get("extra") == "forbid", name


def test_the_v2_contracts_import_no_model_client():
    """SAFE-8 at the module level: contracts cannot reach a model."""

    source = inspect.getsource(v2)
    for forbidden in ("models.client", "import httpx", "requests", "openai"):
        assert forbidden not in source, forbidden


# --------------------------------------------------------------------------- #
# Section 1 — ContextState / ConversationTurn
# --------------------------------------------------------------------------- #


def _turn(index: int, **overrides) -> ConversationTurn:
    payload = {
        "turn_id": f"T{index}",
        "run_id": f"run{index}",
        "at": "2026-10-30T09:14:22Z",
        "question": "What was revenue in 2018?",
        "resolved": _resolved(),
        "intent": "descriptive",
        "status": "answered",
        "claim_ids": ("C1",),
        "scope_summary": "Revenue, 2018",
    }
    payload.update(overrides)
    return ConversationTurn(**payload)


def test_context_rejects_more_than_the_window():
    """CTX-1."""

    with pytest.raises(ValidationError, match="at most 10 turns"):
        ContextState(
            session_id="s1",
            catalog_version="v1",
            turns=tuple(_turn(i) for i in range(CONTEXT_WINDOW + 1)),
        )


def test_the_rewriter_sees_only_the_last_three_turns():
    """CTX-1b: ten stored, three readable.

    A filter from four turns ago must not survive into a new question, while
    a claim from eight turns ago stays resolvable by reference.
    """

    assert REWRITE_WINDOW == 3
    assert REWRITE_WINDOW < CONTEXT_WINDOW

    turns = tuple(_turn(i) for i in range(CONTEXT_WINDOW))
    context = ContextState(session_id="s1", catalog_version="v1", turns=turns)

    visible = context.rewrite_turns()
    assert len(visible) == REWRITE_WINDOW
    assert [turn.turn_id for turn in visible] == ["T7", "T8", "T9"]

    # The four-turn-old filter is out of reach of the rewriter ...
    assert _turn(6) not in visible
    # ... while every turn is still stored for claim resolution.
    assert len(context.turns) == CONTEXT_WINDOW
    assert context.turns[0].claim_ids == ("C1",)


def test_a_stale_filter_is_not_inherited_from_outside_the_rewrite_window():
    """The concrete leak CTX-1b exists to prevent."""

    sp_filter = ResolvedFilter(
        dimension="customer_state",
        operator="=",
        values=("SP",),
        source_phrase="SP",
        link_confidence=0.98,
    )
    turns = (
        _turn(1, resolved=_resolved(filters=(sp_filter,))),
        _turn(2),
        _turn(3),
        _turn(4),
    )
    context = ContextState(session_id="s1", catalog_version="v1", turns=turns)

    latest = context.latest_resolved()
    assert latest is not None
    assert latest.filters == ()


def test_claim_ids_are_references_never_values():
    """CTX-2: a turn stores a pointer, not the figure (SAFE-3)."""

    with pytest.raises(ValidationError, match="ledger references"):
        _turn(1, claim_ids=("1053182.44",))


def test_a_blocked_turn_cannot_seed_the_next_one():
    """CTX-4: an injection attempt leaves no resolved question (SAFE-4)."""

    with pytest.raises(ValidationError, match="blocked turn"):
        _turn(1, status="blocked", resolved=_resolved())

    safe = _turn(1, status="blocked", resolved=None)
    assert safe.resolved is None


def test_scope_summary_stays_one_safe_line():
    """CTX-5."""

    with pytest.raises(ValidationError, match="one safe-to-display line"):
        _turn(1, scope_summary="Revenue\nSELECT * FROM customers")


def test_context_is_void_across_a_catalog_change():
    """CTX-3."""

    context = ContextState(session_id="s1", catalog_version="v1", turns=())
    assert context.is_valid_for("v1") is True
    assert context.is_valid_for("v2") is False


def test_turn_ids_must_be_unique():
    with pytest.raises(ValidationError, match="unique"):
        ContextState(
            session_id="s1",
            catalog_version="v1",
            turns=(_turn(1), _turn(1)),
        )


# --------------------------------------------------------------------------- #
# Section 2 — ResolvedQuestion
# --------------------------------------------------------------------------- #


def test_context_resolution_must_name_what_it_inherited():
    """RQ-2: silent inheritance is how a user trusts the wrong number."""

    with pytest.raises(ValidationError, match="inherited fields"):
        _resolved(resolution_source="context", inherited_fields=())

    ok = _resolved(
        resolution_source="context",
        inherited_fields=("metric_id", "period"),
    )
    assert ok.inherited_fields == ("metric_id", "period")


def test_inherited_fields_outside_a_context_resolution_is_rejected():
    with pytest.raises(ValidationError, match="only meaningful"):
        _resolved(resolution_source="deterministic", inherited_fields=("period",))


def test_inherited_fields_must_name_real_fields():
    with pytest.raises(ValidationError, match="unknown"):
        _resolved(
            resolution_source="context",
            inherited_fields=("metric_id", "nonsense"),
        )


def test_an_ungoverned_metric_must_record_its_raw_term():
    """RQ-5: so the answer can carry the ungoverned_metric badge (MET-4)."""

    with pytest.raises(ValidationError, match="ungoverned_metric_term"):
        _resolved(metric_id=None, ungoverned_metric_term=None)

    ok = _resolved(metric_id=None, ungoverned_metric_term="margin")
    assert ok.ungoverned_metric_term == "margin"


def test_a_governed_metric_cannot_also_be_ungoverned():
    with pytest.raises(ValidationError, match="must be empty"):
        _resolved(metric_id="revenue", ungoverned_metric_term="margin")


def test_low_confidence_resolution_reports_that_it_needs_clarification():
    """RQ-4."""

    assert _resolved(confidence=0.69).needs_clarification() is True
    assert _resolved(confidence=CONFIDENCE_FLOOR).needs_clarification() is False


def test_dimensions_must_not_repeat():
    with pytest.raises(ValidationError, match="must not repeat"):
        _resolved(dimensions=("customer_state", "customer_state"))


def test_a_single_value_operator_rejects_a_value_set():
    """RQ-6 shape: 'in' takes a set, '=' takes one value."""

    with pytest.raises(ValidationError, match="exactly one value"):
        ResolvedFilter(
            dimension="customer_state",
            operator="=",
            values=("SP", "RJ"),
            source_phrase="SP and RJ",
            link_confidence=0.9,
        )


# --------------------------------------------------------------------------- #
# Section 3 — IntentResult
# --------------------------------------------------------------------------- #


def test_the_example_compound_intent_parses_and_round_trips():
    """The worked example from contracts.md section 3."""

    result = _intent(
        intents=(
            ScoredIntent(
                intent="descriptive",
                score=0.94,
                span="how does revenue trend look today",
            ),
            ScoredIntent(
                intent="forecast",
                score=0.91,
                span="what will it be in 3 months",
            ),
        ),
        entities=Entities(
            metric_id="revenue",
            period=YEAR_2018,
            grain="month",
            horizon=Horizon(periods=3, grain="month", anchor="2018-08"),
        ),
    )

    assert result.primary_intent == "descriptive"
    assert result.intent_names == ("descriptive", "forecast")
    restored = IntentResult.model_validate(result.model_dump(mode="json"))
    assert restored == result


def test_clarify_cannot_be_combined_with_another_intent():
    """IR-2."""

    with pytest.raises(ValidationError, match="cannot be combined"):
        _intent(
            intents=(
                ScoredIntent(intent="clarify", score=0.5),
                ScoredIntent(intent="descriptive", score=0.5),
            ),
            confidence=0.8,
            clarification=_clarification(),
        )


def test_discovery_may_be_combined():
    """IR-2: discovery + diagnostic is the K8 shape."""

    result = _intent(
        intents=(
            ScoredIntent(intent="discovery", score=0.9),
            ScoredIntent(intent="diagnostic", score=0.8),
        ),
    )
    assert result.intent_names == ("discovery", "diagnostic")


def test_an_intent_cannot_appear_twice():
    with pytest.raises(ValidationError, match="twice"):
        _intent(
            intents=(
                ScoredIntent(intent="descriptive", score=0.9),
                ScoredIntent(intent="descriptive", score=0.8),
            ),
        )


def test_below_the_confidence_floor_the_only_intent_is_clarify():
    """IR-3: code decides, the model only proposes (RTE-2)."""

    with pytest.raises(ValidationError, match="must resolve to the clarify"):
        _intent(confidence=0.5)

    ok = _intent(
        intents=(ScoredIntent(intent="clarify", score=0.5),),
        confidence=0.5,
        clarification=_clarification(),
    )
    assert ok.primary_intent == "clarify"


def test_a_clarify_intent_without_a_request_is_rejected():
    """IR-3."""

    with pytest.raises(ValidationError, match="needs a ClarificationRequest"):
        _intent(
            intents=(ScoredIntent(intent="clarify", score=0.5),),
            confidence=0.5,
        )


def test_forecast_requires_a_horizon_and_nothing_else_may_carry_one():
    """IR-4."""

    with pytest.raises(ValidationError, match="requires a horizon"):
        _intent(intents=(ScoredIntent(intent="forecast", score=0.9),))

    with pytest.raises(ValidationError, match="only meaningful for the forecast"):
        _intent(
            entities=Entities(
                metric_id="revenue",
                horizon=Horizon(periods=3, grain="month", anchor="2018-08"),
            ),
        )


def test_scenario_requires_parameters_and_nothing_else_may_carry_them():
    """IR-5."""

    shock = ScenarioParam(
        target="list_price",
        kind="multiplicative",
        value=1.05,
        source_phrase="raise prices 5%",
    )

    with pytest.raises(ValidationError, match="requires at least one scenario"):
        _intent(intents=(ScoredIntent(intent="scenario", score=0.9),))

    with pytest.raises(ValidationError, match="only meaningful for the scenario"):
        _intent(entities=Entities(metric_id="revenue", scenario_params=(shock,)))

    ok = _intent(
        intents=(ScoredIntent(intent="scenario", score=0.9),),
        entities=Entities(metric_id="gmv", scenario_params=(shock,)),
    )
    assert ok.entities.scenario_params[0].value == 1.05


def test_a_remove_scenario_must_name_what_it_removes():
    with pytest.raises(ValidationError, match="must name what it removes"):
        ScenarioParam(
            target="customer_state",
            kind="remove",
            value=0.0,
            source_phrase="lose SP entirely",
        )

    ok = ScenarioParam(
        target="customer_state",
        kind="remove",
        value=0.0,
        applies_to=ScenarioAppliesTo(dimension="customer_state", values=("SP",)),
        source_phrase="lose SP entirely",
    )
    assert ok.applies_to is not None


def test_a_multiplicative_shock_must_be_positive():
    with pytest.raises(ValidationError, match="must be positive"):
        ScenarioParam(
            target="freight_value",
            kind="multiplicative",
            value=-1.1,
            source_phrase="freight falls",
        )


def test_the_intent_to_route_mapping_covers_every_intent():
    """Section 9: a V1 client must never see an empty route."""

    for name in v2.INTENT_NAMES:
        assert route_for_intent(name) in (
            "lookup",
            "anomaly",
            "driver",
            "risk",
            "clarify",
            "refused",
            "blocked",
        )

    compound = _intent(
        intents=(
            ScoredIntent(intent="descriptive", score=0.9),
            ScoredIntent(intent="discovery", score=0.8),
        ),
    )
    # Both map to "lookup"; the label is de-duplicated, not repeated.
    assert compound.route_labels == ("lookup",)


# --------------------------------------------------------------------------- #
# Section 4 — ClarificationRequest
# --------------------------------------------------------------------------- #


def test_the_example_clarification_parses_and_round_trips():
    request = _clarification()
    restored = ClarificationRequest.model_validate(request.model_dump(mode="json"))
    assert restored == request
    assert request.round == 1


def test_a_clarification_asks_exactly_one_question():
    """CL-1."""

    with pytest.raises(ValidationError, match="exactly one question"):
        _clarification(question="Which metric? And which window?")


def test_a_clarification_needs_between_two_and_four_options():
    """CL-2."""

    one = (
        ClarificationOption(
            option_id="O1", label="Only choice", resolves_to={"grain": "month"}
        ),
    )
    with pytest.raises(ValidationError):
        _clarification(options=one)

    five = tuple(
        ClarificationOption(
            option_id=f"O{i}", label=f"Option {i}", resolves_to={"grain": "month"}
        )
        for i in range(1, 6)
    )
    with pytest.raises(ValidationError):
        _clarification(options=five)


def test_the_default_must_be_one_of_the_offered_options():
    """CL-3: there is always a default, and it is reachable."""

    with pytest.raises(ValidationError, match="not one of"):
        _clarification(
            default_assumption=DefaultAssumption(
                option_id="O9", rationale="Points at nothing."
            ),
        )


def test_a_clarification_is_bounded_to_two_rounds():
    """CL-4."""

    with pytest.raises(ValidationError):
        _clarification(round=3)

    second = _clarification(round=2, of_run_id="run1")
    assert second.round == 2


def test_a_second_round_must_name_the_run_it_clarifies():
    with pytest.raises(ValidationError, match="must name the run"):
        _clarification(round=2)


def test_at_most_one_option_is_recommended():
    """CL-5."""

    both = (
        ClarificationOption(
            option_id="O1",
            label="A",
            resolves_to={"grain": "month"},
            recommended=True,
        ),
        ClarificationOption(
            option_id="O2",
            label="B",
            resolves_to={"grain": "week"},
            recommended=True,
        ),
    )
    with pytest.raises(ValidationError, match="at most one option"):
        _clarification(
            options=both,
            default_assumption=DefaultAssumption(option_id="O1", rationale="A."),
        )


def test_an_option_patch_must_name_resolved_question_fields():
    """CL-6: accepting an option is deterministic, not reinterpreted."""

    with pytest.raises(ValidationError, match="patch ResolvedQuestion fields"):
        ClarificationOption(
            option_id="O1", label="A", resolves_to={"not_a_field": 1}
        )


def test_an_option_that_resolves_nothing_is_not_a_choice():
    with pytest.raises(ValidationError, match="must resolve something"):
        ClarificationOption(option_id="O1", label="A", resolves_to={})


def test_option_ids_must_be_unique():
    duplicate = (
        ClarificationOption(
            option_id="O1", label="A", resolves_to={"grain": "month"}
        ),
        ClarificationOption(
            option_id="O1", label="B", resolves_to={"grain": "week"}
        ),
    )
    with pytest.raises(ValidationError, match="unique"):
        _clarification(options=duplicate)


# --------------------------------------------------------------------------- #
# Section 5 — Plan and PlanStep
# --------------------------------------------------------------------------- #


def test_the_tool_registry_is_closed():
    """ANA-2, B0: a planner cannot invent a step or pass code."""

    assert len(TOOL_NAMES) == 9
    with pytest.raises(ValidationError):
        _sql_step(tool="python.custom")
    with pytest.raises(ValidationError):
        _sql_step(tool="shell")

    # And no field anywhere accepts a code string.
    for name in TOOL_NAMES:
        assert "exec" not in name and "eval" not in name


def test_a_plan_with_a_cycle_is_rejected():
    """PL-1."""

    steps = (
        _sql_step("P1", depends_on=("P2",)),
        _sql_step("P2", depends_on=("P1",)),
    )
    with pytest.raises(ValidationError, match="cycle"):
        _plan(steps=steps, depth=2, intents_covered=("descriptive",))


def test_a_plan_depending_on_an_unknown_step_is_rejected():
    """PL-1."""

    with pytest.raises(ValidationError, match="unknown step"):
        _plan(
            steps=(_sql_step("P1", depends_on=("P9",)),),
            depth=1,
            intents_covered=("descriptive",),
        )


def test_a_step_cannot_depend_on_itself():
    with pytest.raises(ValidationError, match="depend on itself"):
        _sql_step("P1", depends_on=("P1",))


def test_declared_depth_must_match_the_real_longest_chain():
    """PL-2: depth cannot be understated to slip past the cap."""

    steps = (
        _sql_step("P1"),
        _engine_step("P2", "python.forecast", ("P1",)),
    )
    with pytest.raises(ValidationError, match="does not match the longest"):
        _plan(steps=steps, depth=1)

    assert _plan(steps=steps, depth=2).execution_order() == ("P1", "P2")


def test_a_plan_deeper_than_the_cap_is_rejected():
    """PL-2."""

    steps = [_sql_step("P1")]
    for index in range(2, MAX_PLAN_DEPTH + 3):
        steps.append(
            _engine_step(f"P{index}", "python.impact", (f"P{index - 1}",))
        )
    with pytest.raises(ValidationError):
        _plan(
            steps=tuple(steps),
            depth=len(steps),
            intents_covered=("impact",),
            budget=StepBudget(max_queries=1, max_engine_calls=10),
        )


def test_a_scenario_step_must_perturb_a_real_fit():
    """PL-4: a scenario with no fit behind it is a fabricated number."""

    orphan = (
        _sql_step("P1"),
        _engine_step("P2", "python.scenario", ("P1",)),
    )
    with pytest.raises(ValidationError, match="must depend on a fit"):
        _plan(steps=orphan, depth=2, intents_covered=("scenario",))

    grounded = (
        _sql_step("P1"),
        _engine_step("P2", "python.forecast", ("P1",)),
        _engine_step("P3", "python.scenario", ("P2",)),
    )
    plan = _plan(
        steps=grounded,
        depth=3,
        intents_covered=("forecast", "scenario"),
        budget=StepBudget(max_queries=1, max_engine_calls=2),
    )
    assert plan.execution_order() == ("P1", "P2", "P3")


def test_an_engine_may_not_consume_another_engines_rows():
    """PL-5: engines read tables the orchestrator supplies (SAFE-8)."""

    steps = (
        _sql_step("P1"),
        PlanStep(
            step_id="P2",
            tool="python.driver",
            depends_on=("P1",),
            produces="rows",
            purpose="Pretend an engine emitted rows.",
        ),
        _engine_step("P3", "python.impact", ("P2",)),
    )
    with pytest.raises(ValidationError, match="may take rows only from"):
        _plan(
            steps=steps,
            depth=3,
            intents_covered=("impact",),
            budget=StepBudget(max_queries=1, max_engine_calls=2),
        )


def test_an_engine_may_consume_an_analytical_table():
    """PL-5: analytical_table is a data tool, like sql."""

    steps = (
        PlanStep(
            step_id="P1",
            tool="analytical_table",
            produces="rows",
            purpose="Read the precomputed monthly series.",
        ),
        _engine_step("P2", "python.forecast", ("P1",)),
    )
    plan = _plan(steps=steps, depth=2, intents_covered=("forecast",))
    assert plan.steps[0].tool == "analytical_table"


def test_a_plan_over_its_query_budget_is_rejected_at_planning_time():
    """PL-6: drop an intent explicitly, do not truncate at execution."""

    steps = tuple(_sql_step(f"P{i}") for i in range(1, 5))
    with pytest.raises(ValidationError, match="needs 4 queries"):
        _plan(
            steps=steps,
            depth=1,
            intents_covered=("descriptive",),
            budget=StepBudget(max_queries=3),
        )

    ok = _plan(
        steps=steps,
        depth=1,
        intents_covered=("descriptive",),
        budget=StepBudget(max_queries=4),
    )
    assert len(ok.steps) == 4


def test_a_plan_over_its_engine_budget_is_rejected():
    """PL-6."""

    steps = (
        _sql_step("P1"),
        _engine_step("P2", "python.anomaly", ("P1",)),
        _engine_step("P3", "python.driver", ("P1",)),
    )
    with pytest.raises(ValidationError, match="engine calls"):
        _plan(
            steps=steps,
            depth=2,
            intents_covered=("diagnostic",),
            budget=StepBudget(max_queries=1, max_engine_calls=1),
        )


def test_an_intent_cannot_be_both_covered_and_dropped():
    """PL-7: nothing vanishes without a stated reason."""

    with pytest.raises(ValidationError, match="both covered and dropped"):
        _plan(
            intents_covered=("forecast",),
            intents_dropped=(
                DroppedIntent(intent="forecast", reason="Horizon too long."),
            ),
        )


def test_a_plan_must_cover_or_drop_at_least_one_intent():
    """PL-7."""

    with pytest.raises(ValidationError, match="either cover or explicitly drop"):
        _plan(intents_covered=(), intents_dropped=())


def test_a_dropped_intent_carries_its_reason():
    plan = _plan(
        intents_covered=("forecast",),
        intents_dropped=(
            DroppedIntent(
                intent="scenario",
                reason="No fitted relationship was available to perturb.",
            ),
        ),
    )
    assert plan.intents_dropped[0].reason


def test_step_ids_must_be_unique_within_a_plan():
    with pytest.raises(ValidationError, match="unique"):
        _plan(
            steps=(_sql_step("P1"), _sql_step("P1")),
            depth=1,
            intents_covered=("descriptive",),
        )


def test_the_k10_diagnostic_plan_from_the_spec_validates():
    """The flagship compound path: diagnostic -> impact -> prescriptive."""

    steps = (
        _sql_step("P1"),
        _engine_step("P2", "python.anomaly", ("P1",)),
        # P3 deliberately depends on nothing: the by-category query needs only
        # the window, which is known at planning time, not the anomaly
        # verdict. Making it wait pushed the chain to depth 6 and over the cap
        # for no benefit, and also serialised two queries that can run in
        # parallel (OPS-5).
        _sql_step("P3"),
        _engine_step("P4", "python.driver", ("P3",)),
        _engine_step("P5", "python.impact", ("P2", "P4")),
        PlanStep(
            step_id="P6",
            tool="catalog",
            depends_on=("P4",),
            produces="catalog_facts",
            optional=True,
            purpose="Retrieve candidate actions for the driver type.",
        ),
        PlanStep(
            step_id="P7",
            tool="python.segment",
            depends_on=("P5", "P6"),
            produces="ranked_options",
            optional=True,
            purpose="Rank actions by quantified impact and feasibility.",
        ),
    )
    plan = _plan(
        steps=steps,
        depth=4,
        intents_covered=("diagnostic", "impact", "prescriptive"),
        budget=StepBudget(
            max_queries=4, max_engine_calls=5, max_tokens=8192, max_wall_ms=25_000
        ),
    )

    order = plan.execution_order()
    assert order.index("P1") < order.index("P2") < order.index("P4")
    assert order.index("P5") < order.index("P7")
    # It needs more than V1's three-query default, which is why V2-PRE-2 exists.
    assert sum(1 for step in plan.steps if step.tool == "sql") == 2
    assert plan.depth == 4
    assert plan.depth <= MAX_PLAN_DEPTH
    # The two queries are independent, so neither waits on the other (OPS-5).
    assert plan.steps[2].depends_on == ()


# --------------------------------------------------------------------------- #
# Section 5.1 — Precomputed analytical tables
# --------------------------------------------------------------------------- #


def _anomaly_row(**overrides) -> AnomalyRow:
    payload = {
        "kpi": "revenue",
        "date": "2018-04-01",
        "grain": "month",
        "value": 900_000.0,
        "expected": 1_000_000.0,
        "delta": -100_000.0,
        "delta_pct": -10.0,
        "direction": "dip",
        "score": -3.4,
        "flagged": True,
        "correction": "benjamini_hochberg_0.05",
        "computed_at": "2026-10-30T02:00:00Z",
        "engine_version": "2.0.0",
        "catalog_version": "olist-2026-10-01",
    }
    payload.update(overrides)
    return AnomalyRow(**payload)


def test_an_anomaly_rows_delta_must_follow_from_its_own_figures():
    """A restated delta would detach the figure from its evidence."""

    with pytest.raises(ValidationError, match="delta must equal"):
        _anomaly_row(delta=-5.0)


def test_an_anomaly_rows_direction_must_match_its_delta():
    with pytest.raises(ValidationError, match="contradicts a delta"):
        _anomaly_row(direction="spike")


def test_an_anomaly_row_is_either_total_or_dimensioned():
    with pytest.raises(ValidationError, match="both be set"):
        _anomaly_row(dimension="customer_state")

    ok = _anomaly_row(dimension="customer_state", dimension_value="SP")
    assert ok.dimension_value == "SP"


def _forecast_row(**overrides) -> ForecastRow:
    payload = {
        "kpi": "revenue",
        "grain": "month",
        "anchor_period": "2018-08",
        "ds": "2018-09",
        "yhat": 1_053_182.44,
        "yhat_lower": 862_405.10,
        "yhat_upper": 1_243_959.78,
        "model": "ets",
        "model_fallback_reason": "Prophet needs >= 24 monthly periods.",
        "mape": 0.118,
        "computed_at": "2026-10-30T02:00:00Z",
        "engine_version": "2.0.0",
        "catalog_version": "olist-2026-10-01",
    }
    payload.update(overrides)
    return ForecastRow(**payload)


def test_a_forecast_interval_must_bracket_its_estimate():
    with pytest.raises(ValidationError, match="must bracket"):
        _forecast_row(yhat=2_000_000.0)


def test_a_forecast_period_must_be_after_its_anchor():
    """AT-3: fitting across the period being predicted is leakage."""

    with pytest.raises(ValidationError, match="must be after the anchor"):
        _forecast_row(ds="2018-07")


def test_an_ets_fallback_must_say_why():
    """TR-8: a silent method change misleads about how a figure was made."""

    with pytest.raises(ValidationError, match="must state why"):
        _forecast_row(model_fallback_reason=None)


def test_a_primary_model_carries_no_fallback_reason():
    with pytest.raises(ValidationError, match="only meaningful for a fallback"):
        _forecast_row(model="prophet")

    ok = _forecast_row(model="prophet", model_fallback_reason=None)
    assert ok.model == "prophet"


def test_an_unbacktested_forecast_keeps_a_null_mape_not_a_zero():
    """AT-4: null means "not backtested" and must never render as 0."""

    row = _forecast_row(mape=None)
    assert row.mape is None

    with pytest.raises(ValidationError):
        _forecast_row(mape=-0.1)


# --------------------------------------------------------------------------- #
# Section 6 — ToolResult
# --------------------------------------------------------------------------- #


def test_a_language_model_cannot_be_a_source_of_figures():
    """TR-3: SAFE-8 held at the type level.

    ProvenanceSource has no "model" member and ToolResult has no model
    payload variant, so there is no way to construct a result whose numbers
    came from prose.
    """

    assert set(v2.ProvenanceSource.__args__) == {"sql", "engine", "catalog"}
    with pytest.raises(ValidationError):
        ToolProvenance(source="model")

    assert "model" not in v2._PAYLOAD_FIELDS


def test_exactly_one_payload_matching_produces():
    """TR-1."""

    with pytest.raises(ValidationError, match="must set exactly"):
        _sql_result(rows=None)

    with pytest.raises(ValidationError, match="must set exactly"):
        _sql_result(
            produces="catalog_facts",
            catalog_facts=CatalogFactsPayload(catalog_version="v1"),
        )

    with pytest.raises(ValidationError, match="must set exactly"):
        _sql_result(
            catalog_facts=CatalogFactsPayload(catalog_version="v1"),
        )


def test_a_non_ok_status_always_says_why():
    """TR-2: an engine returns insufficient_evidence with a reason (ANA-4)."""

    with pytest.raises(ValidationError, match="needs a reason"):
        ToolResult(
            step_id="P2",
            tool="python.scenario",
            status="insufficient_evidence",
            produces="analyst_output",
            provenance=ToolProvenance(
                source="engine", engine=_engine_provenance()
            ),
            duration_ms=3,
        )

    ok = ToolResult(
        step_id="P2",
        tool="python.scenario",
        status="insufficient_evidence",
        produces="analyst_output",
        provenance=ToolProvenance(source="engine", engine=_engine_provenance()),
        reason="No fitted price relationship was available to perturb.",
        duration_ms=3,
    )
    assert ok.analyst_output is None


def test_a_failed_step_carries_no_payload():
    """TR-1."""

    with pytest.raises(ValidationError, match="carries no payload"):
        _sql_result(status="error", reason="The warehouse timed out.")


def test_an_empty_result_is_a_finding_not_a_failure():
    """TR-6, SQL-12: a true zero-row result is distinct from a failure."""

    empty = _sql_result(
        status="empty",
        rows=_rows_payload(rows=(), row_count=0),
        reason="No orders matched the filter in this window.",
    )
    assert empty.rows is not None
    assert empty.rows.row_count == 0

    with pytest.raises(ValidationError, match="requires row_count 0"):
        _sql_result(status="empty", reason="Says empty but carries a row.")


def test_deterministic_tools_cannot_claim_otherwise():
    """TR-5."""

    with pytest.raises(ValidationError, match="deterministic by construction"):
        _sql_result(
            provenance=ToolProvenance(
                source="sql", query_ids=("Q1",), deterministic=False
            ),
        )


def test_a_seeded_engine_is_reproducible_and_an_unseeded_one_is_not():
    """TR-5."""

    with pytest.raises(ValidationError, match="must be marked deterministic"):
        ToolResult(
            step_id="P2",
            tool="python.anomaly",
            status="ok",
            produces="analyst_output",
            analyst_output=_analyst_output(),
            provenance=ToolProvenance(
                source="engine",
                engine=_engine_provenance(seed=0),
                deterministic=False,
            ),
            duration_ms=41,
        )

    with pytest.raises(ValidationError, match="must not claim determinism"):
        ToolResult(
            step_id="P2",
            tool="python.anomaly",
            status="ok",
            produces="analyst_output",
            analyst_output=_analyst_output(),
            provenance=ToolProvenance(
                source="engine",
                engine=_engine_provenance(seed=None),
                deterministic=True,
            ),
            duration_ms=41,
        )


def test_engine_provenance_is_required_for_an_engine_result():
    with pytest.raises(ValidationError, match="must name its engine"):
        ToolProvenance(source="engine")

    with pytest.raises(ValidationError, match="only meaningful for an engine"):
        ToolProvenance(source="sql", engine=_engine_provenance())


def test_a_cached_engine_row_keeps_its_engine_attribution():
    """AT-1: reading the cache must not launder a figure into plain SQL."""

    with pytest.raises(ValidationError, match="must keep source 'engine'"):
        ToolResult(
            step_id="P1",
            tool="analytical_table",
            status="ok",
            produces="analyst_output",
            analyst_output=_analyst_output(),
            provenance=ToolProvenance(source="sql", query_ids=("Q1",)),
            duration_ms=4,
        )

    ok = ToolResult(
        step_id="P1",
        tool="analytical_table",
        status="ok",
        produces="analyst_output",
        analyst_output=_analyst_output(),
        provenance=ToolProvenance(
            source="engine", engine=_engine_provenance(), query_ids=("Q1",)
        ),
        duration_ms=4,
    )
    assert ok.provenance.source == "engine"


def test_synthetic_data_must_be_labelled_in_the_result():
    """SY-1, V2-SYN-4: a generated figure is never presented as a measurement."""

    with pytest.raises(ValidationError, match="synthetic caveat"):
        _sql_result(
            provenance=ToolProvenance(
                source="sql",
                query_ids=("Q1",),
                data_layer="synthetic",
                synthetic_tables=("marketing_spend",),
            ),
        )

    ok = _sql_result(
        provenance=ToolProvenance(
            source="sql",
            query_ids=("Q1",),
            data_layer="synthetic",
            synthetic_tables=("marketing_spend",),
        ),
        caveats=(
            "marketing_spend is synthetic data generated for this "
            "environment, not a measurement of the real business.",
        ),
    )
    assert ok.provenance.data_layer == "synthetic"


def test_the_synthetic_label_cannot_be_dropped_or_faked():
    """SY-1 both ways."""

    with pytest.raises(ValidationError, match="cannot claim data_layer 'real'"):
        ToolProvenance(
            source="sql", data_layer="real", synthetic_tables=("promotions",)
        )

    with pytest.raises(ValidationError, match="must name the synthetic tables"):
        ToolProvenance(source="sql", data_layer="mixed", synthetic_tables=())


def test_rows_must_match_their_declared_columns():
    with pytest.raises(ValidationError, match="values but"):
        _rows_payload(rows=(("2018-08",),))


def test_row_count_cannot_understate_the_rows_carried():
    with pytest.raises(ValidationError, match="must not understate"):
        _rows_payload(rows=(("2018-08", 1.0), ("2018-07", 2.0)), row_count=1)


def test_out_of_line_rows_need_a_reference():
    with pytest.raises(ValidationError, match="result_ref"):
        _rows_payload(rows=(), row_count=5000)

    ok = _rows_payload(rows=(), row_count=5000, result_ref="artifact://af_1")
    assert ok.result_ref == "artifact://af_1"


def test_the_example_forecast_tool_result_parses_and_round_trips():
    """The worked example from contracts.md section 6."""

    result = ToolResult(
        step_id="P2",
        tool="python.anomaly",
        status="ok",
        produces="analyst_output",
        analyst_output=_analyst_output(),
        provenance=ToolProvenance(
            source="engine",
            query_ids=("Q1",),
            engine=_engine_provenance(),
            input_step_ids=("P1",),
            deterministic=True,
        ),
        caveats=(
            "The trend interval spans zero, so no trend is statistically "
            "detectable.",
            "Backtest error on the held-out tail was 11.8% (MAPE).",
        ),
        duration_ms=41,
    )

    restored = ToolResult.model_validate(result.model_dump(mode="json"))
    assert restored == result
    assert result.provenance.engine is not None
    assert result.provenance.engine.method == "ets"
    assert result.provenance.engine.fit_quality is not None
    assert result.provenance.engine.fit_quality.value == 0.118


# --------------------------------------------------------------------------- #
# Section 7 — VisualizationSpec
# --------------------------------------------------------------------------- #


def test_a_visualization_carries_no_data_only_column_references():
    """VZ-1: the data is the referenced ToolResult, not the spec."""

    spec = _viz()
    dumped = spec.model_dump(mode="json")
    assert "rows" not in dumped
    assert "data" not in dumped
    assert dumped["encoding"]["x"]["column"] == "period"


def test_an_annotation_stating_a_number_must_cite_its_claim():
    """VZ-2, SAFE-3: an annotation is not a place to introduce a figure."""

    with pytest.raises(ValidationError, match="must cite the claim"):
        VizAnnotation(
            kind="point",
            at=VizAnnotationAt(x="2018-08", y=1_053_182.44),
            label="August",
        )

    ok = VizAnnotation(
        kind="point",
        at=VizAnnotationAt(x="2018-08", y=1_053_182.44),
        label="August",
        claim_id="C4",
    )
    assert ok.claim_id == "C4"


def test_a_top_n_chart_must_report_its_remainder():
    """VZ-3: the frontend never slices rows of its own."""

    with pytest.raises(ValidationError, match="excluded remainder"):
        _viz(encoding=_encoding(limit=5), caption="")

    ok = _viz(
        encoding=_encoding(limit=5),
        caption="Top 5 categories; the remaining 66 total BRL 2.1M.",
    )
    assert ok.encoding.limit == 5


def test_emphasis_is_semantic_never_a_colour():
    """VZ-4: the frontend owns its palette."""

    assert set(v2.VizEmphasis.__args__) == {"normal", "attention"}
    with pytest.raises(ValidationError):
        VizAnnotation(
            kind="line",
            at=VizAnnotationAt(x="2018-08"),
            label="Last complete month",
            emphasis="terracotta",
        )


def test_a_forecast_fan_must_encode_its_interval():
    """VZ-5: a forecast without its interval misrepresents itself."""

    with pytest.raises(ValidationError, match="prediction interval"):
        _viz(kind="forecast_fan")

    ok = _viz(
        kind="forecast_fan",
        encoding=_encoding(
            band=VizBand(
                lower_column="yhat_lower",
                upper_column="yhat_upper",
                label="95% prediction interval",
            )
        ),
    )
    assert ok.encoding.band is not None


def test_the_zero_baseline_choice_is_always_explicit():
    """VZ-7: a truncated axis overstates a change."""

    with pytest.raises(ValidationError, match="zero_baseline must be stated"):
        VizEncoding(
            x=VizAxis(column="period", role="time", label="Month"),
            y=VizAxis(column="value", role="measure", label="Revenue"),
        )


def test_axes_must_carry_the_right_roles():
    with pytest.raises(ValidationError, match="not a measure"):
        VizEncoding(
            x=VizAxis(column="value", role="measure", label="Revenue"),
            y=VizAxis(
                column="value", role="measure", label="Revenue", zero_baseline=True
            ),
        )


def test_a_visualization_must_reference_the_data_it_draws():
    with pytest.raises(ValidationError, match="must reference the data"):
        _viz(source_query_id=None, source_artifact_id=None)


# --------------------------------------------------------------------------- #
# Section 8 — AnswerEnvelopeV2
# --------------------------------------------------------------------------- #


def test_a_v2_envelope_keeps_every_v1_field():
    """Additive: the existing frontend renders a V2 envelope unchanged."""

    for name in v1.AnswerEnvelope.model_fields:
        assert name in AnswerEnvelopeV2.model_fields, name
    assert _envelope().contract_version == CONTRACT_VERSION == "2.0.0"


def test_the_contract_version_is_pinned_to_two_zero_zero():
    """EN-8: the frontend keys its parsing on this."""

    with pytest.raises(ValidationError):
        _envelope(contract_version="1.0.0")


def test_a_clarify_answer_must_carry_its_clarification():
    """EN-1."""

    with pytest.raises(ValidationError, match="must carry its clarification"):
        _envelope(status="clarify")

    ok = _envelope(status="clarify", clarification=_clarification())
    assert ok.clarification is not None
    # V1's two prose fields survive, so the SSE clarify event is unaffected.
    assert ok.clarification.what_understood
    assert ok.clarification.what_needs_clarification


def test_every_planned_step_is_reported_in_plan_order():
    """EN-2: a step that ran and is not reported is a reporting failure."""

    plan = _plan()
    only_one = (
        StepResultSummary(
            step_id="P1",
            tool="sql",
            status="ok",
            purpose="Monthly revenue series.",
            summary="Returned 23 monthly revenue totals.",
            duration_ms=184,
        ),
    )
    with pytest.raises(ValidationError, match="every planned step"):
        _envelope(plan=plan, step_results=only_one)

    both = only_one + (
        StepResultSummary(
            step_id="P2",
            tool="python.anomaly",
            status="ok",
            purpose="Project revenue three months out.",
            summary="Projected three months with a 95% interval.",
            duration_ms=41,
        ),
    )
    ok = _envelope(plan=plan, step_results=both)
    assert [summary.step_id for summary in ok.step_results] == ["P1", "P2"]


def test_step_results_out_of_plan_order_are_rejected():
    """EN-2: order is part of the report."""

    plan = _plan()
    reversed_results = (
        StepResultSummary(
            step_id="P2",
            tool="python.anomaly",
            status="ok",
            purpose="Project revenue.",
            summary="Projected three months.",
            duration_ms=41,
        ),
        StepResultSummary(
            step_id="P1",
            tool="sql",
            status="ok",
            purpose="Monthly revenue series.",
            summary="Returned 23 totals.",
            duration_ms=184,
        ),
    )
    with pytest.raises(ValidationError, match="plan order"):
        _envelope(plan=plan, step_results=reversed_results)


def test_step_results_without_a_plan_are_rejected():
    """EN-2."""

    with pytest.raises(ValidationError, match="nothing to report against"):
        _envelope(
            step_results=(
                StepResultSummary(
                    step_id="P1",
                    tool="sql",
                    status="ok",
                    purpose="A step with no plan.",
                    summary="Orphaned.",
                    duration_ms=1,
                ),
            ),
        )


def test_a_skipped_step_must_say_why():
    with pytest.raises(ValidationError, match="must say why"):
        StepResultSummary(
            step_id="P6",
            tool="python.scenario",
            status="skipped",
            purpose="Perturb the forecast.",
            summary="Not run.",
            duration_ms=0,
        )


def test_every_resolution_assumption_reaches_the_envelope():
    """EN-4: an assumption the user cannot see is a trap."""

    resolved = _resolved(
        assumptions=(
            "2018 was read as 2018-01 to 2018-08: later months are incomplete.",
        ),
    )
    with pytest.raises(ValidationError, match="must appear in the envelope"):
        _envelope(resolved_question=resolved, assumptions=())

    ok = _envelope(
        resolved_question=resolved,
        assumptions=resolved.assumptions,
    )
    assert ok.assumptions == resolved.assumptions


def test_a_follow_up_is_answerable_by_construction():
    """EN-5: there is no way to offer a question the backend cannot answer."""

    suggestion = FollowUpSuggestion(
        text="Why did revenue fall in August 2018?",
        intent="diagnostic",
        rationale="August is the anchor of the projection.",
    )
    assert suggestion.answerable is True

    with pytest.raises(ValidationError):
        FollowUpSuggestion(
            text="Something unanswerable",
            intent="diagnostic",
            rationale="Guessed.",
            answerable=False,
        )


def test_next_actions_belong_to_the_prescriptive_intent():
    """EN-6: closing V1's hardcoded empty tuple, without widening it."""

    action = v1.ActionOption(
        action_id="A1",
        title="Restore paid-search spend in SP",
        rank=1,
        kind="intervention",
    )

    with pytest.raises(ValidationError, match="prescriptive intent"):
        _envelope(
            intent=_intent(),
            next_actions=(action,),
            route=RouteSummary(
                labels=("lookup",), confidence=0.92, reason="Lookup."
            ),
        )

    ok = _envelope(
        intent=_intent(
            intents=(ScoredIntent(intent="prescriptive", score=0.9),),
            entities=Entities(metric_id="revenue"),
        ),
        next_actions=(action,),
        route=RouteSummary(labels=("risk",), confidence=0.92, reason="Advice."),
    )
    assert ok.next_actions[0].action_id == "A1"


def test_route_labels_follow_the_documented_intent_mapping():
    """Section 9: a V1 client is not broken by a V2 run."""

    with pytest.raises(ValidationError, match="documented intent mapping"):
        _envelope(
            intent=_intent(
                intents=(ScoredIntent(intent="forecast", score=0.9),),
                entities=Entities(
                    metric_id="revenue",
                    horizon=Horizon(periods=3, grain="month", anchor="2018-08"),
                ),
            ),
            route=RouteSummary(
                labels=("lookup",), confidence=0.9, reason="Wrong label."
            ),
        )

    ok = _envelope(
        intent=_intent(
            intents=(ScoredIntent(intent="forecast", score=0.9),),
            entities=Entities(
                metric_id="revenue",
                horizon=Horizon(periods=3, grain="month", anchor="2018-08"),
            ),
        ),
        route=RouteSummary(
            labels=("risk",), confidence=0.9, reason="Forward-looking."
        ),
    )
    assert ok.route.labels == ("risk",)


def test_the_full_k1_envelope_round_trips():
    """The compound must-answer question, end to end through the contracts."""

    resolved = _resolved(
        text="How does revenue trend look today and what will it be in 3 months?",
        assumptions=(
            '"Today" was read as the last complete month, 2018-08.',
            "2018-09 and 2018-10 were excluded as incomplete.",
        ),
    )
    intent = _intent(
        intents=(
            ScoredIntent(intent="descriptive", score=0.94),
            ScoredIntent(intent="forecast", score=0.91),
        ),
        entities=Entities(
            metric_id="revenue",
            period=YEAR_2018,
            grain="month",
            horizon=Horizon(periods=3, grain="month", anchor="2018-08"),
        ),
    )
    plan = _plan(intents_covered=("descriptive", "forecast"))
    envelope = _envelope(
        resolved_question=resolved,
        intent=intent,
        plan=plan,
        step_results=(
            StepResultSummary(
                step_id="P1",
                tool="sql",
                status="ok",
                purpose="Monthly revenue series.",
                summary="Returned 23 monthly revenue totals.",
                claim_ids=("C1", "C2", "C3"),
                duration_ms=184,
            ),
            StepResultSummary(
                step_id="P2",
                tool="python.forecast",
                status="ok",
                purpose="Project revenue three months out.",
                summary="Projected three months; no trend was detectable.",
                claim_ids=("C4", "C5"),
                duration_ms=41,
            ),
        ),
        visualizations=(
            _viz(
                kind="forecast_fan",
                encoding=_encoding(
                    band=VizBand(
                        lower_column="yhat_lower",
                        upper_column="yhat_upper",
                        label="95% prediction interval",
                    )
                ),
                claim_ids=("C4", "C5"),
            ),
        ),
        assumptions=resolved.assumptions,
        follow_ups=(
            FollowUpSuggestion(
                text="Why did revenue fall in August 2018?",
                intent="diagnostic",
                rationale="August anchors the projection.",
            ),
        ),
        route=RouteSummary(
            labels=("lookup", "risk"),
            confidence=0.92,
            reason="A trend report plus a 3-month forecast.",
        ),
    )

    restored = AnswerEnvelopeV2.model_validate(envelope.model_dump(mode="json"))
    assert restored == envelope
    assert restored.intent is not None
    assert restored.intent.intent_names == ("descriptive", "forecast")
    assert len(restored.step_results) == 2
    assert restored.visualizations[0].kind == "forecast_fan"


def test_the_module_reexports_cleanly_without_shadowing_v1():
    """Importing both modules must not silently rebind a V1 name."""

    reloaded = importlib.reload(v2)
    assert reloaded.PlanStep is not v1.PlanStep
    assert reloaded.Period is v1.Period
