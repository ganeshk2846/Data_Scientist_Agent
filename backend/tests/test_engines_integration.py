"""Existing analysts and the new engine layer work as one pipeline.

Chains planner steps the way scope.md's compound questions do (K1:
descriptive + forecast; diagnostic feeding a prescriptive ranking), and
checks that the engines go through the existing closed analyst registry
rather than around it.
"""

from __future__ import annotations

import engines
import pandas as pd
from analysts import registry
from contracts.v2 import PlanStep
from engine_helpers import data, table, trending_series
from engines import report_of
from engines.base import table_from_frame


def test_k1_descriptive_trend_feeds_a_forecast_step():
    series = trending_series().rename(columns={"month": "date"})
    rows = table(series, "Q-REVENUE", date="time")
    trend = engines.execute("descriptive", {"operation": "trend", "measure": "value", "period_column": "date"},
                            data({"revenue": rows}))
    assert trend.result.tool == "sql" and trend.result.status == "ok"
    # The forecast reads the descriptive step's own SQL rows, linked by step id and query id.
    frame = pd.DataFrame(list(trend.result.rows.rows), columns=[column.name for column in trend.result.rows.columns])
    step_rows = table_from_frame(frame.rename(columns={"period": "month"}), query_id=trend.result.rows.query_id, roles={"month": "time"})
    step = PlanStep(step_id="P2", tool="python.forecast", depends_on=("P1",), produces="analyst_output",
                    purpose="Forecast the trend", params={"metric": "revenue", "anchor": "2018-08",
                                                          "question": "and what will it be in 3 months?"})
    forecast = engines.run_step(step, data({"series": step_rows}))
    assert forecast.result.provenance.query_ids == (trend.result.rows.query_id,)
    assert forecast.result.provenance.input_step_ids == ("P1",)
    assert len(forecast.result.analyst_output.result.points) == 3


def test_engine_outputs_come_from_the_registered_analyst_modules():
    approved = set(registry.approved_module_names())
    run = engines.execute("forecast", {"metric": "revenue", "anchor": "2018-08", "horizon": 2},
                          data({"series": table(trending_series(), "Q-S", month="time")}))
    assert run.result.analyst_output.module in approved
    assert run.result.analyst_output.module == run.result.tool.removeprefix("python.")
    assert report_of(run.result).engine == "forecast"


def test_diagnostic_grades_feed_the_prescriptive_low_evidence_rule():
    actions = pd.DataFrame({
        "action_id": ["cut", "survey", "pilot"],
        "title": ["Cut spend", "Survey customers", "Run a pilot"],
        "expected_impact": [100.0, 10.0, 30.0],
        "cost": [10.0, 2.0, 5.0],
        "evidence_grade": [1, 1, 1],
        "kind": ["intervention", "information_gathering", "information_gathering"],
        "assumptions": ["a", "b", "c"], "trade_offs": ["a", "b", "c"], "sensitivity": ["a", "b", "c"],
        "monitor": ["a", "b", "c"], "data_that_would_change_ranking": ["a", "b", "c"],
    })
    step = PlanStep(step_id="P3", tool="python.segment", depends_on=("P2",), produces="analyst_output", purpose="Rank actions",
                    params={"mode": "actions", "evidence_grades": (1,)})
    run = engines.run_step(step, data({"actions": table(actions, "Q-A", action_id="key")}))
    kinds = {option.kind for option in run.result.analyst_output.result.actions}
    assert kinds == {"information_gathering"}, "grades below 2 rank only information-gathering options (REC-4)"
