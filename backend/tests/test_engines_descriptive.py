"""Descriptive engine: aggregate, rank and trend, every figure from SQL."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from engine_helpers import assert_complete_report, data, stable, table
from engines import descriptive


def _sales():
    return pd.DataFrame({
        "date": ["2018-01-05", "2018-01-20", "2018-02-03", "2018-02-11", "2018-03-01", "2018-03-09", "2018-03-20"],
        "state": ["SP", "RJ", "SP", "MG", "MG", "SP", "RJ"],
        "revenue": [10.0, 20.0, 30.0, 4.0, 5.0, 7.0, 1.0],
    })


def _run(params, frame=None, **kwargs):
    return descriptive.execute(params, data({"sales": table(frame if frame is not None else _sales(), "Q-SALES", date="time")}, **kwargs))


def test_rank_lists_top_n_with_shares_and_the_remainder():
    run = _run({"operation": "rank", "measure": "revenue", "dimensions": ("state",), "top_n": 1, "unit": "R$"})
    result = run.result
    assert result.status == "ok" and result.tool == "sql" and result.produces == "rows"
    assert result.provenance.source == "sql" and result.provenance.engine is None
    (top, remainder) = result.rows.rows
    assert top[0] == "SP" and top[1] == 47.0 and top[2] == pytest.approx(47.0 / 77.0) and top[3] == 1
    assert remainder[0] == "All remaining" and remainder[1] == 30.0 and remainder[2] == pytest.approx(30.0 / 77.0)
    assert remainder[3] is None
    assert result.rows.query_id in result.provenance.query_ids and "Q-SALES" in result.provenance.query_ids
    assert run.report.number("remainder") == 30.0
    assert_complete_report(run.report)


def test_aggregate_with_a_comparison_window_includes_groups_from_either_window():
    run = _run({"operation": "aggregate", "measure": "revenue", "dimensions": ("state",), "period_column": "date",
                "start": "2018-02-01", "end": "2018-04-01", "comparison_start": "2018-01-01", "comparison_end": "2018-02-01"})
    rows = {row[0]: row[1:] for row in run.result.rows.rows}
    assert rows["SP"] == (37.0, 10.0, 27.0, 270.0)
    assert rows["MG"][0] == 9.0 and rows["MG"][1] is None
    assert rows["RJ"] == (1.0, 20.0, -19.0, -95.0)
    assert_complete_report(run.report)


def test_trend_summary_matches_an_independent_numpy_check():
    run = _run({"operation": "trend", "measure": "revenue", "period_column": "date", "grain": "month"})
    assert run.result.rows.rows == (("2018-01", 30.0), ("2018-02", 34.0), ("2018-03", 13.0))
    values = np.array([30.0, 34.0, 13.0])
    slope = np.polyfit(np.arange(3), values, 1)[0]
    assert abs(run.report.number("slope_per_period") - slope) < 1e-9
    assert abs(run.report.number("change_pct") - (13.0 - 30.0) / 30.0 * 100.0) < 1e-9
    assert run.report.chart_hint.kind == "line"
    assert_complete_report(run.report)


def test_filters_and_values_are_bound_parameters_never_sql_text():
    hostile = _sales().assign(state=["SP'; DROP TABLE input_rows; --"] + ["RJ"] * 6)
    run = _run({"operation": "aggregate", "measure": "revenue", "dimensions": ("state",),
                "filters": {"state": ("SP'; DROP TABLE input_rows; --",)}}, hostile)
    assert run.result.rows.rows == (("SP'; DROP TABLE input_rows; --", 10.0),)
    bad = _run({"operation": "rank", "measure": "revenue; DROP", "dimensions": ("state",)})
    assert bad.result.status == "insufficient_evidence"


def test_zero_matching_rows_is_an_empty_finding_not_a_failure():
    run = _run({"operation": "aggregate", "measure": "revenue", "dimensions": ("state",), "filters": {"state": ("XX",)}})
    assert run.result.status == "empty" and run.result.rows.row_count == 0


def test_descriptive_is_deterministic_and_labels_synthetic_inputs():
    params = {"operation": "rank", "measure": "revenue", "dimensions": ("state",)}
    first, second = _run(params, sources=("marketing_spend",)), _run(params, sources=("marketing_spend",))
    assert stable(first.result) == stable(second.result)
    assert first.result.provenance.data_layer == "synthetic"
