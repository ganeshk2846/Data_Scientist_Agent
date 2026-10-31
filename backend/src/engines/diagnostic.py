"""Diagnostic (WHY): drill-down across every dimension, price/volume/mix
decomposition, lagged correlation with candidate drivers, a
difference-in-differences specificity test, feature importance, and a
ranked driver list with effect size, interval and evidence grade.

Built on :class:`analysts.driver.DriverAnalyst`, which still does the
contribution decomposition (additive and ratio), reconciliation, and the
grade-capped feature importance. This module adds what the brief asks for
on top, keeping the evidence ladder (build-plan-v2 section 4, EVID-1):

====================  ===========================================  =====
stage                 method                                       grade
====================  ===========================================  =====
concentration         contribution by dimension value (DRV-2)      1
co-movement           lagged Pearson on common-shock-adjusted       2
                      series, Benjamini-Hochberg across candidates
association           random-forest importance (capped)            <= 2
specificity           difference-in-differences regression, HC1    3
====================  ===========================================  =====

A share whose numerator and the rest of its total move in opposite
directions is a *reallocation*: it shifts composition, not volume, so it is
held at grade 1 and labelled, never ranked as the driver. Every grade stays observational;
the causal-boundary note is always attached (DRV-9).
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping
from datetime import date
from typing import Any, Literal

import numpy as np
import pandas as pd
import statsmodels.api as sm
from analysts import registry
from contracts.models import ContractModel, DriverContribution, Period, TableRef
from contracts.v2 import DiagnosticEvidence, DiagnosticResult
from pydantic import Field
from scipy.stats import pearsonr, ttest_ind
from statsmodels.stats.multitest import multipletests

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

ENGINE_VERSION = "diagnostic-2.0.0"
EVIDENCE_LABELS = {
    0: "no usable evidence",
    1: "concentration only",
    2: "co-movement (correlation, association only)",
    3: "specific to the treated unit (difference-in-differences)",
    4: "experimental",
}
CAUSAL_BOUNDARY = (
    "Causal boundary: every grade here is observational. Grade 2 is co-movement; grade 3 shows the change is "
    "specific to the treated unit against a comparison group. Neither proves the driver caused the change - "
    "unmeasured factors and reverse causation can produce the same pattern."
)

Filter = dict[str, tuple[str, ...]]


class DriverSpec(ContractModel):
    """One candidate driver series built from a supplied table."""

    name: str = Field(min_length=1)
    table: str = Field(min_length=1)
    value: str = Field(min_length=1)
    date: str = "date"
    agg: Literal["sum", "mean"] = "sum"
    where: Filter = Field(default_factory=dict)
    share_of: Filter | None = None
    relative_to_rest: bool = False
    expected_sign: Literal[1, -1] | None = None


class SpecificitySpec(ContractModel):
    dimension: str = Field(min_length=1)
    treated: tuple[str, ...] = Field(min_length=1)
    control: tuple[str, ...] = ()
    measures: tuple[str, ...] = ()
    table: str = "contrib"
    date: str = "period"
    where: Filter = Field(default_factory=dict)


class PvmSpec(ContractModel):
    table: str = "sales"
    period: str = "period"
    dimension: str = Field(min_length=1)
    price: str = "price"
    quantity: str = "quantity"


class DiagnosticParams(ContractModel):
    metric: str = Field(min_length=1)
    current_period: Period
    comparison_period: Period
    aggregation: Literal["sum", "ratio", "mean"] = "sum"
    dimensions: tuple[str, ...] = ()
    unit: str = ""
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)
    grain: Literal["day", "week", "month"] = "week"
    max_lag: int = Field(default=4, ge=0, le=12)
    target_where: Filter = Field(default_factory=dict)
    target_relative_to_rest: bool = False
    drivers: tuple[DriverSpec, ...] = ()
    specificity: SpecificitySpec | None = None
    pvm: PvmSpec | None = None
    top_k: int = Field(default=5, ge=1, le=20)


# --------------------------------------------------------------------------- #
# Series helpers
# --------------------------------------------------------------------------- #


def _bucket(values: pd.Series, grain: str) -> pd.Series:
    text = values.astype(str).str[:10]
    if grain == "day":
        return text
    if grain == "month":
        return text.str[:7]
    return pd.to_datetime(text).dt.to_period("W-SUN").astype(str)


def _mask(frame: pd.DataFrame, where: Mapping[str, tuple[str, ...]]) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for column, values in where.items():
        mask &= frame[column].astype(str).isin(values)
    return mask


def _aggregate(frame: pd.DataFrame, date_col: str, value_col: str, agg: str, grain: str) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    keys = _bucket(frame[date_col], grain)
    grouped = frame[value_col].astype(float).groupby(keys)
    return (grouped.mean() if agg == "mean" else grouped.sum()).sort_index()


def driver_series(spec: DriverSpec, table: TableRef, grain: str) -> tuple[pd.Series, tuple[pd.Series, pd.Series] | None]:
    """The candidate series, and (numerator, complement) when it is a share."""
    frame = frame_from_table(table)
    scope = _mask(frame, spec.share_of) if spec.share_of is not None else pd.Series(True, index=frame.index)
    chosen = scope & _mask(frame, spec.where)
    numerator = _aggregate(frame[chosen], spec.date, spec.value, spec.agg, grain)
    parts: tuple[pd.Series, pd.Series] | None = None
    if spec.share_of is not None:
        parent = _aggregate(frame[scope], spec.date, spec.value, spec.agg, grain)
        complement = _aggregate(frame[scope & ~_mask(frame, spec.where)], spec.date, spec.value, spec.agg, grain)
        parts = (numerator, complement)
        series = numerator / parent
    elif spec.relative_to_rest:
        rest = _aggregate(frame[~chosen], spec.date, spec.value, spec.agg, grain)
        series = numerator / rest
    else:
        series = numerator
    return series.replace([np.inf, -np.inf], np.nan).dropna(), parts


def _target_series(params: DiagnosticParams, contrib: pd.DataFrame, value_cols: tuple[str, ...], period_col: str) -> pd.Series:
    def level(frame: pd.DataFrame) -> pd.Series:
        if params.aggregation == "ratio":
            numerator = _aggregate(frame, period_col, value_cols[0], "sum", params.grain)
            denominator = _aggregate(frame, period_col, value_cols[1], "sum", params.grain)
            return numerator / denominator
        return _aggregate(frame, period_col, value_cols[0], "mean" if params.aggregation == "mean" else "sum", params.grain)

    chosen = _mask(contrib, params.target_where)
    series = level(contrib[chosen])
    if params.target_relative_to_rest and params.target_where:
        series = series / level(contrib[~chosen])
    return series.replace([np.inf, -np.inf], np.nan).dropna()


def _in_window(index: pd.Index, window: Period, grain: str) -> np.ndarray:
    starts = pd.to_datetime([_period_start(label, grain) for label in index])
    return np.asarray((starts >= pd.Timestamp(window.start)) & (starts < pd.Timestamp(window.end)))


def _period_start(label: str, grain: str) -> str:
    if grain == "week":
        return str(label).split("/")[0]
    return str(label) if grain == "day" else f"{label}-01"


# --------------------------------------------------------------------------- #
# Evidence stages
# --------------------------------------------------------------------------- #


def _fisher_interval(r: float, n: int) -> tuple[float, float]:
    if n <= 3:
        return -1.0, 1.0
    z = math.atanh(min(0.999999, max(-0.999999, r)))
    margin = 1.959963984540054 / math.sqrt(n - 3)
    return math.tanh(z - margin), math.tanh(z + margin)


def lagged_correlations(
    target: pd.Series, candidates: Mapping[str, pd.Series], *, max_lag: int, alpha: float
) -> list[dict[str, Any]]:
    """Best-lag Pearson per candidate, BH-corrected over every (candidate, lag) tested."""
    log_target = np.log(target) if (target > 0).all() else target
    tested: list[dict[str, Any]] = []
    for name in sorted(candidates):
        series = candidates[name]
        values = np.log(series) if (series > 0).all() else series
        for lag in range(max_lag + 1):
            joined = pd.concat([log_target, values.shift(lag)], axis=1, join="inner").dropna()
            if len(joined) < 6 or joined.iloc[:, 0].std() == 0 or joined.iloc[:, 1].std() == 0:
                continue
            result = pearsonr(joined.iloc[:, 0], joined.iloc[:, 1])
            tested.append({"name": name, "lag": lag, "r": float(result.statistic), "p": float(result.pvalue), "n": len(joined)})
    if not tested:
        return []
    q_values = multipletests([item["p"] for item in tested], alpha=alpha, method="fdr_bh")[1]
    for item, q in zip(tested, q_values, strict=True):
        item["q"] = float(q)
    best: dict[str, dict[str, Any]] = {}
    for item in tested:
        current = best.get(item["name"])
        if current is None or abs(item["r"]) > abs(current["r"]) + 1e-12:
            best[item["name"]] = item
    return [best[name] for name in sorted(best)]


def window_screen(candidates: Mapping[str, pd.Series], params: DiagnosticParams, *, outcome_sign: float = 0.0,
                  signs: Mapping[str, int] | None = None, baseline: int = 6) -> list[dict[str, Any]]:
    """Which candidates sat at an unusual level in the question's window, at lags 0..max_lag (DRV-5).

    Each period's level is read against the median of the ``baseline``
    periods before it (log scale for positive series, level otherwise); the
    window's mean deviation is scored against the deviations of every other
    period in the candidate's own history - a robust z-score (median / MAD,
    scaled for the window length), a two-sided normal p-value, and
    Benjamini-Hochberg across every (candidate, lag) tested. The most
    significant lag per candidate is kept. A candidate with a declared
    expected sign is *consistent* when its deviation times that sign has the
    sign of the outcome's change. This is timing evidence only: it says the
    candidate was unusual when the outcome moved, never that it moved the outcome.
    """
    from scipy.stats import norm

    signs = signs or {}
    tested: list[dict[str, Any]] = []
    for name in sorted(candidates):
        series = candidates[name].sort_index().astype(float)
        current = np.flatnonzero(_in_window(series.index, params.current_period, params.grain))
        if not len(current):
            continue
        logged = bool((series > 0).all())
        values = np.log(series.to_numpy()) if logged else series.to_numpy()
        deviation = np.full(len(values), np.nan)
        reference = np.full(len(values), np.nan)
        for t in range(3, len(values)):
            trailing = values[max(0, t - baseline):t]
            reference[t] = float(np.median(trailing))
            deviation[t] = values[t] - reference[t]
        for lag in range(params.max_lag + 1):
            window = current - lag
            if window.min() < 0 or np.isnan(deviation[window]).any():
                continue
            history = np.delete(deviation, window)
            history = history[~np.isnan(history)]
            if len(history) < 6:
                continue
            observed = float(deviation[window].mean())
            centre = float(np.median(history))
            scale = 1.4826 * float(np.median(np.abs(history - centre))) or float(np.std(history))
            if scale <= 1e-12:
                if abs(observed - centre) <= 1e-12:
                    continue
                scale = 1e-12
            z = max(-50.0, min(50.0, (observed - centre) / (scale / math.sqrt(len(window)))))
            base_level = float(np.mean(np.exp(reference[window]) if logged else reference[window]))
            level = float(series.iloc[window].mean())
            sign = signs.get(name)
            tested.append({
                "name": name, "lag": lag, "z": z, "p": float(2 * norm.sf(abs(z))), "n": len(history),
                "change_pct": 100.0 * (level / base_level - 1) if abs(base_level) > 1e-12 else None,
                "consistent": None if sign is None or outcome_sign == 0 else bool(np.sign(observed) * sign == np.sign(outcome_sign)),
            })
    if not tested:
        return []
    q_values = multipletests([item["p"] for item in tested], alpha=params.alpha, method="fdr_bh")[1]
    for item, q in zip(tested, q_values, strict=True):
        item["q"] = float(q)
    best: dict[str, dict[str, Any]] = {}
    for item in tested:
        current_best = best.get(item["name"])
        if current_best is None or item["q"] < current_best["q"] - 1e-12 or (
                abs(item["q"] - current_best["q"]) <= 1e-12 and abs(item["z"]) > abs(current_best["z"])):
            best[item["name"]] = item
    return [best[name] for name in sorted(best)]


def _window_change(series: pd.Series, params: DiagnosticParams) -> tuple[float | None, float | None]:
    current = series[_in_window(series.index, params.current_period, params.grain)]
    comparison = series[_in_window(series.index, params.comparison_period, params.grain)]
    if len(current) < 2 or len(comparison) < 2 or comparison.mean() == 0:
        return None, None
    pct = 100.0 * (current.mean() - comparison.mean()) / comparison.mean()
    test = ttest_ind(current, comparison, equal_var=False)
    return float(pct), float(test.pvalue) if math.isfinite(float(test.pvalue)) else None


def difference_in_differences(
    frame: pd.DataFrame, *, spec: SpecificitySpec, measure: str, params: DiagnosticParams, date_col: str
) -> dict[str, Any] | None:
    """OLS ``y ~ treated + post + treated:post`` with HC1 errors, per row."""
    rows = frame[_mask(frame, spec.where)].copy()
    starts = pd.to_datetime(rows[date_col].astype(str).str[:10])
    post = (starts >= pd.Timestamp(params.current_period.start)) & (starts < pd.Timestamp(params.current_period.end))
    pre = (starts >= pd.Timestamp(params.comparison_period.start)) & (starts < pd.Timestamp(params.comparison_period.end))
    rows = rows[post | pre]
    if rows.empty:
        return None
    group = rows[spec.dimension].astype(str)
    treated = group.isin(spec.treated)
    control = group.isin(spec.control) if spec.control else ~treated
    rows = rows[treated | control]
    if rows.empty:
        return None
    treated = rows[spec.dimension].astype(str).isin(spec.treated).astype(float).to_numpy()
    after = (pd.to_datetime(rows[date_col].astype(str).str[:10]) >= pd.Timestamp(params.current_period.start)).astype(float).to_numpy()
    y = rows[measure].astype(float).to_numpy()
    if len(set(treated)) < 2 or len(set(after)) < 2 or len(y) < 8:
        return None
    design = np.column_stack([np.ones_like(y), treated, after, treated * after])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = sm.OLS(y, design).fit(cov_type="HC1")
    effect = float(fitted.params[3])
    low, high = (float(value) for value in fitted.conf_int(alpha=params.alpha)[3])
    p_value = float(fitted.pvalues[3])
    baseline = float(np.mean(y[(treated == 1) & (after == 0)])) if np.any((treated == 1) & (after == 0)) else None
    if not all(math.isfinite(value) for value in (effect, low, high, p_value)):
        return None
    return {
        "measure": measure,
        "effect": effect,
        "interval": (low, high),
        "p": p_value,
        "n": int(len(y)),
        "baseline": baseline,
        "effect_pct": (100.0 * effect / baseline) if baseline is not None and baseline > 0 else None,
    }


def price_volume_mix(frame: pd.DataFrame, spec: PvmSpec, params: DiagnosticParams) -> dict[str, Any] | None:
    """Exact revenue and average-price decomposition between the two windows.

    Revenue: volume = (Q1 - Q0) * P0, mix = Q1 * sum((s1 - s0) * p0),
    price = sum(q1 * (p1 - p0)); they sum to R1 - R0 exactly.
    Average price: rate = sum(s1 * (p1 - p0)), mix = sum((s1 - s0) * p0);
    they sum to P1 - P0 exactly and volume has no term by construction.
    A segment present in only one window carries its own price on both sides,
    so its whole effect is mix.
    """
    starts = pd.to_datetime(frame[spec.period].astype(str).str[:10])

    def window(period: Period) -> pd.DataFrame:
        rows = frame[(starts >= pd.Timestamp(period.start)) & (starts < pd.Timestamp(period.end))].copy()
        rows["_revenue"] = rows[spec.price].astype(float) * rows[spec.quantity].astype(float)
        grouped = rows.groupby(rows[spec.dimension].astype(str)).agg(q=(spec.quantity, "sum"), r=("_revenue", "sum"))
        return grouped[grouped["q"] > 0]

    before, after = window(params.comparison_period), window(params.current_period)
    if before.empty or after.empty:
        return None
    keys = sorted(set(before.index) | set(after.index))
    q0 = before["q"].reindex(keys, fill_value=0.0).astype(float)
    q1 = after["q"].reindex(keys, fill_value=0.0).astype(float)
    r0 = before["r"].reindex(keys, fill_value=0.0).astype(float)
    r1 = after["r"].reindex(keys, fill_value=0.0).astype(float)
    p0 = (r0 / q0.where(q0 > 0)).fillna(r1 / q1.where(q1 > 0))
    p1 = (r1 / q1.where(q1 > 0)).fillna(p0)
    total_q0, total_q1 = float(q0.sum()), float(q1.sum())
    s0, s1 = q0 / total_q0, q1 / total_q1
    asp0, asp1 = float(r0.sum()) / total_q0, float(r1.sum()) / total_q1
    volume = (total_q1 - total_q0) * asp0
    mix_by = total_q1 * (s1 - s0) * p0
    price_by = q1 * (p1 - p0)
    rate_by = s1 * (p1 - p0)
    asp_mix_by = (s1 - s0) * p0
    revenue_change = float(r1.sum() - r0.sum())
    return {
        "revenue_before": float(r0.sum()),
        "revenue_after": float(r1.sum()),
        "revenue_change": revenue_change,
        "volume_effect": float(volume),
        "mix_effect": float(mix_by.sum()),
        "price_effect": float(price_by.sum()),
        "revenue_residual": float(revenue_change - (volume + mix_by.sum() + price_by.sum())),
        "asp_before": asp0,
        "asp_after": asp1,
        "asp_change": asp1 - asp0,
        "asp_rate_effect": float(rate_by.sum()),
        "asp_mix_effect": float(asp_mix_by.sum()),
        "asp_residual": float((asp1 - asp0) - (rate_by.sum() + asp_mix_by.sum())),
        "units_change_pct": 100.0 * (total_q1 - total_q0) / total_q0,
        "by_segment": [
            (key, float(price_by[key]), float(mix_by[key]), float(q1[key] - q0[key])) for key in keys
        ],
    }


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


def _contrib_columns(table: TableRef, aggregation: str) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    names = [column.name for column in table.columns]
    lowered = {name.lower(): name for name in names}
    period = next((column.name for column in table.columns if column.role == "time"), None) or next(
        (lowered[key] for key in ("period", "date", "month", "week") if key in lowered), None
    )
    if aggregation == "ratio":
        if "numerator" not in lowered or "denominator" not in lowered:
            return None
        values = (lowered["numerator"], lowered["denominator"])
    else:
        value = lowered.get("value") or next((column.name for column in table.columns if column.role == "measure"), None)
        if value is None:
            return None
        values = (value,)
    dimensions = tuple(column.name for column in table.columns if column.role == "dimension" and column.name != period)
    if period is None:
        return None
    return period, values, dimensions


def _driver_params(params: DiagnosticParams, dimensions: tuple[str, ...]) -> dict[str, Any]:
    return {
        "metric": params.metric,
        "current_period": params.current_period,
        "comparison_period": params.comparison_period,
        "dimensions": dimensions,
        "max_dimensions": max(5, len(dimensions)),
        "aggregation": params.aggregation,
        "value_decomposition": params.aggregation == "ratio",
        "alpha": params.alpha,
    }


def _concentration(result: DiagnosticResult) -> float:
    magnitudes = [abs(item.contribution) for item in result.drivers]
    total = math.fsum(magnitudes)
    return max(magnitudes) / total if total > 0 else 0.0


def drill_down(params: DiagnosticParams, contrib: TableRef, dimensions: tuple[str, ...], data: EngineData) -> list[dict[str, Any]]:
    """Run the existing driver decomposition once per dimension (and the top pair)."""
    analyst = registry.resolve("driver")
    levels: list[dict[str, Any]] = []
    for dimension in dimensions:
        output = analyst.run(analyst_input("driver", _driver_params(params, (dimension,)), {"contrib": contrib}, data))
        if output.status == "ok" and isinstance(output.result, DiagnosticResult):
            levels.append({"dimensions": (dimension,), "result": output.result, "output": output,
                           "concentration": _concentration(output.result)})
    levels.sort(key=lambda item: (-item["concentration"], item["dimensions"]))
    if len(levels) >= 2:
        pair = (levels[0]["dimensions"][0], levels[1]["dimensions"][0])
        output = analyst.run(analyst_input("driver", _driver_params(params, pair), {"contrib": contrib}, data))
        if output.status == "ok" and isinstance(output.result, DiagnosticResult):
            levels.append({"dimensions": pair, "result": output.result, "output": output,
                           "concentration": _concentration(output.result)})
    return levels


@guarded("python.driver", ENGINE_VERSION, "diagnostic_ladder")
def execute(params: Mapping[str, Any], data: EngineData) -> EngineRun:
    """Explain a change: where it concentrates, what moved with it, how specific it is."""

    timer = Timer()
    parsed = DiagnosticParams.model_validate(dict(params))
    contrib = data.table("contrib")
    if contrib is None or not contrib.rows:
        return insufficient(tool="python.driver", reason="A diagnosis needs a non-empty 'contrib' table.", data=data,
                            timer=timer, engine_version=ENGINE_VERSION, method="diagnostic_ladder")
    columns = _contrib_columns(contrib, parsed.aggregation)
    if columns is None:
        return insufficient(tool="python.driver", reason="The contrib table needs a period column and measured values.",
                            data=data, timer=timer, engine_version=ENGINE_VERSION, method="diagnostic_ladder")
    period_col, value_cols, available = columns
    dimensions = parsed.dimensions or available
    if not dimensions:
        return insufficient(tool="python.driver", reason="No dimension is available to drill into.", data=data,
                            timer=timer, engine_version=ENGINE_VERSION, method="diagnostic_ladder")

    # 1. Drill-down across every dimension (existing contribution engine).
    levels = drill_down(parsed, contrib, tuple(dimensions), data)
    if not levels:
        output = registry.resolve("driver").run(
            analyst_input("driver", _driver_params(parsed, (dimensions[0],)), {"contrib": contrib}, data)
        )
        return engine_result(tool="python.driver", output=output,
                             report=EngineReport(engine="diagnostic", method="diagnostic_ladder", confidence=confidence_from(basis="not run")),
                             data=data, timer=timer, method="diagnostic_ladder", engine_version=ENGINE_VERSION)
    primary = levels[0]

    contrib_frame = frame_from_table(contrib)
    target = _target_series(parsed, contrib_frame, value_cols, period_col)

    # 2. Candidate drivers and lagged, common-shock-adjusted co-movement.
    candidates: dict[str, pd.Series] = {}
    parents: dict[str, tuple[pd.Series, pd.Series]] = {}
    signs: dict[str, int] = {}
    tables_used: list[str] = []
    for spec in parsed.drivers:
        table = data.table(spec.table)
        if table is None:
            continue
        series, parts = driver_series(spec, table, parsed.grain)
        if len(series) >= 6:
            candidates[spec.name] = series
            tables_used.append(spec.table)
            if parts is not None:
                parents[spec.name] = parts
            if spec.expected_sign is not None:
                signs[spec.name] = spec.expected_sign
    correlations = lagged_correlations(target, candidates, max_lag=parsed.max_lag, alpha=parsed.alpha)
    for item in correlations:
        item["reallocation"] = False
        item["wrong_sign"] = item["name"] in signs and math.copysign(1, item["r"]) != signs[item["name"]]
        item["window_change_pct"], item["window_p"] = _window_change(candidates[item["name"]], parsed)
        parts = parents.get(item["name"])
        if parts is not None:
            moved, _ = _window_change(parts[0], parsed)
            offset, _ = _window_change(parts[1], parsed)
            item["numerator_change_pct"], item["complement_change_pct"] = moved, offset
            if moved is not None and offset is not None and moved * offset < 0:
                item["reallocation"] = True

    # 2b. Timing screen: which candidates moved unusually into the window itself (lagged).
    screen = window_screen(candidates, parsed, outcome_sign=float(np.sign(primary["result"].total_change or 0.0)), signs=signs)

    # 3. Feature importance from the existing engine, on the same adjusted series (monthly).
    importance: tuple[DiagnosticEvidence, ...] = ()
    if len(candidates) >= 2:
        importance = _feature_importance(parsed, target, candidates, data)

    demoted = {item["name"] for item in correlations if item["reallocation"] or item["wrong_sign"]}
    importance = tuple(item.model_copy(update={"grade": 1}) if item.value in demoted else item for item in importance)

    # 4. Specificity: difference-in-differences.
    specificity: list[dict[str, Any]] = []
    if parsed.specificity is not None:
        spec = parsed.specificity
        frame = contrib_frame if spec.table == "contrib" else frame_from_table(data.tables[spec.table])
        date_col = period_col if spec.table == "contrib" else spec.date
        for measure in spec.measures or (value_cols[0],):
            outcome = difference_in_differences(frame, spec=spec, measure=measure, params=parsed, date_col=date_col)
            if outcome is not None:
                specificity.append(outcome)

    # 5. Price / volume / mix.
    pvm = None
    if parsed.pvm is not None and data.table(parsed.pvm.table) is not None:
        pvm = price_volume_mix(frame_from_table(data.tables[parsed.pvm.table]), parsed.pvm, parsed)

    evidence = _evidence(parsed, correlations, specificity)
    ranked = _rank(parsed, primary["result"], correlations, specificity, importance, screen)
    decomposition = _pvm_contributions(pvm) if pvm is not None else primary["result"].value_decomposition
    result = DiagnosticResult(
        **{
            **primary["result"].model_dump(),
            "indicator_drivers": tuple(evidence),
            "feature_importance": importance,
            "value_decomposition": tuple(decomposition),
            "correction_used": f"benjamini_hochberg_{parsed.alpha:.2f}" if correlations else primary["result"].correction_used,
        }
    )
    base_output = primary["output"]
    output = base_output.model_copy(
        update={
            "result": result,
            "assumptions": (*base_output.assumptions, CAUSAL_BOUNDARY,
                            ("Correlations use log series at the stated grain, the target and any 'relative' driver "
                             "expressed against the rest of its table to remove shared trend and calendar effects.")),
            "sources": tuple(dict.fromkeys((*base_output.sources, *(data.tables[name].query_id for name in tables_used)))),
        }
    )
    report = _report(parsed, levels, ranked, pvm, specificity, correlations, result)
    return engine_result(tool="python.driver", output=output, report=report, data=data, timer=timer,
                         method="diagnostic_ladder", engine_version=ENGINE_VERSION, library="scipy+statsmodels+sklearn")


def run(params: Mapping[str, Any], data: EngineData):
    return execute(params, data).result


def _feature_importance(
    params: DiagnosticParams, target: pd.Series, candidates: Mapping[str, pd.Series], data: EngineData
) -> tuple[DiagnosticEvidence, ...]:
    """Monthly random-forest importance via the existing DriverAnalyst (capped at grade 2)."""
    def monthly(series: pd.Series) -> pd.Series:
        starts = pd.to_datetime([_period_start(label, params.grain) for label in series.index])
        return series.groupby(starts.strftime("%Y-%m")).mean()

    target_m = monthly(target)
    frame = pd.DataFrame({"period": [f"{label}-01" for label in target_m.index], "series": "target", "value": target_m.to_numpy()})
    drivers = pd.DataFrame({"date": [f"{label}-01" for label in target_m.index]})
    for name, series in sorted(candidates.items()):
        drivers[name] = monthly(series).reindex(target_m.index).to_numpy()
    drivers = drivers.dropna()
    if len(drivers) < 8:
        return ()
    tables = {
        "contrib": table_from_frame(frame, query_id=derived_query_id("DIAG-T", frame.to_dict("list")),
                                    roles={"period": "time", "series": "dimension", "value": "measure"}),
        "drivers": table_from_frame(drivers, query_id=derived_query_id("DIAG-X", drivers.to_dict("list")), roles={"date": "time"}),
    }
    span = Period(start=date.fromisoformat(frame["period"].iloc[0]), end=date.fromisoformat(frame["period"].iloc[-1]))
    first_half = Period(start=span.start, end=date.fromisoformat(frame["period"].iloc[len(frame) // 2]))
    second_half = Period(start=first_half.end, end=span.end)
    output = registry.resolve("driver").run(
        analyst_input(
            "driver",
            {"metric": params.metric, "current_period": second_half, "comparison_period": first_half,
             "dimensions": ("series",), "aggregation": "sum", "alpha": params.alpha},
            tables,
            data,
        )
    )
    if output.status != "ok" or not isinstance(output.result, DiagnosticResult):
        return ()
    return tuple(
        item.model_copy(update={"value": item.value.removeprefix("drivers.")}) for item in output.result.feature_importance
    )


def _correlation_grade(item: Mapping[str, Any], alpha: float) -> int:
    if item["reallocation"] or item["wrong_sign"] or item["q"] >= alpha:
        return 1
    return 2


def _evidence(params: DiagnosticParams, correlations: list[dict[str, Any]], specificity: list[dict[str, Any]]) -> list[DiagnosticEvidence]:
    evidence = [
        DiagnosticEvidence(
            dimension="driver",
            value=item["name"],
            method="correlation",
            effect_size=item["r"],
            interval=_fisher_interval(item["r"], item["n"]),
            p_value=min(1.0, max(0.0, item["p"])),
            q_value=min(1.0, max(0.0, item["q"])),
            sample_size=item["n"],
            grade=_correlation_grade(item, params.alpha),
            lag_periods=item["lag"],
        )
        for item in correlations
    ]
    if params.specificity is not None:
        for item in specificity:
            evidence.append(
                DiagnosticEvidence(
                    dimension=params.specificity.dimension,
                    value=f"{'+'.join(params.specificity.treated)}:{item['measure']}",
                    method="difference_in_differences",
                    effect_size=item["effect"],
                    interval=item["interval"],
                    p_value=min(1.0, max(0.0, item["p"])),
                    sample_size=item["n"],
                    grade=3 if item["p"] < params.alpha and (item["interval"][0] > 0 or item["interval"][1] < 0) else 1,
                )
            )
    return evidence


def _rank(
    params: DiagnosticParams,
    primary: DiagnosticResult,
    correlations: list[dict[str, Any]],
    specificity: list[dict[str, Any]],
    importance: tuple[DiagnosticEvidence, ...],
    screen: list[dict[str, Any]] = (),
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for item in screen:
        if item["q"] >= params.alpha:
            note = "no unusual level in the window"
        elif item["consistent"]:
            note = "unusual level in the window, in the direction expected to move the outcome"
        elif item["consistent"] is None:
            note = "unusual level in the window, with no declared link to the outcome's direction"
        else:
            note = "unusual level in the window, against the direction expected to move the outcome"
        rows.append((item["name"], "window_change", item["z"], item["z"] - 1.959963984540054, item["z"] + 1.959963984540054,
                     item["p"], item["q"], 1, "unusual level in the same window (timing only)", item["lag"], item["change_pct"], note))
    for item in correlations:
        grade = _correlation_grade(item, params.alpha)
        if item["reallocation"]:
            note = (f"reallocation: the share moved {item['numerator_change_pct']:.1f}% while the rest of its total "
                    f"moved {item['complement_change_pct']:.1f}%")
        elif item["wrong_sign"]:
            note = "sign contradicts the expected direction"
        else:
            note = "co-moves with the outcome" if grade == 2 else "not significant after correction"
        low, high = _fisher_interval(item["r"], item["n"])
        rows.append((item["name"], "correlation", item["r"], low, high, item["p"], item["q"], grade,
                     EVIDENCE_LABELS[grade], item["lag"], item.get("window_change_pct"), note))
    if params.specificity is not None:
        for item in specificity:
            grade = 3 if item["p"] < params.alpha and (item["interval"][0] > 0 or item["interval"][1] < 0) else 1
            rows.append((f"{params.specificity.dimension}={'+'.join(params.specificity.treated)} ({item['measure']})",
                         "difference_in_differences", item["effect"], item["interval"][0], item["interval"][1],
                         item["p"], None, grade, EVIDENCE_LABELS[grade], 0, item["effect_pct"],
                         "specific to the treated group" if grade == 3 else "not specific to the treated group"))
    for item in importance:
        grade = min(item.grade, 2)
        rows.append((item.value, "feature_importance", item.effect_size, item.interval[0], item.interval[1], None, None,
                     grade, "association in a fitted model (not causal)", 0, None,
                     "association in a fitted model" if grade == 2 else "demoted with its correlation evidence"))
    for item in _largest(primary.drivers, params.top_k):
        rows.append((f"{item.dimension}={item.value}", "contribution", item.contribution, item.interval[0], item.interval[1],
                     None, None, 1, EVIDENCE_LABELS[1], 0, None,
                     "ratio component (shares are not additive for a ratio)" if "(" in item.dimension else f"share {item.share:.3f} of the change"))
    method_order = {"difference_in_differences": 0, "correlation": 1, "feature_importance": 2, "window_change": 3, "contribution": 4}
    rows.sort(key=lambda row: (-row[7], method_order[row[1]], row[6] if row[6] is not None else (row[5] if row[5] is not None else 1.0), -abs(row[2]), row[0]))
    return rows


def _largest(drivers: tuple[DriverContribution, ...], count: int) -> list[DriverContribution]:
    """The largest contributions first (ratio components arrive in key order)."""
    return sorted(drivers, key=lambda item: (-abs(item.contribution), item.dimension, item.value))[:count]


def _pvm_contributions(pvm: dict[str, Any]) -> list[DriverContribution]:
    def item(name: str, value: float) -> DriverContribution:
        return DriverContribution(dimension="price_volume_mix", value=name, contribution=value,
                                  share=(value / pvm["revenue_change"]) if pvm["revenue_change"] else 0.0,
                                  interval=(value, value), sample_size=len(pvm["by_segment"]), unstable=False, grade=1)

    return [item("volume", pvm["volume_effect"]), item("mix", pvm["mix_effect"]), item("price", pvm["price_effect"])]


def _report(
    params: DiagnosticParams,
    levels: list[dict[str, Any]],
    ranked: list[tuple[Any, ...]],
    pvm: dict[str, Any] | None,
    specificity: list[dict[str, Any]],
    correlations: list[dict[str, Any]],
    result: DiagnosticResult,
) -> EngineReport:
    drill_rows = []
    for level in levels:
        for driver in _largest(level["result"].drivers, params.top_k):
            drill_rows.append((" / ".join(level["dimensions"]), driver.value, driver.contribution, driver.share,
                               driver.interval[0], driver.interval[1], level["concentration"]))
    tables = [
        ReportTable(name="ranked_drivers", columns=("driver", "method", "effect_size", "interval_low", "interval_high", "p_value",
                                                    "q_value", "grade", "evidence", "lag_periods", "change_pct", "note"),
                    rows=tuple(ranked)),
        ReportTable(name="drill_down", columns=("dimensions", "value", "contribution", "share", "interval_low", "interval_high",
                                                "dimension_concentration"), rows=tuple(drill_rows)),
    ]
    numbers = [
        KeyNumber(name="total_change", value=result.total_change, unit=params.unit, label=f"{params.metric} change"),
        KeyNumber(name="reconciliation_error", value=result.reconciliation_error, unit=params.unit, label="decomposition residual"),
        KeyNumber(name="dimensions_examined", value=float(len(levels)), label="drill-down levels"),
        KeyNumber(name="candidates_tested", value=float(len(correlations)), label="candidate drivers"),
    ]
    if ranked:
        numbers.append(KeyNumber(name="top_driver_grade", value=float(ranked[0][7]), label=str(ranked[0][0])))
    if pvm is not None:
        tables.append(ReportTable(name="price_volume_mix", columns=("component", "revenue_effect", "average_price_effect"), rows=(
            ("volume", pvm["volume_effect"], 0.0),
            ("mix", pvm["mix_effect"], pvm["asp_mix_effect"]),
            ("price", pvm["price_effect"], pvm["asp_rate_effect"]),
            ("total", pvm["revenue_change"], pvm["asp_change"]),
        )))
        tables.append(ReportTable(name="price_volume_mix_by_segment", columns=("segment", "price_effect", "mix_effect", "units_change"),
                                  rows=tuple(pvm["by_segment"])))
        for key in ("revenue_change", "volume_effect", "mix_effect", "price_effect", "asp_change", "asp_rate_effect",
                    "asp_mix_effect", "units_change_pct"):
            numbers.append(KeyNumber(name=key, value=pvm[key], unit="%" if key.endswith("_pct") else params.unit, label=key.replace("_", " ")))
    for item in specificity:
        numbers.append(KeyNumber(name=f"did:{item['measure']}", value=item["effect"], unit=params.unit, label="difference-in-differences effect"))
    top_grade = ranked[0][7] if ranked else 0
    return EngineReport(
        engine="diagnostic",
        method="diagnostic_ladder",
        tables=tuple(tables),
        key_numbers=tuple(numbers),
        assumptions=(
            "Drill-down runs the contribution decomposition once per dimension and once for the most concentrated pair.",
            "Correlations are Benjamini-Hochberg corrected across every candidate and lag tested.",
            ("The window screen reads each candidate's level in the window against its trailing six-period median and "
             "scores that deviation against the rest of its own history (robust z-score, Benjamini-Hochberg across "
             "candidates and lags); it is timing evidence only."),
            "A share whose numerator and the rest of its total move in opposite directions is a reallocation and held at grade 1.",
            "A candidate whose correlation contradicts its declared expected sign is held at grade 1.",
            "Difference-in-differences uses ordinary least squares with HC1 robust errors on the row-level observations.",
            "Price/volume/mix effects reconcile exactly to the revenue and average-price changes.",
            CAUSAL_BOUNDARY,
        ),
        confidence=confidence_from(grade=int(top_grade), sample_size=_samples(levels), basis="Highest evidence grade reached by the top driver."),
        chart_hint=ChartHint(kind="waterfall" if pvm is not None else "bar", table="price_volume_mix" if pvm is not None else "ranked_drivers",
                             x="component" if pvm is not None else "driver", y=("revenue_effect",) if pvm is not None else ("effect_size",),
                             title=f"Why {params.metric} changed"),
    )


def _samples(levels: list[dict[str, Any]]) -> int:
    return sum(driver.sample_size for driver in levels[0]["result"].drivers) if levels else 0


__all__ = ["CAUSAL_BOUNDARY", "DiagnosticParams", "DriverSpec", "PvmSpec", "SpecificitySpec", "difference_in_differences",
           "drill_down", "driver_series", "execute", "lagged_correlations", "price_volume_mix", "run", "window_screen"]
