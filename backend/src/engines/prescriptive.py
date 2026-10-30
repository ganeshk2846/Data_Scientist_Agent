"""Prescriptive (NOW WHAT): k-means segmentation of customers or states,
``scipy.optimize`` reorder and budget allocation, and ranked actions with
trade-offs and assumptions.

The frozen registry routes prescriptive work to ``python.segment``
(build-plan-v2 section 4: ``segment`` incl. ``rank_actions``), so every
result here is a ``python.segment`` result:

* ``segments`` - :class:`analysts.segment.SegmentAnalyst` k-means. Members
  are recovered by nearest standardized centroid, which is exactly the
  k-means assignment, so the clustering is not re-run.
* ``reorder`` - a linear program (HiGHS via ``scipy.optimize.linprog``)
  that spends a budget on replenishment units to maximise the margin of
  forecast demand covered, then compares it against two simple policies as
  ranked actions through the existing ``rank_actions`` mode.
* ``actions`` - the existing ``rank_actions`` (with its budget LP) on a
  supplied candidate-action table.

Recommendations are for human review; nothing here executes an action.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

import numpy as np
import pandas as pd
from analysts import registry
from contracts.models import ContractModel, TableRef
from contracts.v2 import SegmentResult
from pydantic import Field
from scipy.optimize import linprog
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler

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

ENGINE_VERSION = "prescriptive-2.0.0"


class PrescriptiveParams(ContractModel):
    mode: Literal["segments", "reorder", "actions"]
    entity: Literal["customers", "states", "segments"] = "states"
    key: str | None = None
    n_clusters: int = Field(default=3, ge=2)
    budget: float | None = Field(default=None, gt=0.0)
    evidence_grades: tuple[int, ...] = ()
    evidence_grade: int = Field(default=2, ge=0, le=4)
    max_options: int = Field(default=3, ge=2, le=3)
    unit: str = "R$"


# --------------------------------------------------------------------------- #
# Segmentation
# --------------------------------------------------------------------------- #


def cluster_members(table: TableRef, profiles: Mapping[int, Mapping[str, float]], key: str) -> dict[str, int]:
    """Assign each row to its nearest standardized centroid (the k-means rule)."""
    usable = [
        column.name for column in table.columns
        if column.role not in {"key", "time"} and not column.name.lower().endswith("_id")
        and column.name.lower() not in {"id", "customer_unique_id", "customer_id"}
    ]
    frame = frame_from_table(table)
    records = []
    for _, row in frame.iterrows():
        record: dict[str, Any] = {}
        for name in usable:
            value = row[name]
            if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
                if math.isfinite(float(value)):
                    record[name] = float(value)
            elif isinstance(value, str) and value.strip():
                record[name] = value.strip()
        records.append(record)
    vectorizer = DictVectorizer(sparse=False, sort=True)
    matrix = vectorizer.fit_transform(records)
    scaler = StandardScaler().fit(matrix)
    scaled = scaler.transform(matrix)
    names = list(vectorizer.get_feature_names_out())
    labels = sorted(profiles)
    centroids = scaler.transform(np.asarray([[profiles[label].get(name, 0.0) for name in names] for label in labels]))
    distances = ((scaled[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
    nearest = distances.argmin(axis=1)
    return {str(frame[key].iloc[index]): labels[int(choice)] for index, choice in enumerate(nearest)}


def _segments(params: PrescriptiveParams, data: EngineData, timer: Timer) -> EngineRun:
    table = data.table(params.entity) or data.table("customers") or data.table("states") or data.table("segments")
    if table is None:
        return insufficient(tool="python.segment", reason="Segmentation needs a customers, states or segments feature table.",
                            data=data, timer=timer, engine_version=ENGINE_VERSION, method="kmeans")
    output = registry.resolve("segment").run(
        analyst_input("segment", {"mode": "rank_segments", "n_clusters": params.n_clusters}, {params.entity: table}, data)
    )
    if output.status != "ok" or not isinstance(output.result, SegmentResult):
        return engine_result(tool="python.segment", output=output, report=_blank("kmeans"), data=data, timer=timer,
                             method="kmeans", engine_version=ENGINE_VERSION, library="sklearn")
    key = params.key or next((column.name for column in table.columns if column.role == "key"), table.columns[0].name)
    members = cluster_members(table, {cluster.cluster: cluster.profile for cluster in output.result.clusters}, key)
    by_cluster: dict[int, list[str]] = {}
    for member, label in sorted(members.items()):
        by_cluster.setdefault(label, []).append(member)
    features = sorted({name for cluster in output.result.clusters for name in cluster.profile})
    profile_rows = tuple(
        (cluster.cluster, cluster.size, cluster.score, ", ".join(by_cluster.get(cluster.cluster, [])),
         *(cluster.profile.get(name) for name in features))
        for cluster in output.result.clusters
    )
    report = EngineReport(
        engine="prescriptive",
        method="kmeans",
        tables=(
            ReportTable(name="clusters", columns=("cluster", "size", "score", "members", *features), rows=profile_rows),
            ReportTable(name="membership", columns=(key, "cluster"), rows=tuple(sorted(members.items()))),
        ),
        key_numbers=(
            KeyNumber(name="clusters", value=float(len(output.result.clusters)), label="segments"),
            KeyNumber(name="entities", value=float(len(members)), label=params.entity),
            KeyNumber(name="top_cluster_score", value=output.result.clusters[0].score, label=f"cluster {output.result.clusters[0].cluster}"),
        ),
        assumptions=(
            *output.assumptions,
            "Members are assigned to their nearest standardized centroid, which is the k-means assignment rule.",
        ),
        confidence=confidence_from(sample_size=len(members), basis="Seeded k-means over the supplied features; segments are descriptive."),
        chart_hint=ChartHint(kind="scatter", table="clusters", x=features[0], y=(features[1] if len(features) > 1 else features[0],),
                             series="cluster", title=f"{params.entity.capitalize()} segments"),
    )
    return engine_result(tool="python.segment", output=output, report=report, data=data, timer=timer,
                         method="kmeans", engine_version=ENGINE_VERSION, library="sklearn")


# --------------------------------------------------------------------------- #
# Reorder allocation
# --------------------------------------------------------------------------- #


def optimize_reorder(items: pd.DataFrame, budget: float) -> pd.DataFrame | None:
    """Maximise margin on covered demand under a purchasing budget (LP).

    Variables per item: order units x >= 0 (<= max_order_units when given)
    and covered units y >= 0 with y <= stock + x and y <= demand.
    Objective: maximise sum(margin * y). Constraint: sum(unit_cost * x) <= budget.
    Unused budget is left unspent rather than buying stock no demand covers.
    """
    n = len(items)
    margin = items["unit_margin"].to_numpy(dtype=float)
    cost = items["unit_cost"].to_numpy(dtype=float)
    stock = items["stock_on_hand"].to_numpy(dtype=float)
    demand = items["forecast_demand"].to_numpy(dtype=float)
    cap = items["max_order_units"].to_numpy(dtype=float) if "max_order_units" in items else np.full(n, np.inf)
    objective = np.concatenate([np.zeros(n), -margin])
    rows = [np.concatenate([cost, np.zeros(n)])]
    bounds_rhs = [budget]
    for index in range(n):
        row = np.zeros(2 * n)
        row[index] = -1.0
        row[n + index] = 1.0
        rows.append(row)
        bounds_rhs.append(stock[index])
    bounds = [(0.0, None if not math.isfinite(cap[index]) else cap[index]) for index in range(n)]
    bounds += [(0.0, max(0.0, demand[index])) for index in range(n)]
    matrix, rhs = np.asarray(rows), np.asarray(bounds_rhs)
    result = linprog(objective, A_ub=matrix, b_ub=rhs, bounds=bounds, method="highs")
    if not result.success or result.x is None:
        return None
    # Second stage: among margin-optimal plans, spend the least (lexicographic LP).
    best = -float(result.fun)
    floor = np.concatenate([np.zeros(n), -margin])
    second = linprog(
        np.concatenate([cost, np.zeros(n)]),
        A_ub=np.vstack([matrix, floor]),
        b_ub=np.concatenate([rhs, [-(best - 1e-7 * max(1.0, abs(best)))]]),
        bounds=bounds,
        method="highs",
    )
    if second.success and second.x is not None:
        result = second
    order = np.round(result.x[:n], 6)
    covered = np.minimum(stock + order, demand)
    out = items[["item"]].copy()
    out["order_units"] = order
    out["order_cost"] = order * cost
    out["covered_demand"] = covered
    out["fill_rate"] = np.where(demand > 0, covered / np.maximum(demand, 1e-12), 1.0)
    out["margin_covered"] = covered * margin
    return out


def _policy(items: pd.DataFrame, budget: float, weights: np.ndarray) -> dict[str, float]:
    """Spend the budget in proportion to ``weights`` (a simple comparison policy)."""
    cost = items["unit_cost"].to_numpy(dtype=float)
    total = float(weights.sum())
    spend = budget * weights / total if total > 0 else np.zeros(len(items))
    order = np.where(cost > 0, spend / cost, 0.0)
    covered = np.minimum(items["stock_on_hand"].to_numpy(dtype=float) + order, items["forecast_demand"].to_numpy(dtype=float))
    return {"margin": float((covered * items["unit_margin"].to_numpy(dtype=float)).sum()), "cost": float(spend.sum()),
            "fill": float(covered.sum() / max(items["forecast_demand"].sum(), 1e-12))}


def _reorder(params: PrescriptiveParams, data: EngineData, timer: Timer) -> EngineRun:
    table = data.table("reorder") or data.table("items")
    if table is None or params.budget is None:
        return insufficient(tool="python.segment", reason="Reorder allocation needs an 'items' table and a budget.",
                            data=data, timer=timer, engine_version=ENGINE_VERSION, method="linprog_highs")
    items = frame_from_table(table)
    required = {"item", "forecast_demand", "stock_on_hand", "unit_cost", "unit_margin"}
    if not required <= set(items.columns):
        return insufficient(tool="python.segment", reason=f"Reorder items need columns {sorted(required)}.", data=data,
                            timer=timer, engine_version=ENGINE_VERSION, method="linprog_highs")
    items = items.sort_values("item", kind="mergesort").reset_index(drop=True)
    plan = optimize_reorder(items, params.budget)
    if plan is None:
        return insufficient(tool="python.segment", reason="The reorder allocation is infeasible for the supplied budget.",
                            data=data, timer=timer, engine_version=ENGINE_VERSION, method="linprog_highs")
    shortfall = np.maximum(items["forecast_demand"] - items["stock_on_hand"], 0.0).to_numpy(dtype=float)
    optimized = {"margin": float(plan["margin_covered"].sum()), "cost": float(plan["order_cost"].sum()),
                 "fill": float(plan["covered_demand"].sum() / max(items["forecast_demand"].sum(), 1e-12))}
    proportional = _policy(items, params.budget, items["forecast_demand"].to_numpy(dtype=float))
    gap_first = _policy(items, params.budget, shortfall * items["unit_cost"].to_numpy(dtype=float))
    base_margin = float((np.minimum(items["stock_on_hand"], items["forecast_demand"]) * items["unit_margin"]).sum())
    grade = params.evidence_grade
    actions = pd.DataFrame([
        ("optimized_reorder", "Reorder per the margin-maximising allocation", optimized["margin"] - base_margin, optimized["cost"], grade,
         "Forecast demand is unbiased|Unit margins and costs are current", "Concentrates spend on the highest-margin gaps|Low-margin items may stay short",
         "Allocation shifts when demand or margin estimates move", "Fill rate by item|Stockout days", "Updated demand forecast|Supplier lead times"),
        ("proportional_reorder", "Reorder in proportion to forecast demand", proportional["margin"] - base_margin, proportional["cost"], grade,
         "Every item deserves stock in line with its demand", "Simple and predictable|Spends on items that already have stock",
         "Insensitive to margin differences", "Fill rate by item", "A margin-weighted target"),
        ("close_gaps_first", "Reorder to close stock gaps first", gap_first["margin"] - base_margin, gap_first["cost"], grade,
         "Every shortfall unit matters equally", "Restores availability fastest|Ignores margin per unit",
         "Changes when the stock snapshot changes", "Stockout days|Fill rate", "Item-level margin data"),
    ], columns=["action_id", "title", "expected_impact", "cost", "evidence_grade", "assumptions", "trade_offs", "sensitivity",
                "monitor", "data_that_would_change_ranking"])
    action_table = table_from_frame(actions, query_id=derived_query_id("REORDER-ACT", table.query_id, params.budget),
                                    roles={"action_id": "key", "title": "label"})
    output = registry.resolve("segment").run(
        analyst_input("segment", {"mode": "rank_actions", "max_options": params.max_options, "budget": params.budget,
                                  "evidence_grades": params.evidence_grades}, {"actions": action_table}, data)
    )
    if output.status != "ok" or not isinstance(output.result, SegmentResult):
        return engine_result(tool="python.segment", output=output, report=_blank("linprog_highs"), data=data, timer=timer,
                             method="linprog_highs", engine_version=ENGINE_VERSION, library="scipy")
    report = EngineReport(
        engine="prescriptive",
        method="linprog_highs",
        tables=(
            ReportTable(name="reorder_plan", columns=tuple(plan.columns), rows=tuple(plan.itertuples(index=False, name=None))),
            ReportTable(name="policies", columns=("policy", "margin_covered", "cost", "fill_rate"), rows=(
                ("optimized_reorder", optimized["margin"], optimized["cost"], optimized["fill"]),
                ("proportional_reorder", proportional["margin"], proportional["cost"], proportional["fill"]),
                ("close_gaps_first", gap_first["margin"], gap_first["cost"], gap_first["fill"]),
                ("no_reorder", base_margin, 0.0, float(np.minimum(items["stock_on_hand"], items["forecast_demand"]).sum()
                                                         / max(items["forecast_demand"].sum(), 1e-12))),
            )),
            ReportTable(name="ranked_actions", columns=("rank", "action_id", "title", "trade_offs", "assumptions"), rows=tuple(
                (option.rank, option.action_id, option.title, "; ".join(option.trade_offs), "; ".join(option.assumptions))
                for option in output.result.actions)),
        ),
        key_numbers=(
            KeyNumber(name="budget", value=params.budget, unit=params.unit, label="purchasing budget"),
            KeyNumber(name="spend", value=optimized["cost"], unit=params.unit, label="optimized spend"),
            KeyNumber(name="margin_covered", value=optimized["margin"], unit=params.unit, label="margin on covered demand"),
            KeyNumber(name="margin_gain_vs_no_reorder", value=optimized["margin"] - base_margin, unit=params.unit, label="gain vs no reorder"),
            KeyNumber(name="margin_gain_vs_proportional", value=optimized["margin"] - proportional["margin"], unit=params.unit,
                      label="gain vs proportional policy"),
            KeyNumber(name="fill_rate", value=optimized["fill"], label="demand fill rate"),
        ),
        assumptions=(
            ("The allocation is a linear program solved with HiGHS (scipy.optimize.linprog): maximise margin on covered "
             "forecast demand subject to the budget, with covered units <= stock + order and <= demand."),
            "Forecast demand, unit cost and unit margin are taken from the supplied rows; lead times and holding cost are not modelled.",
            *output.assumptions,
        ),
        confidence=confidence_from(grade=grade, sample_size=len(items), basis="Optimal for the stated inputs; as good as the demand forecast."),
        chart_hint=ChartHint(kind="bar", table="reorder_plan", x="item", y=("order_units",), title="Reorder allocation"),
    )
    return engine_result(tool="python.segment", output=output, report=report, data=data, timer=timer,
                         method="linprog_highs", engine_version=ENGINE_VERSION, library="scipy")


def _actions(params: PrescriptiveParams, data: EngineData, timer: Timer) -> EngineRun:
    table = data.table("actions")
    if table is None:
        return insufficient(tool="python.segment", reason="Ranking actions needs an 'actions' table.", data=data, timer=timer,
                            engine_version=ENGINE_VERSION, method="rank_actions")
    output = registry.resolve("segment").run(
        analyst_input("segment", {"mode": "rank_actions", "max_options": params.max_options, "budget": params.budget,
                                  "evidence_grades": params.evidence_grades}, {"actions": table}, data)
    )
    if output.status != "ok" or not isinstance(output.result, SegmentResult):
        return engine_result(tool="python.segment", output=output, report=_blank("rank_actions"), data=data, timer=timer,
                             method="rank_actions", engine_version=ENGINE_VERSION)
    impacts = dict(output.result.action_impacts)
    report = EngineReport(
        engine="prescriptive",
        method="rank_actions" + ("+linprog_highs" if output.result.budget_allocation else ""),
        tables=(
            ReportTable(name="ranked_actions", columns=("rank", "action_id", "title", "kind", "expected_impact", "trade_offs", "assumptions"),
                        rows=tuple((option.rank, option.action_id, option.title, option.kind, impacts.get(option.action_id),
                                    "; ".join(option.trade_offs), "; ".join(option.assumptions)) for option in output.result.actions)),
            ReportTable(name="budget_allocation", columns=("action_id", "fraction_funded"), rows=output.result.budget_allocation),
        ),
        key_numbers=tuple(KeyNumber(name=f"impact:{option.action_id}", value=impacts.get(option.action_id), unit=params.unit,
                                    label=option.title) for option in output.result.actions),
        assumptions=output.assumptions,
        confidence=confidence_from(grade=max(params.evidence_grades) if params.evidence_grades else None,
                                   basis="Upstream evidence grades of the candidate actions."),
        chart_hint=ChartHint(kind="bar", table="ranked_actions", x="action_id", y=("expected_impact",), title="Ranked actions"),
    )
    return engine_result(tool="python.segment", output=output, report=report, data=data, timer=timer,
                         method="rank_actions", engine_version=ENGINE_VERSION, library="scipy")


def _blank(method: str) -> EngineReport:
    return EngineReport(engine="prescriptive", method=method, confidence=confidence_from(basis="not run"))


@guarded("python.segment", ENGINE_VERSION, "prescriptive")
def execute(params: Mapping[str, Any], data: EngineData) -> EngineRun:
    """Segment, allocate a reorder budget, or rank candidate actions."""
    timer = Timer()
    parsed = PrescriptiveParams.model_validate(dict(params))
    if parsed.mode == "segments":
        return _segments(parsed, data, timer)
    if parsed.mode == "reorder":
        return _reorder(parsed, data, timer)
    return _actions(parsed, data, timer)


def run(params: Mapping[str, Any], data: EngineData):
    return execute(params, data).result


__all__ = ["PrescriptiveParams", "cluster_members", "execute", "optimize_reorder", "run"]
