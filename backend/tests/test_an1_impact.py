from __future__ import annotations

from analysts.impact import ImpactAnalyst
from contracts.models import AnalystColumn, AnalystInput, TableRef
from contracts.v2 import ImpactResult


def _input(names, rows, params=None):
    table = TableRef(
        query_id="Q-IMPACT",
        columns=tuple(
            AnalystColumn(
                name=name,
                type="TEXT" if name == "period" else "REAL",
                role="time" if name == "period" else "measure",
            )
            for name in names
        ),
        row_count=len(rows),
        uri="inline://Q-IMPACT",
        rows=tuple(tuple(row) for row in rows),
    )
    return AnalystInput(
        module="impact",
        params={"metric": "revenue", **(params or {})},
        tables={"measurements": table},
        run_id="RUN-IMPACT",
        seed=3,
    )


def test_impact_sizes_change_tests_significance_and_is_deterministic():
    rows = [
        ("baseline", value, 115.0, 100.0)
        for value in (98.0, 100.0, 102.0, 99.0, 101.0)
    ] + [
        ("current", value, 115.0, 100.0)
        for value in (118.0, 120.0, 122.0, 119.0, 121.0)
    ]
    input_value = _input(
        ("period", "value", "target", "peer"),
        rows,
        params={
            "current_period": "current",
            "baseline_period": "baseline",
            "unit": "R$",
        },
    )
    analyst = ImpactAnalyst()
    first = analyst.run(input_value)
    second = analyst.run(input_value)

    assert first.status == "ok"
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert isinstance(first.result, ImpactResult)
    assert first.result.baseline == 500.0
    assert first.result.current == 600.0
    assert first.result.delta == 100.0
    assert first.result.delta_pct == 20.0
    assert first.result.significant is True
    assert first.result.p_value < 0.05
    assert first.result.interval[0] <= 100.0 <= first.result.interval[1]
    assert first.result.target == 115.0
    assert first.result.peer == 100.0


def test_impact_zero_baseline_reports_absolute_change_without_fake_percent():
    output = ImpactAnalyst().run(
        _input(
            ("baseline", "current"),
            ((0.0, 45.0),),
        )
    )

    assert output.status == "ok"
    assert output.result.baseline == 0.0
    assert output.result.delta == 45.0
    assert output.result.delta_pct is None
    assert output.result.significant is None


def test_impact_sparse_or_invalid_inputs_return_insufficient_evidence():
    sparse = ImpactAnalyst().run(
        _input(("period", "value"), (("only-one", 100.0),))
    )
    assert sparse.status == "insufficient_evidence"
    assert sparse.reason

    invalid = ImpactAnalyst().run(
        _input(("baseline", "current"), ((float("nan"), 45.0),))
    )
    assert invalid.status == "insufficient_evidence"
    assert invalid.reason
