"""Grounding check: every entity must map to a real metric, table, column or
value before anything is planned (RQ-1, RQ-3, RQ-6, IR-7, SAFE-1).

Input is the extractor's reading; output is either a ``ResolvedQuestion``
plus the final ``IntentResult``, or a ``ClarificationRequest`` (status
``clarify``). Unknown terms, vague asks and unsupported intents always go to
a clarification with clickable options - never to a refusal or a dead end.
Analytic questions that are clear except for a safe default (a missing window
or an unnamed metric on a "why"/"what did it cost" question) proceed on the
default, recorded in ``assumptions`` in plain words.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

from contracts.models import Period
from contracts.v2 import (
    ClarificationRequest,
    Entities,
    IntentResult,
    ResolvedFilter,
    ResolvedQuestion,
    ScoredIntent,
)

import clarify
from intent import DEFAULT_ANCHOR, HISTORY_START, Extraction, describe_period, prd_label

#: Dimensions a governed dataset (not a registry metric) may be split by.
DATASET_DIMENSIONS = {"carrier", "channel", "segment", "customer_state", "product_category", "payment_type"}
NEEDS_METRIC = {"descriptive", "diagnostic", "impact", "forecast"}
#: Order-grain metrics whose item-grain sibling carries the product breakdowns.
SIBLING_METRICS = {"revenue": "gmv", "order_count": "item_count"}


@dataclass(frozen=True)
class Grounded:
    intent: IntentResult
    resolved: ResolvedQuestion | None
    clarification: ClarificationRequest | None
    special: tuple[str, ...]
    assumptions: tuple[str, ...]

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None


def _month(text: str) -> date:
    year, month = (int(part) for part in text[:7].split("-"))
    return date(year, month, 1)


def _add_months(start: date, months: int) -> date:
    index = start.year * 12 + start.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


class Grounder:
    def __init__(self, registry, *, anchor: str = DEFAULT_ANCHOR, history_start: str = HISTORY_START,
                 available_tables: frozenset[str] | None = None) -> None:
        self.registry = registry
        self.anchor = anchor
        self.anchor_date = _month(anchor)
        self.history_start = _month(history_start)
        self.available_tables = available_tables

    # ------------------------------------------------------------------ #

    def ground(self, extraction: Extraction, *, patch: Mapping[str, Any] | None = None,
               round_number: int = 1, of_run_id: str | None = None, force_defaults: bool = False) -> Grounded:
        entities = extraction.entities
        special = set(extraction.special)
        assumptions: list[str] = list(extraction.time.assumptions)
        names = [item.intent for item in extraction.intents]
        patch = dict(patch or {})
        if patch:
            entities = _apply_patch(entities, patch)
            if "metric_id" in patch:
                special.discard("vague")
            if "period" in patch:
                special.discard("vague")

        def ask(request: ClarificationRequest) -> Grounded:
            if force_defaults or round_number > clarify.MAX_ROUNDS:
                option_patch, note = clarify.patch_for(request, None)
                if "effective_text" in option_patch:
                    # A rewrite cannot be applied here; the caller re-runs on it.
                    return Grounded(self._clarify_intent(extraction, request), None, request, tuple(special), tuple(assumptions))
                regrounded = self.ground(extraction, patch={**patch, **option_patch}, round_number=round_number,
                                         of_run_id=of_run_id, force_defaults=True)
                return replace(regrounded, assumptions=(*regrounded.assumptions, note),
                               resolved=_with_assumption(regrounded.resolved, note))
            return Grounded(self._clarify_intent(extraction, request), None, request, tuple(special), tuple(assumptions))

        build = lambda **kwargs: clarify.build(round_number=round_number, of_run_id=of_run_id, **kwargs)  # noqa: E731

        # 1. Attributes that exist in neither layer are named, with the nearest answerable questions.
        if extraction.absent:
            missing = ", ".join(extraction.absent)
            return ask(build(
                slot="intent",
                understood=f"You asked about {missing}, which is not held in the real snapshot or the synthetic layer.",
                needs="Which answerable question is closest to what you need?",
                question=f"I don't hold {missing}. Would one of these help instead",
                choices=clarify.question_choices([
                    ("What customer data do you have?", "What data do you have?"),
                    ("Customers by state", "How many unique customers ordered by state in 2018?"),
                    ("Customer segments (synthetic)", "Which customer segment should we target?"),
                ]),
                rationale="Listing the data held is the safest next step when an attribute does not exist.",
            ))

        # 2. Risk/churn: there is no risk model, so offer the nearest answerable analyses (no dead end).
        if "risk" in special and not ({"forecast", "diagnostic", "impact", "scenario"} & set(names)):
            return ask(build(
                slot="intent",
                understood="You asked about customer risk or churn. No customer-level risk model exists, so no risk score is invented.",
                needs="Which of the available analyses should I run?",
                question="Which of these would answer your risk question best",
                choices=clarify.question_choices([
                    ("Customers in the at-risk segment (synthetic)", "Which customer segment should we target?"),
                    ("Cancellation rate trend", "What was the cancellation rate by month in 2018?"),
                    ("Why cancellations changed", "Why did cancellations rise in 2018 versus 2017?"),
                    ("Forecast unique customers", "How many customers will we have next quarter?"),
                ]),
                rationale="The at-risk segment is the closest measured signal to churn in this data.",
            ))

        # 3. Nothing recognisable: suggest answerable questions instead of refusing.
        if not names and "vague" not in special:
            metric = entities.metric_id or "revenue"
            label = metric.replace("_", " ")
            return ask(build(
                slot="intent",
                understood="I could not tell what kind of analysis you want.",
                needs="Which kind of answer do you need?",
                question="Which of these is closest to your question",
                choices=clarify.question_choices([
                    (f"How {label} is trending", f"How does {label} trend look today?"),
                    (f"Why {label} changed recently", f"Why did {label} change in {self.anchor_date:%B %Y}?"),
                    (f"Forecast {label}", f"Forecast {label} for the next 3 months"),
                    ("What data is available", "What data do you have?"),
                ]),
                rationale="A trend over the last 12 complete months is the safest general answer.",
            ))

        # 4. Ambiguous terms: gross vs net revenue.
        if any(mention.metric_id == "gross_vs_net" for mention in extraction.metric_mentions) and "metric_id" not in patch:
            return ask(build(
                slot="metric",
                understood="You asked about gross revenue. This warehouse has two governed measures that could mean that.",
                needs="Gross (GMV) or net (payments received)?",
                question="Which revenue do you mean",
                choices=clarify.GROSS_NET_CHOICES,
                default_index=1,
                rationale="Revenue (payments received) is the governed headline revenue metric.",
            ))

        # 5. Vague asks: resolve what can be resolved, ask about exactly one thing.
        if "vague" in special and names[:1] != ["discovery"]:
            if entities.metric_id is None:
                understood = "You asked for a general view of the business." if not entities.filters else (
                    f"You asked about {', '.join(value for item in entities.filters for value in item.values)}.")
                if "anything unusual" in extraction.question.lower() or "unusual" in extraction.question.lower():
                    choices = [clarify.Choice("Scan every metric for spikes and dips", {"effective_text": "What are the spikes across all months?"},
                                              "precomputed, FDR-corrected"),
                               *clarify.METRIC_CHOICES[:3]]
                    return ask(build(slot="metric", understood="You asked whether anything is unusual.",
                                     needs="Which metric should I scan?", question="Which metric should I check for unusual movements",
                                     choices=choices, rationale="Scanning every metric with a false-discovery correction misses nothing."))
                return ask(build(slot="metric", understood=understood, needs="Which metric should the answer use?",
                                 question="Which metric should I use", choices=clarify.METRIC_CHOICES,
                                 rationale="Revenue over the last 12 complete months is the standard business summary."))
            if entities.period is None:
                metric = self.registry.get(entities.metric_id)
                label = metric.name if metric is not None else entities.metric_id
                choices = clarify.recent_choices(self.anchor_date) if "recent" in extraction.question.lower() else clarify.period_choices(self.anchor_date, self.history_start)
                return ask(build(slot="period", understood=f"You are asking for a summary of {label} (metric_id: {entities.metric_id}).",
                                 needs="Which time window should the summary cover?",
                                 question=f"Which time window should I summarise {label.lower()} over",
                                 choices=choices,
                                 rationale=("Twelve complete months covers a full seasonal cycle and excludes the incomplete "
                                            f"months after {self.anchor}.")))
            special.discard("vague")
            if not names:
                names = ["descriptive"]

        # 6. Metric grounding.
        dataset_question = bool({"spike_scan", "delivery", "segments", "inventory"} & special) or names[:1] == ["discovery"] \
            or "scenario" in names
        metric = self.registry.get(entities.metric_id) if entities.metric_id else None
        if entities.metric_id and metric is None:
            entities = replace_entities(entities, metric_id=None)
        if metric is None and not dataset_question and set(names) & NEEDS_METRIC:
            if {"diagnostic", "impact"} & set(names) and (entities.period is not None or "prescriptive" in names):
                entities = replace_entities(entities, metric_id="revenue")
                metric = self.registry.get("revenue")
                assumptions.append("No metric was named, so revenue (payments received) was used.")
            else:
                return ask(build(slot="metric", understood=f"You asked a {names[0]} question but did not name a metric I hold.",
                                 needs="Which metric do you mean?", question="Which metric should I use",
                                 choices=clarify.METRIC_CHOICES, rationale="Revenue is the governed headline metric."))

        # 7. Dimension grounding (RQ-1).
        if metric is not None:
            allowed = {dimension.name for dimension in metric.allowed_dimensions}
            bad = [name for name in entities.dimensions if name not in allowed and name not in {"month", "year"}]
            sibling = SIBLING_METRICS.get(metric.metric_id)
            if bad and sibling is not None and "metric_id" not in patch:
                alternative = self.registry.get(sibling)
                if alternative is not None and all(name in {d.name for d in alternative.allowed_dimensions} for name in bad):
                    assumptions.append(f"{metric.name} is recorded per order and cannot be split by {', '.join(bad)}, so "
                                       f"{alternative.name} ({sibling}), which is recorded per item, was used for this breakdown.")
                    metric = alternative
                    entities = replace_entities(entities, metric_id=sibling)
                    allowed = {dimension.name for dimension in metric.allowed_dimensions}
                    bad = []
            if bad and "dimensions" not in patch:
                options = [name for name in allowed if name not in {"month", "year"}][:4]
                if len(options) >= 2:
                    return ask(build(slot="dimension",
                                     understood=f"{metric.name} cannot be split by {', '.join(bad)} in the governed registry.",
                                     needs="Which allowed breakdown should I use?", question=f"How should I break down {metric.name.lower()}",
                                     choices=[clarify.Choice(name.replace("_", " "), {"dimensions": [name]}) for name in options],
                                     rationale=f"{options[0]} is the first governed breakdown of {metric.name}."))
                entities = replace_entities(entities, dimensions=tuple(name for name in entities.dimensions if name in allowed))
            bad_filters = [item for item in entities.filters if item.dimension not in allowed and item.dimension not in DATASET_DIMENSIONS]
            if bad_filters:
                entities = replace_entities(entities, filters=tuple(item for item in entities.filters if item not in bad_filters))
                assumptions.append(f"{', '.join(item.source_phrase for item in bad_filters)} is not a governed filter for {metric.name} and was ignored.")
        elif not dataset_question:
            entities = replace_entities(entities, dimensions=tuple(name for name in entities.dimensions if name in DATASET_DIMENSIONS))

        # 8. Filter values must be linked with confidence (RQ-6).
        weak = [item for item in entities.filters if item.link_confidence < 0.7]
        if weak:
            item = weak[0]
            return ask(build(slot="filter_value", understood=f"'{item.source_phrase}' could match more than one value.",
                             needs="Which value did you mean?", question=f"What does '{item.source_phrase}' refer to",
                             choices=[clarify.Choice(value, {"filters": [{"dimension": item.dimension, "operator": "=", "values": [value],
                                                                          "source_phrase": item.source_phrase, "link_confidence": 1.0}]})
                                      for value in item.values[:4]] or [clarify.Choice("ignore it", {"filters": []}), clarify.Choice("all", {"filters": []})],
                             rationale="The first listed value is the closest literal match."))

        # 9. Periods: future windows on history intents, defaults recorded.
        period = entities.period
        end_cap = _add_months(self.anchor_date, 1)
        if period is not None and period.start >= end_cap and "forecast" not in names:
            return ask(build(slot="period", understood=f"The data ends at {self.anchor}, the last complete month; {describe_period(period)} has no rows yet.",
                             needs="Which window should I use?", question="Which window should I use instead",
                             choices=[*clarify.period_choices(self.anchor_date, self.history_start)[:2],
                                      clarify.Choice(f"Forecast {describe_period(period)} instead", {"effective_text": f"Forecast {(entities.metric_id or 'revenue').replace('_', ' ')} for the next 3 months"})],
                             rationale="The last 12 complete months are the most recent measured window."))
        if period is None and names[:1] in (["descriptive"], ["diagnostic"], ["impact"]) and not {"spike_scan", "delivery"} & special:
            if names[0] == "descriptive":
                period = Period(start=_add_months(self.anchor_date, -11), end=end_cap)
                assumptions.append(f"No window was given, so the last 12 complete months ({describe_period(period)}) were used.")
            else:
                period = Period(start=self.anchor_date, end=end_cap)
                assumptions.append(f"No window was given, so the last complete month ({self.anchor}) was analysed against the month before.")
            entities = replace_entities(entities, period=period)
        if entities.horizon is not None and entities.horizon.periods > 6:
            assumptions.append(
                f"{entities.horizon.periods} periods were asked for; the forecast reports the defensible horizon for the history available and names the limit."
            )
        if "forecast" in names and not any("horizon" in item.lower() for item in assumptions):
            from engines.horizon import extract_horizon

            if extract_horizon(extraction.question, anchor=self.anchor).horizon is None and entities.horizon is not None:
                assumptions.append(f"No horizon was stated, so {entities.horizon.periods} months was used, anchored on {self.anchor}.")
        if "spike_scan" in special:
            assumptions.append("Spikes are read from the precomputed anomaly scan over every governed metric, FDR-corrected.")

        intents = tuple(ScoredIntent(intent=name, score=_score(extraction, name), span=_span(extraction, name)) for name in dict.fromkeys(names))
        confidence = max(0.7, min(0.99, extraction.confidence if extraction.confidence else 0.75))
        if assumptions and confidence > 0.9:
            confidence = 0.9
        intent_result = IntentResult(
            intents=intents,
            entities=entities,
            signals=extraction.signals,
            confidence=round(confidence, 4),
            reason=extraction.reason,
            clarification=None,
            prd_intent_label=prd_label(names, entities.comparison_period is not None),  # type: ignore[arg-type]
        )
        resolved = ResolvedQuestion(
            text=extraction.question,
            effective_text=patch.get("effective_text"),
            metric_id=entities.metric_id,
            ungoverned_metric_term=None if entities.metric_id else (extraction.ungoverned_term or ("all metrics" if "spike_scan" in special else "catalog" if names[:1] == ["discovery"] else "dataset")),
            dimensions=entities.dimensions,
            filters=entities.filters,
            period=entities.period,
            comparison_period=entities.comparison_period,
            grain=entities.grain or ("month" if entities.period is not None else None),
            assumptions=tuple(dict.fromkeys(assumptions)),
            resolution_source="deterministic" if not (extraction.signals.model and extraction.signals.model.proposed) else "model_proposed_code_validated",
            confidence=round(confidence, 4),
        )
        return Grounded(intent_result, resolved, None, tuple(sorted(special)), tuple(dict.fromkeys(assumptions)))

    def _clarify_intent(self, extraction: Extraction, request: ClarificationRequest) -> IntentResult:
        return IntentResult(
            intents=(ScoredIntent(intent="clarify", score=0.5, span=extraction.question[:200]),),
            entities=replace_entities(extraction.entities, horizon=None, scenario_params=()),
            signals=extraction.signals,
            confidence=0.5,
            reason=f"Asked one question ({request.slot}) before answering: {request.what_needs_clarification}",
            clarification=request,
            prd_intent_label="Descriptive",
        )


def replace_entities(entities: Entities, **changes: Any) -> Entities:
    return entities.model_copy(update=changes)


def _apply_patch(entities: Entities, patch: Mapping[str, Any]) -> Entities:
    changes: dict[str, Any] = {}
    if "metric_id" in patch:
        changes["metric_id"] = patch["metric_id"]
    if "period" in patch and patch["period"] is not None:
        value = patch["period"]
        changes["period"] = value if isinstance(value, Period) else Period.model_validate(value)
    if "grain" in patch:
        changes["grain"] = patch["grain"]
    if "dimensions" in patch:
        changes["dimensions"] = tuple(patch["dimensions"])
    if "filters" in patch:
        changes["filters"] = tuple(item if isinstance(item, ResolvedFilter) else ResolvedFilter.model_validate(item) for item in patch["filters"])
    return replace_entities(entities, **changes)


def _with_assumption(resolved: ResolvedQuestion | None, note: str) -> ResolvedQuestion | None:
    if resolved is None:
        return None
    return resolved.model_copy(update={"assumptions": tuple(dict.fromkeys((*resolved.assumptions, note)))})


def _score(extraction: Extraction, name: str) -> float:
    return next((item.score for item in extraction.intents if item.intent == name), 0.75)


def _span(extraction: Extraction, name: str) -> str | None:
    return next((item.span for item in extraction.intents if item.intent == name), None)


__all__ = ["DATASET_DIMENSIONS", "Grounded", "Grounder", "replace_entities"]
