"""Diagnostic engine: drill-down, price/volume/mix, lagged drivers, DiD, evidence grades."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from contracts.v2 import DiagnosticResult
from engine_helpers import assert_complete_report, data, stable, table
from engines import diagnostic
from engines.diagnostic import (
    CAUSAL_BOUNDARY,
    DiagnosticParams,
    PvmSpec,
    price_volume_mix,
)

CURRENT = {"start": "2018-03-01", "end": "2018-06-01"}
COMPARISON = {"start": "2017-12-01", "end": "2018-03-01"}


def _panel(seed=3):
    """Daily sessions by state and device; SP drops 30% from March, lagged two weeks behind a spend cut."""
    rng = np.random.default_rng(seed)
    days = pd.date_range("2017-06-01", "2018-08-31", freq="D")
    rows = []
    for day in days:
        for state in ("SP", "RJ", "MG", "BA"):
            for device in ("web", "app"):
                level = 1000.0 if state == "SP" else 500.0
                if state == "SP" and pd.Timestamp("2018-03-15") <= day < pd.Timestamp("2018-06-15"):
                    level *= 0.7
                rows.append((day.date().isoformat(), state, device, level * rng.lognormal(0.0, 0.05)))
    contrib = pd.DataFrame(rows, columns=["date", "state", "device", "value"])
    spend_rows = []
    for day in days:
        for channel in ("search", "social"):
            base = 100.0 * rng.lognormal(0.0, 0.03)
            if channel == "search" and pd.Timestamp("2018-03-01") <= day < pd.Timestamp("2018-06-01"):
                base *= 0.5
            for category in ("a", "b"):
                share = 0.5
                if channel == "social" and pd.Timestamp("2018-03-01") <= day < pd.Timestamp("2018-06-01"):
                    share = 0.3 if category == "a" else 0.7
                spend_rows.append((day.date().isoformat(), channel, category, base * share))
    spend = pd.DataFrame(spend_rows, columns=["date", "channel", "category", "spend"])
    return contrib, spend


def _params(**overrides):
    return {
        "metric": "sessions",
        "current_period": CURRENT,
        "comparison_period": COMPARISON,
        "target_where": {"state": ("SP",)},
        "target_relative_to_rest": True,
        "grain": "week",
        "max_lag": 4,
        "drivers": (
            {"name": "search", "table": "spend", "value": "spend", "where": {"channel": ("search",)}, "relative_to_rest": True, "expected_sign": 1},
            {"name": "social", "table": "spend", "value": "spend", "where": {"channel": ("social",)}, "relative_to_rest": True, "expected_sign": 1},
            {"name": "social_share_a", "table": "spend", "value": "spend", "where": {"category": ("a",)}, "share_of": {"channel": ("social",)}},
        ),
        "specificity": {"dimension": "state", "treated": ("SP",), "date": "date"},
        **overrides,
    }


def _run(**overrides):
    contrib, spend = _panel()
    tables = {"contrib": table(contrib, "Q-SESSIONS", date="time"), "spend": table(spend, "Q-SPEND", date="time")}
    return diagnostic.execute(_params(**overrides), data(tables, seed=9))


@pytest.fixture(scope="module")
def run():
    return _run()


def test_drill_down_examines_every_dimension_and_the_most_concentrated_pair(run):
    drill = run.report.table("drill_down")
    levels = {row[0] for row in drill.rows}
    assert {"state", "device"} <= levels
    assert any(" / " in level for level in levels)
    top_state = next(row for row in drill.rows if row[0] == "state")
    assert top_state[1] == "SP"


def test_lagged_correlation_finds_the_driver_at_its_lag_and_corrects_for_multiplicity(run):
    result = run.result.analyst_output.result
    assert isinstance(result, DiagnosticResult)
    correlations = {item.value: item for item in result.indicator_drivers if item.method == "correlation"}
    search = correlations["search"]
    assert search.effect_size > 0.5 and search.grade == 2 and search.q_value is not None and search.q_value < 0.05
    assert 1 <= search.lag_periods <= 3
    assert result.correction_used == "benjamini_hochberg_0.05"


def test_reallocation_and_wrong_sign_candidates_are_held_at_grade_one(run):
    ranked = {(row[0], row[1]): row for row in run.report.table("ranked_drivers").rows}
    share = ranked[("social_share_a", "correlation")]
    assert share[7] == 1 and "reallocation" in share[11]
    social = ranked[("social", "correlation")]
    assert social[7] == 1
    top_correlation = next(row for row in run.report.table("ranked_drivers").rows if row[1] == "correlation")
    assert top_correlation[0] == "search"


def test_difference_in_differences_is_grade_three_with_an_interval(run):
    did = [item for item in run.result.analyst_output.result.indicator_drivers if item.method == "difference_in_differences"]
    assert did and did[0].grade == 3
    assert did[0].interval[0] <= did[0].effect_size <= did[0].interval[1] < 0
    assert run.report.table("ranked_drivers").rows[0][1] == "difference_in_differences"


def test_feature_importance_never_exceeds_grade_two_and_the_causal_note_is_kept(run):
    result = run.result.analyst_output.result
    assert all(item.grade <= 2 for item in result.feature_importance)
    assert CAUSAL_BOUNDARY in run.result.analyst_output.assumptions
    assert any("not causal" in note.lower() for note in run.result.analyst_output.assumptions)
    assert_complete_report(run.report)


def test_price_volume_mix_reconciles_exactly_by_hand():
    frame = pd.DataFrame({
        "period": ["2018-01-01"] * 2 + ["2018-02-01"] * 3,
        "category": ["a", "b", "a", "b", "c"],
        "price": [10.0, 20.0, 8.0, 22.0, 5.0],
        "quantity": [100.0, 50.0, 150.0, 40.0, 10.0],
    })
    params = DiagnosticParams.model_validate({"metric": "revenue", "current_period": {"start": "2018-02-01", "end": "2018-03-01"},
                                              "comparison_period": {"start": "2018-01-01", "end": "2018-02-01"}})
    pvm = price_volume_mix(frame, PvmSpec(dimension="category"), params)
    assert pvm["revenue_change"] == pytest.approx((1200 + 880 + 50) - (1000 + 1000))
    assert pvm["volume_effect"] + pvm["mix_effect"] + pvm["price_effect"] == pytest.approx(pvm["revenue_change"])
    assert pvm["price_effect"] == pytest.approx(150 * -2.0 + 40 * 2.0)
    assert pvm["volume_effect"] == pytest.approx((200 - 150) * (2000 / 150))
    assert pvm["asp_rate_effect"] + pvm["asp_mix_effect"] == pytest.approx(pvm["asp_change"])
    assert abs(pvm["revenue_residual"]) < 1e-9 and abs(pvm["asp_residual"]) < 1e-12


def test_pvm_feeds_the_value_decomposition_and_a_waterfall_hint():
    frame = pd.DataFrame({
        "date": ["2018-01-05", "2018-01-06", "2018-02-05", "2018-02-06"],
        "category": ["a", "b", "a", "b"],
        "numerator": [100.0, 200.0, 90.0, 260.0],
        "denominator": [10.0, 10.0, 12.0, 12.0],
        "price": [10.0, 20.0, 7.5, 21.67],
        "quantity": [10.0, 10.0, 12.0, 12.0],
    })
    tables = {"contrib": table(frame[["date", "category", "numerator", "denominator"]], "Q-C", date="time"),
              "sales": table(frame[["date", "category", "price", "quantity"]], "Q-SALES", date="time")}
    run = diagnostic.execute({"metric": "aov", "aggregation": "ratio", "current_period": {"start": "2018-02-01", "end": "2018-03-01"},
                              "comparison_period": {"start": "2018-01-01", "end": "2018-02-01"},
                              "pvm": {"table": "sales", "period": "date", "dimension": "category"}}, data(tables))
    result = run.result.analyst_output.result
    assert {item.value for item in result.value_decomposition} == {"volume", "mix", "price"}
    assert run.report.chart_hint.kind == "waterfall"
    assert_complete_report(run.report)


def test_null_specificity_is_not_promoted():
    contrib, _spend = _panel()
    contrib["flat"] = 1.0 + np.random.default_rng(1).normal(0.0, 0.1, len(contrib))
    tables = {"contrib": table(contrib, "Q-SESSIONS", date="time", flat="measure")}
    run = diagnostic.execute({**_params(drivers=()), "specificity": {"dimension": "state", "treated": ("SP",), "date": "date",
                                                                      "measures": ("flat",)}}, data(tables))
    did = [item for item in run.result.analyst_output.result.indicator_drivers if item.method == "difference_in_differences"]
    assert did and did[0].grade == 1


def test_diagnostic_is_deterministic_and_handles_empty_input():
    assert stable(_run().result) == stable(_run().result)
    empty = diagnostic.execute(_params(), data({"contrib": table(pd.DataFrame({"date": [], "value": []}), "Q-E")}))
    assert empty.result.status == "insufficient_evidence"
