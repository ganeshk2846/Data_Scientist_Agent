"""Planner: DAG validation, tool params schemas, compound coverage, analytical preference (PL-1..7)."""

from __future__ import annotations

import pytest
from contracts.v2 import Plan, PlanStep, StepBudget
from grounding import Grounder
from intent import IntentExtractor
from planner import Capabilities, Planner, PlanValidationError, validate_plan
from pydantic import ValidationError
from semantic.metrics_v2 import all_metrics

KPIS = frozenset({"revenue", "gmv", "order_count", "aov", "cancellation_rate", "review_score", "item_count", "customer_count", "freight_value"})


def _plan(question, *, analytical=True):
    extraction = IntentExtractor().extract(question)
    grounded = Grounder(all_metrics()).ground(extraction)
    planner = Planner(Capabilities(analytical=analytical, synthetic=True, analytical_kpis=KPIS if analytical else frozenset()))
    return planner.plan(grounded.intent, grounded.resolved, special=grounded.special)


def _step(step_id, tool="sql", depends_on=(), params=None, produces="rows"):
    return PlanStep(step_id=step_id, tool=tool, params=params or {"kind": "metric", "metric_id": "revenue"}, depends_on=depends_on,
                    produces=produces, purpose="test")


def test_k1_shares_one_series_query_between_trend_and_forecast():
    plan = _plan("How does revenue trend look today and what will it be in 3 months?")
    assert [step.tool for step in plan.steps] == ["sql", "python.forecast"]
    assert plan.steps[1].depends_on == ("P1",)
    assert plan.steps[0].params["summary"] == "trend"
    assert plan.steps[0].params["summary_period"]["start"] == "2017-09-01", "the trend keeps the asked window"
    assert plan.steps[1].params["horizon"] == 3
    assert set(plan.intents_covered) == {"descriptive", "forecast"}


def test_precomputed_tables_are_preferred_and_live_engines_used_otherwise():
    cached = _plan("What are the spikes across all months?")
    assert [step.tool for step in cached.steps] == ["analytical_table"]
    live = _plan("What are the spikes across all months?", analytical=False)
    assert [step.tool for step in live.steps].count("python.anomaly") == 3
    assert all(step.tool in {"sql", "python.anomaly"} for step in live.steps)


def test_every_compound_question_covers_or_explicitly_drops_each_intent():
    for question in ("Why did revenue fall and what should we do?", "Forecast revenue and tell me what happens if freight rises 10%",
                     "Why did August fall, what did it cost, and what should we do?", "Compare 2017 and 2018 and tell me what to watch"):
        extraction = IntentExtractor().extract(question)
        grounded = Grounder(all_metrics()).ground(extraction)
        plan = Planner(Capabilities(analytical_kpis=KPIS)).plan(grounded.intent, grounded.resolved, special=grounded.special)
        accepted = set(grounded.intent.intent_names)
        assert set(plan.intents_covered) | {item.intent for item in plan.intents_dropped} == accepted, question
        assert all(item.reason for item in plan.intents_dropped)


def test_a_scenario_always_depends_on_a_fit():
    plan = _plan("What if we raise prices 5%?")
    scenario = next(step for step in plan.steps if step.tool == "python.scenario")
    parents = {step.step_id: step.tool for step in plan.steps}
    assert "python.impact" in {parents[dep] for dep in scenario.depends_on}


def test_the_contract_validator_rejects_bad_dags():
    with pytest.raises(ValidationError, match="cycle"):
        Plan(plan_id="x", steps=(_step("P1", depends_on=("P2",)), _step("P2", depends_on=("P1",))), depth=2, source="deterministic_template",
             intents_covered=("descriptive",))
    chain = tuple(_step(f"P{i}", depends_on=(f"P{i - 1}",) if i > 1 else ()) for i in range(1, 7))
    with pytest.raises(ValidationError):
        Plan(plan_id="x", steps=chain, depth=6, source="deterministic_template", intents_covered=("descriptive",), budget=StepBudget(max_queries=8))
    with pytest.raises(ValidationError):
        Plan(plan_id="x", steps=tuple(_step(f"P{i}") for i in range(1, 10)), depth=1, source="deterministic_template",
             intents_covered=("descriptive",), budget=StepBudget(max_queries=9))
    with pytest.raises(ValidationError):
        _step("P1", tool="python.custom")
    with pytest.raises(ValidationError, match="PL-4"):
        Plan(plan_id="x", steps=(_step("P1"), _step("P2", tool="python.scenario", depends_on=("P1",), params={}, produces="analyst_output")),
             depth=2, source="deterministic_template", intents_covered=("scenario",))
    with pytest.raises(ValidationError, match="PL-6"):
        Plan(plan_id="x", steps=tuple(_step(f"P{i}") for i in range(1, 5)), depth=1, source="deterministic_template",
             intents_covered=("descriptive",), budget=StepBudget(max_queries=3))


def test_the_planner_rejects_bad_tool_params():
    plan = Plan(plan_id="x", steps=(_step("P1", params={"kind": "metric", "metric_id": "revenue", "summary": "nonsense"}),), depth=1,
                source="deterministic_template", intents_covered=("descriptive",))
    with pytest.raises(PlanValidationError, match="PL-3"):
        validate_plan(plan)
    sql_text = Plan(plan_id="x", steps=(_step("P1", params={"kind": "metric", "sql": "DROP TABLE orders"}),), depth=1,
                    source="deterministic_template", intents_covered=("descriptive",))
    with pytest.raises(PlanValidationError):
        validate_plan(sql_text)


def test_plans_are_deterministic():
    assert _plan("Why did AOV fall in January 2018?") == _plan("Why did AOV fall in January 2018?")
