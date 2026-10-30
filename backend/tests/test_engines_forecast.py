"""Forecast engine: horizon from the question, intervals, backtest MAPE, ARIMA challenger."""

from __future__ import annotations

import numpy as np
import pytest
from engine_helpers import assert_complete_report, data, stable, table, trending_series

from engines import forecast
from engines.forecast import arima_challenger
from engines.horizon import extract_horizon


@pytest.mark.parametrize(
    ("question", "periods", "grain"),
    [
        ("What will revenue be over the next 3 months?", 3, "month"),
        ("Forecast orders for the next quarter", 3, "month"),
        ("revenue in two months", 2, "month"),
        ("how much next year", 12, "month"),
        ("forecast the rest of the year", 4, "month"),
        ("projection until March 2019", 7, "month"),
        ("through Q1 2019 please", 7, "month"),
        ("sessions for the next 2 weeks", 2, "week"),
        ("6 months ahead", 6, "month"),
        ("quanto venderemos nos próximos 6 meses", 6, "month"),
    ],
)
def test_horizon_is_extracted_from_the_question(question, periods, grain):
    parsed = extract_horizon(question, anchor="2018-08")
    assert parsed.horizon is not None, parsed.reason
    assert (parsed.horizon.periods, parsed.horizon.grain, parsed.horizon.anchor) == (periods, grain, "2018-08")


def test_no_horizon_is_reported_not_invented():
    parsed = extract_horizon("How is revenue doing?", anchor="2018-08")
    assert parsed.horizon is None and "no forecast horizon" in parsed.reason
    assert extract_horizon("until March 2018", anchor="2018-08").horizon is None


def _run(params, seed=7):
    return forecast.execute({"metric": "revenue", "anchor": "2018-08", **params},
                            data({"series": table(trending_series(), "Q-F", month="time")}, seed=seed))


def test_forecast_uses_the_question_horizon_with_intervals_and_backtest_mape():
    run = _run({"question": "What will revenue be over the next 4 months?"})
    result = run.result.analyst_output.result
    assert len(result.points) == 4
    assert all(point.yhat_lower <= point.yhat <= point.yhat_upper for point in result.points)
    assert result.mape is not None and result.mape > 0
    assert run.result.provenance.engine.fit_quality.measure == "mape"
    assert run.report.number("backtest_mape") == result.mape
    assert any("read from the question" in note for note in run.report.assumptions)
    assert run.report.chart_hint.kind == "forecast_fan"
    assert_complete_report(run.report)


def test_default_horizon_is_disclosed_when_none_is_stated():
    run = _run({"question": "forecast revenue"})
    assert len(run.result.analyst_output.result.points) == forecast.DEFAULT_HORIZON
    assert any("default" in note for note in run.report.assumptions)


def test_arima_challenger_is_backtested_on_the_same_tail_but_never_the_method_of_record():
    run = _run({"horizon": 3})
    result = run.result.analyst_output.result
    assert result.method in {"prophet", "ets"}
    assert run.report.number("arima_backtest_mape") is not None
    assert run.report.table("arima_challenger").rows
    assert any("challenger is shown for comparison only" in note for note in run.report.assumptions)


def test_arima_challenger_reports_null_mape_on_short_history():
    outcome = arima_challenger(np.linspace(10.0, 20.0, 8), horizon=2, alpha=0.05)
    assert outcome["mape"] is None and outcome["reason"]
    assert len(outcome["points"]) == 2


def test_forecast_is_deterministic():
    assert stable(_run({"horizon": 3}, seed=4).result) == stable(_run({"horizon": 3}, seed=4).result)


def test_short_history_is_insufficient():
    run = forecast.execute({"metric": "revenue", "anchor": "2018-08", "horizon": 3},
                           data({"series": table(trending_series(count=8), "Q-F", month="time")}))
    assert run.result.status == "insufficient_evidence"
