"""Pure variance attribution over a prepared contribution table (DRV)."""

from __future__ import annotations

import math
import re
from datetime import date
from statistics import NormalDist
from typing import Any, Literal

import numpy as np
from pydantic import Field
from scipy.stats import pearsonr, spearmanr
from sklearn.ensemble import RandomForestRegressor

from contracts.models import (
    AnalystInput,
    ContractModel,
    DriverContribution,
    DriverResult,
    Period,
    TableRef,
)
from contracts.v2 import AnalystOutput, DiagnosticEvidence, DiagnosticResult

_DATE_PATTERN = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")

_CAUSAL_NOTE = (
    "This analysis identifies the dimensions whose values moved with the "
    "metric. It is not causal evidence that those dimensions caused the "
    "change."
)
_E5_NOTE = (
    "Observed covariation indicates statistical association, not proven "
    "causality. Unmeasured exogenous variables and reverse causation can "
    "produce the same pattern."
)


class DriverParams(ContractModel):
    metric: str = Field(min_length=1)
    current_period: Period
    comparison_period: Period
    dimensions: tuple[str, ...] = Field(min_length=1)
    max_dimensions: int = Field(default=5, ge=1)
    max_depth: int = Field(default=2, ge=1)
    metric_tree: tuple[dict[str, Any], ...] = ()
    value_decomposition: bool = False
    indicators: tuple[dict[str, str], ...] = ()
    comparison_group: dict[str, Any] | None = None
    n_bootstrap: int = Field(default=200, ge=0)
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    aggregation: Literal["sum", "count", "avg", "mean", "ratio"] = "sum"


class DriverAnalyst:
    """Attribute an additive change with explicit evidence guardrails."""

    module = "driver"

    def __init__(
        self,
        *,
        zero_change_tolerance: float = 1e-12,
        small_cell_threshold: int = 5,
    ) -> None:
        if (
            not math.isfinite(zero_change_tolerance)
            or zero_change_tolerance < 0.0
        ):
            raise ValueError(
                "zero_change_tolerance must be a finite non-negative number"
            )
        if small_cell_threshold < 1:
            raise ValueError("small_cell_threshold must be at least 1")
        self.zero_change_tolerance = zero_change_tolerance
        self.small_cell_threshold = small_cell_threshold

    def run(self, analyst_input: AnalystInput) -> AnalystOutput:
        table = analyst_input.tables.get("contrib")
        if table is None:
            return _insufficient(
                "The driver analyst requires a 'contrib' table.",
                analyst_input,
            )
        try:
            params = DriverParams.model_validate(analyst_input.params)
        except Exception as exc:
            return _insufficient(
                f"Invalid driver parameters: {exc}",
                analyst_input,
                table,
            )
        unsupported = _unsupported_reason(params)
        if unsupported is not None:
            return _insufficient(unsupported, analyst_input, table)
        if params.aggregation in {"avg", "mean", "ratio"} or params.value_decomposition:
            return _run_ratio_metric(
                self,
                analyst_input,
                table,
                params,
            )

        columns = _driver_columns(table, params.dimensions)
        if columns is None:
            return _insufficient(
                "The contribution table needs a period column, a numeric "
                "value column and every requested dimension.",
                analyst_input,
                table,
            )
        period_index, value_index, dimensions = columns
        current_groups: dict[tuple[str, ...], list[float]] = {}
        comparison_groups: dict[tuple[str, ...], list[float]] = {}
        samples: dict[tuple[str, ...], int] = {}
        indexes = (period_index, value_index, *dimensions.values())
        for row in table.rows:
            if max(indexes) >= len(row):
                return _insufficient(
                    "A contribution row is missing one of its required values.",
                    analyst_input,
                    table,
                )
            period = _as_date(row[period_index])
            if period is None:
                return _insufficient(
                    "The contribution table contains an invalid period value.",
                    analyst_input,
                    table,
                )
            in_current = (
                params.current_period.start
                <= period
                < params.current_period.end
            )
            in_comparison = (
                params.comparison_period.start
                <= period
                < params.comparison_period.end
            )
            if not in_current and not in_comparison:
                continue
            try:
                value = float(row[value_index])
            except (TypeError, ValueError):
                return _insufficient(
                    "The contribution table contains a non-numeric value.",
                    analyst_input,
                    table,
                )
            if not math.isfinite(value):
                return _insufficient(
                    "The contribution table contains a non-finite value; "
                    "finite values are required.",
                    analyst_input,
                    table,
                )
            key_parts: list[str] = []
            for index in dimensions.values():
                raw = row[index]
                if raw is None:
                    return _insufficient(
                        "A requested dimension has a missing value.",
                        analyst_input,
                        table,
                    )
                text = str(raw).strip()
                if not text:
                    return _insufficient(
                        "A requested dimension has a blank value.",
                        analyst_input,
                        table,
                    )
                key_parts.append(text)
            key = tuple(key_parts)
            if in_current:
                current_groups.setdefault(key, []).append(value)
                samples[key] = samples.get(key, 0) + 1
            else:
                comparison_groups.setdefault(key, []).append(value)

        current, problem = _sum_groups(current_groups)
        if problem is not None:
            return _insufficient(problem, analyst_input, table)
        comparison, problem = _sum_groups(comparison_groups)
        if problem is not None:
            return _insufficient(problem, analyst_input, table)

        if not current and not comparison:
            return _insufficient(
                "Both the current and comparison windows need observations.",
                analyst_input,
                table,
            )
        if not current:
            return _insufficient(
                "The current window has no observations.",
                analyst_input,
                table,
            )
        if not comparison:
            return _insufficient(
                "The comparison window has no observations.",
                analyst_input,
                table,
            )

        try:
            current_total = math.fsum(sorted(current.values()))
            comparison_total = math.fsum(sorted(comparison.values()))
        except OverflowError:
            return _insufficient(
                "The contribution values overflow while being aggregated.",
                analyst_input,
                table,
            )
        total_change = current_total - comparison_total
        if not math.isfinite(total_change):
            return _insufficient(
                "The total change is not finite.",
                analyst_input,
                table,
            )
        if abs(total_change) <= self.zero_change_tolerance:
            return _insufficient(
                "Total change is zero or near zero; contribution shares are "
                "undefined.",
                analyst_input,
                table,
            )

        keys = sorted(
            set(current) | set(comparison),
            key=lambda key: (
                -abs(current.get(key, 0.0) - comparison.get(key, 0.0)),
                key,
            ),
        )
        contributions = [
            current.get(key, 0.0) - comparison.get(key, 0.0)
            for key in keys
        ]
        z_score = NormalDist().inv_cdf(1.0 - params.alpha / 2.0)
        drivers = tuple(
            _contribution(
                key=key,
                contribution=contribution,
                total_change=total_change,
                sample_size=samples.get(key, 0),
                dimensions=params.dimensions,
                z_score=z_score,
                small_cell_threshold=self.small_cell_threshold,
            )
            for key, contribution in zip(keys, contributions, strict=True)
        )
        try:
            reconciliation_error = total_change - math.fsum(contributions)
        except OverflowError:
            return _insufficient(
                "The contribution values overflow during reconciliation.",
                analyst_input,
                table,
            )
        if not _drivers_are_finite(
            total_change,
            reconciliation_error,
            drivers,
        ):
            return _insufficient(
                "The driver calculation produced a non-finite value.",
                analyst_input,
                table,
            )

        indicator_evidence, feature_evidence = _indicator_evidence(
            analyst_input,
            target_by_period=_target_series(table, params),
            params=params,
        )
        specificity = _difference_in_differences(
            current,
            comparison,
            params,
        )
        return AnalystOutput(
            module="driver",
            status="ok",
            result=DiagnosticResult(
                metric=params.metric,
                current_period=_period_label(params.current_period),
                comparison_period=_period_label(params.comparison_period),
                total_change=float(total_change),
                drivers=drivers,
                reconciliation_error=float(reconciliation_error),
                candidates_examined=len(keys),
                correction_used=(
                    f"benjamini_hochberg_{params.alpha:.2f}"
                    if indicator_evidence
                    else None
                ),
                indicator_drivers=indicator_evidence + specificity,
                feature_importance=feature_evidence,
                value_decomposition=drivers if params.value_decomposition else (),
            ),
            parameters={
                "metric": params.metric,
                "current_period": _period_label(params.current_period),
                "comparison_period": _period_label(params.comparison_period),
                "dimensions": params.dimensions,
                "aggregation": params.aggregation,
                "value_decomposition": params.value_decomposition,
                "max_dimensions": params.max_dimensions,
                "max_depth": params.max_depth,
                "n_bootstrap": params.n_bootstrap,
                "alpha": params.alpha,
                "zero_change_tolerance": self.zero_change_tolerance,
                "small_cell_threshold": self.small_cell_threshold,
            },
            assumptions=(
                "Contributions are exact current-minus-comparison changes for "
                "the prepared dimension rows.",
                "The interval is a normal approximation over the aggregate "
                "row count, not a row-level bootstrap.",
                "Drivers are single-level; no metric-tree traversal or correction was applied to the contribution ranking.",
                "Correlation candidates are Benjamini-Hochberg corrected across tested indicators and lags.",
                "Feature importance is capped at evidence grade 2 and is associational, not causal.",
                _CAUSAL_NOTE,
                _E5_NOTE,
            ),
            sources=tuple(
                dict.fromkeys(item.query_id for item in analyst_input.tables.values())
            ),
        )


def _unsupported_reason(params: DriverParams) -> str | None:
    if params.metric_tree:
        return "Metric-tree traversal is not implemented in this phase."
    if len(params.dimensions) > params.max_dimensions:
        return (
            f"{len(params.dimensions)} dimensions were requested, exceeding "
            f"max_dimensions={params.max_dimensions}."
        )
    if len({dimension.lower() for dimension in params.dimensions}) != len(
        params.dimensions
    ):
        return "Requested dimensions must be unique."
    return None


def _run_ratio_metric(
    analyst: DriverAnalyst,
    inp: AnalystInput,
    table: TableRef,
    params: DriverParams,
) -> AnalystOutput:
    columns = _ratio_columns(table, params)
    if columns is None:
        return _insufficient(
            "A mean/ratio contribution table needs period, numerator, denominator and requested dimension columns.",
            inp,
            table,
        )
    period_index, numerator_index, denominator_index, dimensions = columns
    current: dict[tuple[str, ...], tuple[float, float, int]] = {}
    comparison: dict[tuple[str, ...], tuple[float, float, int]] = {}
    work: dict[str, dict[tuple[str, ...], list[float]]] = {
        "current_num": {},
        "current_den": {},
        "comparison_num": {},
        "comparison_den": {},
    }
    for row in table.rows:
        if max((period_index, numerator_index, denominator_index, *dimensions.values())) >= len(row):
            return _insufficient("A ratio contribution row is incomplete.", inp, table)
        period = _as_date(row[period_index])
        if period is None:
            return _insufficient("The ratio contribution table has an invalid period.", inp, table)
        in_current = params.current_period.start <= period < params.current_period.end
        in_comparison = params.comparison_period.start <= period < params.comparison_period.end
        if not in_current and not in_comparison:
            continue
        try:
            numerator = float(row[numerator_index])
            denominator = (
                1.0 if denominator_index == -1 else float(row[denominator_index])
            )
        except (TypeError, ValueError):
            return _insufficient("Ratio numerators and denominators must be numeric.", inp, table)
        if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator < 0:
            return _insufficient("Ratio values must be finite and denominators non-negative.", inp, table)
        key: list[str] = []
        for index in dimensions.values():
            value = str(row[index]).strip()
            if not value:
                return _insufficient("Ratio contribution dimensions cannot be blank.", inp, table)
            key.append(value)
        dimension_key = tuple(key)
        prefix = "current" if in_current else "comparison"
        work[f"{prefix}_num"].setdefault(dimension_key, []).append(numerator)
        work[f"{prefix}_den"].setdefault(dimension_key, []).append(denominator)

    keys = sorted(
        set(work["current_num"])
        | set(work["current_den"])
        | set(work["comparison_num"])
        | set(work["comparison_den"])
    )
    if not keys:
        return _insufficient("Both ratio periods need prepared observations.", inp, table)
    for key in keys:
        current[key] = (
            math.fsum(work["current_num"].get(key, ())),
            math.fsum(work["current_den"].get(key, ())),
            len(work["current_num"].get(key, ())),
        )
        comparison[key] = (
            math.fsum(work["comparison_num"].get(key, ())),
            math.fsum(work["comparison_den"].get(key, ())),
            len(work["comparison_num"].get(key, ())),
        )
    current_n = math.fsum(value[0] for value in current.values())
    current_d = math.fsum(value[1] for value in current.values())
    comparison_n = math.fsum(value[0] for value in comparison.values())
    comparison_d = math.fsum(value[1] for value in comparison.values())
    if current_d <= 0 or comparison_d <= 0:
        return _insufficient("Both periods need positive ratio denominators.", inp, table)
    current_value = current_n / current_d
    comparison_value = comparison_n / comparison_d
    total_change = current_value - comparison_value
    components: list[DriverContribution] = []
    z_score = NormalDist().inv_cdf(1.0 - params.alpha / 2.0)
    for key in keys:
        current_num, current_den, sample_size = current[key]
        comparison_num, comparison_den, _ = comparison[key]
        numerator_effect = 0.5 * (current_num - comparison_num) * (
            1.0 / comparison_d + 1.0 / current_d
        )
        denominator_effect = (
            -0.5
            * (comparison_n + current_n)
            * (current_den - comparison_den)
            / (comparison_d * current_d)
        )
        for name, effect in (
            ("numerator", numerator_effect),
            ("denominator", denominator_effect),
        ):
            margin = z_score * abs(effect) / math.sqrt(max(sample_size, 1))
            components.append(
                DriverContribution(
                    dimension=f"{' / '.join(params.dimensions)} ({name})",
                    value=" / ".join(key),
                    contribution=float(effect),
                    share=0.0,
                    interval=(float(effect - margin), float(effect + margin)),
                    sample_size=sample_size,
                    unstable=sample_size < analyst.small_cell_threshold,
                    grade=1,
                    data_needed_to_strengthen=(
                        "A longer observation window and row-level denominator data.",
                    ),
                )
            )
    reconciliation_error = total_change - math.fsum(
        item.contribution for item in components
    )
    indicator_evidence, feature_evidence = _indicator_evidence(
        inp,
        target_by_period=_target_series(table, params, ratio=True),
        params=params,
    )
    return AnalystOutput(
        module="driver",
        status="ok",
        result=DiagnosticResult(
            metric=params.metric,
            current_period=_period_label(params.current_period),
            comparison_period=_period_label(params.comparison_period),
            total_change=total_change,
            drivers=tuple(components),
            reconciliation_error=reconciliation_error,
            candidates_examined=len(components),
            correction_used=(
                f"benjamini_hochberg_{params.alpha:.2f}"
                if indicator_evidence
                else None
            ),
            indicator_drivers=indicator_evidence
            + _difference_in_differences(current, comparison, params),
            feature_importance=feature_evidence,
            value_decomposition=tuple(components),
        ),
        parameters={
            "metric": params.metric,
            "aggregation": params.aggregation,
            "dimensions": params.dimensions,
            "value_decomposition": True,
            "correlation_candidates": len(indicator_evidence),
        },
        assumptions=(
            "The mean/ratio change is decomposed into numerator and denominator effects using a two-factor Shapley decomposition; the components reconcile exactly.",
            "Dimension shares are not additive shares of a mean or ratio; numerator/denominator components are used instead.",
            "The share field is zero for these non-additive components and must not be interpreted as a contribution share.",
            "Correlation and model-importance scores are associations, not proof of cause.",
            _CAUSAL_NOTE,
            _E5_NOTE,
        ),
        sources=tuple(dict.fromkeys(item.query_id for item in inp.tables.values())),
    )


def _ratio_columns(
    table: TableRef, params: DriverParams
) -> tuple[int, int, int, dict[str, int]] | None:
    names = {column.name.lower(): index for index, column in enumerate(table.columns)}
    period = next(
        (
            index
            for index, column in enumerate(table.columns)
            if column.role == "time"
            or column.name.lower() in {"period", "month", "date", "week", "quarter", "year"}
        ),
        None,
    )
    numerator = names.get("numerator")
    denominator = names.get("denominator")
    if numerator is None and params.aggregation in {"avg", "mean"}:
        numerator = next(
            (
                index
                for index, column in enumerate(table.columns)
                if column.role == "measure" or column.name.lower() in {"value", "score"}
            ),
            None,
        )
    if denominator is None and params.aggregation in {"avg", "mean"} and numerator is not None:
        denominator = names.get("count")
    if period is None or numerator is None:
        return None
    if denominator is None and params.aggregation in {"avg", "mean"}:
        denominator = -1
    if denominator is None:
        return None
    dimensions: dict[str, int] = {}
    for requested in params.dimensions:
        index = names.get(requested.lower())
        if index is None:
            return None
        dimensions[requested] = index
    return period, numerator, denominator, dimensions


def _target_series(
    table: TableRef, params: DriverParams, *, ratio: bool = False
) -> dict[date, float]:
    if ratio:
        columns = _ratio_columns(table, params)
        if columns is None:
            return {}
        period_index, numerator_index, denominator_index, _ = columns
        aggregate: dict[date, tuple[list[float], list[float]]] = {}
        for row in table.rows:
            period = _as_date(row[period_index])
            if period is None:
                continue
            try:
                numerator = float(row[numerator_index])
                denominator = 1.0 if denominator_index == -1 else float(row[denominator_index])
            except (IndexError, TypeError, ValueError):
                continue
            if math.isfinite(numerator) and math.isfinite(denominator) and denominator > 0:
                group = aggregate.setdefault(period, ([], []))
                group[0].append(numerator)
                group[1].append(denominator)
        return {
            period: math.fsum(numerators) / math.fsum(denominators)
            for period, (numerators, denominators) in aggregate.items()
            if math.fsum(denominators) > 0
        }
    columns = _driver_columns(table, params.dimensions)
    if columns is None:
        return {}
    period_idx, value_idx, _ = columns
    aggregate_values: dict[date, list[float]] = {}
    for row in table.rows:
        period = _as_date(row[period_idx])
        if period is None:
            continue
        try:
            value = float(row[value_idx])
        except (IndexError, TypeError, ValueError):
            continue
        if math.isfinite(value):
            aggregate_values.setdefault(period, []).append(value)
    return {period: math.fsum(values) for period, values in aggregate_values.items()}


def _difference_in_differences(
    current: dict[tuple[str, ...], Any],
    comparison: dict[tuple[str, ...], Any],
    params: DriverParams,
) -> tuple[DiagnosticEvidence, ...]:
    group = params.comparison_group
    if not group:
        return ()
    dimension = str(group.get("dimension", ""))
    treated = str(group.get("treated", ""))
    control = str(group.get("control", ""))
    try:
        dimension_index = params.dimensions.index(dimension)
    except ValueError:
        return ()
    treated_key = next(
        (key for key in set(current) | set(comparison) if key[dimension_index] == treated),
        None,
    )
    control_key = next(
        (key for key in set(current) | set(comparison) if key[dimension_index] == control),
        None,
    )
    if treated_key is None or control_key is None:
        return ()

    def scalar(row: Any) -> float:
        if isinstance(row, tuple):
            return float(row[0]) / float(row[1]) if float(row[1]) > 0 else 0.0
        return float(row)

    treated_delta = scalar(current.get(treated_key, 0.0)) - scalar(comparison.get(treated_key, 0.0))
    control_delta = scalar(current.get(control_key, 0.0)) - scalar(comparison.get(control_key, 0.0))
    effect = treated_delta - control_delta
    return (
        DiagnosticEvidence(
            dimension=dimension,
            value=treated,
            method="difference_in_differences",
            effect_size=effect,
            interval=(effect, effect),
            sample_size=2,
            grade=3,
        ),
    )


def _indicator_evidence(
    inp: AnalystInput,
    *,
    target_by_period: dict[date, float],
    params: DriverParams,
) -> tuple[tuple[DiagnosticEvidence, ...], tuple[DiagnosticEvidence, ...]]:
    if len(target_by_period) < 4:
        return (), ()
    target_periods = tuple(sorted(target_by_period))
    candidates: list[
        tuple[str, str, float, tuple[float, float], float, int, int]
    ] = []
    feature_series: dict[str, dict[date, float]] = {}
    for table_name, table in sorted(inp.tables.items()):
        if table_name.lower() in {"contrib", "series"}:
            continue
        date_index = next(
            (
                index
                for index, column in enumerate(table.columns)
                if column.role == "time"
                or column.name.lower() in {"date", "period", "month", "week"}
                or column.name.lower().endswith("_date")
            ),
            None,
        )
        if date_index is None:
            continue
        for value_index, column in enumerate(table.columns):
            if value_index == date_index or column.role in {"key", "time"}:
                continue
            name = column.name.lower()
            if name == "id" or name.endswith("_id"):
                continue
            period_values: dict[date, list[float]] = {}
            for row in table.rows:
                if max(date_index, value_index) >= len(row):
                    continue
                period = _as_date(row[date_index])
                if period is None:
                    continue
                period = date(period.year, period.month, 1)
                if period not in target_by_period:
                    continue
                try:
                    number = float(row[value_index])
                except (TypeError, ValueError):
                    continue
                if math.isfinite(number):
                    period_values.setdefault(period, []).append(number)
            if len(period_values) < 4:
                continue
            use_mean = any(
                marker in name
                for marker in ("rate", "flag", "pct", "score", "days", "price")
            )
            values = {
                period: (
                    math.fsum(observations) / len(observations)
                    if use_mean
                    else math.fsum(observations)
                )
                for period, observations in period_values.items()
            }
            feature_name = f"{table_name}.{column.name}"
            feature_series[feature_name] = values
            for lag in range(min(3, len(target_periods) // 3) + 1):
                pairs = [
                    (target_by_period[target_periods[index]], values[target_periods[index - lag]])
                    for index in range(lag, len(target_periods))
                    if target_periods[index] in values
                    and target_periods[index - lag] in values
                ]
                if len(pairs) < 4:
                    continue
                target_values = np.asarray([pair[0] for pair in pairs], dtype=float)
                indicator_values = np.asarray([pair[1] for pair in pairs], dtype=float)
                if np.ptp(target_values) == 0.0 or np.ptp(indicator_values) == 0.0:
                    continue
                try:
                    pearson = pearsonr(target_values, indicator_values)
                    spearman = spearmanr(target_values, indicator_values)
                except ValueError:
                    continue
                statistic, p_value = max(
                    (
                        (float(pearson.statistic), float(pearson.pvalue)),
                        (float(spearman.statistic), float(spearman.pvalue)),
                    ),
                    key=lambda pair: abs(pair[0]),
                )
                interval = _correlation_interval(statistic, len(pairs))
                candidates.append(
                    (
                        table_name,
                        column.name,
                        statistic,
                        interval,
                        p_value,
                        len(pairs),
                        lag,
                    )
                )
    q_values = _benjamini_hochberg([candidate[4] for candidate in candidates])
    evidence = tuple(
        DiagnosticEvidence(
            dimension=table_name,
            value=column,
            method="correlation",
            effect_size=effect,
            interval=interval,
            p_value=p_value,
            q_value=q_values[index],
            sample_size=sample_size,
            grade=2,
            lag_periods=lag,
        )
        for index, (
            table_name,
            column,
            effect,
            interval,
            p_value,
            sample_size,
            lag,
        ) in enumerate(candidates)
    )
    ranked_evidence = tuple(
        sorted(
            evidence,
            key=lambda item: (
                item.q_value if item.q_value is not None else 1.0,
                -abs(item.effect_size),
                item.dimension,
                item.value,
                item.lag_periods,
            ),
        )[:10]
    )
    importance: tuple[DiagnosticEvidence, ...] = ()
    selected_features = {
        name: values
        for name, values in feature_series.items()
        if all(period in values for period in target_periods)
        and len(set(values[period] for period in target_periods)) > 1
    }
    if len(selected_features) >= 2 and len(target_periods) >= 8:
        names = tuple(sorted(selected_features))
        matrix = np.asarray(
            [
                [selected_features[name][period] for name in names]
                for period in target_periods
            ],
            dtype=float,
        )
        target = np.asarray(
            [target_by_period[period] for period in target_periods],
            dtype=float,
        )
        if np.isfinite(matrix).all() and np.isfinite(target).all():
            model = RandomForestRegressor(
                n_estimators=100,
                max_depth=3,
                random_state=inp.seed if inp.seed is not None else 0,
                n_jobs=1,
            )
            model.fit(matrix, target)
            tree_values = np.asarray(
                [tree.feature_importances_ for tree in model.estimators_],
                dtype=float,
            )
            importance = tuple(
                DiagnosticEvidence(
                    dimension="feature_importance",
                    value=name,
                    method="feature_importance",
                    effect_size=float(model.feature_importances_[index]),
                    interval=(
                        float(np.quantile(tree_values[:, index], 0.025)),
                        float(np.quantile(tree_values[:, index], 0.975)),
                    ),
                    sample_size=len(target_periods),
                    grade=2,
                )
                for index, name in enumerate(names)
            )
            importance = tuple(
                sorted(importance, key=lambda item: (-item.effect_size, item.value))[:10]
            )
    return ranked_evidence, importance


def _correlation_interval(effect: float, sample_size: int) -> tuple[float, float]:
    if sample_size <= 3:
        return -1.0, 1.0
    bounded = min(0.999999, max(-0.999999, effect))
    z = math.atanh(bounded)
    margin = NormalDist().inv_cdf(0.975) / math.sqrt(sample_size - 3)
    return math.tanh(z - margin), math.tanh(z + margin)


def _benjamini_hochberg(p_values: list[float]) -> tuple[float, ...]:
    if not p_values:
        return ()
    order = sorted(range(len(p_values)), key=lambda index: (p_values[index], index))
    q_values = [1.0] * len(p_values)
    total = len(p_values)
    running = 1.0
    for position in range(total - 1, -1, -1):
        index = order[position]
        running = min(running, p_values[index] * total / (position + 1))
        q_values[index] = min(1.0, running)
    return tuple(q_values)


def _sum_groups(
    groups: dict[tuple[str, ...], list[float]],
) -> tuple[dict[tuple[str, ...], float], str | None]:
    totals: dict[tuple[str, ...], float] = {}
    for key in sorted(groups):
        try:
            totals[key] = math.fsum(sorted(groups[key]))
        except OverflowError:
            return {}, "The contribution values overflow while being aggregated."
    return totals, None


def _contribution(
    *,
    key: tuple[str, ...],
    contribution: float,
    total_change: float,
    sample_size: int,
    dimensions: tuple[str, ...],
    z_score: float,
    small_cell_threshold: int,
) -> DriverContribution:
    share = contribution / total_change
    half_width = (
        z_score * abs(contribution) / math.sqrt(sample_size)
        if sample_size > 0
        else abs(contribution)
    )
    unstable = sample_size < small_cell_threshold
    return DriverContribution(
        dimension=" / ".join(dimensions),
        value=" / ".join(key),
        contribution=float(contribution),
        share=float(share),
        interval=(float(contribution - half_width), float(contribution + half_width)),
        sample_size=sample_size,
        unstable=unstable,
        grade=1 if unstable else 2,
        data_needed_to_strengthen=(
            "A longer comparison window with row-level observations.",
            "A bootstrap or hierarchical attribution model for interval "
            "estimation.",
        )
        if unstable
        else (),
    )


def _drivers_are_finite(
    total_change: float,
    reconciliation_error: float,
    drivers: tuple[DriverContribution, ...],
) -> bool:
    if not math.isfinite(total_change) or not math.isfinite(
        reconciliation_error
    ):
        return False
    for driver in drivers:
        values = (
            driver.contribution,
            driver.share,
            driver.interval[0],
            driver.interval[1],
        )
        if not all(math.isfinite(value) for value in values):
            return False
    return True


def _driver_columns(
    table: TableRef,
    requested: tuple[str, ...],
) -> tuple[int, int, dict[str, int]] | None:
    period_index = None
    value_index = None
    by_name: dict[str, int] = {}
    dimension_candidates: dict[str, int] = {}
    for index, column in enumerate(table.columns):
        name = column.name.lower()
        if period_index is None and (
            column.role == "time"
            or name in {"period", "month", "date", "week", "quarter", "year"}
            or name.endswith("_date")
        ):
            period_index = index
            continue
        if value_index is None and (
            column.role == "measure"
            or name in {"value", "measure", "metric_value", "contribution"}
        ):
            value_index = index
            continue
        by_name[name] = index
        if column.role == "dimension":
            dimension_candidates[name] = index

    resolved: dict[str, int] = {}
    remaining = list(dimension_candidates.items())
    for dimension in requested:
        lowered = dimension.lower()
        if lowered in by_name:
            resolved[dimension] = by_name[lowered]
            continue
        match = next(
            (
                index
                for name, index in remaining
                if lowered in name or name in lowered
            ),
            None,
        )
        if match is None:
            return None
        resolved[dimension] = match
    if period_index is None or value_index is None:
        return None
    if len(set(resolved.values())) != len(resolved):
        return None
    return period_index, value_index, resolved


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    match = _DATE_PATTERN.match(value.strip())
    if match is None:
        return None
    return date(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or 1),
    )


def _period_label(period: Period) -> str:
    return f"{period.start.isoformat()}/{period.end.isoformat()}"


def _insufficient(
    reason: str,
    analyst_input: AnalystInput,
    table: TableRef | None = None,
) -> AnalystOutput:
    return AnalystOutput(
        module="driver",
        status="insufficient_evidence",
        reason=reason,
        sources=(table.query_id,) if table is not None else (),
        parameters=dict(analyst_input.params),
    )


__all__ = ["DriverAnalyst", "DriverParams"]
