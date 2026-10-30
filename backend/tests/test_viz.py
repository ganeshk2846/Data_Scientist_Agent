"""Track 5 visualization agent: deterministic chart choice, no invented numbers."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from contracts.v2 import (
    AnswerEnvelopeV2,
    PlanStep,
    RowsColumn,
    RowsPayload,
    ToolProvenance,
    ToolResult,
)
from viz import ARTIFACT_PATH_SEPARATOR, EVIDENCE_ROW_CAP, build_visualizations
from viz.rules import choose

pytestmark = pytest.mark.filterwarnings("ignore::ResourceWarning")

VIZ_DIR = Path(__file__).resolve().parents[1] / "src" / "viz"


def _col(name: str, role: str, kind: str = "REAL") -> RowsColumn:
    return RowsColumn(name=name, type=kind, role=role)  # type: ignore[arg-type]


def _rows_result(columns, rows, *, row_count=None, step_id="S1") -> tuple[PlanStep, ToolResult]:
    step = PlanStep(step_id=step_id, tool="sql", produces="rows", purpose="Measure revenue.")
    payload = RowsPayload(query_id="Q1", columns=tuple(columns), rows=tuple(tuple(r) for r in rows),
                          row_count=row_count if row_count is not None else len(rows))
    result = ToolResult(step_id=step_id, tool="sql", status="ok", produces="rows", rows=payload,
                        provenance=ToolProvenance(source="sql", deterministic=True, query_ids=("Q1",)), duration_ms=1)
    return step, result


def _build(step, result, claims=("C1",)):
    return build_visualizations([step], {step.step_id: result}, {step.step_id: claims})


# --------------------------------------------------------------------------- #
# Rules over rows
# --------------------------------------------------------------------------- #


def test_time_series_is_a_line():
    step, result = _rows_result([_col("month", "time", "TEXT"), _col("revenue", "measure")],
                                [("2018-01", 1.0), ("2018-02", 2.0)])
    (spec,) = _build(step, result)
    assert spec.kind == "line" and spec.encoding.x.role == "time" and spec.encoding.y.column == "revenue"
    assert spec.source_query_id == "Q1" and spec.claim_ids == ("C1",)
    assert spec.encoding.y.unit == "BRL" and spec.encoding.y.zero_baseline is True


def test_time_series_with_a_dimension_splits_series():
    step, result = _rows_result([_col("month", "time", "TEXT"), _col("state", "dimension", "TEXT"), _col("revenue", "measure")],
                                [("2018-01", "SP", 1.0), ("2018-01", "RJ", 2.0)])
    (spec,) = _build(step, result)
    assert spec.kind == "line" and spec.encoding.series is not None and spec.encoding.series.column == "state"


def test_category_comparison_is_a_bar_with_zero_baseline():
    step, result = _rows_result([_col("category", "dimension", "TEXT"), _col("revenue", "measure")],
                                [("a", 1.0), ("b", 2.0)])
    (spec,) = _build(step, result)
    assert spec.kind == "bar" and spec.encoding.y.zero_baseline is True


def test_share_with_a_split_is_grouped_not_stacked():
    step, result = _rows_result([_col("state", "dimension", "TEXT"), _col("channel", "dimension", "TEXT"), _col("revenue_share", "measure")],
                                [("SP", "web", 0.5), ("SP", "app", 0.5)])
    (spec,) = _build(step, result)
    assert spec.kind == "grouped_bar" and spec.encoding.y.unit == "%"
    assert "not stacked" in spec.caption


def test_distribution_uses_sql_bins_and_never_bins_itself():
    step, result = _rows_result([_col("price_bin", "dimension", "TEXT"), _col("orders", "measure")],
                                [("0-50", 10), ("50-100", 4)])
    (spec,) = _build(step, result)
    assert spec.kind == "bar" and spec.encoding.x.column == "price_bin"
    assert spec.title.startswith("Distribution")


def test_relationship_is_a_scatter():
    step, result = _rows_result([_col("freight_value", "measure"), _col("review_score", "measure")],
                                [(1.0, 5.0), (2.0, 4.0), (3.0, 3.0)])
    (spec,) = _build(step, result)
    assert spec.kind == "scatter" and spec.encoding.y.zero_baseline is False


def test_a_single_row_is_never_a_line():  # VZ-6
    step, result = _rows_result([_col("month", "time", "TEXT"), _col("revenue", "measure")], [("2018-01", 1.0)])
    (spec,) = _build(step, result)
    assert spec.kind == "table"


def test_no_measure_draws_nothing():
    assert choose((_col("state", "dimension", "TEXT"),), 5) is None


def test_more_rows_than_the_evidence_carries_sets_limit_and_reports_the_rest():  # VZ-3
    rows = [(f"c{i}", float(i)) for i in range(EVIDENCE_ROW_CAP + 10)]
    step, result = _rows_result([_col("category", "dimension", "TEXT"), _col("revenue", "measure")], rows)
    (spec,) = _build(step, result)
    assert spec.encoding.limit == EVIDENCE_ROW_CAP
    assert f"{EVIDENCE_ROW_CAP} of {EVIDENCE_ROW_CAP + 10}" in spec.caption


def test_failed_steps_draw_nothing():
    step = PlanStep(step_id="S1", tool="sql", produces="rows", purpose="x")
    result = ToolResult(step_id="S1", tool="sql", status="error", produces="rows", reason="boom",
                        provenance=ToolProvenance(source="sql", deterministic=True), duration_ms=1)
    assert _build(step, result) == ()


def test_specs_are_deterministic():
    step, result = _rows_result([_col("month", "time", "TEXT"), _col("revenue", "measure")],
                                [("2018-01", 1.0), ("2018-02", 2.0)])
    assert _build(step, result) == _build(step, result)


# --------------------------------------------------------------------------- #
# Architecture: no model, no SQL, no arithmetic on data
# --------------------------------------------------------------------------- #


def test_viz_package_imports_no_model_client_connection_or_sql():
    banned = {"ollama", "httpx", "requests", "sqlite3", "sqlalchemy", "gateway", "sql", "models.client", "pandas", "numpy"}
    for path in VIZ_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in banned and name not in banned, f"{path.name} imports {name}"


def test_viz_package_does_no_arithmetic():
    # SAFE-8: the only arithmetic allowed is the spec-id counter.
    for path in VIZ_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Pow)):
                if isinstance(node.op, ast.Add) and isinstance(node.left, (ast.Constant, ast.JoinedStr)):
                    continue
                pytest.fail(f"{path.name}:{node.lineno} does arithmetic")
            if isinstance(node, ast.AugAssign):
                target = ast.unparse(node.target)
                assert target == "self.count", f"{path.name}:{node.lineno} accumulates {target}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"sum", "round", "sorted", "max"}, f"{path.name}:{node.lineno} calls {node.func.id}"


# --------------------------------------------------------------------------- #
# End to end: every spec resolves against data the envelope already carries
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def pipeline(v2_build):
    from pipeline_v2 import PipelineV2
    from service import build_runtime

    runtime = build_runtime(v2_build["db"], reasoning_client=False)
    yield PipelineV2(guard=runtime.guard, catalog=runtime.catalog, manager=runtime.manager)
    runtime.close()


def _resolve(envelope: AnswerEnvelopeV2, spec) -> list[dict]:
    """Mirror the frontend resolver: find the spec's records in the envelope."""

    if spec.source_query_id is not None:
        block = next(b for b in envelope.evidence if b.module == "lookup" and b.output["query_id"] == spec.source_query_id)
        return [dict(zip(block.output["columns"], row)) for row in block.output["rows"]]
    artifact, path = spec.source_artifact_id.split(ARTIFACT_PATH_SEPARATOR)
    step_id, tool = artifact.split(":", 1)
    summary = next(s for s in envelope.step_results if s.step_id == step_id)
    module = tool.removeprefix("python.")
    blocks = [b for b in envelope.evidence if b.module == module and tuple(b.source_claims) == tuple(summary.claim_ids)]
    node = blocks[0].output
    for part in path.split("."):
        node = node[part]
    return node if isinstance(node, list) else [node]


def _column(record: dict, name: str):
    node = record
    for part in name.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


QUESTIONS = {
    "diagnostic": "Why did revenue drop in the top category in April 2018?",
    "forecast": "Forecast revenue for the next 3 months",
    "forecast_live": "Forecast revenue in SP for the next 3 months",
    "segment": "Which customer segment should we target?",
    "compound": "How does revenue trend look today and what will it be in 3 months?",
    "scenario": "What if we raise prices 5%?",
    "spikes": "What are the spikes across all months?",
    "impact": "How much did the April 2018 drop cost us?",
}


@pytest.mark.parametrize("name", sorted(QUESTIONS))
def test_must_answer_questions_get_specs_that_resolve_to_carried_data(pipeline, name):
    envelope = pipeline.run(QUESTIONS[name]).envelope
    assert envelope.status == "answered"
    assert envelope.visualizations, f"{name} produced no chart"
    claim_ids = {claim.claim_id for claim in envelope.claims}
    dumped = json.dumps([spec.model_dump(mode="json") for spec in envelope.visualizations])
    for spec in envelope.visualizations:
        records = _resolve(envelope, spec)
        assert records, f"{spec.viz_id} resolves to no rows"
        columns = [spec.encoding.x.column, spec.encoding.y.column]
        if spec.encoding.band is not None:
            columns += [spec.encoding.band.lower_column, spec.encoding.band.upper_column]
        if spec.encoding.series is not None:
            columns.append(spec.encoding.series.column)
        for column in columns:
            _column(records[0], column)  # raises if the column is not carried
        assert set(spec.claim_ids) <= claim_ids
        for note in spec.annotations:
            assert note.at.y is None or note.claim_id in claim_ids
    assert '"data"' not in dumped and '"values"' not in dumped  # VZ-1: no inline arrays


@pytest.mark.parametrize("name", ["forecast", "forecast_live"])
def test_forecast_always_carries_its_interval(pipeline, name):  # VZ-5, 5.8
    envelope = pipeline.run(QUESTIONS[name]).envelope
    fans = [spec for spec in envelope.visualizations if spec.kind in ("forecast_fan", "range_band")]
    assert fans and all(spec.encoding.band is not None for spec in fans)


def test_a_live_forecast_offers_trend_and_seasonality_components(pipeline):
    envelope = pipeline.run(QUESTIONS["forecast_live"]).envelope
    titles = {spec.title for spec in envelope.visualizations}
    assert "Trend component" in titles


def test_flagged_anomalies_are_marked_and_never_joined_by_a_line(pipeline):
    envelope = pipeline.run(QUESTIONS["spikes"]).envelope
    (spec,) = envelope.visualizations
    assert spec.kind == "table" and spec.annotations
    assert all(note.emphasis == "attention" and note.label.split()[0] in ("Spike", "Dip") for note in spec.annotations)


def test_a_diagnostic_series_marks_the_tested_month_on_the_line(pipeline):
    envelope = pipeline.run(QUESTIONS["diagnostic"]).envelope
    line = envelope.visualizations[0]
    assert line.kind == "line" and line.annotations
    records = _resolve(envelope, line)
    assert line.annotations[0].at.x in {str(record[line.encoding.x.column]) for record in records}


def test_diagnostic_draws_a_waterfall(pipeline):
    envelope = pipeline.run(QUESTIONS["diagnostic"]).envelope
    assert any(spec.kind == "waterfall" for spec in envelope.visualizations)


def test_clarify_and_discovery_draw_nothing(pipeline):
    assert pipeline.run("Summarize revenue").envelope.visualizations == ()
    assert pipeline.run("What data do you have?").envelope.visualizations == ()
