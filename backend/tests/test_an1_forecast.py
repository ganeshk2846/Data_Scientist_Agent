"""python.forecast: ETS fallback, anchoring, intervals, MAPE (TR-8, AT-4, V2-DATA-2)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from analysts.forecast import MIN_HISTORY, forecast_series
from test_an1_architecture import _matching_imports

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
