"""Forecast engines: ForecastAnalyst and python.forecast (TR-8, AT-4, V2-DATA-2)."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from analysts import _prophet
from analysts.forecast import MIN_HISTORY, ForecastAnalyst, forecast_series
from contracts.models import AnalystColumn, AnalystInput, TableRef
from contracts.v2 import ForecastResult
from test_an1_architecture import _matching_imports


def _table(names, rows, *, query_id="Q-FORECAST"):
    return TableRef(
        query_id=query_id,
        columns=tuple(
            AnalystColumn(
                name=name,
                type="TEXT" if name in {"month", "category"} else "REAL",
                role="time" if name == "month" else "dimension" if name == "category" else "measure",
            )
            for name in names
        ),
        row_count=len(rows),
        uri=f"inline://{query_id}",
        rows=tuple(tuple(row) for row in rows),
    )


def _months(count=23):
    year, month = 2016, 10
    result = []
    for index in range(count):
        result.append((date(year, month, 1).isoformat(), index))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return result


def _input(rows, names=("month", "value"), *, params=None, seed=7):
    return AnalystInput(
        module="forecast",
        params={
            "metric": "revenue",
            "horizon": 3,
            "anchor": "2018-08",
            "grain": "month",
            **(params or {}),
        },
        tables={"series": _table(names, rows)},
        run_id="RUN-FORECAST",
        seed=seed,
    )


def test_forecast_is_seeded_and_excludes_incomplete_tail_periods():
    rows = [
        (period, 1000.0 + index * 12.0 + (index % 4) * 7.0)
        for period, index in _months()
    ]
    rows.extend((("2018-09-01", 1_000_000.0), ("2018-10-01", 2_000_000.0)))
    analyst = ForecastAnalyst()

    first = analyst.run(_input(rows))
    second = analyst.run(_input(rows))

    assert first.status == "ok"
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert isinstance(first.result, ForecastResult)
    assert first.result.anchor_period == "2018-08"
    assert first.result.history_periods == 23
    assert first.result.method == "ets"
    assert first.result.method_fallback_reason
    assert first.result.mape is not None
    assert len(first.result.points) == 3
    assert first.result.points[0].ds == "2018-09"
    assert any("later periods were excluded" in item for item in first.assumptions)


def test_forecast_ratio_fits_numerator_and_denominator():
    rows = [
        (period, 1000.0 + index * 15, 20.0 + index, (1000.0 + index * 15) / (20.0 + index))
        for period, index in _months()
    ]
    output = ForecastAnalyst().run(
        _input(
            rows,
            names=("month", "numerator", "denominator", "value"),
            params={"metric": "aov", "ratio": True},
        )
    )

    assert output.status == "ok"
    assert output.result.method == "ets"
    assert any(
        "separately fitting its measured numerator and denominator" in item
        for item in output.assumptions
    )
    assert all(point.yhat_lower <= point.yhat <= point.yhat_upper for point in output.result.points)


def test_forecast_bounds_review_scores_and_handles_all_zero_series():
    review_rows = [
        (period, 4.0 + (index % 3) * 0.4)
        for period, index in _months()
    ]
    review = ForecastAnalyst().run(
        _input(review_rows, params={"metric": "review_score"})
    )
    assert review.status == "ok"
    assert all(1.0 <= point.yhat_lower <= point.yhat <= point.yhat_upper <= 5.0 for point in review.result.points)

    zeros = ForecastAnalyst().run(
        _input([(period, 0.0) for period, _ in _months()])
    )
    assert zeros.status == "ok"
    assert all(point.yhat == 0.0 for point in zeros.result.points)


def test_forecast_short_history_returns_insufficient_evidence():
    rows = [(period, float(index + 1)) for period, index in _months(10)]
    output = ForecastAnalyst().run(
        _input(rows, params={"anchor": rows[-1][0]})
    )

    assert output.status == "insufficient_evidence"
    assert output.result is None
    assert "12 complete periods" in output.reason


def test_forecast_limits_many_series_and_reports_the_remainder():
    rows = []
    for category in range(7):
        for period, index in _months():
            rows.append((period, f"category-{category}", float((category + 1) * 10 + index)))
    output = ForecastAnalyst().run(
        _input(
            rows,
            names=("month", "category", "value"),
            params={"series_column": "category", "top_n": 5},
        )
    )

    assert output.status == "ok"
    assert len(output.result.series) == 6
    assert output.result.remainder_series_count == 2
    assert output.result.series[-1].name == "All remaining"
    assert any("remainder as an aggregate" in item for item in output.assumptions)


def test_prophet_adapter_uses_required_frame_fit_future_and_prediction(monkeypatch):
    class FakeProphet:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fit(self, frame):
            assert tuple(frame.columns) == ("ds", "y")
            self.history = frame
            return self

        def make_future_dataframe(self, *, periods, freq):
            self.future_periods = periods
            dates = pd.date_range(
                start=self.history.iloc[0]["ds"],
                periods=len(self.history) + periods,
                freq=freq,
            )
            return pd.DataFrame({"ds": dates})

        def predict(self, future):
            assert len(future) == len(self.history) + self.future_periods
            return pd.DataFrame(
                {
                    "ds": future["ds"],
                    "yhat": [10.0] * len(future),
                    "yhat_lower": [8.0] * len(future),
                    "yhat_upper": [12.0] * len(future),
                    "trend": [9.0] * len(future),
                    "yearly": [1.0] * len(future),
                }
            )

    periods = tuple(
        date(year, month, 1)
        for year in (2017, 2018)
        for month in range(1, 13)
    )
    future = (date(2019, 1, 1), date(2019, 2, 1))
    monkeypatch.setattr(_prophet, "Prophet", FakeProphet)

    result, reason = _prophet.forecast_with_prophet(
        periods,
        tuple(float(index + 1) for index in range(len(periods))),
        future,
        alpha=0.05,
        seed=11,
    )

    assert reason is None
    assert result is not None
    assert result["yhat"] == (10.0, 10.0)
    assert result["yhat_lower"] == (8.0, 8.0)
    assert result["yhat_upper"] == (12.0, 12.0)
    assert result["trend"] == (9.0, 9.0)
    assert result["seasonality"] == (1.0, 1.0)


def test_forecast_automatically_uses_ets_without_prophet_and_prophet_when_available(monkeypatch):
    rows = []
    year, month = 2015, 9
    for index in range(24):
        rows.append((date(year, month, 1).isoformat(), 100.0 + index * 4.0 + (index % 12)))
        month += 1
        if month == 13:
            year += 1
            month = 1
    params = {"anchor": "2017-08", "horizon": 2}

    monkeypatch.setattr(_prophet, "Prophet", None)
    fallback = ForecastAnalyst().run(_input(rows, params=params))
    assert fallback.status == "ok"
    assert fallback.result.method == "ets"
    assert fallback.result.method_fallback_reason
    assert "prophet" in fallback.result.method_fallback_reason.lower()

    class FakeProphet:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fit(self, frame):
            self.history = frame
            return self

        def make_future_dataframe(self, *, periods, freq):
            self.periods = periods
            dates = pd.date_range(
                start=self.history.iloc[0]["ds"],
                periods=len(self.history) + periods,
                freq=freq,
            )
            return pd.DataFrame({"ds": dates})

        def predict(self, future):
            count = len(future)
            return pd.DataFrame(
                {
                    "ds": future["ds"],
                    "yhat": [50.0] * count,
                    "yhat_lower": [40.0] * count,
                    "yhat_upper": [60.0] * count,
                    "trend": [48.0] * count,
                    "yearly": [2.0] * count,
                }
            )

    monkeypatch.setattr(_prophet, "Prophet", FakeProphet)
    primary = ForecastAnalyst().run(_input(rows, params=params))
    assert primary.status == "ok"
    assert primary.result.method == "prophet"
    assert primary.result.method_fallback_reason is None
    assert primary.result.components[0].trend == 48.0
    assert primary.result.components[0].seasonality == 2.0


# --- python.forecast (forecast_series) ----------------------------------------

MONTHS = [f"{2017 + i // 12}-{i % 12 + 1:02d}" for i in range(20)]  # 2017-01 .. 2018-08
TREND = [1000 + 40 * i + 30 * math.sin(i) for i in range(20)]


def test_ets_fallback_is_reported_and_anchored_on_the_last_period():
    fit = forecast_series(MONTHS, TREND, horizon=3)

    assert fit.status == "ok"
    assert fit.model == "ets"
    assert "24" in fit.model_fallback_reason  # under two yearly cycles
    assert fit.anchor_period == "2018-08"
    assert [p.period for p in fit.points] == ["2018-09", "2018-10", "2018-11"]


def test_every_point_carries_an_interval_that_widens():
    fit = forecast_series(MONTHS, TREND, horizon=3)

    widths = [p.yhat_upper - p.yhat_lower for p in fit.points]
    assert all(width > 0 for width in widths)
    assert widths == sorted(widths)
    assert fit.points[0].yhat > TREND[-1] - 100  # follows the trend


def test_mape_is_a_real_backtest_or_null_never_zero():
    assert 0 < forecast_series(MONTHS, TREND).mape < 0.2
    short = forecast_series(MONTHS[:13], TREND[:13], horizon=3)
    assert short.status == "ok" and short.mape is None


def test_short_history_is_insufficient_not_forced():
    fit = forecast_series(MONTHS[: MIN_HISTORY - 1], TREND[: MIN_HISTORY - 1])
    assert fit.status == "insufficient_evidence"
    assert fit.points == ()


def test_bounded_metric_stays_in_bounds():
    fit = forecast_series(MONTHS, [4.9 + 0.01 * i for i in range(20)], horizon=3, bounds=(1.0, 5.0))
    assert all(1.0 <= v <= 5.0 for p in fit.points for v in (p.yhat_lower, p.yhat, p.yhat_upper))


def test_deterministic():
    assert forecast_series(MONTHS, TREND) == forecast_series(MONTHS, TREND)


def test_rejects_gapped_or_misaligned_periods():
    with pytest.raises(ValueError, match="consecutive"):
        forecast_series(["2018-01", "2018-03"], [1.0, 2.0])
    with pytest.raises(ValueError, match="same length"):
        forecast_series(MONTHS, TREND[:-1])


def test_only_the_adapter_imports_prophet():
    analysts = Path(__file__).resolve().parents[1] / "src" / "analysts"
    importers = {path.name for path in analysts.glob("*.py") if _matching_imports(path, {"prophet"})}
    assert importers <= {"_prophet.py"}
