"""Stage 5 analyst harness and diagnostic analyst tests (ANA-1, ANOM, DRV)."""

from __future__ import annotations

from datetime import date

import pytest

from analysts.harness import AnalystHarness, UnsupportedAnalystError
from contracts.models import (
    AnalystInput,
    AnomalyResult,
    DriverResult,
    ExecutionColumn,
    ExecutionResult,
    Period,
    TableRef,
)


def _execution(columns, rows, query_id="Q1", duration_ms=1) -> ExecutionResult:
    return ExecutionResult(
        query_id=query_id,
        status="ok",
        columns=tuple(columns),
        row_count=len(rows),
        rows=tuple(rows),
        duration_ms=duration_ms,
    )


def _series_execution(values, start_year=2017, start_month=1, query_id="Q1"):
    rows = []
    year = start_year
    month = start_month
    for value in values:
        rows.append((f"{year:04d}-{month:02d}", value))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return _execution(
        (
            ExecutionColumn(name="month", type="TEXT"),
            ExecutionColumn(name="order_count", type="INTEGER"),
        ),
        rows,
        query_id=query_id,
    )


def _anomaly_params(
    test_start="2018-12-01",
    test_end="2019-01-01",
    history_start="2017-01-01",
    history_end="2018-12-01",
) -> dict:
    return {
        "metric": "order_count",
        "grain": "month",
        "test_window": Period(
            start=date.fromisoformat(test_start),
            end=date.fromisoformat(test_end),
        ),
        "history_window": Period(
            start=date.fromisoformat(history_start),
            end=date.fromisoformat(history_end),
        ),
        "alpha": 0.05,
        "min_volume": 0,
    }


def test_harness_converts_execution_to_typed_table_and_input():
    harness = AnalystHarness()
    execution = _series_execution((100, 101, 99), query_id="Q9")
    table = harness.table_from_execution(
        execution,
        roles={"month": "time", "order_count": "measure"},
    )

    assert isinstance(table, TableRef)
    assert table.query_id == "Q9"
    assert table.uri == "inline://Q9"
    assert table.row_count == 3
    assert table.rows == execution.rows
    assert table.columns[0].role == "time"
    assert table.columns[1].role == "measure"

    analyst_input = harness.build_input(
        "anomaly",
        params=_anomaly_params(),
        tables={"series": execution},
        run_id="RUN-1",
        seed=7,
    )
    assert isinstance(analyst_input, AnalystInput)
    assert analyst_input.module == "anomaly"
    assert analyst_input.run_id == "RUN-1"
    assert analyst_input.seed == 7
    assert analyst_input.tables["series"].query_id == "Q9"


def test_anomaly_analyst_flags_planted_drop_with_full_evidence():
    harness = AnalystHarness()
    values = [100] * 23 + [20]
    execution = _series_execution(values)
    analyst_input = harness.build_input(
        "anomaly",
        params=_anomaly_params(),
        tables={"series": execution},
        run_id="RUN-ANOMALY",
    )

    first = harness.run(analyst_input)
    second = harness.run(analyst_input)

    assert first.status == "ok"
    assert first.reason is None
    assert isinstance(first.result, AnomalyResult)
    result = first.result
    assert result.verdict == "unusual"
    assert result.actual == 20.0
    assert result.expected == pytest.approx(100.0, abs=1.0)
    assert result.expected_range[0] < result.expected < result.expected_range[1]
    assert not result.expected_range[0] <= result.actual <= result.expected_range[1]
    assert result.deviation_pct == pytest.approx(-80.0, abs=1.0)
    assert result.persistence == "one_off"
    assert result.baseline_kind == "robust_trailing"
    assert result.correction_used is None
    assert result.calendar_effects == ()
    assert first.sources == ("Q1",)
    assert first.assumptions
    assert first.parameters["test_window"] == "2018-12-01/2019-01-01"
    assert first == second


def test_anomaly_analyst_does_not_force_an_anomaly_label():
    harness = AnalystHarness()
    execution = _series_execution([100] * 23 + [102])
    analyst_input = harness.build_input(
        "anomaly",
        params=_anomaly_params(),
        tables={"series": execution},
        run_id="RUN-STABLE",
    )

    output = harness.run(analyst_input)

    assert output.status == "ok"
    assert isinstance(output.result, AnomalyResult)
    assert output.result.verdict == "within_normal_range"
    assert output.result.persistence == "unknown"


def test_anomaly_insufficient_history_returns_typed_insufficient_evidence():
    harness = AnalystHarness()
    execution = _series_execution([100, 20], start_year=2018, start_month=11)
    analyst_input = harness.build_input(
        "anomaly",
        params=_anomaly_params(
            history_start="2018-11-01",
            test_start="2018-12-01",
        ),
        tables={"series": execution},
        run_id="RUN-SHORT",
    )

    output = harness.run(analyst_input)

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason
    assert "history" in output.reason.lower()


def test_anomaly_missing_measure_column_is_insufficient_not_a_crash():
    harness = AnalystHarness()
    execution = _execution(
        (ExecutionColumn(name="month", type="TEXT"),),
        (("2018-12-01",),),
    )
    analyst_input = harness.build_input(
        "anomaly",
        params=_anomaly_params(),
        tables={"series": execution},
        run_id="RUN-MISSING",
    )

    output = harness.run(analyst_input)

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert output.reason


def test_driver_analyst_attributes_change_and_reconciles():
    harness = AnalystHarness()
    execution = _execution(
        (
            ExecutionColumn(name="period", type="TEXT"),
            ExecutionColumn(name="customer_state", type="TEXT"),
            ExecutionColumn(name="value", type="REAL"),
        ),
        (
            ("2017-10-01", "SP", 100.0),
            ("2017-10-01", "RJ", 80.0),
            ("2018-01-01", "SP", 140.0),
            ("2018-01-01", "RJ", 60.0),
        ),
        query_id="Q-DRIVER",
    )
    params = {
        "metric": "revenue",
        "current_period": Period(
            start=date(2018, 1, 1),
            end=date(2018, 4, 1),
        ),
        "comparison_period": Period(
            start=date(2017, 10, 1),
            end=date(2018, 1, 1),
        ),
        "dimensions": ("customer_state",),
        "aggregation": "sum",
        "value_decomposition": False,
    }
    analyst_input = harness.build_input(
        "driver",
        params=params,
        tables={"contrib": execution},
        run_id="RUN-DRIVER",
        seed=11,
    )

    output = harness.run(analyst_input)

    assert output.status == "ok"
    assert isinstance(output.result, DriverResult)
    result = output.result
    assert result.total_change == pytest.approx(20.0)
    assert result.reconciliation_error == pytest.approx(0.0, abs=1e-9)
    assert [driver.value for driver in result.drivers] == ["SP", "RJ"]
    assert result.drivers[0].contribution == pytest.approx(40.0)
    assert result.drivers[0].share == pytest.approx(2.0)
    assert result.drivers[1].contribution == pytest.approx(-20.0)
    assert result.drivers[1].share == pytest.approx(-1.0)
    assert result.drivers[0].sample_size == 1
    assert result.drivers[1].unstable is True
    assert result.drivers[0].grade <= 1
    assert len(result.drivers[0].interval) == 2
    assert any("not causal" in note.lower() for note in output.assumptions)
    assert output.sources == ("Q-DRIVER",)


def test_unknown_analyst_module_is_rejected():
    harness = AnalystHarness()
    with pytest.raises(UnsupportedAnalystError):
        harness.build_input("freeform_python", {}, {}, run_id="RUN-UNKNOWN")


def test_harness_dispatches_every_track2_engine_through_the_closed_mapping():
    harness = AnalystHarness()
    modules = ("forecast", "impact", "scenario", "segment")

    assert set(modules) <= set(harness.modules)
    for module in modules:
        output = harness.run(
            AnalystInput(
                module=module,
                params={"mode": "rank_segments"} if module == "segment" else {},
                run_id=f"RUN-{module.upper()}-MISSING",
                seed=5,
            )
        )
        assert output.module == module
        assert output.status == "insufficient_evidence"
        assert output.reason
