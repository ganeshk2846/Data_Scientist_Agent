"""Impact (SO WHAT): is the change significant, how big in R$ and % against
the baseline, the target and the peers; anomaly detection on any series.

Reuses :class:`analysts.impact.ImpactAnalyst` for the change, its Welch test
and interval, and :class:`analysts.anomaly.AnomalyAnalyst` for anomalies.
The engine adds measured target and peer comparisons: the target is read
from a supplied target table (e.g. ``regional_targets``) and the peer value
is the same aggregation over a supplied peer table, so neither is ever
assumed (``ImpactAnalyst`` reports them only when measured upstream).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

import pandas as pd
from analysts import registry
from contracts.models import AnomalyParams, ContractModel, Period, TableRef
from contracts.v2 import AnalystOutput, ImpactResult
from pydantic import Field

from .base import (
    EngineData,
    Timer,
    analyst_input,
    derived_query_id,
    engine_result,
    frame_from_table,
    guarded,
    insufficient,
    table_from_frame,
)
from .report import (
    ChartHint,
    EngineReport,
    EngineRun,
    KeyNumber,
    ReportTable,
    confidence_from,
)

ENGINE_VERSION = "impact-2.0.0"
ANOMALY_VERSION = "anomaly-scan-2.0.0"


class ImpactEngineParams(ContractModel):
    mode: Literal["change", "anomaly"] = "change"
    metric: str = Field(min_length=1)
    unit: str = "R$"
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    aggregation: Literal["sum", "mean"] = "sum"
    basis: Literal["measured_change", "anomaly_gap", "driver_change"] = "measured_change"
    current_period: str | None = None
    baseline_period: str | None = None
    target_column: str = "target"
    peer_label: str = "peers"
    # anomaly mode
    grain: Literal["day", "week", "month", "quarter", "year"] = "month"
    test_window: Period | None = None
    scan_window: Period | None = None
    history_window: Period | None = None
    use_calendar: bool = False


def _column(table: TableRef, *names: str) -> int | None:
    lowered = {column.name.lower(): index for index, column in enumerate(table.columns)}
    return next((lowered[name] for name in names if name in lowered), None)


def _aggregate(values: list[float], aggregation: str) -> float:
    return math.fsum(values) / len(values) if aggregation == "mean" else math.fsum(values)


def _period_values(table: TableRef, label: str | None) -> list[float] | None:
    period = _column(table, "period")
    value = _column(table, "value")
    if period is None or value is None:
        return None
    labels = sorted({str(row[period]) for row in table.rows})
    chosen = label if label is not None else (labels[-1] if labels else None)
    return [float(row[value]) for row in table.rows if str(row[period]) == chosen]


def _with_comparisons(measurements: TableRef, target: float | None, peer: float | None) -> TableRef:
    frame = frame_from_table(measurements)
    roles = {column.name: column.role for column in measurements.columns}
    if target is not None:
        frame["target"] = target
        roles["target"] = "measure"
    if peer is not None:
        frame["peer"] = peer
        roles["peer"] = "measure"
    return table_from_frame(frame, query_id=measurements.query_id, roles=roles)


def _change(params: ImpactEngineParams, data: EngineData, timer: Timer) -> EngineRun:
    measurements = data.table("measurements") or data.table("impact")
    if measurements is None:
        return insufficient(tool="python.impact", reason="Impact needs a 'measurements' table.", data=data,
                            timer=timer, engine_version=ENGINE_VERSION, method="welch_t_test")
    target_value: float | None = None
    targets = data.table("targets")
    if targets is not None:
        index = _column(targets, params.target_column, "revenue_target", "target")
        if index is None or not targets.rows:
            return insufficient(tool="python.impact", reason="The target table has no measured target column.",
                                data=data, timer=timer, engine_version=ENGINE_VERSION, method="welch_t_test")
        target_value = math.fsum(float(row[index]) for row in targets.rows)

    peers = data.table("peers")
    peer_output: AnalystOutput | None = None
    peer_value: float | None = None
    if peers is not None:
        peer_current = _period_values(peers, params.current_period)
        if not peer_current:
            return insufficient(tool="python.impact", reason="The peer table has no measured current-period values.",
                                data=data, timer=timer, engine_version=ENGINE_VERSION, method="welch_t_test")
        peer_value = _aggregate(peer_current, params.aggregation)
        peer_output = registry.resolve("impact").run(
            analyst_input("impact", _impact_params(params), {"measurements": peers}, data)
        )

    tables = {"measurements": _with_comparisons(measurements, target_value, peer_value)}
    output = registry.resolve("impact").run(analyst_input("impact", _impact_params(params), tables, data))
    if output.status != "ok" or not isinstance(output.result, ImpactResult):
        return engine_result(tool="python.impact", output=output, report=_blank(), data=data, timer=timer,
                             method="welch_t_test", engine_version=ENGINE_VERSION, library="scipy")
    result = output.result
    peer_result = peer_output.result if peer_output is not None and isinstance(peer_output.result, ImpactResult) else None
    report = _change_report(params, result, peer_result)
    return engine_result(tool="python.impact", output=output, report=report, data=data, timer=timer,
                         method="welch_t_test", engine_version=ENGINE_VERSION, library="scipy")


def _impact_params(params: ImpactEngineParams) -> dict[str, Any]:
    return {
        "metric": params.metric,
        "basis": params.basis,
        "unit": params.unit,
        "alpha": params.alpha,
        "aggregation": params.aggregation,
        "current_period": params.current_period,
        "baseline_period": params.baseline_period,
    }


def _blank() -> EngineReport:
    return EngineReport(engine="impact", method="welch_t_test", confidence=confidence_from(basis="not run"))


def _change_report(params: ImpactEngineParams, result: ImpactResult, peer: ImpactResult | None) -> EngineReport:
    unit = params.unit
    numbers = [
        KeyNumber(name="baseline", value=result.baseline, unit=unit, label="baseline"),
        KeyNumber(name="current", value=result.current, unit=unit, label="current"),
        KeyNumber(name="delta", value=result.delta, unit=unit, label="change vs baseline"),
        KeyNumber(name="delta_pct", value=result.delta_pct, unit="%", label="change vs baseline"),
        KeyNumber(name="interval_low", value=result.interval[0], unit=unit, label="change interval low"),
        KeyNumber(name="interval_high", value=result.interval[1], unit=unit, label="change interval high"),
        KeyNumber(name="p_value", value=result.p_value, label="Welch t-test p-value"),
    ]
    rows: list[tuple[Any, ...]] = [("baseline", result.baseline, result.delta, result.delta_pct)]
    assumptions = [
        f"Impact is sized in {unit} as current minus baseline, and in % of the baseline.",
        "Significance is a Welch two-sample t-test over the per-period observations.",
    ]
    if result.target is not None:
        gap = result.current - result.target
        attainment = 100.0 * result.current / result.target if result.target != 0 else None
        numbers += [
            KeyNumber(name="target", value=result.target, unit=unit, label="target"),
            KeyNumber(name="gap_to_target", value=gap, unit=unit, label="current minus target"),
            KeyNumber(name="gap_to_target_pct", value=(100.0 * gap / result.target) if result.target else None, unit="%", label="vs target"),
            KeyNumber(name="target_attainment_pct", value=attainment, unit="%", label="attainment"),
        ]
        rows.append(("target", result.target, gap, (100.0 * gap / result.target) if result.target else None))
        assumptions.append("The target is the measured sum of the supplied target rows for the same scope and window.")
    if result.peer is not None:
        gap = result.current - result.peer
        numbers += [
            KeyNumber(name="peer", value=result.peer, unit=unit, label=params.peer_label),
            KeyNumber(name="gap_to_peer", value=gap, unit=unit, label=f"current minus {params.peer_label}"),
        ]
        rows.append((params.peer_label, result.peer, gap, (100.0 * gap / result.peer) if result.peer else None))
        if peer is not None and peer.delta_pct is not None and result.delta_pct is not None:
            numbers += [
                KeyNumber(name="peer_delta_pct", value=peer.delta_pct, unit="%", label=f"{params.peer_label} change"),
                KeyNumber(name="excess_vs_peer_pts", value=result.delta_pct - peer.delta_pct, unit="pts",
                          label=f"change minus {params.peer_label} change"),
            ]
        assumptions.append(
            f"The {params.peer_label} value is the same aggregation over the supplied peer rows; the excess change "
            "compares percentage changes, not levels."
        )
    return EngineReport(
        engine="impact",
        method="welch_t_test",
        tables=(ReportTable(name="comparisons", columns=("against", "value", "gap", "gap_pct"), rows=tuple(rows)),),
        key_numbers=tuple(numbers),
        assumptions=tuple(assumptions),
        confidence=confidence_from(p_value=result.p_value, interval=result.interval,
                                   basis="Welch t-test p-value and change interval."),
        chart_hint=ChartHint(kind="bar", table="comparisons", x="against", y=("value",), title=f"{params.metric}: current vs baseline, target and peers"),
    )


# --------------------------------------------------------------------------- #
# Anomaly detection on any series
# --------------------------------------------------------------------------- #


def _anomaly_params(params: ImpactEngineParams, window: Period) -> dict[str, Any]:
    return AnomalyParams(
        metric=params.metric,
        grain=params.grain if params.grain in {"day", "week", "month"} else "month",  # type: ignore[arg-type]
        test_window=window,
        history_window=params.history_window,
        alpha=params.alpha,
        use_calendar=params.use_calendar,
    ).model_dump()


def _windows(scan: Period, grain: str) -> list[Period]:
    periods = pd.period_range(scan.start, scan.end, freq={"day": "D", "week": "W-SUN", "month": "M"}.get(grain, "M"))
    windows = []
    for item in periods:
        start = item.start_time.date()
        end = (item + 1).start_time.date()
        if start >= scan.start and end <= scan.end:
            windows.append(Period(start=start, end=end))
    return windows


def _anomaly(params: ImpactEngineParams, data: EngineData, timer: Timer) -> EngineRun:
    series = data.table("series")
    if series is None:
        return insufficient(tool="python.anomaly", reason="Anomaly detection needs a 'series' table.", data=data,
                            timer=timer, engine_version=ANOMALY_VERSION, method="robust_baseline")
    windows = [params.test_window] if params.test_window is not None else (
        _windows(params.scan_window, params.grain) if params.scan_window is not None else []
    )
    if not windows:
        return insufficient(tool="python.anomaly", reason="Give a test_window or a scan_window.", data=data,
                            timer=timer, engine_version=ANOMALY_VERSION, method="robust_baseline")
    analyst = registry.resolve("anomaly")
    outputs: list[tuple[Period, AnalystOutput]] = []
    for window in windows:
        output = analyst.run(analyst_input("anomaly", _anomaly_params(params, window), {"series": series}, data))
        outputs.append((window, output))
    usable = [(window, output) for window, output in outputs if output.status == "ok" and output.result is not None]
    if not usable:
        return engine_result(tool="python.anomaly", output=outputs[0][1], report=_blank(), data=data, timer=timer,
                             method="robust_baseline", engine_version=ANOMALY_VERSION)
    flagged = [(window, output) for window, output in usable if output.result.verdict == "unusual"]  # type: ignore[union-attr]
    pool = flagged or usable
    window, chosen = max(pool, key=lambda item: (abs(item[1].result.robust_score), -item[0].start.toordinal()))  # type: ignore[union-attr]
    rows = tuple(
        (
            item_window.start.isoformat(),
            output.result.actual,  # type: ignore[union-attr]
            output.result.expected,  # type: ignore[union-attr]
            output.result.deviation_pct,  # type: ignore[union-attr]
            output.result.robust_score,  # type: ignore[union-attr]
            output.result.verdict,  # type: ignore[union-attr]
        )
        for item_window, output in usable
    )
    result = chosen.result
    report = EngineReport(
        engine="impact",
        method="robust_baseline_anomaly" + ("_scan" if params.scan_window is not None else ""),
        tables=(ReportTable(name="anomalies", columns=("period", "actual", "expected", "deviation_pct", "robust_score", "verdict"), rows=rows),),
        key_numbers=(
            KeyNumber(name="actual", value=result.actual, unit=params.unit, label=f"actual {window.start.isoformat()}"),  # type: ignore[union-attr]
            KeyNumber(name="expected", value=result.expected, unit=params.unit, label="expected"),  # type: ignore[union-attr]
            KeyNumber(name="deviation_pct", value=result.deviation_pct, unit="%", label="deviation"),  # type: ignore[union-attr]
            KeyNumber(name="robust_score", value=result.robust_score, label="robust score"),  # type: ignore[union-attr]
            KeyNumber(name="flagged_periods", value=float(len(flagged)), label="unusual periods"),
            KeyNumber(name="tested_periods", value=float(len(usable)), label="periods tested"),
        ),
        assumptions=(
            *chosen.assumptions,
            "When scanning, each period is tested against its own history; the most extreme unusual period is the headline.",
        ),
        confidence=confidence_from(sample_size=len(usable), basis="Robust baseline score against the history window."),
        chart_hint=ChartHint(kind="line", table="anomalies", x="period", y=("actual", "expected"), title=f"{params.metric}: actual vs expected"),
    )
    return engine_result(tool="python.anomaly", output=chosen, report=report, data=data, timer=timer,
                         method="robust_baseline", engine_version=ANOMALY_VERSION)


@guarded("python.impact", ENGINE_VERSION, "welch_t_test")
def execute(params: Mapping[str, Any], data: EngineData) -> EngineRun:
    """Size a change (``mode="change"``) or detect anomalies (``mode="anomaly"``)."""
    timer = Timer()
    parsed = ImpactEngineParams.model_validate(dict(params))
    if parsed.mode == "anomaly":
        return _anomaly(parsed, data, timer)
    return _change(parsed, data, timer)


def run(params: Mapping[str, Any], data: EngineData):
    return execute(params, data).result


def period_table(frame: pd.DataFrame, *, period: str, value: str, query_id: str | None = None) -> TableRef:
    """Shape a frame into the ``period``/``value`` table ImpactAnalyst reads."""
    shaped = frame[[period, value]].rename(columns={period: "period", value: "value"})
    shaped["period"] = shaped["period"].astype(str)
    return table_from_frame(
        shaped,
        query_id=query_id or derived_query_id("IMPACT", shaped.to_dict("list")),
        roles={"period": "time", "value": "measure"},
    )


__all__ = ["ImpactEngineParams", "execute", "period_table", "run"]

