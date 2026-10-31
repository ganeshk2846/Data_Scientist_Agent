"""Optional, isolated Prophet adapter - the only module that imports Prophet.

Prophet is an optional extra (``pip install .[forecast]``). Every function
here returns ``None`` with a reason when Prophet is unavailable or unsuitable,
so the forecast engines fall back to ETS and say why (TR-8).
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

try:
    from prophet import Prophet
except (ImportError, OSError, RuntimeError) as exc:
    Prophet = None
    _IMPORT_FAILURE = f"Prophet could not be imported: {type(exc).__name__}: {exc}"
else:
    _IMPORT_FAILURE = None

_RNG_LOCK = threading.Lock()

#: Prophet's yearly seasonality needs at least two full cycles.
MIN_PROPHET_PERIODS = 24


def forecast_with_prophet(
    periods: tuple[date, ...],
    values: tuple[float, ...],
    future_periods: tuple[date, ...],
    *,
    alpha: float,
    seed: int,
) -> tuple[dict[str, tuple[float, ...]] | None, str | None]:
    """Fit Prophet and return its forecast/components, or an explicit fallback reason."""

    if Prophet is None:
        return None, _IMPORT_FAILURE or "Prophet is not installed."
    frame = pd.DataFrame({"ds": periods, "y": values})
    model: Any = Prophet(
        interval_width=1.0 - alpha,
        yearly_seasonality=len(periods) >= 24,
        weekly_seasonality=False,
        daily_seasonality=False,
    )
    freq = "MS" if all(item.day == 1 for item in periods) else "D"
    try:
        with _RNG_LOCK:
            rng_state = np.random.get_state()
            np.random.seed(seed)
            try:
                model.fit(frame)
                future = model.make_future_dataframe(
                    periods=len(future_periods),
                    freq=freq,
                )
                predicted = model.predict(future)
            finally:
                np.random.set_state(rng_state)
    except (ArithmeticError, FloatingPointError, RuntimeError, ValueError) as exc:
        return None, f"Prophet could not fit this series: {type(exc).__name__}: {exc}"

    forecast = predicted.tail(len(future_periods))
    columns = ("yhat", "yhat_lower", "yhat_upper", "trend")
    if any(column not in forecast for column in columns):
        return None, "Prophet did not return the required forecast columns."
    seasonality_columns = tuple(
        column
        for column in ("yearly", "weekly", "daily")
        if column in forecast
    )
    seasonality = (
        forecast.loc[:, seasonality_columns].sum(axis=1).to_numpy(dtype=float)
        if seasonality_columns
        else np.zeros(len(future_periods), dtype=float)
    )
    result = {
        column: tuple(float(value) for value in forecast[column].to_numpy())
        for column in columns
    }
    result["seasonality"] = tuple(float(value) for value in seasonality)
    return result, None


def prophet_forecast(
    periods: Sequence[str],
    values: Sequence[float],
    horizon: int,
    alpha: float,
) -> tuple[list[tuple[float, float, float]] | None, str | None]:
    """``([(yhat, lower, upper), ...], None)`` or ``(None, fallback_reason)``."""
    if len(values) < MIN_PROPHET_PERIODS:
        return None, (
            f"history has {len(values)} monthly periods, under the "
            f"{MIN_PROPHET_PERIODS} Prophet needs for two yearly cycles"
        )
    if Prophet is None:  # pragma: no cover - depends on the environment
        return None, "prophet is not installed"
    try:  # pragma: no cover - exercised only where prophet is installed
        frame = pd.DataFrame({"ds": pd.to_datetime([f"{p}-01" for p in periods]), "y": list(values)})
        model = Prophet(interval_width=1 - alpha, yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
        model.fit(frame)
        future = model.make_future_dataframe(periods=horizon, freq="MS").tail(horizon)
        predicted = model.predict(future)
        return [
            (float(row.yhat), float(row.yhat_lower), float(row.yhat_upper))
            for row in predicted.itertuples()
        ], None
    except Exception as exc:  # pragma: no cover
        return None, f"prophet raised {type(exc).__name__}"
