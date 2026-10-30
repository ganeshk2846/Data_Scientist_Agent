"""Result sanity checks and the self-correction loop (item 6).

After a plan runs, each result is checked for problems a reader would catch:
an empty result where data was expected, a stale or missing precomputed
table, an engine refusing on short history, negative values for a metric
that cannot be negative, a ratio outside its bounds, a truncated result. Each
issue names a deterministic fix the planner can apply; the run re-plans at
most ``MAX_REPLANS`` times and otherwise answers with the issues as caveats.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from contracts.v2 import ToolResult
from executor_v2 import Execution

MAX_REPLANS = 2
Fix = Literal["live_engine", "widen_window", "drop_dimension", "none"]
NON_NEGATIVE = frozenset({"revenue", "gmv", "order_count", "item_count", "customer_count", "freight_value", "marketing_spend", "sessions"})
BOUNDED = {"cancellation_rate": (0.0, 1.0), "conversion_rate": (0.0, 1.0), "stockout_rate": (0.0, 1.0), "return_rate": (0.0, 1.0),
           "review_score": (1.0, 5.0)}


@dataclass(frozen=True)
class Issue:
    step_id: str
    kind: str
    message: str
    fix: Fix


def _values(result: ToolResult, metric: str | None) -> list[float]:
    if result.rows is None or not result.rows.rows:
        return []
    names = [column.name for column in result.rows.columns]
    index = names.index(metric) if metric in names else names.index("value") if "value" in names else None
    if index is None:
        return []
    return [float(row[index]) for row in result.rows.rows if isinstance(row[index], (int, float)) and not isinstance(row[index], bool)]


def check(execution: Execution, *, metric: str | None) -> list[Issue]:
    issues: list[Issue] = []
    for step in execution.plan.steps:
        result = execution.results.get(step.step_id)
        if result is None:
            continue
        if result.status == "insufficient_evidence" and step.tool == "analytical_table":
            issues.append(Issue(step.step_id, "cache_unavailable", result.reason or "The precomputed table could not serve this step.", "live_engine"))
            continue
        if result.status == "empty" and step.tool in ("sql", "analytical_table") and not step.optional:
            issues.append(Issue(step.step_id, "empty_result", "The query returned no rows for the requested window.", "widen_window"))
            continue
        reason = (result.reason or "").lower()
        if (result.status == "insufficient_evidence" and step.is_engine and step.tool != "python.scenario"
                and ("complete periods" in reason or "short history" in reason or "history periods" in reason or "observations" in reason)):
            issues.append(Issue(step.step_id, "short_history", result.reason, "widen_window"))
            continue
        if result.rows is not None and result.rows.truncated:
            issues.append(Issue(step.step_id, "truncated", "The result hit the row cap.", "drop_dimension"))
        values = _values(result, step.params.get("metric_id") or metric)
        if any(not math.isfinite(value) for value in values):
            issues.append(Issue(step.step_id, "non_finite", "The result contains a non-finite value.", "none"))
        name = step.params.get("metric_id") or metric
        if name in NON_NEGATIVE and any(value < 0 for value in values):
            issues.append(Issue(step.step_id, "negative", f"{name} cannot be negative but the result holds a negative value.", "none"))
        if name in BOUNDED and values:
            low, high = BOUNDED[name]
            if any(value < low - 1e-9 or value > high + 1e-9 for value in values):
                issues.append(Issue(step.step_id, "out_of_bounds", f"{name} must lie in [{low}, {high}].", "none"))
    return issues


def actionable(issues: list[Issue]) -> list[Issue]:
    return [issue for issue in issues if issue.fix != "none"]


__all__ = ["BOUNDED", "MAX_REPLANS", "NON_NEGATIVE", "Issue", "actionable", "check"]
