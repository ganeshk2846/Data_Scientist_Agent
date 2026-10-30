"""Impact engine: significance and sizing vs baseline, target and peers; anomalies."""

from __future__ import annotations

import numpy as np
import pandas as pd
from contracts.v2 import ImpactResult
from engine_helpers import assert_complete_report, data, months, stable, table

from engines import impact


def _measurements(current, baseline, query_id="Q-M"):
    frame = pd.DataFrame({"period": ["base"] * len(baseline) + ["curr"] * len(current), "value": [*baseline, *current]})
    return table(frame, query_id, period="time")


def test_change_is_sized_in_reais_and_percent_vs_baseline_target_and_peers():
    tables = {
        "measurements": _measurements([7.0, 8.0, 7.0, 6.0, 7.0], [10.0, 11.0, 9.0, 10.0, 10.0]),
        "peers": _measurements([10.0, 10.0, 9.0, 11.0, 10.0], [10.0, 11.0, 9.0, 10.0, 10.0], "Q-P"),
        "targets": table(pd.DataFrame({"revenue_target": [20.0, 20.0]}), "Q-T"),
    }
    run = impact.execute({"metric": "revenue", "current_period": "curr", "baseline_period": "base"}, data(tables))
    result = run.result.analyst_output.result
    assert run.result.tool == "python.impact" and isinstance(result, ImpactResult)
    assert result.unit == "R$" and result.delta == -15.0 and result.delta_pct == -30.0
    assert result.significant is True and result.target == 40.0 and result.peer == 50.0
    report = run.report
    assert report.number("gap_to_target") == -5.0 and report.number("target_attainment_pct") == 87.5
    assert report.number("gap_to_peer") == -15.0 and report.number("peer_delta_pct") == 0.0
    assert report.number("excess_vs_peer_pts") == -30.0
    assert_complete_report(report)


def test_impact_without_target_or_peer_reports_neither():
    run = impact.execute({"metric": "revenue", "current_period": "curr", "baseline_period": "base"},
                         data({"measurements": _measurements([5.0, 6.0], [4.0, 4.0])}))
    assert run.result.analyst_output.result.target is None
    assert all(item.name not in {"gap_to_target", "gap_to_peer"} for item in run.report.key_numbers)


def test_zero_baseline_reports_no_fake_percent():
    run = impact.execute({"metric": "revenue", "current_period": "curr", "baseline_period": "base"},
                         data({"measurements": _measurements([5.0, 6.0], [0.0, 0.0])}))
    assert run.result.analyst_output.result.delta_pct is None


def test_missing_target_column_is_insufficient_not_assumed():
    run = impact.execute({"metric": "revenue"}, data({"measurements": _measurements([1.0], [1.0]),
                                                      "targets": table(pd.DataFrame({"x": [1.0]}), "Q-X")}))
    assert run.result.status == "insufficient_evidence" and "target" in run.result.reason


def _monthly_with_dip():
    rng = np.random.default_rng(5)
    labels = months("2016-09", 24)
    values = 1000.0 + rng.normal(0.0, 10.0, len(labels))
    values[labels.index("2018-03")] = 600.0
    return table(pd.DataFrame({"month": [f"{label}-01" for label in labels], "value": values}), "Q-S", month="time")


def test_anomaly_mode_tests_a_window_and_scan_mode_finds_the_planted_dip():
    series = _monthly_with_dip()
    single = impact.execute({"mode": "anomaly", "metric": "value", "test_window": {"start": "2018-03-01", "end": "2018-04-01"}},
                            data({"series": series}))
    assert single.result.tool == "python.anomaly"
    assert single.result.analyst_output.result.verdict == "unusual"
    scan = impact.execute({"mode": "anomaly", "metric": "value", "scan_window": {"start": "2017-11-01", "end": "2018-09-01"}},
                          data({"series": series}))
    assert scan.result.analyst_output.result.window.startswith("2018-03")
    assert scan.report.number("flagged_periods") >= 1
    assert_complete_report(scan.report)
    assert stable(scan.result) == stable(impact.execute(
        {"mode": "anomaly", "metric": "value", "scan_window": {"start": "2017-11-01", "end": "2018-09-01"}}, data({"series": series})).result)
