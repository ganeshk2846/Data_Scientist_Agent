"""Deterministic forecasts over prepared, governed series (V2-DATA-2, ANA-1)."""

from __future__ import annotations

import math
import re
import warnings
from datetime import date, datetime, timedelta
from typing import Literal

import numpy as np
from pydantic import Field, ValidationError
from scipy.stats import linregress, norm, t
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from contracts.models import AnalystInput, ContractModel, TableRef
from contracts.v2 import (
    AnalystOutput,
    ForecastComponent,
    ForecastPoint,
    ForecastResult,
    ForecastSeries,
)

from ._prophet import forecast_with_prophet

_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_MAX_DEFENSIBLE_HORIZON = 6


class ForecastParams(ContractModel):
    metric: str = Field(min_length=1)
    horizon: int = Field(ge=1)
    anchor: str = Field(min_length=1)
    grain: Literal["day", "week", "month", "quarter", "year"] = "month"
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    top_n: int = Field(default=5, ge=1)
    series_column: str | None = None
    ratio: bool = False


class ForecastAnalyst:
    module = "forecast"

    def run(self, inp: AnalystInput) -> AnalystOutput:
        table = inp.tables.get("series")
        if table is None:
            return _insufficient(
                "The forecast analyst requires a prepared 'series' table.", inp
            )
        try:
            params = ForecastParams.model_validate(inp.params)
        except ValidationError as exc:
            return _insufficient(f"Invalid forecast parameters: {exc}", inp, table)
        if params.metric in {"aov", "cancellation_rate"} and not params.ratio:
            params = params.model_copy(update={"ratio": True})

        anchor = _parse_period(params.anchor)
        if anchor is None:
            return _insufficient("The forecast anchor is not a valid period.", inp, table)
        columns = _series_columns(table, params)
        if columns is None:
            return _insufficient(
                "The series table needs a period and numeric value column; "
                "ratio forecasts also need numerator and denominator columns.",
                inp,
                table,
            )
        period_idx, value_idx, numerator_idx, denominator_idx, series_idx = columns
        groups: dict[str, dict[date, list[tuple[float, float | None, float | None]]]] = {}
        for row in table.rows:
            if max(
                index
                for index in (
                    period_idx,
                    value_idx,
                    numerator_idx,
                    denominator_idx,
                    series_idx,
                )
                if index is not None
            ) >= len(row):
                return _insufficient("A series row is missing required values.", inp, table)
            period = _parse_period(row[period_idx])
            if period is None:
                return _insufficient("The series contains an invalid period.", inp, table)
            if period > anchor:
                continue
            name = "All" if series_idx is None else str(row[series_idx]).strip()
            if not name or name.lower() == "none":
                return _insufficient("A series has a missing name.", inp, table)
            try:
                value = _finite_number(row[value_idx])
                numerator = (
                    _finite_number(row[numerator_idx])
                    if numerator_idx is not None
                    else None
                )
                denominator = (
                    _finite_number(row[denominator_idx])
                    if denominator_idx is not None
                    else None
                )
            except (TypeError, ValueError):
                return _insufficient("The series contains a non-finite value.", inp, table)
            if denominator is not None and denominator <= 0:
                return _insufficient(
                    "A ratio-series denominator must be positive.", inp, table
                )
            groups.setdefault(name, {}).setdefault(period, []).append(
                (value, numerator, denominator)
            )

        groups = {
            name: values
            for name, values in groups.items()
            if values
        }
        if not groups:
            return _insufficient(
                "No complete observations are available through the forecast anchor.",
                inp,
                table,
            )
        series_data: dict[str, tuple[tuple[date, ...], tuple[float, ...], tuple[float, ...] | None, tuple[float, ...] | None]] = {}
        try:
            for name in sorted(groups):
                packed = _aggregate_rows(groups[name], params.ratio)
                if packed is None:
                    return _insufficient(
                        "Ratio series require measured numerator and denominator columns.",
                        inp,
                        table,
                    )
                series_data[name] = packed
            total_data = _combine_series(tuple(series_data.values()), params.ratio)
        except OverflowError:
            return _insufficient(
                "The prepared series overflows during aggregation.", inp, table
            )
        if total_data is None:
            return _insufficient("The series could not be aggregated.", inp, table)

        ranked_names = sorted(
            series_data,
            key=lambda name: (-math.fsum(series_data[name][1]), name),
        )
        selected_names = ranked_names[: params.top_n] if series_idx is not None else []
        remainder_names = ranked_names[params.top_n :] if series_idx is not None else []
        required_horizon = params.horizon
        available_periods = len(total_data[0])
        defensible_horizon = min(
            _MAX_DEFENSIBLE_HORIZON,
            max(3, available_periods // 4),
        )
        effective_horizon = min(required_horizon, defensible_horizon)
        bounded_reason = (
            f"The requested {required_horizon}-period horizon was bounded to "
            f"{effective_horizon} defensible periods for {available_periods} observations."
            if effective_horizon < required_horizon
            else None
        )
        if available_periods < 12:
            return _insufficient(
                "At least 12 complete periods are required to fit a forecast.",
                inp,
                table,
            )
        future_periods = _future_periods(
            anchor, effective_horizon, params.grain
        )
        if future_periods is None:
            return _insufficient("The forecast horizon could not be generated.", inp, table)

        cache: dict[
            tuple[str, str],
            tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...], tuple[float, ...], tuple[float, ...], str, str | None],
        ] = {}

        def fit_named(
            name: str,
            data: tuple[
                tuple[date, ...],
                tuple[float, ...],
                tuple[float, ...] | None,
                tuple[float, ...] | None,
            ],
        ):
            key = (name, params.grain)
            if key not in cache:
                cache[key] = _fit_series(
                    data,
                    future_periods,
                    alpha=params.alpha,
                    seed=inp.seed or 0,
                    grain=params.grain,
                    ratio=params.ratio,
                )
            return cache[key]

        try:
            total_fit = fit_named("All", total_data)
            series_outputs: list[ForecastSeries] = []
            if selected_names:
                for name in selected_names:
                    values = fit_named(name, series_data[name])
                    series_outputs.append(
                        _to_forecast_series(name, future_periods, values, params.grain)
                    )
            if remainder_names:
                remainder_data = _combine_series(
                    tuple(series_data[name] for name in remainder_names), params.ratio
                )
                if remainder_data is not None:
                    remainder_fit = fit_named("All remaining", remainder_data)
                    series_outputs.append(
                        _to_forecast_series(
                            "All remaining",
                            future_periods,
                            remainder_fit,
                            params.grain,
                        )
                    )
        except (ArithmeticError, FloatingPointError, RuntimeError, ValueError) as exc:
            return _insufficient(
                f"The forecast model could not fit the prepared series: {exc}",
                inp,
                table,
            )

        yhat, lower, upper, trend, seasonal, method, fallback_reason = total_fit
        if not all(
            math.isfinite(value)
            for values in (yhat, lower, upper, trend, seasonal)
            for value in values
        ):
            return _insufficient(
                "The fitted forecast contains a non-finite value.", inp, table
            )
        mape, backtest_periods = _backtest(
            total_data,
            alpha=params.alpha,
            seed=inp.seed or 0,
            grain=params.grain,
            ratio=params.ratio,
        )
        if method == "ets" and fallback_reason is None:
            fallback_reason = "ETS was selected as the deterministic baseline model."
        points = tuple(
            ForecastPoint(
                ds=_format_period(period, params.grain),
                yhat=_bounded(value, params.metric),
                yhat_lower=_bounded(lo, params.metric),
                yhat_upper=_bounded(hi, params.metric),
            )
            for period, value, lo, hi in zip(
                future_periods, yhat, lower, upper, strict=True
            )
        )
        components = tuple(
            ForecastComponent(
                ds=_format_period(period, params.grain),
                trend=float(trend_value),
                seasonality=float(seasonal_value),
            )
            for period, trend_value, seasonal_value in zip(
                future_periods, trend, seasonal, strict=True
            )
        )
        slope, slope_interval = _trend_interval(total_data[1], params.alpha)
        if not math.isfinite(slope) or not all(
            math.isfinite(value) for value in slope_interval
        ):
            return _insufficient(
                "The trend estimate is not finite for this series.", inp, table
            )
        trend_detectable = not (slope_interval[0] <= 0.0 <= slope_interval[1])
        assumptions = [
            f"Fitted on complete observations through {_format_period(anchor, params.grain)}; all later periods were excluded.",
            "The prediction interval reflects held-out residual spread, not a confidence interval on the trend.",
            "The backtest MAPE uses a held-out tail and is unavailable when the series is too short or has a zero actual.",
        ]
        if params.ratio:
            assumptions.append(
                "The ratio was forecast by separately fitting its measured numerator and denominator, then forming their ratio."
            )
        if len(total_data[0]) < 24 and params.grain == "month":
            assumptions.append(
                "Yearly seasonality was not fitted because fewer than two complete annual cycles are available."
            )
        if bounded_reason:
            assumptions.append(bounded_reason)
        if series_idx is not None and len(series_data) > params.top_n:
            assumptions.append(
                f"Forecast the top {params.top_n} series by observed volume and the remainder as an aggregate."
            )
        assumptions.append(
            "Forecasts are deterministic for identical input rows and seed."
        )
        return AnalystOutput(
            module="forecast",
            status="ok",
            result=ForecastResult(
                anchor_period=_format_period(anchor, params.grain),
                points=points,
                components=components,
                trend_per_period=slope,
                trend_interval=slope_interval,
                trend_detectable=trend_detectable,
                method=method,
                method_fallback_reason=fallback_reason,
                mape=mape,
                history_periods=len(total_data[0]),
                backtest_periods=backtest_periods,
                series=tuple(series_outputs),
                remainder_series_count=len(remainder_names),
            ),
            parameters={
                "metric": params.metric,
                "grain": params.grain,
                "requested_horizon": required_horizon,
                "horizon": effective_horizon,
                "anchor": _format_period(anchor, params.grain),
                "alpha": params.alpha,
                "top_n": params.top_n,
                "ratio": params.ratio,
                "series_count": len(series_data),
                "cache_fits": len(cache),
            },
            assumptions=tuple(assumptions),
            sources=(table.query_id,),
        )


def _series_columns(
    table: TableRef, params: ForecastParams
) -> tuple[int, int, int | None, int | None, int | None] | None:
    names = {column.name.lower(): index for index, column in enumerate(table.columns)}
    period = next((names[key] for key in ("ds", "date", "month", "period") if key in names), None)
    value = next((names[key] for key in ("y", "value", params.metric.lower()) if key in names), None)
    numerator = names.get("numerator")
    denominator = names.get("denominator")
    if value is None and params.ratio and numerator is not None:
        value = numerator
    if params.series_column is not None and params.series_column.lower() not in names:
        return None
    series = (
        names.get(params.series_column.lower())
        if params.series_column is not None
        else next((names[key] for key in ("series", "dimension_value", "category") if key in names), None)
    )
    if period is None or value is None:
        return None
    if params.ratio and (numerator is None or denominator is None):
        return None
    return period, value, numerator, denominator, series


def _aggregate_rows(
    rows: dict[date, list[tuple[float, float | None, float | None]]],
    ratio: bool,
) -> tuple[
    tuple[date, ...],
    tuple[float, ...],
    tuple[float, ...] | None,
    tuple[float, ...] | None,
] | None:
    dates = tuple(sorted(rows))
    values: list[float] = []
    numerators: list[float] = []
    denominators: list[float] = []
    for period in dates:
        group = rows[period]
        if ratio:
            if any(row[1] is None or row[2] is None for row in group):
                return None
            numerator = math.fsum(sorted(float(row[1]) for row in group))
            denominator = math.fsum(sorted(float(row[2]) for row in group))
            if denominator <= 0:
                return None
            numerators.append(numerator)
            denominators.append(denominator)
            values.append(numerator / denominator)
        else:
            values.append(math.fsum(sorted(row[0] for row in group)))
    return (
        dates,
        tuple(values),
        tuple(numerators) if ratio else None,
        tuple(denominators) if ratio else None,
    )


def _combine_series(
    data: tuple[
        tuple[tuple[date, ...], tuple[float, ...], tuple[float, ...] | None, tuple[float, ...] | None],
        ...,
    ],
    ratio: bool,
) -> tuple[
    tuple[date, ...],
    tuple[float, ...],
    tuple[float, ...] | None,
    tuple[float, ...] | None,
] | None:
    dates = tuple(sorted(set().union(*(set(item[0]) for item in data))))
    if not dates:
        return None
    value_maps = [
        {period: value for period, value in zip(item[0], item[1], strict=True)}
        for item in data
    ]
    if ratio:
        if any(item[2] is None or item[3] is None for item in data):
            return None
        numerator_maps = [
            {period: value for period, value in zip(item[0], item[2] or (), strict=True)}
            for item in data
        ]
        denominator_maps = [
            {period: value for period, value in zip(item[0], item[3] or (), strict=True)}
            for item in data
        ]
        numerators = tuple(
            math.fsum(mapping.get(period, 0.0) for mapping in numerator_maps)
            for period in dates
        )
        denominators = tuple(
            math.fsum(mapping.get(period, 0.0) for mapping in denominator_maps)
            for period in dates
        )
        if any(value <= 0 for value in denominators):
            return None
        return (
            dates,
            tuple(numerator / denominator for numerator, denominator in zip(numerators, denominators, strict=True)),
            numerators,
            denominators,
        )
    return (
        dates,
        tuple(
            math.fsum(mapping.get(period, 0.0) for mapping in value_maps)
            for period in dates
        ),
        None,
        None,
    )


def _fit_series(
    data: tuple[
        tuple[date, ...],
        tuple[float, ...],
        tuple[float, ...] | None,
        tuple[float, ...] | None,
    ],
    future_periods: tuple[date, ...],
    *,
    alpha: float,
    seed: int,
    grain: str,
    ratio: bool,
) -> tuple[
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    Literal["prophet", "ets"],
    str | None,
]:
    dates, values, numerators, denominators = data
    if ratio and numerators is not None and denominators is not None:
        num_result = _fit_component(
            dates, numerators, future_periods, alpha, seed, grain
        )
        den_result = _fit_component(
            dates, denominators, future_periods, alpha, seed + 1, grain
        )
        yhat = tuple(
            numerator / denominator
            for numerator, denominator in zip(num_result[0], den_result[0], strict=True)
        )
        lower = tuple(
            numerator / denominator
            for numerator, denominator in zip(num_result[1], den_result[2], strict=True)
        )
        upper = tuple(
            numerator / denominator
            for numerator, denominator in zip(num_result[2], den_result[1], strict=True)
        )
        trend = _linear_component(yhat)
        seasonality = tuple(
            value - trend_value
            for value, trend_value in zip(yhat, trend, strict=True)
        )
        return (
            yhat,
            lower,
            upper,
            trend,
            seasonality,
            "prophet"
            if num_result[5] == den_result[5] == "prophet"
            else "ets",
            (
                None
                if num_result[5] == den_result[5] == "prophet"
                else "Ratio metrics are forecast by separately fitting numerator and denominator with ETS. "
                + "; ".join(
                    reason
                    for reason in (num_result[6], den_result[6])
                    if reason is not None
                )
            ),
        )
    result = _fit_component(dates, values, future_periods, alpha, seed, grain)
    yhat, lower, upper, trend, seasonality, method, reason = result
    return yhat, lower, upper, trend, seasonality, method, reason


def _fit_component(
    dates: tuple[date, ...],
    values: tuple[float, ...],
    future_periods: tuple[date, ...],
    alpha: float,
    seed: int,
    grain: str,
) -> tuple[
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
    Literal["prophet", "ets"],
    str | None,
]:
    if len(values) >= 24 and grain == "month":
        prophet_result, reason = forecast_with_prophet(
            dates,
            values,
            future_periods,
            alpha=alpha,
            seed=seed,
        )
        if prophet_result is not None:
            trend = prophet_result["trend"]
            return (
                prophet_result["yhat"],
                prophet_result["yhat_lower"],
                prophet_result["yhat_upper"],
                trend,
                prophet_result["seasonality"],
                "prophet",
                None,
            )
        fallback_reason = reason or "Prophet returned no forecast."
    else:
        fallback_reason = (
            "Prophet yearly seasonality requires at least 24 complete monthly periods."
            if grain == "month"
            else "Prophet seasonal fitting is restricted to monthly series."
        )
    values_array = np.asarray(values, dtype=float)
    if float(np.ptp(values_array)) == 0.0:
        level = float(values_array[0])
        flat = tuple(level for _ in future_periods)
        zeros = tuple(0.0 for _ in future_periods)
        return (
            flat,
            flat,
            flat,
            flat,
            zeros,
            "ets",
            "A constant series uses its exact observed level; fitting ETS would be numerically degenerate.",
        )
    seasonal_periods = 12 if len(values) >= 24 and grain == "month" else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ExponentialSmoothing(
            values_array,
            trend="add",
            damped_trend=True,
            seasonal="add" if seasonal_periods else None,
            seasonal_periods=seasonal_periods,
            initialization_method="estimated",
        )
        fitted = model.fit(optimized=True, use_brute=False)
    raw = np.asarray(fitted.forecast(len(future_periods)), dtype=float)
    residuals = values_array - np.asarray(fitted.fittedvalues, dtype=float)
    spread = float(np.std(residuals, ddof=1)) if len(residuals) > 1 else 0.0
    z_value = float(norm.ppf(1.0 - alpha / 2.0))
    margins = tuple(z_value * spread * math.sqrt(step) for step in range(1, len(raw) + 1))
    lower = tuple(float(value - margin) for value, margin in zip(raw, margins, strict=True))
    upper = tuple(float(value + margin) for value, margin in zip(raw, margins, strict=True))
    seasonality = _seasonal_component(
        dates,
        values,
        future_periods,
        enabled=seasonal_periods is not None,
    )
    trend = tuple(
        float(value - seasonal)
        for value, seasonal in zip(raw, seasonality, strict=True)
    )
    return (
        tuple(float(value) for value in raw),
        lower,
        upper,
        trend,
        seasonality,
        "ets",
        fallback_reason,
    )


def _backtest(
    data: tuple[
        tuple[date, ...],
        tuple[float, ...],
        tuple[float, ...] | None,
        tuple[float, ...] | None,
    ],
    *,
    alpha: float,
    seed: int,
    grain: str,
    ratio: bool,
) -> tuple[float | None, int]:
    dates, values, numerators, denominators = data
    holdout = min(3, max(1, len(values) // 5))
    if len(values) - holdout < 8:
        return None, 0
    split = len(values) - holdout
    if ratio and numerators is not None and denominators is not None:
        train = (dates[:split], values[:split], numerators[:split], denominators[:split])
    else:
        train = (dates[:split], values[:split], None, None)
    actual = values[split:]
    try:
        prediction = _fit_series(
            train,
            dates[split:],
            alpha=alpha,
            seed=seed,
            grain=grain,
            ratio=ratio,
        )[0]
    except (ArithmeticError, FloatingPointError, RuntimeError, ValueError):
        return None, 0
    if any(value == 0 for value in actual):
        return None, holdout
    try:
        mape = math.fsum(
            abs(predicted - observed) / abs(observed)
            for predicted, observed in zip(prediction, actual, strict=True)
        ) / holdout
    except OverflowError:
        return None, holdout
    return (float(mape), holdout) if math.isfinite(mape) else (None, holdout)


def _trend_interval(
    values: tuple[float, ...], alpha: float
) -> tuple[float, tuple[float, float]]:
    x = np.arange(len(values), dtype=float)
    fit = linregress(x, np.asarray(values, dtype=float))
    if len(values) <= 2 or not math.isfinite(float(fit.stderr)):
        return float(fit.slope), (float(fit.slope), float(fit.slope))
    critical = float(t.ppf(1.0 - alpha / 2.0, len(values) - 2))
    margin = critical * float(fit.stderr)
    return float(fit.slope), (float(fit.slope - margin), float(fit.slope + margin))


def _linear_component(values: tuple[float, ...]) -> tuple[float, ...]:
    if not values:
        return ()
    x = np.arange(len(values), dtype=float)
    slope, intercept = np.polyfit(x, np.asarray(values, dtype=float), 1)
    return tuple(float(intercept + slope * index) for index in range(len(values)))


def _seasonal_component(
    dates: tuple[date, ...],
    values: tuple[float, ...],
    future_periods: tuple[date, ...],
    *,
    enabled: bool,
) -> tuple[float, ...]:
    if not enabled:
        return tuple(0.0 for _ in future_periods)
    x = np.arange(len(values), dtype=float)
    slope, intercept = np.polyfit(x, np.asarray(values, dtype=float), 1)
    residuals = np.asarray(values, dtype=float) - (intercept + slope * x)
    by_month: dict[int, list[float]] = {}
    for period, residual in zip(dates, residuals, strict=True):
        by_month.setdefault(period.month, []).append(float(residual))
    month_means = {
        month: math.fsum(residual_values) / len(residual_values)
        for month, residual_values in by_month.items()
    }
    center = math.fsum(month_means.values()) / len(month_means)
    return tuple(
        float(month_means.get(period.month, 0.0) - center)
        for period in future_periods
    )


def _format_period(period: date, grain: str) -> str:
    return period.strftime("%Y-%m") if grain == "month" else period.isoformat()


def _to_forecast_series(
    name: str,
    periods: tuple[date, ...],
    fitted: tuple[
        tuple[float, ...],
        tuple[float, ...],
        tuple[float, ...],
        tuple[float, ...],
        tuple[float, ...],
        Literal["prophet", "ets"],
        str | None,
    ],
    grain: str,
) -> ForecastSeries:
    yhat, lower, upper, trend, seasonality, _, _ = fitted
    return ForecastSeries(
        name=name,
        points=tuple(
            ForecastPoint(
                ds=_format_period(period, grain),
                yhat=value,
                yhat_lower=lo,
                yhat_upper=hi,
            )
            for period, value, lo, hi in zip(periods, yhat, lower, upper, strict=True)
        ),
        components=tuple(
            ForecastComponent(
                ds=_format_period(period, grain),
                trend=trend_value,
                seasonality=seasonal,
            )
            for period, trend_value, seasonal in zip(periods, trend, seasonality, strict=True)
        ),
    )


def _future_periods(anchor: date, horizon: int, grain: str) -> tuple[date, ...] | None:
    periods: list[date] = []
    current = anchor
    for _ in range(horizon):
        if grain == "month":
            year = current.year + (current.month // 12)
            month = current.month % 12 + 1
            current = date(year, month, 1)
        elif grain == "quarter":
            month_index = current.year * 12 + current.month - 1 + 3
            current = date(month_index // 12, month_index % 12 + 1, 1)
        elif grain == "year":
            try:
                current = current.replace(year=current.year + 1)
            except ValueError:
                return None
        elif grain == "week":
            current += timedelta(days=7)
        else:
            current += timedelta(days=1)
        periods.append(current)
    return tuple(periods)


def _parse_period(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    match = _MONTH.fullmatch(value.strip())
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), 1)
        except ValueError:
            return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _finite_number(value: object) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("values must be finite")
    return result


def _bounded(value: float, metric: str) -> float:
    if metric == "review_score":
        return min(5.0, max(1.0, value))
    return value


def _insufficient(
    reason: str,
    inp: AnalystInput,
    table: TableRef | None = None,
) -> AnalystOutput:
    return AnalystOutput(
        module="forecast",
        status="insufficient_evidence",
        reason=reason,
        sources=(table.query_id,) if table is not None else (),
    )


__all__ = ["ForecastAnalyst", "ForecastParams"]
