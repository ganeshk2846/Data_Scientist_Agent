"""The only module that imports Prophet (build plan Track 2).

Prophet is an optional extra (``pip install .[forecast]``). Every function
here returns ``None`` with a reason when Prophet is unavailable or unsuitable,
so the forecast engine falls back to ETS and says why (TR-8).
"""

from __future__ import annotations

from collections.abc import Sequence

#: Prophet's yearly seasonality needs at least two full cycles.
MIN_PROPHET_PERIODS = 24


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
    try:
        import pandas as pd
        from prophet import Prophet
    except Exception:  # pragma: no cover - depends on the environment
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
