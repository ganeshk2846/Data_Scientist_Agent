"""Customer/state segmentation and evidence-bounded action ranking."""

from __future__ import annotations

import math
from typing import Literal

import numpy as np
from pydantic import Field, ValidationError, field_validator
from scipy.optimize import linprog
from sklearn.cluster import KMeans
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler

from contracts.models import ActionOption, AnalystInput, ContractModel, TableRef
from contracts.v2 import AnalystOutput, SegmentCluster, SegmentResult


class SegmentParams(ContractModel):
    mode: Literal["rank_segments", "rank_actions"]
    n_clusters: int = Field(default=4, ge=2)
    max_options: int = Field(default=3, ge=2, le=3)
    budget: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    evidence_grades: tuple[int, ...] = ()

    @field_validator("evidence_grades")
    @classmethod
    def _grades_are_valid(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if any(grade < 0 or grade > 4 for grade in value):
            raise ValueError("evidence grades must be between 0 and 4")
        return value


class SegmentAnalyst:
    module = "segment"

    def run(self, inp: AnalystInput) -> AnalystOutput:
        try:
            params = SegmentParams.model_validate(inp.params)
        except ValidationError as exc:
            return _insufficient(f"Invalid segment parameters: {exc}", inp)
        if params.mode == "rank_actions":
            table = inp.tables.get("actions")
            if table is None:
                return _insufficient(
                    "rank_actions requires measured candidate actions and their trade-offs.",
                    inp,
                )
            return _rank_actions(inp, table, params)
        table = (
            inp.tables.get("customers")
            or inp.tables.get("states")
            or inp.tables.get("segments")
        )
        if table is None:
            return _insufficient(
                "rank_segments requires prepared customer or state feature rows.",
                inp,
            )
        return _rank_segments(inp, table, params)


def _rank_segments(
    inp: AnalystInput, table: TableRef, params: SegmentParams
) -> AnalystOutput:
    usable = [
        (index, column)
        for index, column in enumerate(table.columns)
        if column.role not in {"key", "time"}
        and not column.name.lower().endswith("_id")
        and column.name.lower() not in {"id", "customer_unique_id", "customer_id"}
    ]
    if not usable or len(table.rows) < 2:
        return _insufficient(
            "At least two customer/state rows and one non-identifier feature are required.",
            inp,
            table,
        )
    records: list[dict[str, object]] = []
    for row in table.rows:
        record: dict[str, object] = {}
        for index, column in usable:
            if index >= len(row) or row[index] is None:
                continue
            value = row[index]
            if isinstance(value, bool):
                record[column.name] = float(value)
            elif isinstance(value, (int, float)):
                numeric = float(value)
                if math.isfinite(numeric):
                    record[column.name] = numeric
            elif isinstance(value, str) and value.strip():
                record[column.name] = value.strip()
        if record:
            records.append(record)
    if len(records) < 2:
        return _insufficient(
            "At least two rows need usable feature values for segmentation.",
            inp,
            table,
        )
    cluster_count = min(params.n_clusters, len(records))
    if cluster_count < 2 or len(records) < cluster_count:
        return _insufficient("Too few usable rows to form at least two clusters.", inp, table)
    vectorizer = DictVectorizer(sparse=False, sort=True)
    matrix = vectorizer.fit_transform(records)
    if matrix.shape[1] == 0 or not np.isfinite(matrix).all():
        return _insufficient("The segmentation features are empty or non-finite.", inp, table)
    scaled = StandardScaler().fit_transform(matrix)
    if not np.isfinite(scaled).all():
        return _insufficient("The segmentation features cannot be normalized.", inp, table)
    try:
        model = KMeans(
            n_clusters=cluster_count,
            random_state=inp.seed if inp.seed is not None else 0,
            n_init=10,
            algorithm="lloyd",
        )
        labels = model.fit_predict(scaled)
    except ValueError as exc:
        return _insufficient(
            f"The prepared features cannot be segmented: {exc}",
            inp,
            table,
        )
    if len(set(int(value) for value in labels)) < 2:
        return _insufficient(
            "The supplied features do not contain distinct clusters.",
            inp,
            table,
        )
    names = tuple(str(name) for name in vectorizer.get_feature_names_out())
    clusters: list[SegmentCluster] = []
    for label in sorted(set(int(value) for value in labels)):
        indexes = np.flatnonzero(labels == label)
        profile = {
            names[index]: float(value)
            for index, value in enumerate(np.mean(matrix[indexes], axis=0))
            if math.isfinite(float(value))
        }
        score_column = next(
            (
                column.name
                for _, column in usable
                if column.name.lower() in {"ltv", "revenue", "gmv", "customer_value"}
            ),
            None,
        )
        score = (
            float(np.mean([float(records[index][score_column]) for index in indexes]))
            if score_column is not None
            and all(score_column in records[index] for index in indexes)
            else float(len(indexes))
        )
        clusters.append(
            SegmentCluster(
                cluster=label,
                size=int(len(indexes)),
                profile=profile,
                score=score,
            )
        )
    clusters.sort(key=lambda item: (-item.score, item.cluster))
    return AnalystOutput(
        module="segment",
        status="ok",
        result=SegmentResult(mode="rank_segments", clusters=tuple(clusters)),
        parameters={
            "mode": params.mode,
            "n_clusters": cluster_count,
            "feature_names": names,
            "seed": inp.seed if inp.seed is not None else 0,
        },
        assumptions=(
            "K-means uses only the supplied customer/state features; it does not infer a segment value not present in the input rows.",
            "Categorical features are one-hot encoded and numeric features are standardized before clustering.",
            "Cluster labels are arbitrary identifiers; clusters are ranked by measured LTV/revenue where available, otherwise by size.",
        ),
        sources=(table.query_id,),
    )


def _rank_actions(
    inp: AnalystInput, table: TableRef, params: SegmentParams
) -> AnalystOutput:
    columns = {column.name.lower(): index for index, column in enumerate(table.columns)}
    required = {
        "action_id",
        "title",
        "expected_impact",
        "cost",
        "evidence_grade",
        "assumptions",
        "trade_offs",
        "sensitivity",
        "monitor",
        "data_that_would_change_ranking",
    }
    if not required <= columns.keys():
        return _insufficient(
            "Action rows must include measured impact, cost, evidence grade, assumptions, trade-offs, sensitivity and monitoring fields.",
            inp,
            table,
        )
    candidates: list[dict[str, object]] = []
    for row in table.rows:
        try:
            grade = int(row[columns["evidence_grade"]])
            impact = _finite(row[columns["expected_impact"]])
            cost = _finite(row[columns["cost"]])
            if cost < 0 or grade < 0 or grade > 4:
                raise ValueError("cost or evidence grade is outside its valid range")
            kind = str(row[columns["kind"]]).strip().lower() if "kind" in columns else "intervention"
            if kind not in {"intervention", "information_gathering"}:
                raise ValueError("action kind is not supported")
            action_id = str(row[columns["action_id"]]).strip()
            title = str(row[columns["title"]]).strip()
            if not action_id or not title:
                raise ValueError("action id and title must not be blank")
            candidates.append(
                {
                    "id": action_id,
                    "title": title,
                    "impact": impact,
                    "cost": cost,
                    "grade": grade,
                    "kind": "information_gathering" if kind == "information_gathering" else "intervention",
                    "assumptions": _list_text(row[columns["assumptions"]]),
                    "trade_offs": _list_text(row[columns["trade_offs"]]),
                    "sensitivity": str(row[columns["sensitivity"]]),
                    "monitor": _list_text(row[columns["monitor"]]),
                    "changes": _list_text(row[columns["data_that_would_change_ranking"]]),
                }
            )
        except (IndexError, TypeError, ValueError):
            return _insufficient("An action row contains invalid measured values.", inp, table)
    if not candidates:
        return _insufficient("No measured candidate actions are available.", inp, table)
    low_evidence = bool(params.evidence_grades) and max(params.evidence_grades) < 2
    if low_evidence:
        information = [
            item for item in candidates if item["kind"] == "information_gathering"
        ]
        if not information:
            return _insufficient(
                "Evidence grades are below 2 and no measured information-gathering option was supplied.",
                inp,
                table,
            )
        ranked = sorted(information, key=lambda item: (float(item["cost"]), str(item["id"])))
        ranked = ranked[: params.max_options]
    else:
        ranked = sorted(
            candidates,
            key=lambda item: (
                -(float(item["impact"]) / max(float(item["cost"]), 1e-12)),
                -int(item["grade"]),
                str(item["id"]),
            ),
        )[: params.max_options]
    if len(ranked) < 2:
        return _insufficient(
            "At least two evidence-backed action options are required to rank alternatives.",
            inp,
            table,
        )
    if any(
        not item["assumptions"]
        or not item["trade_offs"]
        or not item["sensitivity"]
        or not item["monitor"]
        or not item["changes"]
        for item in ranked
    ):
        return _insufficient(
            "Each action needs assumptions, trade-offs, sensitivity, monitoring and ranking-change conditions.",
            inp,
            table,
        )
    options = tuple(
        ActionOption(
            action_id=str(item["id"]),
            title=str(item["title"]),
            rank=index,
            assumptions=tuple(item["assumptions"]),
            trade_offs=tuple(item["trade_offs"]),
            sensitivity=str(item["sensitivity"]),
            monitor=tuple(item["monitor"]),
            data_that_would_change_ranking=tuple(item["changes"]),
            kind=(
                "information_gathering"
                if item["kind"] == "information_gathering"
                else "intervention"
            ),
        )
        for index, item in enumerate(ranked, start=1)
    )
    allocation: tuple[tuple[str, float], ...] = ()
    if params.budget is not None:
        allocation = _allocate_budget(ranked, params.budget)
        if not allocation:
            return _insufficient("Budget allocation could not be optimized from the supplied costs.", inp, table)
    return AnalystOutput(
        module="segment",
        status="ok",
        result=SegmentResult(
            mode="rank_actions",
            actions=options,
            action_impacts=tuple(
                (str(item["id"]), float(item["impact"])) for item in ranked
            ),
            budget_allocation=allocation,
        ),
        parameters={
            "mode": params.mode,
            "max_options": params.max_options,
            "low_evidence_fallback": low_evidence,
            "budget": params.budget,
        },
        assumptions=(
            "Action impacts and costs are taken only from the prepared input table.",
            "This output ranks options for human review and does not execute actions.",
            "When evidence grades are below 2, only supplied information-gathering options are ranked.",
        ),
        sources=(table.query_id,),
    )


def _allocate_budget(
    actions: list[dict[str, object]], budget: float
) -> tuple[tuple[str, float], ...]:
    costs = np.asarray([float(item["cost"]) for item in actions], dtype=float)
    impacts = np.asarray([float(item["impact"]) for item in actions], dtype=float)
    try:
        result = linprog(
            c=-impacts,
            A_ub=np.asarray([costs]),
            b_ub=np.asarray([budget]),
            bounds=[(0.0, 1.0) for _ in actions],
            method="highs",
        )
    except (ValueError, RuntimeError):
        return ()
    if not result.success or result.x is None:
        return ()
    return tuple(
        (str(item["id"]), float(fraction))
        for item, fraction in zip(actions, result.x, strict=True)
    )


def _list_text(value: object) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split("|") if part.strip())
    return ()


def _finite(value: object) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("value must be finite")
    return result


def _insufficient(
    reason: str,
    inp: AnalystInput,
    table: TableRef | None = None,
) -> AnalystOutput:
    return AnalystOutput(
        module="segment",
        status="insufficient_evidence",
        reason=reason,
        sources=(table.query_id,) if table is not None else (),
    )


__all__ = ["SegmentAnalyst", "SegmentParams"]
