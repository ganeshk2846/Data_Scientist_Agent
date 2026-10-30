"""AN-1 Phase 2 hardening tests for the driver analyst."""

from __future__ import annotations

import math
from datetime import date

import pytest

from analysts.driver import DriverAnalyst
from contracts.models import (
    AnalystColumn,
    AnalystInput,
    AnalystOutput,
    DriverResult,
    Period,
    TableRef,
)


def _table(rows) -> TableRef:
    return TableRef(
        query_id="Q-DRIVER",
        columns=(
            AnalystColumn(name="period", type="TEXT", role="time"),
            AnalystColumn(name="customer_state", type="TEXT", role="dimension"),
            AnalystColumn(name="value", type="REAL", role="measure"),
        ),
        row_count=len(rows),
        uri="inline://Q-DRIVER",
        rows=tuple(rows),
    )


def _params(**overrides) -> dict:
    params = {
        "metric": "revenue",
        "current_period": Period(start=date(2018, 1, 1), end=date(2018, 4, 1)),
        "comparison_period": Period(
            start=date(2017, 10, 1),
            end=date(2018, 1, 1),
        ),
        "dimensions": ("customer_state",),
        "aggregation": "sum",
        "value_decomposition": False,
    }
    params.update(overrides)
    return params


def _run(
    rows,
    *,
    params: dict | None = None,
    analyst: DriverAnalyst | None = None,
    table: TableRef | None = None,
) -> AnalystOutput:
    analyst_input = AnalystInput(
        module="driver",
        params=params or _params(),
        tables={"contrib": table or _table(rows)},
        run_id="RUN-AN1-DRIVER",
    )
    return (analyst or DriverAnalyst()).run(analyst_input)


def _valid_rows():
    return [
        ("2017-10-01", "SP", 100.0),
        ("2017-10-01", "RJ", 80.0),
        ("2018-01-01", "SP", 140.0),
        ("2018-01-01", "RJ", 60.0),
    ]


def test_driver_valid_change_reconciles_and_ranks():
    output = _run(_valid_rows())

    assert output.status == "ok"
    assert isinstance(output.result, DriverResult)
    result = output.result
    assert result.total_change == pytest.approx(20.0)
    assert result.reconciliation_error == pytest.approx(0.0, abs=1e-12)
    assert [driver.value for driver in result.drivers] == ["SP", "RJ"]
    assert result.drivers[0].contribution == pytest.approx(40.0)
    assert result.drivers[0].share == pytest.approx(2.0)
    assert result.drivers[1].contribution == pytest.approx(-20.0)
    assert result.drivers[1].share == pytest.approx(-1.0)
    assert result.candidates_examined == 2


def test_driver_empty_current_window_is_insufficient():
    output = _run(
        [
            ("2017-10-01", "SP", 100.0),
            ("2017-10-01", "RJ", 80.0),
        ]
    )

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "current" in output.reason.lower()


def test_driver_empty_comparison_window_is_insufficient():
    output = _run(
        [
            ("2018-01-01", "SP", 140.0),
            ("2018-01-01", "RJ", 60.0),
        ]
    )

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "comparison" in output.reason.lower()


def test_driver_empty_table_is_insufficient():
    output = _run([])

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "current" in output.reason.lower()
    assert "comparison" in output.reason.lower()


def test_driver_zero_total_change_is_insufficient():
    output = _run(
        [
            ("2017-10-01", "SP", 100.0),
            ("2017-10-01", "RJ", 80.0),
            ("2018-01-01", "SP", 110.0),
            ("2018-01-01", "RJ", 70.0),
        ]
    )

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "zero" in output.reason.lower()
    assert "share" in output.reason.lower()


def test_driver_near_zero_total_change_is_insufficient():
    output = _run(
        [
            ("2017-10-01", "SP", 100.0),
            ("2018-01-01", "SP", 100.0 + 1e-13),
        ]
    )

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "near zero" in output.reason.lower()


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_driver_non_finite_value_is_insufficient(bad_value):
    output = _run(
        [
            ("2017-10-01", "SP", 100.0),
            ("2018-01-01", "SP", bad_value),
        ]
    )

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "finite" in output.reason.lower()


def test_driver_invalid_parameters_are_insufficient_not_a_crash():
    output = _run(_valid_rows(), params={"metric": "revenue"})

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "parameters" in output.reason.lower()


def test_driver_missing_dimension_column_is_insufficient():
    table = TableRef(
        query_id="Q-NO-DIM",
        columns=(
            AnalystColumn(name="period", type="TEXT", role="time"),
            AnalystColumn(name="value", type="REAL", role="measure"),
        ),
        row_count=2,
        uri="inline://Q-NO-DIM",
        rows=(
            ("2017-10-01", 100.0),
            ("2018-01-01", 140.0),
        ),
    )

    output = _run([], table=table)

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "dimension" in output.reason.lower()


def test_driver_dimension_limit_is_enforced():
    output = _run(
        _valid_rows(),
        params=_params(
            dimensions=("customer_state", "period"),
            max_dimensions=1,
        ),
    )

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "max_dimensions" in output.reason


@pytest.mark.parametrize(
    "overrides",
    [
        {"metric_tree": ({"metric": "revenue"},)},
    ],
)
def test_driver_unsupported_capabilities_fail_closed(overrides):
    output = _run(_valid_rows(), params=_params(**overrides))

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "not implemented" in output.reason.lower()


def test_driver_duplicate_dimension_rows_are_aggregated_once():
    rows = [
        ("2017-10-01", "SP", 80.0),
        ("2018-01-01", "SP", 50.0),
        ("2018-01-01", "SP", 90.0),
    ]
    output = _run(rows)

    assert output.status == "ok"
    assert isinstance(output.result, DriverResult)
    assert len(output.result.drivers) == 1
    assert output.result.drivers[0].value == "SP"
    assert output.result.drivers[0].contribution == pytest.approx(60.0)
    assert output.result.drivers[0].share == pytest.approx(1.0)
    assert output.result.total_change == pytest.approx(60.0)


def test_driver_unsorted_rows_are_deterministic():
    output = _run(_valid_rows())
    reversed_output = _run(list(reversed(_valid_rows())))

    assert output.status == "ok"
    assert output == reversed_output


def test_driver_repeated_execution_is_deterministic():
    output = _run(_valid_rows())

    assert output == _run(_valid_rows())


def test_driver_negative_contributions_are_supported():
    output = _run(
        [
            ("2017-10-01", "SP", 80.0),
            ("2017-10-01", "RJ", -10.0),
            ("2018-01-01", "SP", 100.0),
            ("2018-01-01", "RJ", -20.0),
        ]
    )

    assert output.status == "ok"
    assert isinstance(output.result, DriverResult)
    assert output.result.total_change == pytest.approx(10.0)
    assert output.result.reconciliation_error == pytest.approx(0.0, abs=1e-12)
    assert output.result.drivers[0].value == "SP"
    assert output.result.drivers[0].contribution == pytest.approx(20.0)
    assert output.result.drivers[1].contribution == pytest.approx(-10.0)
    assert all(
        math.isfinite(value)
        for driver in output.result.drivers
        for value in (
            driver.contribution,
            driver.share,
            driver.interval[0],
            driver.interval[1],
        )
    )


def test_driver_exact_additive_reconciliation():
    output = _run(_valid_rows())

    assert output.status == "ok"
    assert isinstance(output.result, DriverResult)
    assert sum(
        driver.contribution for driver in output.result.drivers
    ) == pytest.approx(output.result.total_change, abs=1e-12)
    assert abs(output.result.reconciliation_error) <= 1e-12


def test_driver_small_cell_grade_is_conservative():
    rows = []
    for _ in range(5):
        rows.append(("2017-10-01", "SP", 16.0))
        rows.append(("2018-01-01", "SP", 20.0))
    output = _run(rows)

    assert output.status == "ok"
    assert isinstance(output.result, DriverResult)
    driver = output.result.drivers[0]
    assert driver.sample_size == 5
    assert driver.unstable is False
    assert driver.grade <= 2


def test_driver_causal_boundary_is_explicit():
    output = _run(_valid_rows())

    assert output.status == "ok"
    assert any("not causal" in note.lower() for note in output.assumptions)
    assert any(
        "not proven causality" in note.lower()
        for note in output.assumptions
    )
    assert any(
        "not a row-level bootstrap" in note.lower()
        for note in output.assumptions
    )
    assert output.result is not None
    assert output.result.correction_used is None
