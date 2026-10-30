"""Build ``VisualizationSpec``s for every step of a run (Track 5, item 1).

How a spec points at its data (VZ-1, no inline values):

* **SQL / analytical-table rows** - ``source_query_id`` is the rows'
  ``query_id``; the composer puts those rows in a ``lookup`` evidence block
  keyed by the same id, capped at :data:`EVIDENCE_ROW_CAP` rows.
* **Engine output** - ``source_artifact_id`` is
  ``"<step_id>:<tool>#<path>"``. ``<step_id>:<tool>`` is the artifact id the
  ledger already cites for that step's claims; ``<path>`` is a dotted path into
  the step's evidence block ``output`` (e.g. ``result.points``). A path that
  lands on a list is a table of records; one that lands on an object is a
  single row. Column names may index a pair with ``.0`` / ``.1`` (for example
  ``expected_range.0``).

Nothing here computes a figure: no aggregation, binning, sorting or rounding.
Labels and captions carry no number other than row counts the result itself
reports.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from contracts.v2 import (
    AnomalyResult,
    DiagnosticResult,
    DriverResult,
    ForecastResult,
    ImpactResult,
    PlanStep,
    ScenarioResult,
    SegmentResult,
    ToolResult,
    VisualizationSpec,
    VizAnnotation,
    VizAnnotationAt,
    VizAxis,
    VizBand,
    VizEncoding,
    VizSeries,
)
from viz.rules import choose, label, unit_for

#: Rows the composer copies into a lookup evidence block (composer.compose).
EVIDENCE_ROW_CAP = 50
ARTIFACT_PATH_SEPARATOR = "#"
_MAX_SPECS = 8


class _Ids:
    def __init__(self) -> None:
        self.count = 0

    def next(self) -> str:
        self.count += 1
        return f"vz_{self.count}"


def _artifact(result: ToolResult, path: str) -> str:
    return f"{result.step_id}:{result.tool}{ARTIFACT_PATH_SEPARATOR}{path}"


def _axis(column: str, role: str, text: str, *, unit: str | None = None, zero: bool | None = None) -> VizAxis:
    return VizAxis(column=column, role=role, label=text, unit=unit, zero_baseline=zero)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Rows (SQL / analytical tables)
# --------------------------------------------------------------------------- #


def _rows_spec(step: PlanStep, result: ToolResult, claim_ids: tuple[str, ...], ids: _Ids,
               anomalies: list[tuple[AnomalyResult, str | None]]) -> VisualizationSpec | None:
    rows = result.rows
    if rows is None or result.status != "ok" or not rows.columns:
        return None
    shown = min(len(rows.rows), EVIDENCE_ROW_CAP)
    if shown == 0:
        return None
    choice = choose(rows.columns, shown)
    if choice is None:
        return None
    limit = None
    caption = step.purpose
    if rows.row_count > shown:
        # VZ-3: the cut is the backend's, and the remainder is reported.
        limit = shown
        caption = (f"{step.purpose} Showing the first {shown} of {rows.row_count} rows in query order; "
                   f"the remaining rows are not drawn.")
    y_name = choice.y.name
    series = VizSeries(column=choice.series.name, label=label(choice.series.name)) if choice.series is not None else None
    annotations: tuple[VizAnnotation, ...] = ()
    metric = str(step.params.get("kpi") or step.params.get("metric") or "")
    y_text = label(metric) if y_name == "value" and metric else label(y_name)
    y = _axis(y_name, "measure", y_text, unit=unit_for(metric if y_name == "value" else y_name),
              zero=choice.family != "relationship")
    x_index = [c.name for c in rows.columns].index(choice.x.name)
    x_values = [str(row[x_index]) for row in rows.rows[:shown]]
    if series is not None:
        s_index = [c.name for c in rows.columns].index(series.column)
        if all(row[s_index] is None for row in rows.rows[:shown]):
            series = None  # an all-total series has nothing to split by
    if choice.family == "forecast":
        # VZ-5 / VZ-6: the interval is always drawn; one point is a range.
        kind = "forecast_fan" if shown > 1 else "range_band"
        x = _axis(choice.x.name, "time", label(choice.x.name) if choice.x.name != "ds" else "Period")
        y = _axis(y_name, "measure", f"Projected {y_text.lower()}" if metric else "Projected value",
                  unit=unit_for(metric), zero=True)
        band = VizBand(lower_column=choice.lower.name, upper_column=choice.upper.name, label="Prediction interval")  # type: ignore[union-attr]
        title = f"{label(metric) if metric else 'Value'} projection with prediction interval"
        caption = f"{caption} The shaded band is the model's prediction interval."
        anchor = _first_value(rows, "anchor_period", shown)
        annotations = (VizAnnotation(kind="line", at=VizAnnotationAt(x=anchor), label="Last complete period",
                                     emphasis="attention"),) if anchor else ()
        return VisualizationSpec(
            viz_id=ids.next(), kind=kind, title=title[:200], source_step_id=step.step_id, source_query_id=rows.query_id,  # type: ignore[arg-type]
            encoding=VizEncoding(x=x, y=y, band=band, limit=limit), annotations=annotations, caption=caption, claim_ids=claim_ids,
        )
    if choice.family == "flagged":
        kind = "table"
        x = _axis(choice.x.name, "time", label(choice.x.name))
        title = "Flagged spikes and dips"
        caption = f"{caption} Only flagged points are listed, so they are not joined by a line."
        annotations = _flag_marks(rows, x_index, shown, claim_ids)
    elif choice.family == "time_series":
        kind = "line"
        x = _axis(choice.x.name, "time", label(choice.x.name))
        title = f"{y_text} over time"
        annotations = _anomaly_marks(anomalies, x_values)
    elif choice.family == "distribution":
        kind = "bar"
        x = _axis(choice.x.name, "dimension", label(choice.x.name))
        title = f"Distribution of {y_text.lower()} by {label(choice.x.name).lower()}"
        caption = f"{caption} Bins as produced by the query."
    elif choice.family == "share":
        kind = "grouped_bar" if series is not None else "bar"
        x = _axis(choice.x.name, "dimension", label(choice.x.name))
        title = f"{y_text} by {label(choice.x.name).lower()}"
        if series is not None:
            caption = f"{caption} Shares are shown side by side per group, not stacked."
    elif choice.family == "category":
        kind = "grouped_bar" if series is not None else "bar"
        x = _axis(choice.x.name, "dimension", label(choice.x.name))
        title = f"{y_text} by {label(choice.x.name).lower()}"
    elif choice.family == "relationship":
        kind = "scatter"
        # The frozen encoding reserves `measure` for y; the explanatory
        # variable sits on x as a dimension-role axis.
        x = _axis(choice.x.name, "dimension", label(choice.x.name), unit=unit_for(choice.x.name))
        title = f"{y_text} against {label(choice.x.name).lower()}"
    else:
        kind = "table"
        x = _axis(choice.x.name, "time" if choice.x.role == "time" else "dimension", label(choice.x.name))
        title = step.purpose
    return VisualizationSpec(
        viz_id=ids.next(), kind=kind, title=title[:200], source_step_id=step.step_id, source_query_id=rows.query_id,  # type: ignore[arg-type]
        encoding=VizEncoding(x=x, y=y, series=series, limit=limit), annotations=annotations,
        caption=caption, claim_ids=claim_ids,
    )


def _first_value(rows, name: str, shown: int) -> str | None:
    names = [c.name for c in rows.columns]
    if name not in names or not rows.rows:
        return None
    value = rows.rows[0][names.index(name)]
    return str(value) if value is not None else None


def _on_axis(window: str, x_values: list[str] | None) -> str:
    """The x value a window starts on, copied from the rows (never formatted)."""

    start = window.split("/")[0]
    if x_values:
        match = next((value for value in x_values if start.startswith(value) or value.startswith(start)), None)
        if match is not None:
            return match
    return start


def _anomaly_marks(anomalies: list[tuple[AnomalyResult, str | None]], x_values: list[str] | None = None) -> tuple[VizAnnotation, ...]:
    marks = []
    for result, claim in anomalies:
        at = _on_axis(result.window, x_values)
        if result.verdict == "unusual":
            text = "Spike" if result.actual > result.expected_range[1] else "Dip" if result.actual < result.expected_range[0] else "Unusual"
            marks.append(VizAnnotation(kind="point", at=VizAnnotationAt(x=at), label=f"{text}: {at}",
                                       emphasis="attention", claim_id=claim))
        elif result.verdict == "within_normal_range":
            marks.append(VizAnnotation(kind="label", at=VizAnnotationAt(x=at),
                                       label=f"{at}: within the normal range", claim_id=claim))
    return tuple(marks)


def _flag_marks(rows, x_index: int, shown: int, claim_ids: tuple[str, ...]) -> tuple[VizAnnotation, ...]:
    names = [c.name for c in rows.columns]
    d_index = names.index("direction")
    k_index = names.index("kpi") if "kpi" in names else None
    marks = []
    for row in rows.rows[:shown]:
        direction = str(row[d_index] or "")
        if direction not in ("spike", "dip"):
            continue
        metric = f" in {label(str(row[k_index]))}" if k_index is not None and row[k_index] else ""
        marks.append(VizAnnotation(kind="point", at=VizAnnotationAt(x=str(row[x_index])),
                                   label=f"{direction.capitalize()}{metric}", emphasis="attention",
                                   claim_id=claim_ids[0] if claim_ids else None))
    return tuple(marks[:12])


# --------------------------------------------------------------------------- #
# Engine outputs
# --------------------------------------------------------------------------- #


def _forecast_specs(step: PlanStep, result: ToolResult, payload: ForecastResult, claim_ids: tuple[str, ...], ids: _Ids) -> list[VisualizationSpec]:
    band = VizBand(lower_column="yhat_lower", upper_column="yhat_upper", label="Prediction interval")
    # VZ-6: a one-point projection is a range, never a line.
    kind = "forecast_fan" if len(payload.points) > 1 else "range_band"
    method = payload.method.upper() if payload.method == "ets" else payload.method.capitalize()
    specs = [VisualizationSpec(
        viz_id=ids.next(), kind=kind, title=f"{label(str(step.params.get('metric') or 'value'))} projection with prediction interval",  # type: ignore[arg-type]
        source_step_id=step.step_id, source_artifact_id=_artifact(result, "result.points"),
        encoding=VizEncoding(x=_axis("ds", "time", "Period"), y=_axis("yhat", "measure", "Projected value", zero=True), band=band),
        annotations=(VizAnnotation(kind="line", at=VizAnnotationAt(x=payload.anchor_period), label="Last complete period",
                                   emphasis="attention"),),
        caption=f"{step.purpose} Method: {method}. The shaded band is the model's prediction interval.",
        claim_ids=claim_ids,
    )]
    if len(payload.components) > 1:
        specs.append(VisualizationSpec(
            viz_id=ids.next(), kind="line", title="Trend component", source_step_id=step.step_id,
            source_artifact_id=_artifact(result, "result.components"),
            encoding=VizEncoding(x=_axis("ds", "time", "Period"), y=_axis("trend", "measure", "Trend", zero=False)),
            caption="The fitted trend the projection follows.", claim_ids=claim_ids,
        ))
        if all(component.seasonality is not None for component in payload.components):
            specs.append(VisualizationSpec(
                viz_id=ids.next(), kind="line", title="Seasonality component", source_step_id=step.step_id,
                source_artifact_id=_artifact(result, "result.components"),
                encoding=VizEncoding(x=_axis("ds", "time", "Period"), y=_axis("seasonality", "measure", "Seasonality", zero=True)),
                caption="The repeating seasonal effect added to the trend.", claim_ids=claim_ids,
            ))
    return specs


def _driver_specs(step: PlanStep, result: ToolResult, payload: DriverResult, claim_ids: tuple[str, ...], ids: _Ids) -> list[VisualizationSpec]:
    specs = []
    if payload.drivers:
        specs.append(VisualizationSpec(
            viz_id=ids.next(), kind="waterfall", title=f"What moved {label(payload.metric).lower()}",
            source_step_id=step.step_id, source_artifact_id=_artifact(result, "result.drivers"),
            encoding=VizEncoding(x=_axis("value", "dimension", "Driver"),
                                 y=_axis("contribution", "measure", "Contribution", unit=unit_for(payload.metric), zero=True),
                                 series=VizSeries(column="dimension", label="Dimension")),
            caption=f"Contributions from {payload.comparison_period} to {payload.current_period}, in the order the engine ranked them.",
            claim_ids=claim_ids,
        ))
    if isinstance(payload, DiagnosticResult) and payload.indicator_drivers:
        specs.append(VisualizationSpec(
            viz_id=ids.next(), kind="bar", title="Indicator effects (positive and negative)",
            source_step_id=step.step_id, source_artifact_id=_artifact(result, "result.indicator_drivers"),
            encoding=VizEncoding(x=_axis("value", "dimension", "Indicator"),
                                 y=_axis("effect_size", "measure", "Effect size", zero=True),
                                 band=VizBand(lower_column="interval.0", upper_column="interval.1", label="Interval")),
            caption="Bars diverge from zero: association, not proven cause.", claim_ids=claim_ids,
        ))
    return specs


def _anomaly_spec(step: PlanStep, result: ToolResult, payload: AnomalyResult, claim_ids: tuple[str, ...], ids: _Ids) -> VisualizationSpec:
    marks = _anomaly_marks([(payload, claim_ids[0] if claim_ids else None)])
    return VisualizationSpec(
        viz_id=ids.next(), kind="range_band", title=f"{payload.window} against its expected range",
        source_step_id=step.step_id, source_artifact_id=_artifact(result, "result"),
        encoding=VizEncoding(x=_axis("window", "time", "Period"), y=_axis("actual", "measure", "Actual", zero=True),
                             band=VizBand(lower_column="expected_range.0", upper_column="expected_range.1", label="Expected range")),
        annotations=marks, caption=step.purpose, claim_ids=claim_ids,
    )


def _scenario_specs(step: PlanStep, result: ToolResult, payload: ScenarioResult, claim_ids: tuple[str, ...], ids: _Ids) -> list[VisualizationSpec]:
    # The engine reports one interval (for the chosen shock) and a point
    # sensitivity curve; the fan is that curve plus the chosen shock's band.
    # No per-shock band is drawn because the engine does not compute one.
    return [
        VisualizationSpec(
            viz_id=ids.next(), kind="range_band", title=f"Scenario: {payload.scenario}",
            source_step_id=step.step_id, source_artifact_id=_artifact(result, "result"),
            encoding=VizEncoding(x=_axis("scenario", "dimension", "Scenario"),
                                 y=_axis("revenue_delta_pct", "measure", "Revenue change", unit="%", zero=True),
                                 band=VizBand(lower_column="revenue_delta_interval.0", upper_column="revenue_delta_interval.1",
                                              label="Uncertainty interval")),
            caption="The chosen scenario with its uncertainty interval.", claim_ids=claim_ids,
        ),
        VisualizationSpec(
            viz_id=ids.next(), kind="line", title="Sensitivity to the size of the change",
            source_step_id=step.step_id, source_artifact_id=_artifact(result, "result.sensitivity"),
            encoding=VizEncoding(x=_axis("shock_pct", "dimension", "Price change", unit="%"),
                                 y=_axis("revenue_delta_pct", "measure", "Revenue change", unit="%", zero=True)),
            caption="Point estimates for other shock sizes; only the chosen scenario carries an interval.",
            claim_ids=claim_ids,
        ),
    ]


def _impact_spec(step: PlanStep, result: ToolResult, payload: ImpactResult, claim_ids: tuple[str, ...], ids: _Ids) -> VisualizationSpec:
    return VisualizationSpec(
        viz_id=ids.next(), kind="range_band", title=f"Change in {label(payload.metric).lower()}",
        source_step_id=step.step_id, source_artifact_id=_artifact(result, "result"),
        encoding=VizEncoding(x=_axis("metric", "dimension", "Metric"),
                             y=_axis("delta", "measure", "Change", unit=payload.unit, zero=True),
                             band=VizBand(lower_column="interval.0", upper_column="interval.1", label="Interval")),
        caption=step.purpose, claim_ids=claim_ids,
    )


def _segment_spec(step: PlanStep, result: ToolResult, payload: SegmentResult, claim_ids: tuple[str, ...], ids: _Ids) -> VisualizationSpec | None:
    if payload.mode != "rank_segments" or len(payload.clusters) < 2:
        return None  # ranked actions render as the NOW WHAT list, not a chart
    return VisualizationSpec(
        viz_id=ids.next(), kind="bar", title="Segment sizes", source_step_id=step.step_id,
        source_artifact_id=_artifact(result, "result.clusters"),
        encoding=VizEncoding(x=_axis("cluster", "dimension", "Segment"), y=_axis("size", "measure", "Customers", zero=True)),
        caption=step.purpose, claim_ids=claim_ids,
    )


def _engine_specs(step: PlanStep, result: ToolResult, claim_ids: tuple[str, ...], ids: _Ids) -> list[VisualizationSpec]:
    output = result.analyst_output
    if output is None or output.status != "ok" or output.result is None:
        return []
    payload = output.result
    if isinstance(payload, ForecastResult):
        return _forecast_specs(step, result, payload, claim_ids, ids)
    if isinstance(payload, DriverResult):  # DiagnosticResult included
        return _driver_specs(step, result, payload, claim_ids, ids)
    if isinstance(payload, AnomalyResult):
        return [_anomaly_spec(step, result, payload, claim_ids, ids)]
    if isinstance(payload, ScenarioResult):
        return _scenario_specs(step, result, payload, claim_ids, ids)
    if isinstance(payload, ImpactResult):
        return [_impact_spec(step, result, payload, claim_ids, ids)]
    if isinstance(payload, SegmentResult):
        spec = _segment_spec(step, result, payload, claim_ids, ids)
        return [spec] if spec is not None else []
    return []


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def build_visualizations(steps: Iterable[PlanStep], results: Mapping[str, ToolResult],
                         claim_ids: Mapping[str, tuple[str, ...]]) -> tuple[VisualizationSpec, ...]:
    """One pass over the plan, in plan order, returning the specs to draw.

    Deterministic: the same plan and results always give the same specs, ids
    included. A spec that fails the contract's own validation is dropped
    rather than raised, so a chart can never break an answer.
    """

    steps = list(steps)
    anomalies: list[tuple[AnomalyResult, str | None]] = []
    for step in steps:
        result = results.get(step.step_id)
        output = result.analyst_output if result is not None else None
        if output is not None and isinstance(output.result, AnomalyResult):
            ids_for = claim_ids.get(step.step_id, ())
            anomalies.append((output.result, ids_for[0] if ids_for else None))

    ids = _Ids()
    specs: list[VisualizationSpec] = []
    annotated = False
    for step in steps:
        result = results.get(step.step_id)
        if result is None or result.status != "ok":
            continue
        step_claims = tuple(claim_ids.get(step.step_id, ()))
        try:
            if result.rows is not None:
                spec = _rows_spec(step, result, step_claims, ids, [] if annotated else anomalies)
                if spec is not None:
                    annotated = annotated or bool(spec.annotations and spec.kind == "line")
                    specs.append(spec)
            elif result.analyst_output is not None:
                found = _engine_specs(step, result, step_claims, ids)
                if annotated:
                    # The spikes and dips are already marked on the series.
                    found = [spec for spec in found if not (spec.kind == "range_band" and spec.source_artifact_id
                                                            and spec.source_artifact_id.endswith(":python.anomaly#result"))]
                specs.extend(found)
        except ValueError:
            continue
    return tuple(specs[:_MAX_SPECS])


__all__ = ["ARTIFACT_PATH_SEPARATOR", "EVIDENCE_ROW_CAP", "build_visualizations"]
