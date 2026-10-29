"""Pure scoring tests against injected planted truth (ANA-5, ANOM-9, DRV-10)."""

from __future__ import annotations

import math
from datetime import date

from analysts.scoring import (
    AnomalyCaseScore,
    DriverCaseScore,
    score_anomaly_detection,
    score_driver_attribution,
    score_false_alert,
    summarize_anomaly_scores,
    summarize_driver_scores,
)
from contracts.models import (
    AnalystOutput,
    AnomalyResult,
    DriverContribution,
    DriverResult,
    NegativeControl,
    Period,
    PlantedAnomaly,
    PlantedDriver,
    TruthUnit,
)


def _anomaly_result(
    *,
    verdict: str = "unusual",
    window: str = "2024-03-01/2024-04-01",
) -> AnomalyResult:
    return AnomalyResult(
        verdict=verdict,
        window=window,
        actual=80.0,
        expected=100.0,
        expected_range=(90.0, 110.0),
        deviation_pct=-20.0,
        robust_score=-4.0,
        persistence="sustained",
        threshold=2.5,
        baseline_kind="robust_trailing",
    )


def _anomaly_output(
    *,
    verdict: str = "unusual",
    window: str = "2024-03-01/2024-04-01",
    status: str = "ok",
    reason: str | None = None,
) -> AnalystOutput:
    return AnalystOutput(
        module="anomaly",
        status=status,
        reason=reason,
        result=(
            _anomaly_result(verdict=verdict, window=window)
            if status == "ok"
            else None
        ),
    )


def _planted_anomaly(
    *,
    anomaly_id: str = "ANOM-001",
    end: date | None = date(2024, 4, 1),
) -> PlantedAnomaly:
    return PlantedAnomaly(
        anomaly_id=anomaly_id,
        metric="orders",
        unit=TruthUnit(dimension="region", value="SP"),
        kind="level_shift",
        start=date(2024, 3, 1),
        end=end,
        magnitude_pct=-25.0,
    )


def _negative_control() -> NegativeControl:
    return NegativeControl(
        control_id="CTRL-001",
        metric="orders",
        unit=TruthUnit(dimension="region", value="SP"),
        period=Period(start=date(2024, 3, 1), end=date(2024, 4, 1)),
        kind="ordinary",
    )


def _contribution(value: str, contribution: float, share: float) -> DriverContribution:
    return DriverContribution(
        dimension="region",
        value=value,
        contribution=contribution,
        share=share,
        interval=(contribution, contribution),
        sample_size=10,
        unstable=False,
        grade=2,
    )


def _driver_output(
    rows: tuple[DriverContribution, ...],
    *,
    reconciliation_error: float = 0.0,
    status: str = "ok",
    reason: str | None = None,
) -> AnalystOutput:
    return AnalystOutput(
        module="driver",
        status=status,
        reason=reason,
        result=(
            DriverResult(
                metric="orders",
                current_period="2024-03-01/2024-04-01",
                comparison_period="2024-02-01/2024-03-01",
                total_change=100.0,
                drivers=rows,
                reconciliation_error=reconciliation_error,
                candidates_examined=len(rows),
            )
            if status == "ok"
            else None
        ),
    )


def _planted_driver(
    *,
    anomaly_id: str = "ANOM-001",
    true_share: float = 0.8,
) -> PlantedDriver:
    return PlantedDriver(
        anomaly_id=anomaly_id,
        cause_kind="segment",
        cause=TruthUnit(dimension="region", value="SP"),
        true_share=true_share,
    )


def test_anomaly_detection_success_is_a_true_positive():
    score = score_anomaly_detection(
        _anomaly_output(verdict="unusual"),
        _planted_anomaly(),
    )

    assert score.status == "scored"
    assert score.outcome == "true_positive"
    assert score.detected is True
    assert score.detection_delay_supported is True
    assert score.detection_delay_days == 0


def test_anomaly_detection_miss_is_a_false_negative():
    score = score_anomaly_detection(
        _anomaly_output(verdict="within_normal_range"),
        _planted_anomaly(),
    )

    assert score.status == "scored"
    assert score.outcome == "false_negative"
    assert score.detected is False


def test_false_alert_scoring_distinguishes_flag_from_control():
    flagged = score_false_alert(
        _anomaly_output(verdict="unusual"),
        _negative_control(),
    )
    quiet = score_false_alert(
        _anomaly_output(verdict="within_normal_range"),
        _negative_control(),
    )

    assert flagged.status == "scored"
    assert flagged.outcome == "false_alert"
    assert quiet.status == "scored"
    assert quiet.outcome == "true_negative"


def test_detection_delay_is_reported_when_truth_has_timing_fields():
    score = score_anomaly_detection(
        _anomaly_output(window="2024-03-15/2024-04-01"),
        _planted_anomaly(),
        detection_delay_tolerance_days=7,
    )

    assert score.detection_delay_supported is True
    assert score.detection_delay_days == 14
    assert score.within_detection_tolerance is False


def test_detection_delay_is_not_reported_without_truth_end():
    score = score_anomaly_detection(
        _anomaly_output(window="2024-03-15/2024-04-01"),
        _planted_anomaly(end=None),
    )

    assert score.outcome == "true_positive"
    assert score.detection_delay_supported is False
    assert score.detection_delay_days is None


def test_driver_top1_hit_and_contribution_agreement():
    score = score_driver_attribution(
        _driver_output(
            (
                _contribution("SP", 80.0, 0.8),
                _contribution("RJ", 20.0, 0.2),
            )
        ),
        _planted_anomaly(),
        (_planted_driver(true_share=0.8),),
    )

    assert score.status == "scored"
    assert score.top1_hit is True
    assert score.top3_hit is True
    assert score.matched_rank == 1
    assert score.contribution_agreement is True
    assert score.share_difference == 0.0


def test_driver_top3_hit_when_truth_is_ranked_second():
    score = score_driver_attribution(
        _driver_output(
            (
                _contribution("RJ", 20.0, 0.2),
                _contribution("SP", 80.0, 0.8),
            )
        ),
        _planted_anomaly(),
        (_planted_driver(),),
    )

    assert score.top1_hit is False
    assert score.top3_hit is True
    assert score.matched_rank == 2


def test_driver_miss_has_no_contribution_agreement():
    score = score_driver_attribution(
        _driver_output((_contribution("RJ", 100.0, 1.0),)),
        _planted_anomaly(),
        (_planted_driver(),),
    )

    assert score.status == "scored"
    assert score.top1_hit is False
    assert score.top3_hit is False
    assert score.matched_rank is None
    assert score.contribution_agreement is None


def test_contribution_agreement_uses_explicit_share_tolerance():
    within = score_driver_attribution(
        _driver_output((_contribution("SP", 50.0, 0.5),)),
        _planted_anomaly(),
        (_planted_driver(true_share=0.52),),
        share_tolerance=0.05,
    )
    outside = score_driver_attribution(
        _driver_output((_contribution("SP", 50.0, 0.5),)),
        _planted_anomaly(),
        (_planted_driver(true_share=0.8),),
        share_tolerance=0.05,
    )

    assert within.contribution_agreement is True
    assert outside.contribution_agreement is False


def test_reconciliation_validation_uses_explicit_tolerance():
    valid = score_driver_attribution(
        _driver_output((_contribution("SP", 100.0, 1.0),), reconciliation_error=0.0),
        _planted_anomaly(),
        (_planted_driver(true_share=1.0),),
        reconciliation_tolerance=1e-9,
    )
    invalid = score_driver_attribution(
        _driver_output(
            (_contribution("SP", 100.0, 1.0),),
            reconciliation_error=0.5,
        ),
        _planted_anomaly(),
        (_planted_driver(true_share=1.0),),
        reconciliation_tolerance=1e-9,
    )

    assert valid.reconciliation_valid is True
    assert invalid.reconciliation_valid is False


def test_empty_evaluation_input_fails_closed():
    anomaly = summarize_anomaly_scores(())
    driver = summarize_driver_scores(())

    assert anomaly.status == "insufficient_evidence"
    assert anomaly.reason is not None
    assert anomaly.scored_cases == 0
    assert anomaly.detection_rate is None
    assert anomaly.false_alert_rate is None

    assert driver.status == "insufficient_evidence"
    assert driver.reason is not None
    assert driver.scored_cases == 0
    assert driver.top1_rate is None
    assert driver.top3_rate is None


def test_mismatched_ids_fail_closed():
    score = score_driver_attribution(
        _driver_output((_contribution("SP", 100.0, 1.0),)),
        _planted_anomaly(anomaly_id="ANOM-001"),
        (_planted_driver(anomaly_id="ANOM-404"),),
    )

    assert score.status == "invalid_input"
    assert score.reason is not None
    assert score.top1_hit is None


def test_insufficient_evidence_inputs_are_not_scored():
    anomaly = score_anomaly_detection(
        _anomaly_output(status="insufficient_evidence", reason="too little history"),
        _planted_anomaly(),
    )
    driver = score_driver_attribution(
        _driver_output(
            (),
            status="insufficient_evidence",
            reason="no comparison window",
        ),
        _planted_anomaly(),
        (_planted_driver(),),
    )

    assert anomaly.status == "insufficient_evidence"
    assert anomaly.outcome == "not_evaluated"
    assert driver.status == "insufficient_evidence"
    assert driver.top1_hit is None

    summary = summarize_anomaly_scores((anomaly,))
    assert summary.status == "insufficient_evidence"
    assert summary.not_evaluated == 1
    assert summary.scored_cases == 0


def test_repeated_scoring_is_deterministic():
    first_pair = (
        score_anomaly_detection(_anomaly_output(), _planted_anomaly()),
        score_driver_attribution(
            _driver_output(
                (
                    _contribution("SP", 80.0, 0.8),
                    _contribution("RJ", 20.0, 0.2),
                )
            ),
            _planted_anomaly(),
            (_planted_driver(true_share=0.8),),
        ),
    )
    second_pair = (
        score_anomaly_detection(_anomaly_output(), _planted_anomaly()),
        score_driver_attribution(
            _driver_output(
                (
                    _contribution("SP", 80.0, 0.8),
                    _contribution("RJ", 20.0, 0.2),
                )
            ),
            _planted_anomaly(),
            (_planted_driver(true_share=0.8),),
        ),
    )

    assert first_pair[0].model_dump() == second_pair[0].model_dump()
    assert first_pair[1].model_dump() == second_pair[1].model_dump()
    assert summarize_anomaly_scores((first_pair[0],)).model_dump() == (
        summarize_anomaly_scores((second_pair[0],)).model_dump()
    )
    assert summarize_driver_scores((first_pair[1],)).model_dump() == (
        summarize_driver_scores((second_pair[1],)).model_dump()
    )


def test_anomaly_summary_counts_and_rates_are_finite():
    scores = (
        score_anomaly_detection(_anomaly_output(), _planted_anomaly()),
        score_anomaly_detection(
            _anomaly_output(verdict="within_normal_range"),
            _planted_anomaly(anomaly_id="ANOM-002"),
        ),
        score_false_alert(
            _anomaly_output(verdict="within_normal_range"),
            _negative_control(),
        ),
        score_false_alert(
            _anomaly_output(
                verdict="unusual",
                window="2024-05-01/2024-06-01",
            ),
            NegativeControl(
                control_id="CTRL-002",
                metric="orders",
                unit=TruthUnit(dimension="region", value="SP"),
                period=Period(
                    start=date(2024, 5, 1),
                    end=date(2024, 6, 1),
                ),
                kind="noise",
            ),
        ),
    )
    summary = summarize_anomaly_scores(scores)

    assert summary.status == "scored"
    assert summary.true_positives == 1
    assert summary.false_negatives == 1
    assert summary.false_alerts == 1
    assert summary.true_negatives == 1
    assert summary.detection_rate == 0.5
    assert summary.false_alert_rate == 0.5
    _assert_finite_numbers(summary.model_dump())


def test_driver_summary_counts_and_rates_are_finite():
    scores = (
        score_driver_attribution(
            _driver_output((_contribution("SP", 100.0, 1.0),)),
            _planted_anomaly(),
            (_planted_driver(true_share=1.0),),
        ),
        score_driver_attribution(
            _driver_output((_contribution("RJ", 100.0, 1.0),)),
            _planted_anomaly(anomaly_id="ANOM-002"),
            (_planted_driver(anomaly_id="ANOM-002", true_share=1.0),),
        ),
    )
    summary = summarize_driver_scores(scores)

    assert summary.status == "scored"
    assert summary.top1_hits == 1
    assert summary.top3_hits == 1
    assert summary.top1_rate == 0.5
    assert summary.top3_rate == 0.5
    assert summary.reconciliation_valid_cases == 2
    _assert_finite_numbers(summary.model_dump())


def test_all_scoring_outputs_are_finite():
    anomaly = score_anomaly_detection(_anomaly_output(), _planted_anomaly())
    control = score_false_alert(
        _anomaly_output(verdict="within_normal_range"),
        _negative_control(),
    )
    driver = score_driver_attribution(
        _driver_output((_contribution("SP", 100.0, 1.0),)),
        _planted_anomaly(),
        (_planted_driver(true_share=1.0),),
    )
    invalid = score_driver_attribution(
        _driver_output((_contribution("SP", 100.0, 1.0),)),
        _planted_anomaly(),
        (_planted_driver(anomaly_id="ANOM-404"),),
    )

    for record in (anomaly, control, driver, invalid):
        assert isinstance(record, (AnomalyCaseScore, DriverCaseScore))
        _assert_finite_numbers(record.model_dump())


def test_malformed_truth_fails_closed_even_with_invalid_tolerance():
    for tolerance in (-1, "not-a-number", None):
        score = score_anomaly_detection(
            _anomaly_output(),
            object(),
            detection_delay_tolerance_days=tolerance,
        )

        assert score.status == "invalid_input"
        assert score.outcome == "not_evaluated"
        assert score.reason == "truth must be a PlantedAnomaly"
        assert score.truth_id == "unknown"
        assert score.truth_metric == "unknown"


def test_malformed_anomaly_output_fails_closed():
    score = score_anomaly_detection(object(), _planted_anomaly())

    assert score.status == "invalid_input"
    assert score.outcome == "not_evaluated"
    assert score.reason == "output must be an AnalystOutput"
    assert score.truth_id == "ANOM-001"
    assert score.truth_metric == "orders"


def test_malformed_driver_inputs_fail_closed():
    malformed_anomaly = score_driver_attribution(
        _driver_output((_contribution("SP", 100.0, 1.0),)),
        object(),
        (_planted_driver(),),
    )
    malformed_drivers = score_driver_attribution(
        _driver_output((_contribution("SP", 100.0, 1.0),)),
        _planted_anomaly(),
        (object(),),
    )
    malformed_output = score_driver_attribution(
        object(),
        _planted_anomaly(),
        (_planted_driver(),),
    )

    assert malformed_anomaly.status == "invalid_input"
    assert malformed_anomaly.reason == "anomaly must be a PlantedAnomaly"
    assert malformed_anomaly.anomaly_id == "unknown"

    assert malformed_drivers.status == "invalid_input"
    assert malformed_drivers.reason == (
        "drivers must be a tuple of PlantedDriver records"
    )
    assert malformed_drivers.anomaly_id == "ANOM-001"

    assert malformed_output.status == "invalid_input"
    assert malformed_output.reason == "output must be an AnalystOutput"
    assert malformed_output.anomaly_id == "ANOM-001"


def test_malformed_summary_inputs_fail_closed():
    anomaly_not_tuple = summarize_anomaly_scores(None)
    anomaly_wrong_member = summarize_anomaly_scores((object(),))
    driver_not_tuple = summarize_driver_scores(None)
    driver_wrong_member = summarize_driver_scores((object(),))

    for summary in (
        anomaly_not_tuple,
        anomaly_wrong_member,
        driver_not_tuple,
        driver_wrong_member,
    ):
        assert summary.status == "invalid_input"
        assert summary.reason is not None
        assert summary.scored_cases == 0


def test_typed_failure_results_are_deterministic():
    first_anomaly = score_anomaly_detection(
        object(),
        object(),
        detection_delay_tolerance_days=-1,
    )
    second_anomaly = score_anomaly_detection(
        object(),
        object(),
        detection_delay_tolerance_days=-1,
    )
    first_driver = score_driver_attribution(object(), object(), ())
    second_driver = score_driver_attribution(object(), object(), ())

    assert first_anomaly.model_dump() == second_anomaly.model_dump()
    assert first_driver.model_dump() == second_driver.model_dump()
    assert first_anomaly.status == "invalid_input"
    assert first_driver.status == "invalid_input"


def _assert_finite_numbers(value) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _assert_finite_numbers(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _assert_finite_numbers(item)
        return
    if isinstance(value, float):
        assert math.isfinite(value)
