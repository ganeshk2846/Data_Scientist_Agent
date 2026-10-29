"""Pure scoring of analyst outputs against planted ground truth.

The functions in this module accept typed analyst outputs and typed truth
records. They never read a manifest file, database, network resource or model
client, and they contain no benchmark runner or result persistence. Scores
describe synthetic evaluation fixtures only; they are not production
performance measurements.

Requirement IDs: ANA-5, ANOM-9, DRV-10.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Literal

from pydantic import Field, model_validator

from contracts.models import (
    AnalystOutput,
    AnomalyResult,
    ContractModel,
    DriverContribution,
    DriverResult,
    NegativeControl,
    PlantedAnomaly,
    PlantedDriver,
)

ScoringStatus = Literal["scored", "insufficient_evidence", "invalid_input"]
AnomalyOutcome = Literal[
    "true_positive",
    "false_negative",
    "false_alert",
    "true_negative",
    "not_evaluated",
]


class AnomalyCaseScore(ContractModel):
    """One anomaly or negative-control scoring decision."""

    truth_id: str = Field(min_length=1)
    truth_kind: Literal["planted_anomaly", "negative_control"]
    truth_metric: str = Field(min_length=1)
    status: ScoringStatus
    outcome: AnomalyOutcome = "not_evaluated"
    reason: str | None = None
    detected: bool | None = None
    detection_delay_days: int | None = Field(default=None, ge=0)
    detection_delay_supported: bool = False
    within_detection_tolerance: bool | None = None

    @model_validator(mode="after")
    def _outcome_matches_status(self) -> AnomalyCaseScore:
        if self.status == "scored":
            if self.outcome == "not_evaluated":
                raise ValueError("a scored case needs a concrete outcome")
        else:
            if self.outcome != "not_evaluated":
                raise ValueError("an unscored case cannot carry an outcome")
            if not self.reason:
                raise ValueError("an unscored case needs a reason")
        return self


class AnomalyScoringSummary(ContractModel):
    """Aggregate anomaly scoring for a set of injected evaluation cases."""

    status: ScoringStatus
    reason: str | None = None
    cases: tuple[AnomalyCaseScore, ...] = ()
    scored_cases: int = Field(default=0, ge=0)
    true_positives: int = Field(default=0, ge=0)
    false_negatives: int = Field(default=0, ge=0)
    false_alerts: int = Field(default=0, ge=0)
    true_negatives: int = Field(default=0, ge=0)
    not_evaluated: int = Field(default=0, ge=0)
    detection_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    false_alert_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    detection_delay_supported: bool = False
    mean_detection_delay_days: float | None = Field(default=None, ge=0.0)
    max_detection_delay_days: int | None = Field(default=None, ge=0)
    detection_delay_tolerance_days: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _unscored_summary_has_a_reason(self) -> AnomalyScoringSummary:
        if self.status != "scored" and not self.reason:
            raise ValueError("an unscored summary needs a reason")
        return self


class DriverCaseScore(ContractModel):
    """One driver-attribution scoring decision."""

    anomaly_id: str = Field(min_length=1)
    status: ScoringStatus
    reason: str | None = None
    top1_hit: bool | None = None
    top3_hit: bool | None = None
    matched_rank: int | None = Field(default=None, ge=1)
    matched_dimension: str | None = None
    matched_value: str | None = None
    true_share: float | None = None
    observed_share: float | None = None
    share_difference: float | None = Field(default=None, ge=0.0)
    share_tolerance: float = Field(default=0.0, ge=0.0)
    contribution_agreement: bool | None = None
    reconciliation_valid: bool | None = None
    reconciliation_error: float | None = None
    reconciliation_tolerance: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _outcome_matches_status(self) -> DriverCaseScore:
        if self.status == "scored":
            if self.top1_hit is None or self.top3_hit is None:
                raise ValueError("a scored driver case needs top-1 and top-3 hits")
            if self.reconciliation_valid is None:
                raise ValueError(
                    "a scored driver case needs a reconciliation decision"
                )
        else:
            if not self.reason:
                raise ValueError("an unscored driver case needs a reason")
        return self


class DriverScoringSummary(ContractModel):
    """Aggregate driver scoring for a set of injected evaluation cases."""

    status: ScoringStatus
    reason: str | None = None
    cases: tuple[DriverCaseScore, ...] = ()
    scored_cases: int = Field(default=0, ge=0)
    top1_hits: int = Field(default=0, ge=0)
    top3_hits: int = Field(default=0, ge=0)
    contribution_agreements: int = Field(default=0, ge=0)
    reconciliation_valid_cases: int = Field(default=0, ge=0)
    top1_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    top3_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    contribution_agreement_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    reconciliation_valid_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    share_tolerance: float = Field(default=0.0, ge=0.0)
    reconciliation_tolerance: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _unscored_summary_has_a_reason(self) -> DriverScoringSummary:
        if self.status != "scored" and not self.reason:
            raise ValueError("an unscored summary needs a reason")
        return self


def score_anomaly_detection(
    output: AnalystOutput,
    truth: PlantedAnomaly,
    *,
    detection_delay_tolerance_days: int = 0,
) -> AnomalyCaseScore:
    """Score one analyst output against one planted anomaly.

    Detection requires an ``unusual`` verdict whose evaluated window overlaps
    the planted period. A detection delay is reported only when the truth
    record supplies both ``start`` and ``end``.
    """

    if not isinstance(truth, PlantedAnomaly):
        return _anomaly_unscored(
            "unknown",
            "planted_anomaly",
            "unknown",
            "invalid_input",
            "truth must be a PlantedAnomaly",
        )
    if not isinstance(output, AnalystOutput):
        return _anomaly_unscored(
            truth.anomaly_id,
            "planted_anomaly",
            truth.metric,
            "invalid_input",
            "output must be an AnalystOutput",
        )
    if not _is_non_negative_int(detection_delay_tolerance_days):
        return _anomaly_unscored(
            truth.anomaly_id,
            "planted_anomaly",
            truth.metric,
            "invalid_input",
            "detection_delay_tolerance_days must be a non-negative integer",
        )
    if output.module != "anomaly":
        return _anomaly_unscored(
            truth.anomaly_id,
            "planted_anomaly",
            truth.metric,
            "invalid_input",
            "output module is not 'anomaly'",
        )
    if output.status != "ok":
        return _anomaly_unscored(
            truth.anomaly_id,
            "planted_anomaly",
            truth.metric,
            "insufficient_evidence",
            output.reason or "the analyst returned no anomaly result",
        )
    result = output.result
    if not isinstance(result, AnomalyResult):
        return _anomaly_unscored(
            truth.anomaly_id,
            "planted_anomaly",
            truth.metric,
            "invalid_input",
            "the analyst output does not contain an AnomalyResult",
        )
    window = _parse_window(result.window)
    if window is None:
        return _anomaly_unscored(
            truth.anomaly_id,
            "planted_anomaly",
            truth.metric,
            "invalid_input",
            "the anomaly result window is not a valid start/end pair",
        )
    window_start, window_end = window
    if not _overlaps_planted_period(window_start, window_end, truth):
        return _anomaly_unscored(
            truth.anomaly_id,
            "planted_anomaly",
            truth.metric,
            "invalid_input",
            "the analyst window does not overlap the planted anomaly period",
        )

    detected = result.verdict == "unusual"
    delay_supported = detected and truth.end is not None
    delay = (
        max(0, (window_start - truth.start).days)
        if delay_supported
        else None
    )
    within_tolerance = (
        delay <= detection_delay_tolerance_days
        if delay is not None
        else None
    )
    return AnomalyCaseScore(
        truth_id=truth.anomaly_id,
        truth_kind="planted_anomaly",
        truth_metric=truth.metric,
        status="scored",
        outcome="true_positive" if detected else "false_negative",
        detected=detected,
        detection_delay_days=delay,
        detection_delay_supported=delay_supported,
        within_detection_tolerance=within_tolerance,
    )


def score_false_alert(
    output: AnalystOutput,
    truth: NegativeControl,
) -> AnomalyCaseScore:
    """Score one analyst output against one generator negative control."""

    if not isinstance(truth, NegativeControl):
        return _anomaly_unscored(
            "unknown",
            "negative_control",
            "unknown",
            "invalid_input",
            "truth must be a NegativeControl",
        )
    if not isinstance(output, AnalystOutput):
        return _anomaly_unscored(
            truth.control_id,
            "negative_control",
            truth.metric,
            "invalid_input",
            "output must be an AnalystOutput",
        )
    if output.module != "anomaly":
        return _anomaly_unscored(
            truth.control_id,
            "negative_control",
            truth.metric,
            "invalid_input",
            "output module is not 'anomaly'",
        )
    if output.status != "ok":
        return _anomaly_unscored(
            truth.control_id,
            "negative_control",
            truth.metric,
            "insufficient_evidence",
            output.reason or "the analyst returned no anomaly result",
        )
    result = output.result
    if not isinstance(result, AnomalyResult):
        return _anomaly_unscored(
            truth.control_id,
            "negative_control",
            truth.metric,
            "invalid_input",
            "the analyst output does not contain an AnomalyResult",
        )
    window = _parse_window(result.window)
    if window is None:
        return _anomaly_unscored(
            truth.control_id,
            "negative_control",
            truth.metric,
            "invalid_input",
            "the anomaly result window is not a valid start/end pair",
        )
    window_start, window_end = window
    if not (
        window_start < truth.period.end
        and window_end > truth.period.start
    ):
        return _anomaly_unscored(
            truth.control_id,
            "negative_control",
            truth.metric,
            "invalid_input",
            "the analyst window does not overlap the negative-control period",
        )
    if result.verdict == "insufficient_evidence":
        return _anomaly_unscored(
            truth.control_id,
            "negative_control",
            truth.metric,
            "insufficient_evidence",
            "the analyst returned an insufficient-evidence verdict",
        )

    flagged = result.verdict == "unusual"
    return AnomalyCaseScore(
        truth_id=truth.control_id,
        truth_kind="negative_control",
        truth_metric=truth.metric,
        status="scored",
        outcome="false_alert" if flagged else "true_negative",
        detected=flagged,
    )


def summarize_anomaly_scores(
    scores: tuple[AnomalyCaseScore, ...],
    *,
    detection_delay_tolerance_days: int = 0,
) -> AnomalyScoringSummary:
    """Summarize already-computed anomaly case scores deterministically."""

    if not _is_non_negative_int(detection_delay_tolerance_days):
        return AnomalyScoringSummary(
            status="invalid_input",
            reason="detection_delay_tolerance_days must be a non-negative integer",
            cases=(),
            detection_delay_tolerance_days=0,
        )
    if not isinstance(scores, tuple) or any(
        not isinstance(score, AnomalyCaseScore) for score in scores
    ):
        return AnomalyScoringSummary(
            status="invalid_input",
            reason="scores must be a tuple of AnomalyCaseScore records",
            cases=(),
            detection_delay_tolerance_days=detection_delay_tolerance_days,
        )
    if not scores:
        return AnomalyScoringSummary(
            status="insufficient_evidence",
            reason="no anomaly evaluation cases were supplied",
            cases=(),
            detection_delay_tolerance_days=detection_delay_tolerance_days,
        )

    true_positives = sum(
        score.outcome == "true_positive" for score in scores
    )
    false_negatives = sum(
        score.outcome == "false_negative" for score in scores
    )
    false_alerts = sum(score.outcome == "false_alert" for score in scores)
    true_negatives = sum(
        score.outcome == "true_negative" for score in scores
    )
    not_evaluated = sum(
        score.outcome == "not_evaluated" for score in scores
    )
    scored_cases = (
        true_positives + false_negatives + false_alerts + true_negatives
    )
    detection_rate = (
        true_positives / (true_positives + false_negatives)
        if (true_positives + false_negatives) > 0
        else None
    )
    false_alert_rate = (
        false_alerts / (false_alerts + true_negatives)
        if (false_alerts + true_negatives) > 0
        else None
    )
    delays = tuple(
        score.detection_delay_days
        for score in scores
        if score.detection_delay_supported
        and score.detection_delay_days is not None
    )
    mean_delay = (
        math.fsum(delays) / len(delays)
        if delays
        else None
    )
    max_delay = max(delays) if delays else None
    numbers = (
        detection_rate,
        false_alert_rate,
        mean_delay,
    )
    if any(
        number is not None and not math.isfinite(number)
        for number in numbers
    ):
        return AnomalyScoringSummary(
            status="invalid_input",
            reason="an anomaly score produced a non-finite value",
            cases=scores,
            detection_delay_tolerance_days=detection_delay_tolerance_days,
        )
    if scored_cases == 0:
        return AnomalyScoringSummary(
            status="insufficient_evidence",
            reason="no anomaly case could be scored",
            cases=scores,
            not_evaluated=not_evaluated,
            detection_delay_tolerance_days=detection_delay_tolerance_days,
        )
    return AnomalyScoringSummary(
        status="scored",
        cases=scores,
        scored_cases=scored_cases,
        true_positives=true_positives,
        false_negatives=false_negatives,
        false_alerts=false_alerts,
        true_negatives=true_negatives,
        not_evaluated=not_evaluated,
        detection_rate=detection_rate,
        false_alert_rate=false_alert_rate,
        detection_delay_supported=bool(delays),
        mean_detection_delay_days=mean_delay,
        max_detection_delay_days=max_delay,
        detection_delay_tolerance_days=detection_delay_tolerance_days,
    )


def score_driver_attribution(
    output: AnalystOutput,
    anomaly: PlantedAnomaly,
    drivers: tuple[PlantedDriver, ...],
    *,
    share_tolerance: float = 0.05,
    reconciliation_tolerance: float = 1e-9,
) -> DriverCaseScore:
    """Score top-1, top-3, share agreement and reconciliation for one case."""

    if not _is_finite_non_negative(share_tolerance):
        return _driver_unscored(
            "unknown",
            "invalid_input",
            "share_tolerance must be finite and non-negative",
        )
    if not _is_finite_non_negative(reconciliation_tolerance):
        return _driver_unscored(
            "unknown",
            "invalid_input",
            "reconciliation_tolerance must be finite and non-negative",
        )
    if not isinstance(anomaly, PlantedAnomaly):
        return _driver_unscored(
            "unknown",
            "invalid_input",
            "anomaly must be a PlantedAnomaly",
        )
    if not isinstance(drivers, tuple) or any(
        not isinstance(driver, PlantedDriver) for driver in drivers
    ):
        return _driver_unscored(
            anomaly.anomaly_id,
            "invalid_input",
            "drivers must be a tuple of PlantedDriver records",
        )
    if not drivers:
        return _driver_unscored(
            anomaly.anomaly_id,
            "insufficient_evidence",
            "no planted drivers are available for this anomaly",
        )
    if any(driver.anomaly_id != anomaly.anomaly_id for driver in drivers):
        return _driver_unscored(
            anomaly.anomaly_id,
            "invalid_input",
            "planted driver anomaly_id values do not match the anomaly",
        )
    if not isinstance(output, AnalystOutput):
        return _driver_unscored(
            anomaly.anomaly_id,
            "invalid_input",
            "output must be an AnalystOutput",
        )
    if output.module != "driver":
        return _driver_unscored(
            anomaly.anomaly_id,
            "invalid_input",
            "output module is not 'driver'",
        )
    if output.status != "ok":
        return _driver_unscored(
            anomaly.anomaly_id,
            "insufficient_evidence",
            output.reason or "the analyst returned no driver result",
        )
    result = output.result
    if not isinstance(result, DriverResult):
        return _driver_unscored(
            anomaly.anomaly_id,
            "invalid_input",
            "the analyst output does not contain a DriverResult",
        )
    if result.metric != anomaly.metric:
        return _driver_unscored(
            anomaly.anomaly_id,
            "invalid_input",
            "the driver result metric does not match the planted anomaly metric",
        )
    if not _driver_result_is_finite(result):
        return _driver_unscored(
            anomaly.anomaly_id,
            "invalid_input",
            "the driver result contains a non-finite value",
        )

    matched_rank = None
    matched_contribution = None
    matched_truth = None
    for index, contribution in enumerate(result.drivers):
        for truth in drivers:
            if _contribution_matches(contribution, truth):
                matched_rank = index + 1
                matched_contribution = contribution
                matched_truth = truth
                break
        if matched_rank is not None:
            break

    top1_hit = (
        any(
            _contribution_matches(result.drivers[0], truth)
            for truth in drivers
        )
        if result.drivers
        else False
    )
    top3_hit = any(
        _contribution_matches(contribution, truth)
        for contribution in result.drivers[:3]
        for truth in drivers
    )
    reconciliation_valid = (
        abs(result.reconciliation_error) <= reconciliation_tolerance
    )

    true_share = None
    observed_share = None
    share_difference = None
    contribution_agreement = None
    if matched_contribution is not None and matched_truth is not None:
        true_share = float(matched_truth.true_share)
        observed_share = float(matched_contribution.share)
        share_difference = abs(observed_share - true_share)
        contribution_agreement = share_difference <= share_tolerance

    return DriverCaseScore(
        anomaly_id=anomaly.anomaly_id,
        status="scored",
        top1_hit=top1_hit,
        top3_hit=top3_hit,
        matched_rank=matched_rank,
        matched_dimension=(
            matched_contribution.dimension
            if matched_contribution is not None
            else None
        ),
        matched_value=(
            matched_contribution.value
            if matched_contribution is not None
            else None
        ),
        true_share=true_share,
        observed_share=observed_share,
        share_difference=share_difference,
        share_tolerance=float(share_tolerance),
        contribution_agreement=contribution_agreement,
        reconciliation_valid=reconciliation_valid,
        reconciliation_error=float(result.reconciliation_error),
        reconciliation_tolerance=float(reconciliation_tolerance),
    )


def summarize_driver_scores(
    scores: tuple[DriverCaseScore, ...],
    *,
    share_tolerance: float = 0.05,
    reconciliation_tolerance: float = 1e-9,
) -> DriverScoringSummary:
    """Summarize already-computed driver case scores deterministically."""

    if not _is_finite_non_negative(share_tolerance):
        return DriverScoringSummary(
            status="invalid_input",
            reason="share_tolerance must be finite and non-negative",
            cases=(),
        )
    if not _is_finite_non_negative(reconciliation_tolerance):
        return DriverScoringSummary(
            status="invalid_input",
            reason="reconciliation_tolerance must be finite and non-negative",
            cases=(),
        )
    if not isinstance(scores, tuple) or any(
        not isinstance(score, DriverCaseScore) for score in scores
    ):
        return DriverScoringSummary(
            status="invalid_input",
            reason="scores must be a tuple of DriverCaseScore records",
            cases=(),
            share_tolerance=float(share_tolerance),
            reconciliation_tolerance=float(reconciliation_tolerance),
        )
    if not scores:
        return DriverScoringSummary(
            status="insufficient_evidence",
            reason="no driver evaluation cases were supplied",
            cases=(),
            share_tolerance=float(share_tolerance),
            reconciliation_tolerance=float(reconciliation_tolerance),
        )

    top1_hits = sum(score.top1_hit is True for score in scores)
    top3_hits = sum(score.top3_hit is True for score in scores)
    contribution_agreements = sum(
        score.contribution_agreement is True for score in scores
    )
    reconciliation_valid_cases = sum(
        score.reconciliation_valid is True for score in scores
    )
    scored_cases = sum(score.status == "scored" for score in scores)
    top1_denominator = sum(score.top1_hit is not None for score in scores)
    top3_denominator = sum(score.top3_hit is not None for score in scores)
    agreement_denominator = sum(
        score.contribution_agreement is not None for score in scores
    )
    reconciliation_denominator = sum(
        score.reconciliation_valid is not None for score in scores
    )
    top1_rate = (
        top1_hits / top1_denominator if top1_denominator else None
    )
    top3_rate = (
        top3_hits / top3_denominator if top3_denominator else None
    )
    agreement_rate = (
        contribution_agreements / agreement_denominator
        if agreement_denominator
        else None
    )
    reconciliation_rate = (
        reconciliation_valid_cases / reconciliation_denominator
        if reconciliation_denominator
        else None
    )
    numbers = (top1_rate, top3_rate, agreement_rate, reconciliation_rate)
    if any(
        number is not None and not math.isfinite(number)
        for number in numbers
    ):
        return DriverScoringSummary(
            status="invalid_input",
            reason="a driver score produced a non-finite value",
            cases=scores,
            share_tolerance=float(share_tolerance),
            reconciliation_tolerance=float(reconciliation_tolerance),
        )
    if scored_cases == 0:
        return DriverScoringSummary(
            status="insufficient_evidence",
            reason="no driver case could be scored",
            cases=scores,
            share_tolerance=float(share_tolerance),
            reconciliation_tolerance=float(reconciliation_tolerance),
        )
    return DriverScoringSummary(
        status="scored",
        cases=scores,
        scored_cases=scored_cases,
        top1_hits=top1_hits,
        top3_hits=top3_hits,
        contribution_agreements=contribution_agreements,
        reconciliation_valid_cases=reconciliation_valid_cases,
        top1_rate=top1_rate,
        top3_rate=top3_rate,
        contribution_agreement_rate=agreement_rate,
        reconciliation_valid_rate=reconciliation_rate,
        share_tolerance=float(share_tolerance),
        reconciliation_tolerance=float(reconciliation_tolerance),
    )


def _parse_window(label: object) -> tuple[date, date] | None:
    if not isinstance(label, str):
        return None
    parts = label.split("/")
    if len(parts) != 2:
        return None
    try:
        start = date.fromisoformat(parts[0])
        end = date.fromisoformat(parts[1])
    except ValueError:
        return None
    if end <= start:
        return None
    return start, end


def _overlaps_planted_period(
    window_start: date,
    window_end: date,
    truth: PlantedAnomaly,
) -> bool:
    if truth.end is None:
        return window_end > truth.start
    return window_start < truth.end and window_end > truth.start


def _anomaly_unscored(
    truth_id: str,
    truth_kind: Literal["planted_anomaly", "negative_control"],
    truth_metric: str,
    status: ScoringStatus,
    reason: str,
) -> AnomalyCaseScore:
    return AnomalyCaseScore(
        truth_id=truth_id,
        truth_kind=truth_kind,
        truth_metric=truth_metric,
        status=status,
        reason=reason,
    )


def _driver_unscored(
    anomaly_id: str,
    status: ScoringStatus,
    reason: str,
) -> DriverCaseScore:
    return DriverCaseScore(
        anomaly_id=anomaly_id,
        status=status,
        reason=reason,
    )


def _driver_result_is_finite(result: DriverResult) -> bool:
    if not math.isfinite(result.total_change):
        return False
    if not math.isfinite(result.reconciliation_error):
        return False
    for driver in result.drivers:
        values = (
            driver.contribution,
            driver.share,
            driver.interval[0],
            driver.interval[1],
        )
        if not all(math.isfinite(value) for value in values):
            return False
    return True


def _contribution_matches(
    contribution: DriverContribution,
    truth: PlantedDriver,
) -> bool:
    return _matches_component(
        contribution.value,
        truth.cause.value,
    ) and _matches_component(
        contribution.dimension,
        truth.cause.dimension,
    )


def _matches_component(text: str, expected: str) -> bool:
    normalised = text.strip().lower()
    expected_normalised = expected.strip().lower()
    if normalised == expected_normalised:
        return True
    return any(
        part.strip().lower() == expected_normalised
        for part in normalised.split("/")
    )


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_finite_non_negative(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


__all__ = [
    "AnomalyCaseScore",
    "AnomalyOutcome",
    "AnomalyScoringSummary",
    "DriverCaseScore",
    "DriverScoringSummary",
    "ScoringStatus",
    "score_anomaly_detection",
    "score_driver_attribution",
    "score_false_alert",
    "summarize_anomaly_scores",
    "summarize_driver_scores",
]
