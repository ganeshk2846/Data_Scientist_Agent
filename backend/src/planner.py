"""Planner: a validated Plan DAG per question (contracts.md section 5, PL-1..7).

Plans are drafted from fixed templates per intent - deterministic, so the
same question always gets the same plan - then validated by code:

* the contract's own validator: DAG shape, depth <= 5, steps <= 8, scenario
  has an upstream fit, the query and engine budgets, covered + dropped intents;
* every ``tool`` is in the closed ``ToolName`` union and every ``params``
  object validates against that tool's schema (PL-3);
* the precomputed analytical tables are preferred when they cover the
  question; otherwise the engine runs live.

A compound question gets one block of steps per intent, sharing series steps
where the intents use the same data (scope.md section 4 rule 3). When a plan
cannot fit the caps the lowest-priority intents are dropped with a stated
reason - never silently (PL-7).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from contracts.models import ContractModel, Period
from contracts.v2 import (
    MAX_PLAN_STEPS,
    DroppedIntent,
    IntentName,
    IntentResult,
    Plan,
    PlanStep,
    ResolvedQuestion,
    StepBudget,
    StepOutputKind,
    ToolName,
)
from engines.diagnostic import DiagnosticParams
from engines.forecast import ForecastEngineParams
from engines.impact import ImpactEngineParams
from engines.prescriptive import PrescriptiveParams
from engines.scenario import ScenarioEngineParams
from pydantic import Field, ValidationError
from semantic.metrics_v2 import all_metrics

RATIO_METRICS = frozenset({"aov", "cancellation_rate", "review_score", "conversion_rate", "stockout_rate", "return_rate",
                           "margin", "target_attainment"})
ANALYTICAL_DIMENSIONS = frozenset({"customer_state", "product_category", "payment_type", "channel"})
SPIKE_FALLBACK_METRICS = ("revenue", "order_count", "aov")
DATASETS = ("indicators_monthly", "delivery_sla", "price_panel", "customer_features", "reorder_items", "regional_targets")
_INTENT_PRIORITY: tuple[IntentName, ...] = ("diagnostic", "forecast", "descriptive", "impact", "prescriptive", "scenario", "discovery")


# --------------------------------------------------------------------------- #
# Tool params schemas (PL-3)
# --------------------------------------------------------------------------- #


class FilterParam(ContractModel):
    dimension: str = Field(min_length=1)
    operator: Literal["=", "in"] = "="
    values: tuple[str, ...] = Field(min_length=1)


class SqlParams(ContractModel):
    kind: Literal["metric", "dataset"]
    metric_id: str | None = None
    dataset: Literal["indicators_monthly", "delivery_sla", "price_panel", "customer_features", "reorder_items",
                     "regional_targets"] | None = None
    grain: Literal["day", "week", "month", "quarter", "year"] = "month"
    period: Period | None = None
    dimensions: tuple[str, ...] = ()
    filters: tuple[FilterParam, ...] = ()
    summary: Literal["none", "trend", "rank", "compare", "aggregate"] = "none"
    summary_period: Period | None = None
    current: Period | None = None
    comparison: Period | None = None
    top_n: int = Field(default=10, ge=1, le=50)


class AnalyticalParams(ContractModel):
    table: Literal["analytical_anomalies", "analytical_forecasts", "analytical_series"]
    kpi: str | None = None
    grain: Literal["month", "day"] = "month"
    dimension: str | None = None
    dimension_values: tuple[str, ...] = ()
    period: Period | None = None
    flagged_only: bool = False
    limit: int = Field(default=500, ge=1, le=5000)


class CatalogParams(ContractModel):
    lookup: Literal["warehouse", "metric_definition", "action_library"]
    metric_ids: tuple[str, ...] = ()


ENGINE_PARAMS: dict[str, type[ContractModel]] = {
    "python.forecast": ForecastEngineParams,
    "python.impact": ImpactEngineParams,
    "python.anomaly": ImpactEngineParams,
    "python.driver": DiagnosticParams,
    "python.scenario": ScenarioEngineParams,
    "python.segment": PrescriptiveParams,
}
TOOL_PARAMS: dict[str, type[ContractModel]] = {
    "sql": SqlParams,
    "analytical_table": AnalyticalParams,
    "catalog": CatalogParams,
    **ENGINE_PARAMS,
}
#: Executor-only keys an engine step may carry beside its engine params (bound at run time).
BINDING_KEYS = frozenset({"bind"})


class PlanValidationError(ValueError):
    """The drafted plan violates a planner rule."""


def validate_step_params(step: PlanStep) -> None:
    schema = TOOL_PARAMS.get(step.tool)
    if schema is None:
        raise PlanValidationError(f"step {step.step_id!r} uses unknown tool {step.tool!r} (PL-3)")
    params = {key: value for key, value in step.params.items() if key not in BINDING_KEYS}
    if step.tool == "python.anomaly":
        params = {**params, "mode": "anomaly"}
    try:
        schema.model_validate(params)
    except ValidationError as exc:
        raise PlanValidationError(f"step {step.step_id!r} has invalid {step.tool} params: {exc.errors()[0]['msg']} (PL-3)") from exc


def validate_plan(plan: Plan) -> Plan:
    for step in plan.steps:
        validate_step_params(step)
    return plan


# --------------------------------------------------------------------------- #
# Drafting
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Capabilities:
    analytical: bool = True
    synthetic: bool = True
    analytical_kpis: frozenset[str] = frozenset()
    forecast_horizon: int = 6
    anchor: str = "2018-08"
    history_start: str = "2016-10"


@dataclass
class _Draft:
    steps: list[PlanStep] = field(default_factory=list)
    keys: dict[str, str] = field(default_factory=dict)
    covered: list[IntentName] = field(default_factory=list)
    dropped: list[DroppedIntent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, key: str | None, tool: ToolName, params: Mapping[str, Any], *, produces: StepOutputKind,
            purpose: str, depends_on: tuple[str, ...] = (), optional: bool = False) -> str:
        if key is not None and key in self.keys:
            return self.keys[key]
        step_id = f"P{len(self.steps) + 1}"
        self.steps.append(PlanStep(step_id=step_id, tool=tool, params=_jsonable(params), depends_on=tuple(dict.fromkeys(depends_on)),
                                   produces=produces, optional=optional, purpose=purpose[:200]))
        if key is not None:
            self.keys[key] = step_id
        return step_id


def _jsonable(value: Any) -> Any:
    if isinstance(value, Period):
        return {"start": value.start.isoformat(), "end": value.end.isoformat()}
    if isinstance(value, ContractModel):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items() if item is not None}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _month(text: str) -> date:
    year, month = (int(part) for part in text[:7].split("-"))
    return date(year, month, 1)


def _add_months(start: date, months: int) -> date:
    index = start.year * 12 + start.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _previous(period: Period) -> Period:
    months = (period.end.year - period.start.year) * 12 + period.end.month - period.start.month
    return Period(start=_add_months(period.start, -months), end=period.start)


class Planner:
    def __init__(self, capabilities: Capabilities | None = None) -> None:
        self.capabilities = capabilities or Capabilities()

    # The public entry point ------------------------------------------------

    def plan(self, intent: IntentResult, resolved: ResolvedQuestion, *, special: tuple[str, ...] = (),
             attempt: int = 0, avoid_analytical: bool = False) -> Plan:
        accepted = [item.intent for item in intent.intents]
        ordered = sorted(accepted, key=lambda name: (_INTENT_PRIORITY.index(name), accepted.index(name)))
        kept = list(accepted)
        while True:
            draft = self._draft(intent, resolved, special, kept, avoid_analytical)
            if len(draft.steps) <= MAX_PLAN_STEPS:
                try:
                    plan = self._finish(intent, resolved, draft, accepted, attempt)
                    return validate_plan(plan)
                except (ValueError, PlanValidationError):
                    if len(kept) == 1:
                        raise
            if len(kept) == 1:
                raise PlanValidationError("even a single-intent plan exceeds the plan caps")
            drop = next(name for name in reversed(ordered) if name in kept and name != kept[0]) if len(kept) > 1 else kept[-1]
            kept.remove(drop)

    def _finish(self, intent: IntentResult, resolved: ResolvedQuestion, draft: _Draft, accepted: list[IntentName], attempt: int) -> Plan:
        covered = [name for name in accepted if name in draft.covered]
        dropped = [*draft.dropped]
        for name in accepted:
            if name not in covered and name not in {item.intent for item in dropped}:
                dropped.append(DroppedIntent(intent=name, reason="Dropped to keep the plan within the 8-step and depth-5 caps."))
        sql_steps = sum(1 for step in draft.steps if step.tool == "sql")
        engines = sum(1 for step in draft.steps if step.is_engine)
        budget = StepBudget(max_queries=max(3, sql_steps + 1), max_engine_calls=max(4, engines + 1),
                            max_tokens=4096, max_wall_ms=60_000)
        steps = tuple(draft.steps)
        source = "deterministic_template" if not dropped or covered else "fallback_single_step"
        seed = json.dumps({"q": resolved.text, "intents": accepted, "attempt": attempt}, sort_keys=True)
        return Plan(
            plan_id="pl_" + hashlib.sha256(seed.encode()).hexdigest()[:10],
            steps=steps,
            depth=_depth(steps),
            source=source,  # type: ignore[arg-type]
            intents_covered=tuple(covered),
            intents_dropped=tuple(item for item in dropped if item.intent not in covered),
            budget=budget,
        )

    # Templates ---------------------------------------------------------------

    def _draft(self, intent: IntentResult, resolved: ResolvedQuestion, special: tuple[str, ...], intents: list[IntentName],
               avoid_analytical: bool) -> _Draft:
        draft = _Draft()
        caps = self.capabilities
        use_analytical = caps.analytical and not avoid_analytical
        metric = resolved.metric_id
        entities = intent.entities
        for name in intents:
            handler = getattr(self, f"_plan_{name}")
            handler(draft, resolved, entities, special, use_analytical, metric)
        return draft

    def _series(self, draft: _Draft, metric: str, resolved: ResolvedQuestion, use_analytical: bool, *,
                start: date | None = None, dimension: str | None = None) -> str:
        caps = self.capabilities
        anchor = _month(caps.anchor)
        history = start or _month(caps.history_start)
        period = Period(start=history, end=_add_months(anchor, 1))
        filters = [item for item in resolved.filters]
        dims_ok = all(item.dimension in ANALYTICAL_DIMENSIONS for item in filters) and len(filters) <= 1 and (dimension is None or not filters)
        if use_analytical and metric in caps.analytical_kpis and dims_ok:
            if filters:
                params = {"table": "analytical_series", "kpi": metric, "grain": "month", "dimension": filters[0].dimension,
                          "dimension_values": list(filters[0].values), "period": period}
            elif dimension is not None:
                params = {"table": "analytical_series", "kpi": metric, "grain": "month", "dimension": dimension, "period": period}
            else:
                params = {"table": "analytical_series", "kpi": metric, "grain": "month", "period": period}
            return draft.add(f"series:{metric}:{dimension}:{params.get('dimension_values')}:{history}", "analytical_table", params,
                             produces="rows", purpose=f"Monthly {metric} series{' by ' + dimension if dimension else ''} from the precomputed analytical layer.")
        return draft.add(f"series:{metric}:{dimension}:{history}", "sql", {
            "kind": "metric", "metric_id": metric, "grain": "month", "period": period,
            "dimensions": [dimension] if dimension else [], "filters": [_filter(item) for item in filters],
        }, produces="rows", purpose=f"Monthly {metric} series{' by ' + dimension if dimension else ''} through the last complete month.")

    def _plan_discovery(self, draft, resolved, entities, special, use_analytical, metric) -> None:
        if metric and any(word in resolved.text.lower() for word in ("defined", "definition", "mean", "difference between", "dimensions", "break")):
            ids = [metric, *entities.secondary_metric_ids]
            draft.add("catalog:definition", "catalog", {"lookup": "metric_definition", "metric_ids": ids}, produces="catalog_facts",
                      purpose="Metric definitions and allowed dimensions from the governed registry.")
        else:
            draft.add("catalog:warehouse", "catalog", {"lookup": "warehouse"}, produces="catalog_facts",
                      purpose="Every table, row count, date span and synthetic label from the catalog.")
        draft.covered.append("discovery")

    def _plan_descriptive(self, draft, resolved, entities, special, use_analytical, metric) -> None:
        caps = self.capabilities
        if "spike_scan" in special or metric is None:
            if use_analytical and caps.analytical:
                draft.add("anomalies", "analytical_table", {"table": "analytical_anomalies", "flagged_only": True, "limit": 50},
                          produces="rows", purpose="Flagged spikes and dips across every metric and month, precomputed by python.anomaly.")
            else:
                anchor = _month(caps.anchor)
                window = Period(start=_add_months(anchor, -11), end=_add_months(anchor, 1))
                for name in SPIKE_FALLBACK_METRICS:
                    series = self._series(draft, name, resolved.model_copy(update={"filters": ()}), False)
                    draft.add(f"scan:{name}", "python.anomaly", {"metric": name, "unit": "", "grain": "month", "scan_window": window},
                              produces="analyst_output", purpose=f"Live anomaly scan of {name} over the last 12 complete months.", depends_on=(series,))
            draft.covered.append("descriptive")
            return
        lowered = resolved.text.lower()
        summary = "none"
        if resolved.comparison_period is not None and resolved.period is not None:
            summary = "compare"
        elif resolved.dimensions and any(word in lowered for word in ("top", "highest", "lowest", "biggest", "largest", "best", "worst", "rank")):
            summary = "rank"
        elif "trend" in lowered or "today" in lowered or resolved.grain in {"month", "week", "day"} and not resolved.dimensions:
            summary = "trend"
        elif resolved.dimensions:
            summary = "aggregate"
        period = resolved.period
        current, comparison = resolved.period, resolved.comparison_period
        if summary == "compare" and current is not None and comparison is not None:
            period = Period(start=min(current.start, comparison.start), end=max(current.end, comparison.end))
        draft.add(f"describe:{metric}", "sql", {
            "kind": "metric", "metric_id": metric, "grain": resolved.grain or "month", "period": period,
            "dimensions": list(resolved.dimensions), "filters": [_filter(item) for item in resolved.filters],
            "summary": summary, "current": current if summary == "compare" else None,
            "comparison": comparison if summary == "compare" else None,
        }, produces="rows", purpose=f"{metric} {summary if summary != 'none' else 'value'} for {_label(resolved.period)}.")
        draft.covered.append("descriptive")

    def _plan_diagnostic(self, draft, resolved, entities, special, use_analytical, metric) -> None:
        caps = self.capabilities
        if "delivery" in special and caps.synthetic:
            anchor = _month(caps.anchor)
            auto = resolved.period is None
            period = resolved.period or Period(start=anchor, end=_add_months(anchor, 1))
            comparison = resolved.comparison_period or _previous(period)
            window = Period(start=_add_months(anchor, -12), end=_add_months(anchor, 1)) if auto else Period(start=comparison.start, end=period.end)
            data = draft.add("dataset:delivery", "sql", {"kind": "dataset", "dataset": "delivery_sla", "period": window},
                             produces="rows", purpose="Delivery SLA rows (synthetic) for the window and the month before.")
            drill = draft.add("driver:delivery", "python.driver", {
                "metric": "sla_breach_rate", "aggregation": "ratio", "current_period": period, "comparison_period": comparison,
                "dimensions": ["carrier", "customer_state"], "grain": "day", "bind": {"auto_window": auto}},
                produces="analyst_output", purpose="Drill the breach-rate change down by carrier and state.", depends_on=(data,))
            draft.add("driver:delivery:did", "python.driver", {
                "metric": "sla_breach_rate", "aggregation": "ratio", "current_period": period, "comparison_period": comparison,
                "dimensions": ["carrier"], "grain": "day",
                "specificity": {"dimension": "carrier", "treated": ["auto"], "date": "date", "measures": ["delay_days", "freight_cost"]},
                "bind": {"treated_from": drill, "auto_window": auto}},
                produces="analyst_output", purpose="Test whether the delay is specific to the top carrier against the others.",
                depends_on=(data, drill))
            draft.covered.append("diagnostic")
            return
        metric = metric or "revenue"
        period = resolved.period or Period(start=_month(caps.anchor), end=_add_months(_month(caps.anchor), 1))
        comparison = resolved.comparison_period or _previous(period)
        series = self._series(draft, metric, resolved, use_analytical)
        anomaly_window = period if (period.end.year - period.start.year) * 12 + period.end.month - period.start.month <= 3 else None
        if anomaly_window is not None:
            draft.add(f"anomaly:{metric}", "python.anomaly", {"metric": metric, "grain": "month", "test_window": anomaly_window},
                      produces="analyst_output", purpose=f"Test whether {metric} in {_label(period)} is outside its expected range.",
                      depends_on=(series,))
        dimension = next(iter(resolved.dimensions), None) or _default_dimension(metric)
        by_dimension = self._series(draft, metric, resolved.model_copy(update={"filters": ()}), use_analytical,
                                    start=comparison.start, dimension=dimension)
        depends = [by_dimension]
        params: dict[str, Any] = {
            "metric": metric, "current_period": period, "comparison_period": comparison, "dimensions": [dimension],
            "aggregation": "ratio" if metric in RATIO_METRICS else "sum", "grain": "month", "max_lag": 2,
        }
        if caps.synthetic:
            indicators = draft.add("dataset:indicators", "sql", {"kind": "dataset", "dataset": "indicators_monthly",
                                                                  "period": Period(start=_month(caps.history_start), end=_add_months(_month(caps.anchor), 1))},
                                   produces="rows", purpose="Monthly synthetic indicators: spend by channel, sessions, stockouts, discounts, delays.",
                                   optional=True)
            depends.append(indicators)
            params["bind"] = {"indicators_from": indicators}
        draft.add(f"driver:{metric}", "python.driver", params, produces="analyst_output",
                  purpose=f"Attribute the {metric} change by {dimension} and test co-movement with candidate drivers.",
                  depends_on=tuple(depends))
        draft.covered.append("diagnostic")

    def _plan_impact(self, draft, resolved, entities, special, use_analytical, metric) -> None:
        caps = self.capabilities
        metric = metric or "revenue"
        period = resolved.period or Period(start=_month(caps.anchor), end=_add_months(_month(caps.anchor), 1))
        comparison = resolved.comparison_period or _previous(period)
        lowered = resolved.text.lower()
        if "target" in lowered and caps.synthetic:
            # Regional targets are revenue targets, so the gap is sized in revenue whatever word was used.
            metric = "revenue"
        unit = "R$" if metric in {"revenue", "gmv", "aov", "freight_value", "marketing_spend"} else metric.replace("_", " ")
        series = self._series(draft, metric, resolved, use_analytical)
        if "target" in lowered and caps.synthetic:
            targets = draft.add("dataset:targets", "sql", {"kind": "dataset", "dataset": "regional_targets", "period": period,
                                                            "filters": [_filter(item) for item in resolved.filters]},
                                produces="rows", purpose="Regional revenue targets (synthetic) for the same window and scope.")
            draft.add(f"impact:{metric}:target", "python.impact", {
                "metric": metric, "unit": unit, "current_period": "current", "baseline_period": "baseline",
                "bind": {"current": period, "baseline": comparison, "targets_from": targets}},
                produces="analyst_output", purpose="Size the gap to target and to the prior period, in R$ and %.",
                depends_on=(series, targets))
        elif draft.keys.get(f"anomaly:{metric}") or (period.end.year - period.start.year) * 12 + period.end.month - period.start.month == 1:
            anomaly = draft.keys.get(f"anomaly:{metric}") or draft.add(
                f"anomaly:{metric}", "python.anomaly", {"metric": metric, "grain": "month", "test_window": period},
                produces="analyst_output", purpose=f"Expected {metric} for {_label(period)} from its own history.", depends_on=(series,))
            draft.add(f"impact:{metric}", "python.impact", {
                "metric": metric, "unit": unit, "basis": "anomaly_gap", "bind": {"anomaly_from": anomaly}},
                produces="analyst_output", purpose=f"Size the gap between actual and expected {metric}, in {unit}.",
                depends_on=(series, anomaly))
        else:
            draft.add(f"impact:{metric}", "python.impact", {
                "metric": metric, "unit": unit, "current_period": "current", "baseline_period": "baseline",
                "bind": {"current": period, "baseline": comparison}},
                produces="analyst_output", purpose=f"Size the {metric} change against the prior window, in {unit} and %.",
                depends_on=(series,))
        draft.covered.append("impact")

    def _plan_forecast(self, draft, resolved, entities, special, use_analytical, metric) -> None:
        caps = self.capabilities
        metric = metric or "revenue"
        horizon = entities.horizon.periods if entities.horizon else 3
        if (use_analytical and metric in caps.analytical_kpis and not resolved.filters and not resolved.dimensions
                and horizon <= caps.forecast_horizon and "describe:" + metric not in draft.keys):
            draft.add(f"forecast:{metric}", "analytical_table", {"table": "analytical_forecasts", "kpi": metric, "limit": 50},
                      produces="rows", purpose=f"Precomputed {metric} forecast with intervals and backtest MAPE.")
            draft.covered.append("forecast")
            return
        source = draft.keys.get(f"describe:{metric}") if not resolved.dimensions and not resolved.comparison_period else None
        if source is None or self._summary_of(draft, source) != "trend":
            source = self._series(draft, metric, resolved, use_analytical)
        else:
            # The trend query must reach back far enough to fit on (V2-DATA-2).
            self._extend_history(draft, source)
        draft.add(f"forecast:{metric}", "python.forecast", {
            "metric": metric, "anchor": caps.anchor, "horizon": horizon, "grain": "month",
            "ratio": metric in {"aov", "cancellation_rate"}, "question": resolved.text[:300],
            "unit": "R$" if metric in {"revenue", "gmv", "aov"} else ""},
            produces="analyst_output", purpose=f"Forecast {metric} {horizon} months ahead with intervals and a backtest.",
            depends_on=(source,))
        draft.covered.append("forecast")

    def _plan_scenario(self, draft, resolved, entities, special, use_analytical, metric) -> None:
        caps = self.capabilities
        params = list(entities.scenario_params)
        target_metric = "revenue"
        series = self._series(draft, target_metric, resolved.model_copy(update={"filters": ()}), use_analytical)
        anchor = _month(caps.anchor)
        current = Period(start=_add_months(anchor, -2), end=_add_months(anchor, 1))
        baseline = draft.add("impact:baseline", "python.impact", {
            "metric": target_metric, "unit": "R$", "current_period": "current", "baseline_period": "baseline",
            "bind": {"current": current, "baseline": _previous(current)}},
            produces="analyst_output", purpose="Measure the baseline revenue the scenario is sized against.", depends_on=(series,))
        price = next((item for item in params if item.target == "price"), None)
        removal = next((item for item in params if item.kind == "remove" and item.applies_to is not None), None)
        if removal is not None and price is None:
            # No fitted response exists for a removal, but the size of what is at stake is measured directly.
            dimension = removal.applies_to.dimension
            draft.add(f"stake:{dimension}", "sql", {
                "kind": "metric", "metric_id": target_metric, "grain": "month", "period": Period(start=_add_months(anchor, -11), end=_add_months(anchor, 1)),
                "dimensions": [dimension], "summary": "rank", "top_n": 5},
                produces="rows", purpose=f"Revenue by {dimension} over the last 12 complete months: what the scenario puts at stake.")
        depends = [baseline]
        scenario_params: dict[str, Any] = {"question": resolved.text[:300], "unit": "R$"}
        if price is not None and caps.synthetic:
            panel = draft.add("dataset:price_panel", "sql", {"kind": "dataset", "dataset": "price_panel"}, produces="rows",
                              purpose="Category-day units, list prices, promotions and competitor prices (synthetic).")
            depends.append(panel)
            scenario_params["price_change_pct"] = round((price.value - 1.0) * 100.0, 6)
            scenario_params["bind"] = {"panel_from": panel, "baseline_from": baseline}
        else:
            scenario_params["bind"] = {"baseline_from": baseline, "unsupported": [item.model_dump(mode="json") for item in params]}
        draft.add("scenario", "python.scenario", scenario_params, produces="analyst_output",
                  purpose="Simulate the stated change with Monte Carlo intervals and driver sensitivity.", depends_on=tuple(depends))
        draft.covered.append("scenario")

    def _plan_prescriptive(self, draft, resolved, entities, special, use_analytical, metric) -> None:
        caps = self.capabilities
        lowered = resolved.text.lower()
        if "segments" in special and caps.synthetic or "target" in lowered and "segment" in lowered:
            data = draft.add("dataset:customers", "sql", {"kind": "dataset", "dataset": "customer_features"}, produces="rows",
                             purpose="Customer features: synthetic segment, LTV band, channel, and measured orders and revenue.")
            draft.add("segment:customers", "python.segment", {"mode": "segments", "entity": "customers", "key": "customer_unique_id",
                                                              "n_clusters": 4},
                      produces="analyst_output", purpose="Cluster customers and rank the segments by measured revenue.", depends_on=(data,))
            draft.covered.append("prescriptive")
            return
        if "inventory" in special and caps.synthetic:
            data = draft.add("dataset:reorder", "sql", {"kind": "dataset", "dataset": "reorder_items"}, produces="rows",
                             purpose="Latest stock, recent in-stock demand, price and unit cost per category (synthetic).")
            draft.add("segment:reorder", "python.segment", {"mode": "reorder", "budget": 1.0, "bind": {"budget_share": 0.5}},
                      produces="analyst_output", purpose="Allocate a reorder budget across categories with a linear program.",
                      depends_on=(data,))
            draft.covered.append("prescriptive")
            return
        upstream = [step for key, step in draft.keys.items() if key.startswith(("driver:", "impact:", "anomaly:"))]
        if not upstream:
            if "watch" in lowered or "monitor" in lowered:
                if use_analytical and caps.analytical:
                    upstream.append(draft.add("anomalies", "analytical_table", {"table": "analytical_anomalies", "flagged_only": True, "limit": 50},
                                              produces="rows", purpose="Recent flagged movements to monitor, from the precomputed scan."))
                else:
                    self._plan_diagnostic(draft, resolved, entities, (), use_analytical, metric)
                    draft.covered.remove("diagnostic")
            else:
                self._plan_diagnostic(draft, resolved, entities, special, use_analytical, metric)
                draft.covered.remove("diagnostic")
            upstream = [step for key, step in draft.keys.items() if key.startswith(("driver:", "impact:", "anomaly:", "anomalies"))]
        library = draft.add("catalog:actions", "catalog", {"lookup": "action_library"}, produces="catalog_facts",
                            purpose="Candidate actions matching the identified driver types.", optional=True)
        draft.add("segment:actions", "python.segment", {"mode": "actions", "max_options": 3, "bind": {"actions_from": [*upstream, library]}},
                  produces="analyst_output", purpose="Rank 2-3 actions by quantified impact and evidence grade.",
                  depends_on=tuple(dict.fromkeys([*upstream, library])))
        draft.covered.append("prescriptive")

    @staticmethod
    def _summary_of(draft: _Draft, step_id: str) -> str | None:
        step = next(item for item in draft.steps if item.step_id == step_id)
        return step.params.get("summary")

    def _extend_history(self, draft: _Draft, step_id: str) -> None:
        index = next(i for i, item in enumerate(draft.steps) if item.step_id == step_id)
        step = draft.steps[index]
        params = dict(step.params)
        # The trend keeps the window the user asked for; the query reaches back far enough to fit on.
        if params.get("period"):
            params["summary_period"] = params["period"]
        params["period"] = {"start": f"{self.capabilities.history_start}-01", "end": _add_months(_month(self.capabilities.anchor), 1).isoformat()}
        draft.steps[index] = step.model_copy(update={"params": params})


def _filter(item) -> dict[str, Any]:
    return {"dimension": item.dimension, "operator": "in" if len(item.values) > 1 else "=", "values": list(item.values)}


_REGISTRY = all_metrics()
_DIMENSION_PREFERENCE = ("product_category", "customer_state", "channel", "payment_type", "order_status", "customer_city")


def _default_dimension(metric: str) -> str:
    """The first governed breakdown the metric allows, in a fixed order of usefulness."""
    definition = _REGISTRY.get(metric)
    allowed = [dimension.name for dimension in definition.allowed_dimensions] if definition is not None else []
    return next((name for name in _DIMENSION_PREFERENCE if name in allowed), allowed[0] if allowed else "customer_state")


def _label(period: Period | None) -> str:
    if period is None:
        return "the default window"
    last = _add_months(period.end, -1)
    return f"{period.start:%Y-%m}" if last == period.start else f"{period.start:%Y-%m} to {last:%Y-%m}"


def _depth(steps: tuple[PlanStep, ...]) -> int:
    by_id = {step.step_id: step for step in steps}
    memo: dict[str, int] = {}

    def depth(step_id: str) -> int:
        if step_id not in memo:
            step = by_id[step_id]
            memo[step_id] = 1 + max((depth(dep) for dep in step.depends_on), default=0)
        return memo[step_id]

    return max(depth(step.step_id) for step in steps)


def plan_shape(plan: Plan) -> list[str]:
    """``tool<-deps`` per step, the form the question bank asserts on."""
    index = {step.step_id: position for position, step in enumerate(plan.steps, start=1)}
    return [step.tool + ("<-" + ",".join(str(index[dep]) for dep in step.depends_on) if step.depends_on else "") for step in plan.steps]


__all__ = [
    "ANALYTICAL_DIMENSIONS",
    "DATASETS",
    "RATIO_METRICS",
    "TOOL_PARAMS",
    "AnalyticalParams",
    "Capabilities",
    "CatalogParams",
    "PlanValidationError",
    "Planner",
    "SqlParams",
    "plan_shape",
    "validate_plan",
    "validate_step_params",
]
