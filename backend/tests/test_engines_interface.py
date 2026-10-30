"""The common engine interface: closed map, ToolResult contract, report, plan steps."""

from __future__ import annotations

import pandas as pd
import pytest
from contracts.v2 import PlanStep, ToolResult
from engine_helpers import REPORT_PARTS, data, stable, table, trending_series

import engines
from engines import ENGINES, INTENT_ENGINES, TOOL_ENGINES, UnknownEngineError, report_of
from engines.report import EngineReport, EngineRun


def _series_data(**kwargs):
    return data({"series": table(trending_series(), "Q-SERIES", month="time")}, **kwargs)


def test_engine_map_is_closed_and_covers_every_analytical_intent():
    assert set(ENGINES) == {"descriptive", "diagnostic", "impact", "forecast", "scenario", "prescriptive"}
    assert set(INTENT_ENGINES.values()) <= set(ENGINES)
    assert set(TOOL_ENGINES) == {"python.anomaly", "python.driver", "python.forecast", "python.impact",
                                 "python.scenario", "python.segment"}
    with pytest.raises(TypeError):
        ENGINES["custom"] = lambda params, data: None  # type: ignore[index]
    with pytest.raises(UnknownEngineError):
        engines.run("python.custom", {}, _series_data())


def test_run_returns_a_contract_tool_result_and_execute_adds_the_report():
    result = engines.run("forecast", {"metric": "revenue", "anchor": "2018-08", "horizon": 3}, _series_data())
    assert isinstance(result, ToolResult)
    assert result.status == "ok" and result.tool == "python.forecast"
    assert result.provenance.source == "engine" and result.provenance.deterministic
    run = engines.execute("forecast", {"metric": "revenue", "anchor": "2018-08", "horizon": 3}, _series_data())
    assert isinstance(run, EngineRun) and isinstance(run.report, EngineReport)
    assert report_of(run.result) == run.report
    assert set(REPORT_PARTS) <= set(EngineReport.model_fields)


def test_same_input_and_seed_give_identical_results():
    params = {"metric": "revenue", "anchor": "2018-08", "question": "next 3 months"}
    first = engines.run("forecast", params, _series_data(seed=3))
    second = engines.run("forecast", params, _series_data(seed=3))
    assert stable(first) == stable(second)


def test_synthetic_source_tables_label_the_result_and_add_the_caveat():
    result = engines.run("forecast", {"metric": "sessions", "anchor": "2018-08", "horizon": 2},
                         _series_data(sources=("web_traffic",)))
    assert result.provenance.data_layer == "synthetic"
    assert result.provenance.synthetic_tables == ("web_traffic",)
    assert any("synthetic" in caveat.lower() for caveat in result.caveats)


def test_bad_input_returns_insufficient_evidence_instead_of_raising():
    for engine, params in (
        ("forecast", {"metric": "revenue", "anchor": "2018-08"}),
        ("impact", {"metric": "revenue"}),
        ("diagnostic", {"metric": "x", "current_period": {"start": "2018-02-01", "end": "2018-03-01"},
                        "comparison_period": {"start": "2018-01-01", "end": "2018-02-01"}}),
        ("scenario", {"price_change_pct": 5}),
        ("prescriptive", {"mode": "reorder", "budget": 10}),
        ("descriptive", {"operation": "rank", "measure": "value", "dimensions": ("missing",)}),
    ):
        result = engines.run(engine, params, data({}))
        assert result.status == "insufficient_evidence", engine
        assert result.reason
    garbage = engines.run("impact", {"metric": "revenue", "mode": "not-a-mode"}, data({}))
    assert garbage.status == "insufficient_evidence"


def test_run_step_maps_frozen_tool_names_onto_engines():
    step = PlanStep(step_id="P2", tool="python.forecast", params={"metric": "revenue", "anchor": "2018-08", "horizon": 2},
                    depends_on=("P1",), produces="analyst_output", purpose="Forecast revenue")
    run = engines.run_step(step, _series_data())
    assert run.result.step_id == "P2"
    assert run.result.provenance.input_step_ids == ("P1",)
    anomaly = PlanStep(step_id="P3", tool="python.anomaly", depends_on=("P1",), produces="analyst_output", purpose="Scan",
                       params={"metric": "value", "scan_window": {"start": "2018-01-01", "end": "2018-09-01"}})
    assert engines.run_step(anomaly, _series_data()).result.tool == "python.anomaly"
    sql = PlanStep(step_id="P1", tool="sql", produces="rows", purpose="Read")
    with pytest.raises(UnknownEngineError):
        engines.run_step(sql, _series_data())


def test_engine_tool_results_round_trip_through_json():
    result = engines.run("forecast", {"metric": "revenue", "anchor": "2018-08", "horizon": 3}, _series_data())
    restored = ToolResult.model_validate_json(result.model_dump_json())
    assert report_of(restored) == report_of(result)
    assert pd.notna(report_of(restored).number("backtest_mape"))
