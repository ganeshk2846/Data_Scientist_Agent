"""``python.forecast`` - project a monthly series with an interval (Track 2).

Pure and deterministic: a prepared series in, a fit out. No warehouse
access, no model client (SAFE-8). The caller supplies only **complete**
periods (V2-DATA-2); the engine anchors on the last of them and says so.

Prophet is tried first when it is installed and the history spans two
yearly cycles; otherwise statsmodels ETS (additive, damped trend) runs and
the fallback reason is reported (TR-8). On the Olist snapshot - 20 complete
months - ETS is the normal path.

Backtest MAPE holds out the last ``horizon`` periods. It is ``None`` when the
history is too short to hold them out and still fit, and a ``None`` MAPE
means "not backtested", never zero (AT-4).
"""

from __future__ import annotations

import math
import re
import warnings
from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from contracts.models import ContractModel

from ._prophet import prophet_forecast

ENGINE_VERSION = "forecast-0.1.0"
MIN_HISTORY = 12
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class ForecastPoint(ContractModel):
    period: str
    yhat: float
    yhat_lower: float
    yhat_upper: float

    @model_validator(mode="after")
    def _interval_is_ordered(self) -> ForecastPoint:
        if not self.yhat_lower <= self.yhat <= self.yhat_upper:
            raise ValueError("forecast interval must contain yhat")
        return self


class ForecastFit(ContractModel):
    status: Literal["ok", "insufficient_evidence"]
    reason: str | None = None
    anchor_period: str | None = None
    history_periods: int = Field(ge=0)
    model: Literal["prophet", "ets"] | None = None
    model_fallback_reason: str | None = None
    mape: float | None = None
    alpha: float
    points: tuple[ForecastPoint, ...] = ()
    engine_version: str = ENGINE_VERSION


def _next_month(period: str, steps: int) -> str:
    year, month = (int(part) for part in period.split("-"))
    index = year * 12 + month - 1 + steps
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _ets(values: np.ndarray, horizon: int, alpha: float) -> list[tuple[float, float, float]]:
    import pandas as pd
    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    # statsmodels' prediction results need a pandas index on the endog.
    endog = pd.Series(values, index=pd.RangeIndex(len(values)))
    seasonal = 12 if len(values) >= 24 else None
    for trend, damped in (("add", True), (None, False)):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = ETSModel(
                    endog,
                    error="add",
                    trend=trend,
                    damped_trend=damped,
                    seasonal="add" if seasonal else None,
                    seasonal_periods=seasonal,
                )
                fit = model.fit(disp=False, maxiter=2000)
                frame = fit.get_prediction(start=len(values), end=len(values) + horizon - 1).summary_frame(alpha=alpha)
            out = [
                (float(row["mean"]), float(row["pi_lower"]), float(row["pi_upper"]))
                for _, row in frame.iterrows()
            ]
            if all(all(math.isfinite(v) for v in point) for point in out):
                return out
        except Exception:
            continue
    raise ValueError("ETS failed to fit")


def _project(values: np.ndarray, periods: Sequence[str], horizon: int, alpha: float, prefer_prophet: bool):
    reason = "prophet not requested"
    if prefer_prophet:
        points, reason = prophet_forecast(periods, values.tolist(), horizon, alpha)
        if points is not None:
            return points, "prophet", None
    return _ets(values, horizon, alpha), "ets", reason


def forecast_series(
    periods: Sequence[str],
    values: Sequence[float],
    *,
    horizon: int = 3,
    alpha: float = 0.05,
    bounds: tuple[float, float] | None = None,
    prefer_prophet: bool = True,
) -> ForecastFit:
    """Forecast ``horizon`` months past the last of ``periods``.

    ``periods`` must be consecutive ``YYYY-MM`` months, all complete.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least 1")
    if not 0 < alpha < 0.5:
        raise ValueError("alpha must be in (0, 0.5)")
    if len(periods) != len(values):
        raise ValueError("periods and values must have the same length")
    for earlier, later in zip(periods, periods[1:]):
        if not _MONTH.match(earlier) or _next_month(earlier, 1) != later:
            raise ValueError("periods must be consecutive YYYY-MM months")

    series = np.asarray(values, dtype=float)
    if len(series) < MIN_HISTORY or not np.all(np.isfinite(series)):
        return ForecastFit(
            status="insufficient_evidence",
            reason=f"needs at least {MIN_HISTORY} complete, finite periods; got {len(series)}",
            history_periods=len(series),
            alpha=alpha,
        )

    try:
        raw, model, fallback = _project(series, periods, horizon, alpha, prefer_prophet)
    except ValueError as exc:
        return ForecastFit(
            status="insufficient_evidence", reason=str(exc), history_periods=len(series), alpha=alpha
        )

    mape = None
    if len(series) >= MIN_HISTORY + horizon:
        held, actual = series[:-horizon], series[-horizon:]
        try:
            back, _, _ = _project(held, periods[:-horizon], horizon, alpha, prefer_prophet and model == "prophet")
            nonzero = actual != 0
            if nonzero.any():
                predicted = np.array([point[0] for point in back])
                mape = float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])))
        except ValueError:
            mape = None

    anchor = periods[-1]
    points = []
    for step, (yhat, lower, upper) in enumerate(raw, start=1):
        if bounds is not None:
            low, high = bounds
            yhat, lower, upper = (min(max(v, low), high) for v in (yhat, lower, upper))
        lower, upper = min(lower, yhat), max(upper, yhat)
        points.append(ForecastPoint(period=_next_month(anchor, step), yhat=yhat, yhat_lower=lower, yhat_upper=upper))
    return ForecastFit(
        status="ok",
        anchor_period=anchor,
        history_periods=len(series),
        model=model,
        model_fallback_reason=fallback if model == "ets" else None,
        mape=mape,
        alpha=alpha,
        points=tuple(points),
    )


__all__ = ["ENGINE_VERSION", "ForecastFit", "ForecastPoint", "forecast_series"]
