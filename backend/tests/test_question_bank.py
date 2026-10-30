"""Track 3 acceptance over the scope.md question bank (3.3, 3.4, V2-ANS-2).

Each case runs through extraction -> grounding -> planning against the seeded
V2 build's real capabilities; the must-answer cases also execute end to end.
Accuracy per intent and a confusion matrix are printed on every run.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pytest
import yaml
from planner import plan_shape

BANK = yaml.safe_load((Path(__file__).parent / "data" / "question_bank_v2.yaml").read_text(encoding="utf-8"))["cases"]
INTENT_FLOOR = 0.80
OVERALL_FLOOR = 0.90


@pytest.fixture(scope="module")
def pipeline(v2_build):
    from pipeline_v2 import PipelineV2
    from service import build_runtime

    runtime = build_runtime(v2_build["db"], reasoning_client=False)
    yield PipelineV2(guard=runtime.guard, catalog=runtime.catalog, manager=runtime.manager)
    runtime.close()


def _period(period) -> str | None:
    if period is None:
        return None
    end_year, end_month = period.end.year, period.end.month - 1
    if end_month == 0:
        end_year, end_month = end_year - 1, 12
    return f"{period.start:%Y-%m}..{end_year:04d}-{end_month:02d}"


def _evaluate(pipeline, case):
    extraction = pipeline.extractor.extract(case["question"])
    grounded = pipeline.grounder.ground(extraction)
    intents = list(grounded.intent.intent_names)
    outcome = "clarify" if grounded.needs_clarification else "answer"
    plan = None
    plan_error = None
    if outcome == "answer":
        try:
            plan = pipeline.planner.plan(grounded.intent, grounded.resolved, special=grounded.special)
        except Exception as exc:  # recorded as a planning failure for the case
            plan_error = f"{type(exc).__name__}: {exc}"
    return extraction, grounded, intents, outcome, plan, plan_error


def _entity_failures(case, grounded) -> list[str]:
    expected = case.get("entities")
    if not expected:
        return []
    failures = []
    entities = grounded.intent.entities
    resolved = grounded.resolved
    if "metric" in expected and (resolved.metric_id if resolved else entities.metric_id) != expected["metric"]:
        failures.append(f"metric {resolved.metric_id if resolved else entities.metric_id!r} != {expected['metric']!r}")
    if "dimensions" in expected and not set(expected["dimensions"]) <= set(entities.dimensions):
        failures.append(f"dimensions {list(entities.dimensions)} missing {expected['dimensions']}")
    if "filters" in expected:
        got = {item.dimension: list(item.values) for item in entities.filters}
        for dimension, values in expected["filters"].items():
            if sorted(got.get(dimension, [])) != sorted(values):
                failures.append(f"filter {dimension}={got.get(dimension)} != {values}")
    if "period" in expected and _period(resolved.period if resolved else entities.period) != expected["period"]:
        failures.append(f"period {_period(resolved.period if resolved else entities.period)} != {expected['period']}")
    if "comparison" in expected and _period(entities.comparison_period) != expected["comparison"]:
        failures.append(f"comparison {_period(entities.comparison_period)} != {expected['comparison']}")
    if "horizon" in expected and (entities.horizon.periods if entities.horizon else None) != expected["horizon"]:
        failures.append(f"horizon {entities.horizon.periods if entities.horizon else None} != {expected['horizon']}")
    for want in expected.get("scenario", []):
        match = [param for param in entities.scenario_params
                 if all(getattr(param, key) == value if key != "value" else abs(param.value - value) < 1e-9 for key, value in want.items())]
        if not match:
            failures.append(f"scenario {want} not in {[(p.target, p.kind, p.value) for p in entities.scenario_params]}")
    return failures


@pytest.fixture(scope="module")
def evaluated(pipeline):
    return [(case, *_evaluate(pipeline, case)) for case in BANK]


def test_the_bank_has_more_than_100_questions_from_scope():
    assert len(BANK) >= 100
    ids = [case["id"] for case in BANK]
    assert len(ids) == len(set(ids))
    for prefix in ("D", "C", "S", "G", "I", "F", "X", "P", "K", "V", "U"):
        assert sum(1 for name in ids if name.startswith(prefix) and name[1:].isdigit()) >= 10, prefix


def test_intent_accuracy_per_intent_and_confusion_matrix(evaluated, capsys):
    by_intent: dict[str, list[bool]] = defaultdict(list)
    confusion: Counter = Counter()
    misses = []
    for case, _extraction, _grounded, intents, outcome, _plan, _error in evaluated:
        expected = case["intents"]
        primary = case.get("first", expected[0])
        correct = set(intents) == set(expected) and (intents[:1] == [primary] if "first" in case else True)
        by_intent[primary].append(correct)
        confusion[(primary, intents[0] if intents else "none")] += 1
        if not correct:
            misses.append(f"{case['id']}: expected {expected}, got {intents} - {case['question']}")
    total = sum(len(values) for values in by_intent.values())
    overall = sum(sum(values) for values in by_intent.values()) / total
    names = sorted(by_intent)
    lines = ["", "Question bank: intent accuracy per expected primary intent", f"{'intent':14}{'cases':>7}{'correct':>9}{'accuracy':>10}"]
    for name in names:
        values = by_intent[name]
        lines.append(f"{name:14}{len(values):>7}{sum(values):>9}{sum(values) / len(values):>10.1%}")
    lines.append(f"{'overall':14}{total:>7}{int(round(overall * total)):>9}{overall:>10.1%}")
    columns = sorted({got for _, got in confusion})
    lines.append("")
    lines.append("Confusion matrix (rows: expected primary, columns: produced primary)")
    lines.append(f"{'':14}" + "".join(f"{column[:11]:>12}" for column in columns))
    for name in names:
        lines.append(f"{name:14}" + "".join(f"{confusion[(name, column)]:>12}" for column in columns))
    if misses:
        lines.append("")
        lines.append("Misses:")
        lines.extend(f"  {line}" for line in misses)
    report = "\n".join(lines)
    with capsys.disabled():
        print(report)
    assert overall >= OVERALL_FLOOR, report
    for name in names:
        values = by_intent[name]
        assert sum(values) / len(values) >= INTENT_FLOOR, f"{name} below {INTENT_FLOOR:.0%}\n{report}"


def test_outcomes_entities_and_plan_shapes(evaluated, capsys):
    outcome_hits = entity_hits = entity_total = plan_hits = plan_total = slot_hits = slot_total = 0
    problems = []
    for case, _extraction, grounded, intents, outcome, plan, error in evaluated:
        outcome_hits += outcome == case["outcome"]
        if outcome != case["outcome"]:
            problems.append(f"{case['id']} outcome {outcome} != {case['outcome']}")
        if case["outcome"] == "answer" and outcome == "answer" and error:
            problems.append(f"{case['id']} plan error: {error}")
        if "entities" in case and outcome == case["outcome"]:
            entity_total += 1
            failures = _entity_failures(case, grounded)
            entity_hits += not failures
            problems.extend(f"{case['id']} {failure}" for failure in failures)
        if "plan" in case and plan is not None:
            plan_total += 1
            tools = [step.tool for step in plan.steps]
            ok = tools == case["plan"]
            if ok and "deps" in case:
                shape = plan_shape(plan)
                for index, deps in case["deps"].items():
                    want = ",".join(str(dep) for dep in deps)
                    ok = ok and shape[int(index) - 1].endswith("<-" + want)
            plan_hits += ok
            if not ok:
                problems.append(f"{case['id']} plan {plan_shape(plan)} != {case['plan']}")
        if case["outcome"] == "clarify" and grounded.clarification is not None:
            request = grounded.clarification
            assert 2 <= len(request.options) <= 4 and request.question.count("?") == 1, case["id"]
            assert request.default_assumption.option_id in {option.option_id for option in request.options}, case["id"]
            if "slot" in case:
                slot_total += 1
                slot_hits += request.slot == case["slot"]
                if request.slot != case["slot"]:
                    problems.append(f"{case['id']} slot {request.slot} != {case['slot']}")
            for word in case.get("missing", []):
                assert word.lower() in request.what_understood.lower() + request.question.lower(), case["id"]
            if "default_label" in case:
                default = next(option for option in request.options if option.option_id == request.default_assumption.option_id)
                assert default.label == case["default_label"], case["id"]
    n = len(evaluated)
    report = (f"\nOutcome accuracy {outcome_hits}/{n} = {outcome_hits / n:.1%}; entity accuracy {entity_hits}/{entity_total} = "
              f"{entity_hits / max(entity_total, 1):.1%}; plan-shape accuracy {plan_hits}/{plan_total} = {plan_hits / max(plan_total, 1):.1%}; "
              f"clarification slot accuracy {slot_hits}/{slot_total} = {slot_hits / max(slot_total, 1):.1%}")
    with capsys.disabled():
        print(report)
        for line in problems:
            print("  " + line)
    assert outcome_hits / n >= OVERALL_FLOOR, report
    assert entity_hits / max(entity_total, 1) >= 0.85, report
    assert plan_hits / max(plan_total, 1) >= 0.85, report
    assert slot_hits / max(slot_total, 1) >= 0.85, report
    assert not any("plan error" in line for line in problems), problems


@pytest.mark.parametrize("case", [case for case in BANK if case.get("must_answer")], ids=lambda case: case["id"])
def test_must_answer_questions_return_answered(pipeline, case):
    outcome = pipeline.run(case["question"])
    envelope = outcome.envelope
    assert envelope.status == "answered", (envelope.status, envelope.conclusion, envelope.caveats)
    assert envelope.conclusion and envelope.claims
    assert envelope.plan is not None and len(envelope.step_results) == len(envelope.plan.steps)
