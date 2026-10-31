"""Significance and sizing for measured period changes (ANA-1)."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import Field, ValidationError
from scipy.stats import ttest_ind, t

from contracts.models import AnalystInput, ContractModel, TableRef
from contracts.v2 import AnalystOutput, ImpactResult


class ImpactParams(ContractModel):
    metric: str = Field(min_length=1)
    basis: Literal["measured_change", "anomaly_gap", "driver_change"] = "measured_change"
    unit: str = "R$"
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    aggregation: Literal["sum", "mean"] = "sum"
    current_period: str | None = None
    baseline_period: str | None = None


class ImpactAnalyst:
    module = "impact"

    def run(self, inp: AnalystInput) -> AnalystOutput:
        table = inp.tables.get("measurements") or inp.tables.get("impact")
        if table is None:
            return _insufficient(
                "The impact analyst requires measured totals or period-level observations.",
                inp,
            )
        try:
            params = ImpactParams.model_validate(inp.params)
        except ValidationError as exc:
            return _insufficient(f"Invalid impact parameters: {exc}", inp, table)

        columns = {column.name.lower(): index for index, column in enumerate(table.columns)}
        if "baseline" in columns and "current" in columns:
            if not table.rows or len(table.rows[0]) <= max(columns["baseline"], columns["current"]):
                return _insufficient("The impact table is missing its measured totals.", inp, table)
            try:
                baseline = _number(table.rows[0][columns["baseline"]])
                current = _number(table.rows[0][columns["current"]])
            except (TypeError, ValueError):
                return _insufficient("Impact totals must be finite measured values.", inp, table)
            baseline_samples: tuple[float, ...] = ()
            current_samples: tuple[float, ...] = ()
        elif {"period", "value"} <= columns.keys():
            groups: dict[str, list[float]] = {}
            for row in table.rows:
                try:
                    label = str(row[columns["period"]])
                    value = _number(row[columns["value"]])
                except (IndexError, TypeError, ValueError):
                    return _insufficient("Impact observations must have valid period and value cells.", inp, table)
                groups.setdefault(label, []).append(value)
            current_label = params.current_period
            baseline_label = params.baseline_period
            if current_label is None or baseline_label is None:
                labels = sorted(groups)
                if len(labels) != 2:
                    return _insufficient(
                        "Specify current_period and baseline_period or provide exactly two measured periods.",
                        inp,
                        table,
                    )
                baseline_label, current_label = labels
            if current_label not in groups or baseline_label not in groups:
                return _insufficient("The requested measured periods are absent.", inp, table)
            baseline_samples = tuple(groups[baseline_label])
            current_samples = tuple(groups[current_label])
            if params.aggregation == "mean":
                baseline = math.fsum(baseline_samples) / len(baseline_samples)
                current = math.fsum(current_samples) / len(current_samples)
            else:
                baseline = math.fsum(baseline_samples)
                current = math.fsum(current_samples)
        else:
            return _insufficient(
                "Provide baseline/current totals or period/value observations.",
                inp,
                table,
            )

        delta = current - baseline
        delta_pct = 100.0 * delta / baseline if baseline != 0.0 else None
        try:
            target = _optional_measure(table, columns, "target")
            peer = _optional_measure(table, columns, "peer")
        except (IndexError, TypeError, ValueError):
            return _insufficient(
                "Target and peer comparisons must be finite measured values.",
                inp,
                table,
            )
        p_value: float | None = None
        significant: bool | None = None
        effect_size: float | None = None
        interval = (delta, delta)
        if len(current_samples) >= 2 and len(baseline_samples) >= 2:
            test = ttest_ind(current_samples, baseline_samples, equal_var=False)
            if math.isfinite(float(test.pvalue)):
                p_value = float(test.pvalue)
                significant = p_value < params.alpha
            pooled_standard_deviation = _pooled_standard_deviation(
                current_samples, baseline_samples
            )
            sample_mean_delta = (
                math.fsum(current_samples) / len(current_samples)
                - math.fsum(baseline_samples) / len(baseline_samples)
            )
            effect_size = (
                sample_mean_delta / pooled_standard_deviation
                if pooled_standard_deviation is not None
                else None
            )
            if math.isfinite(float(test.statistic)):
                interval = _difference_interval(
                    current_samples,
                    baseline_samples,
                    delta,
                    params.alpha,
                    aggregation=params.aggregation,
                )
        if not all(math.isfinite(value) for value in (delta, *interval)):
            return _insufficient("The impact calculation produced a non-finite value.", inp, table)

        return AnalystOutput(
            module="impact",
            status="ok",
            result=ImpactResult(
                metric=params.metric,
                baseline=baseline,
                current=current,
                delta=delta,
                delta_pct=delta_pct,
                interval=interval,
                unit=params.unit,
                p_value=p_value,
                significant=significant,
                effect_size=effect_size,
                target=target,
                peer=peer,
            ),
            parameters={
                "metric": params.metric,
                "basis": params.basis,
                "unit": params.unit,
                "alpha": params.alpha,
                "aggregation": params.aggregation,
                "baseline_period": params.baseline_period,
                "current_period": params.current_period,
            },
            assumptions=(
                "Impact is current measured value minus the measured baseline.",
                "A percent change is undefined when the measured baseline is zero.",
                "A significance test is reported only when both periods have at least two observations.",
                "Target attainment and peer comparisons are reported only when their measured values are supplied upstream.",
            ),
            sources=(table.query_id,),
        )


def _difference_interval(
    current: tuple[float, ...],
    baseline: tuple[float, ...],
    delta: float,
    alpha: float,
    *,
    aggregation: str,
) -> tuple[float, float]:
    n_current = len(current)
    n_baseline = len(baseline)
    variance_current = _sample_variance(current)
    variance_baseline = _sample_variance(baseline)
    scale_current = 1.0 / n_current if aggregation == "mean" else n_current
    scale_baseline = 1.0 / n_baseline if aggregation == "mean" else n_baseline
    component_current = variance_current * scale_current
    component_baseline = variance_baseline * scale_baseline
    standard_error = math.sqrt(component_current + component_baseline)
    numerator = (component_current + component_baseline) ** 2
    denominator = (
        component_current**2 / (n_current - 1)
        + component_baseline**2 / (n_baseline - 1)
    )
    degrees = numerator / denominator if denominator else min(n_current, n_baseline) - 1
    margin = float(t.ppf(1.0 - alpha / 2.0, degrees)) * standard_error
    return delta - margin, delta + margin


def _pooled_standard_deviation(
    current: tuple[float, ...], baseline: tuple[float, ...]
) -> float | None:
    degrees = len(current) + len(baseline) - 2
    if degrees <= 0:
        return None
    variance = (
        (len(current) - 1) * _sample_variance(current)
        + (len(baseline) - 1) * _sample_variance(baseline)
    ) / degrees
    return math.sqrt(variance) if variance > 0 else None


def _sample_variance(values: tuple[float, ...]) -> float:
    mean = math.fsum(values) / len(values)
    return math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1)


def _number(value: object) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("values must be finite")
    return result


def _optional_measure(
    table: TableRef, columns: dict[str, int], name: str
) -> float | None:
    index = columns.get(name)
    if index is None or not table.rows:
        return None
    return _number(table.rows[0][index])


def _insufficient(
    reason: str,
    inp: AnalystInput,
    table: TableRef | None = None,
) -> AnalystOutput:
    return AnalystOutput(
        module="impact",
        status="insufficient_evidence",
        reason=reason,
        sources=(table.query_id,) if table is not None else (),
    )


__all__ = ["ImpactAnalyst", "ImpactParams"]
