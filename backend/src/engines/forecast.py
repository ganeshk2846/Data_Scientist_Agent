"""Forecast (WHAT NEXT): Prophet / ETS through ``analysts.forecast`` plus an
ARIMA challenger, with the horizon taken from the question.

The method of record stays the existing ``python.forecast`` path (Prophet,
falling back to statsmodels ETS, TR-8), because ``ForecastResult.method``
is frozen to ``"prophet" | "ets"``. ARIMA runs as a *challenger*: it is
fitted and backtested on exactly the same held-out tail, its MAPE is
reported beside the primary MAPE, and its path is listed in the report. It
never silently replaces the reported forecast.
"""

from __future__ import annotations

import itertools
import math
import warnings
from collections.abc import Mapping
from typing import Any, Literal

import numpy as np
import pandas as pd
from analysts import registry
from contracts.models import ContractModel
from contracts.v2 import FitQuality, ForecastResult
from pydantic import Field
from statsmodels.tools.sm_exceptions import ConvergenceWarning
from statsmodels.tsa.arima.model import ARIMA

from .base import (
    EngineData,
    Timer,
    analyst_input,
    engine_result,
    frame_from_table,
    guarded,
    insufficient,
)
from .horizon import extract_horizon
from .report import (
    ChartHint,
    EngineReport,
    EngineRun,
    KeyNumber,
    ReportTable,
    confidence_from,
)

ENGINE_VERSION = "forecast-2.0.0"
DEFAULT_HORIZON = 3
_ORDERS = tuple(itertools.product((0, 1, 2), (0, 1), (0, 1, 2)))


class ForecastEngineParams(ContractModel):
    metric: str = Field(min_length=1)
    anchor: str = Field(min_length=1)
    question: str | None = None
    horizon: int | None = Field(default=None, ge=1)
    grain: Literal["day", "week", "month", "quarter", "year"] = "month"
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    top_n: int = Field(default=5, ge=1)
    series_column: str | None = None
    ratio: bool = False
    challenger: bool = True
    unit: str = ""


def _total_series(frame: pd.DataFrame, params: ForecastEngineParams) -> pd.Series | None:
    """The total series the analyst fits, rebuilt for the challenger."""
    names = {column.lower(): column for column in frame.columns}
    period = next((names[key] for key in ("ds", "date", "month", "period") if key in names), None)
    if period is None:
        return None
    frame = frame.copy()
    frame["_period"] = frame[period].astype(str).str[:7 if params.grain == "month" else 10]
    frame = frame[frame["_period"] <= params.anchor[:7 if params.grain == "month" else 10]]
    if params.ratio or params.metric in {"aov", "cancellation_rate"}:
        if "numerator" not in names or "denominator" not in names:
            return None
        grouped = frame.groupby("_period")[[names["numerator"], names["denominator"]]].sum()
        return (grouped[names["numerator"]] / grouped[names["denominator"]]).sort_index()
    value = next((names[key] for key in ("y", "value", params.metric.lower()) if key in names), None)
    if value is None:
        return None
    return frame.groupby("_period")[value].sum().sort_index().astype(float)


def _fit_arima(values: np.ndarray, horizon: int, alpha: float) -> tuple[tuple[int, int, int], np.ndarray, np.ndarray] | None:
    best: tuple[float, tuple[int, int, int], Any] | None = None
    for order in _ORDERS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            warnings.simplefilter("ignore", UserWarning)
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                fitted = ARIMA(values, order=order, trend="n" if order[1] else "c").fit()
            except (ValueError, np.linalg.LinAlgError, IndexError):
                continue
        aic = float(fitted.aic)
        if math.isfinite(aic) and (best is None or aic < best[0] - 1e-9):
            best = (aic, order, fitted)
    if best is None:
        return None
    forecast = best[2].get_forecast(horizon)
    mean = np.asarray(forecast.predicted_mean, dtype=float)
    interval = np.asarray(forecast.conf_int(alpha=alpha), dtype=float)
    if not np.isfinite(mean).all() or not np.isfinite(interval).all():
        return None
    return best[1], mean, interval


def arima_challenger(values: np.ndarray, *, horizon: int, alpha: float) -> dict[str, Any]:
    """Fit an AIC-selected ARIMA and backtest it on the analyst's holdout."""
    holdout = min(3, max(1, len(values) // 5))
    outcome: dict[str, Any] = {"order": None, "mape": None, "holdout": holdout, "points": ()}
    fit = _fit_arima(values, horizon, alpha)
    if fit is None:
        outcome["reason"] = "No ARIMA order converged on this series."
        return outcome
    order, mean, interval = fit
    outcome["order"] = order
    outcome["points"] = tuple(
        (float(m), float(min(lo, m)), float(max(hi, m))) for m, (lo, hi) in zip(mean, interval, strict=True)
    )
    if len(values) - holdout < 8:
        outcome["reason"] = "History too short to hold out a backtest tail."
        return outcome
    train, actual = values[:-holdout], values[-holdout:]
    backtest = _fit_arima(train, holdout, alpha)
    if backtest is None or np.any(actual == 0):
        outcome["reason"] = "The challenger backtest could not be scored."
        return outcome
    outcome["mape"] = float(np.mean(np.abs((backtest[1] - actual) / actual)))
    return outcome


@guarded("python.forecast", ENGINE_VERSION, "ets")
def execute(params: Mapping[str, Any], data: EngineData) -> EngineRun:
    """Forecast a series for the horizon stated in the question."""

    timer = Timer()
    parsed = ForecastEngineParams.model_validate(dict(params))
    series = data.table("series")
    if series is None:
        return insufficient(tool="python.forecast", reason="A forecast needs a prepared 'series' table.", data=data,
                            timer=timer, engine_version=ENGINE_VERSION, method="ets")
    horizon_note: str
    if parsed.horizon is not None:
        horizon = parsed.horizon
        horizon_note = f"Horizon of {horizon} {parsed.grain} periods was given explicitly."
    else:
        extracted = extract_horizon(parsed.question or "", anchor=parsed.anchor, grain=parsed.grain)  # type: ignore[arg-type]
        if extracted.horizon is not None:
            horizon = extracted.horizon.periods
            horizon_note = f"Horizon of {horizon} periods was read from the question ({extracted.phrase!r})."
        else:
            horizon = DEFAULT_HORIZON
            horizon_note = f"No horizon was stated ({extracted.reason}); the default of {DEFAULT_HORIZON} periods was used."

    analyst_params = {
        "metric": parsed.metric,
        "horizon": horizon,
        "anchor": parsed.anchor,
        "grain": parsed.grain,
        "alpha": parsed.alpha,
        "top_n": parsed.top_n,
        "series_column": parsed.series_column,
        "ratio": parsed.ratio,
    }
    output = registry.resolve("forecast").run(analyst_input("forecast", analyst_params, {"series": series}, data))
    if output.status != "ok" or not isinstance(output.result, ForecastResult):
        return engine_result(tool="python.forecast", output=output,
                             report=EngineReport(engine="forecast", method="ets", confidence=confidence_from(basis="not run")),
                             data=data, timer=timer, method="ets", engine_version=ENGINE_VERSION)
    result = output.result
    challenger: dict[str, Any] | None = None
    total = _total_series(frame_from_table(series), parsed) if parsed.challenger else None
    if total is not None and len(total) >= 12:
        challenger = arima_challenger(total.to_numpy(dtype=float), horizon=len(result.points), alpha=parsed.alpha)

    report = _report(parsed, result, challenger, horizon_note, horizon)
    fit_quality = FitQuality(measure="mape", value=result.mape, n_observations=result.history_periods)
    return engine_result(
        tool="python.forecast",
        output=output,
        report=report,
        data=data,
        timer=timer,
        method=result.method,
        method_fallback_reason=result.method_fallback_reason,
        library="prophet" if result.method == "prophet" else "statsmodels",
        fit_quality=fit_quality,
        engine_version=ENGINE_VERSION,
    )


def run(params: Mapping[str, Any], data: EngineData):
    return execute(params, data).result


def _report(
    params: ForecastEngineParams,
    result: ForecastResult,
    challenger: dict[str, Any] | None,
    horizon_note: str,
    requested: int,
) -> EngineReport:
    rows = tuple((point.ds, point.yhat, point.yhat_lower, point.yhat_upper) for point in result.points)
    tables = [ReportTable(name="forecast", columns=("ds", "yhat", "yhat_lower", "yhat_upper"), rows=rows)]
    numbers = [
        KeyNumber(name="horizon", value=float(len(result.points)), label="forecast periods"),
        KeyNumber(name="requested_horizon", value=float(requested), label="requested periods"),
        KeyNumber(name="final_yhat", value=result.points[-1].yhat, unit=params.unit, label=f"forecast {result.points[-1].ds}"),
        KeyNumber(name="final_lower", value=result.points[-1].yhat_lower, unit=params.unit, label="interval low"),
        KeyNumber(name="final_upper", value=result.points[-1].yhat_upper, unit=params.unit, label="interval high"),
        KeyNumber(name="backtest_mape", value=result.mape, unit="ratio", label=f"{result.method} backtest MAPE"),
        KeyNumber(name="trend_per_period", value=result.trend_per_period, unit=params.unit, label="trend per period"),
    ]
    assumptions = [horizon_note]
    if result.mape is None:
        assumptions.append("Not backtested: the history was too short or had a zero actual (AT-4); MAPE is null, not 0.")
    if challenger is not None:
        numbers.append(KeyNumber(name="arima_backtest_mape", value=challenger.get("mape"), unit="ratio", label="ARIMA challenger backtest MAPE"))
        if challenger.get("points"):
            tables.append(
                ReportTable(
                    name="arima_challenger",
                    columns=("ds", "yhat", "yhat_lower", "yhat_upper"),
                    rows=tuple((point.ds, *values) for point, values in zip(result.points, challenger["points"], strict=False)),
                )
            )
        order = challenger.get("order")
        if challenger.get("mape") is not None and result.mape is not None:
            better = challenger["mape"] < result.mape
            numbers.append(KeyNumber(name="challenger_better", value=1.0 if better else 0.0, label="ARIMA beat the primary on backtest"))
            assumptions.append(
                f"ARIMA{tuple(order) if order else ''} was backtested on the same {challenger['holdout']}-period tail: "
                f"MAPE {challenger['mape']:.4f} vs {result.method} {result.mape:.4f}. The reported forecast stays the "
                f"{result.method} path; the challenger is shown for comparison only."
            )
        else:
            assumptions.append(f"ARIMA challenger: {challenger.get('reason', 'not scored')}")
    mape = result.mape
    level_basis = "Backtest MAPE of the reported model." if mape is not None else "No backtest available."
    confidence = confidence_from(
        p_value=None if mape is None else (0.001 if mape < 0.1 else 0.03 if mape < 0.2 else 0.5),
        sample_size=result.history_periods,
        basis=level_basis,
    )
    return EngineReport(
        engine="forecast",
        method=result.method,
        tables=tuple(tables),
        key_numbers=tuple(numbers),
        assumptions=tuple(assumptions),
        confidence=confidence,
        chart_hint=ChartHint(kind="forecast_fan", table="forecast", x="ds", y=("yhat", "yhat_lower", "yhat_upper"),
                             title=f"{params.metric} forecast"),
    )


__all__ = ["DEFAULT_HORIZON", "ForecastEngineParams", "arima_challenger", "execute", "run"]
