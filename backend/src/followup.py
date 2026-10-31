"""Deterministic follow-up rewriting (Track 4, scope.md §6, contracts.md §1-2).

Runs after the ingress guard and before intent routing. It reads the new
message and **only the last** :data:`REWRITE_WINDOW` **turns** of the session
(CTX-1b) and returns one of:

- ``cold`` - a self-contained question (or no usable context): routed as is.
- ``reset`` - "new topic" / "start over": the caller clears the session; any
  question after the reset phrase is routed cold.
- ``followup`` - a standalone ``effective_text`` plus a slot ``patch`` over the
  prior turn's ``ResolvedQuestion`` and the ``inherited_fields`` that came from
  it, so the answer can say what was carried (RQ-2).
- ``clarify`` - a follow-up that is ambiguous even with context (scope.md U2,
  U4, V10): one question with options whose patches are complete.

Everything here is regex plus the existing entity extractor: **no model is
called**, so rewriting behaves identically when Ollama is unavailable. Only
resolved *slots* (metric id, filters, window, breakdown, grain) are inherited;
a prior answer's figures are never read or copied (CTX-2, SAFE-3/SAFE-8).

The eight shapes of scope.md §6.1 map onto ``shape``: ``filter_swap``,
``window_shift``, ``compare_period``, ``escalate_diagnostic``,
``escalate_forecast``, ``escalate_impact``, ``drill_down``, ``grain_change``
and ``metric_swap``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Literal

import clarify
from contracts.models import Period
from contracts.v2 import (
    ClarificationRequest,
    ContextState,
    ConversationTurn,
    IntentName,
    ResolvedFilter,
    ResolvedQuestion,
    ScoredIntent,
)
from intent import DEFAULT_ANCHOR, Extraction, describe_period

RewriteKind = Literal["cold", "reset", "followup", "clarify"]

#: The slots a follow-up may inherit, in the order they are reported.
SLOTS = ("metric_id", "filters", "dimensions", "period", "comparison_period", "grain")

_RESET = re.compile(
    r"^\s*(?:let'?s\s+)?(?:new\s+topic|change\s+(?:of\s+)?(?:the\s+)?topic|start\s+(?:over|again|fresh)|"
    r"reset(?:\s+(?:the\s+)?(?:context|conversation|session|chat))?|clear\s+(?:the\s+)?(?:context|conversation|history)|"
    r"forget\s+(?:that|everything|it|the\s+(?:context|conversation)))\b[\s.,:;!\-]*(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
#: Anaphora that make a message lean on the previous turn even when it names its own metric ("same for GMV").
_MARKER = re.compile(
    r"^\s*(?:and|or|but|also|now|then|so)\b|\bwhat about\b|\bhow about\b|\bsame\b|\binstead\b|\bthat\b|\bthose\b|"
    r"\bthis\b|\bthese\b|\bit\b|\bthem\b|\btoo\b|\bas well\b",
    re.IGNORECASE,
)
_COMPARE = re.compile(r"\bcompare\w*\b|\bversus\b|\bvs\.?\b|\bagainst\b|\brelative to\b", re.IGNORECASE)
_LAST_YEAR = re.compile(r"\b(?:last|previous|prior|the)\s+year\b|\byear\s+(?:before|earlier)\b|\ba year (?:ago|earlier)\b",
                        re.IGNORECASE)
_PREVIOUS_PERIOD = re.compile(r"\b(?:previous|prior|last)\s+(?:month|period)\b|\bmonth before\b|\bperiod before\b", re.IGNORECASE)
_FORECAST = re.compile(r"\b(?:forecast|predict|project)\w*\b|\bwhat(?:'s| is| will)\b.*\bnext\b", re.IGNORECASE)
_BREAKDOWN = re.compile(r"\bbreak\w*\s+(?:it|that|this|them)?\s*down\b|\bsplit\s+(?:it|that|this)\b|\bdrill\s+down\b",
                        re.IGNORECASE)
#: A judgement about the prior figure ("why is that so low?") implies a norm to compare it with (scope.md 6.1 reference).
_JUDGEMENT = re.compile(r"\bso\s+(?:low|high|weak|strong|bad|good|small|big)\b|\b(?:lower|higher|weaker|stronger|worse|better)\s+than\s+(?:usual|normal|expected)\b",
                        re.IGNORECASE)
_RANK = re.compile(r"\b(top|bottom|highest|lowest|biggest|largest|best|worst)(?:\s+(\d{1,2}))?\b", re.IGNORECASE)
_PLURALS = {"category": "categories", "city": "cities"}
_MONTHS = {name: index for index, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"),
    start=1)}
_MONTH_ABBREVIATIONS = {name[:3]: index for name, index in _MONTHS.items()}
_BARE_MONTH = re.compile(
    r"\b(" + "|".join(sorted([*(name for name in _MONTHS if name != "may"), *(k for k in _MONTH_ABBREVIATIONS if k not in ("may", "mar"))],
                              key=len, reverse=True)) + r"|(?<=in )may|(?<=and )may|(?<=for )may)\b(?!\s+20\d\d)",
    re.IGNORECASE,
)
_DIMENSION_WORDS = {"product_category": "category", "customer_state": "state", "customer_city": "city",
                    "seller_state": "seller state", "payment_type": "payment type", "order_status": "order status"}
_GRAIN_WORDS = {"day": "daily", "week": "weekly", "month": "monthly", "quarter": "quarterly", "year": "yearly"}
#: Intents that inherit nothing from context; their questions carry their own inputs.
_COLD_INTENTS = frozenset({"discovery", "scenario", "prescriptive"})


@dataclass(frozen=True)
class Rewrite:
    kind: RewriteKind
    text: str
    shape: str | None = None
    effective_text: str | None = None
    patch: dict[str, Any] = field(default_factory=dict)
    inherited_fields: tuple[str, ...] = ()
    prior_turn_id: str | None = None
    prior_scope: str | None = None
    intent: IntentName | None = None
    clarification: ClarificationRequest | None = None

    @property
    def note(self) -> str | None:
        """The user-visible line saying what was carried (RQ-2)."""
        if self.kind != "followup" or not self.inherited_fields:
            return None
        carried = ", ".join(_FIELD_WORDS.get(name, name) for name in self.inherited_fields)
        return f"Carried from your previous question ({self.prior_scope}): {carried}. Interpreted as: \"{self.effective_text}\""


_FIELD_WORDS = {"metric_id": "metric", "filters": "filters", "dimensions": "breakdown", "period": "time window",
                "comparison_period": "comparison window", "grain": "grain"}


# --------------------------------------------------------------------------- #
# date helpers


def _add_months(start: date, months: int) -> date:
    index = start.year * 12 + start.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _months(period: Period) -> int:
    return (period.end.year - period.start.year) * 12 + period.end.month - period.start.month


def _shift(period: Period, months: int) -> Period:
    return Period(start=_add_months(period.start, months), end=_add_months(period.end, months))


def period_text(period: Period, *, anchor: str = DEFAULT_ANCHOR) -> str:
    """A phrase the extractor reads back to the same window ("July 2018", "2018")."""
    last = _add_months(period.end, -1)
    if _months(period) == 1:
        return f"{period.start:%B %Y}"
    anchor_end = _add_months(date(int(anchor[:4]), int(anchor[5:7]), 1), 1)
    if period.start.month == 1 and period.start.year == last.year and (last.month == 12 or period.end == anchor_end):
        return f"{period.start.year}"
    return f"{period.start:%B %Y} to {last:%B %Y}"


# --------------------------------------------------------------------------- #
# rendering a standalone question


def _metric_label(registry, metric_id: str | None) -> str:
    if metric_id is None:
        return "the metric"
    metric = registry.get(metric_id) if registry is not None else None
    name = metric.name if metric is not None else metric_id.replace("_", " ")
    return name if name.isupper() else name.lower()


def _scope_text(filters: tuple[ResolvedFilter, ...]) -> str:
    parts = []
    for item in filters:
        values = " or ".join(item.values)
        if item.dimension in ("customer_state", "customer_city"):
            parts.append(f" in {values}")
        else:
            parts.append(f" for {_DIMENSION_WORDS.get(item.dimension, item.dimension.replace('_', ' '))} {values}")
    return "".join(parts)


def render(*, intent: IntentName, metric: str, filters: tuple[ResolvedFilter, ...], dimensions: tuple[str, ...],
           period: Period | None, comparison: Period | None, grain: str | None, anchor: str = DEFAULT_ANCHOR,
           horizon: int = 3, rank: str | None = None) -> str:
    scope = _scope_text(filters)
    window = f" in {period_text(period, anchor=anchor)}" if period is not None else ""
    split = "".join(f" by {_DIMENSION_WORDS.get(name, name.replace('_', ' '))}" for name in dimensions)
    grain_word = f"{_GRAIN_WORDS[grain]} " if grain in _GRAIN_WORDS and grain != "month" else ""
    if intent == "diagnostic":
        versus = f" versus {period_text(comparison, anchor=anchor)}" if comparison is not None else ""
        return f"Why did {metric}{scope} change{window}{versus}{split}?"
    if intent == "forecast":
        return f"Forecast {grain_word}{metric}{scope}{split} for the next {horizon} months"
    if intent == "impact":
        return f"How much did the change in {metric}{scope}{window} cost us?"
    if rank and dimensions:
        word = _DIMENSION_WORDS.get(dimensions[0], dimensions[0].replace("_", " "))
        return f"What were the {rank} {_PLURALS.get(word, word + 's')} by {metric}{scope}{window}?"
    if comparison is not None and period is not None:
        return (f"Compare {grain_word}{metric}{scope} in {period_text(period, anchor=anchor)} with "
                f"{period_text(comparison, anchor=anchor)}{split}")
    return f"What was {grain_word}{metric}{scope}{window}{split}?"


# --------------------------------------------------------------------------- #


def detect_reset(message: str) -> tuple[bool, str]:
    """Whether the message resets the topic, and any question that follows the reset phrase."""
    match = _RESET.match(message)
    if match is None:
        return False, message
    return True, match.group("rest").strip()


def promote_bare_metric(extraction: Extraction) -> Extraction:
    """"revenue in SP in July 2018" names a governed metric and a scope but no verb: read it as a lookup.

    Without this a bare noun phrase - the most common way a first turn is
    typed - routes to an intent clarification. Only applies when a governed
    metric *and* a scope were found and nothing else (absent attributes,
    vague or special asks) was detected.
    """
    entities = extraction.entities
    if extraction.intents or entities.metric_id is None or extraction.absent or extraction.special:
        return extraction
    if entities.period is None and not entities.filters and not entities.dimensions:
        return extraction
    return replace(
        extraction,
        intents=(ScoredIntent(intent="descriptive", score=0.8, span=extraction.question[:200]),),
        rules_matched=(*extraction.rules_matched, "bare_metric_scope"),
        confidence=max(extraction.confidence, 0.8),
        reason=(extraction.reason + " " if extraction.reason else "")
        + "Read as a lookup because it names a governed metric and a scope.",
    )


def _prior(context: ContextState) -> tuple[ConversationTurn, ResolvedQuestion] | None:
    for turn in reversed(context.rewrite_turns()):  # CTX-1b: never beyond the last 3 turns
        if turn.resolved is not None and turn.status in ("answered", "insufficient_evidence"):
            return turn, turn.resolved
    return None


def _bare_month(message: str, prior: Period | None, anchor: date) -> Period | None:
    match = _BARE_MONTH.search(message)
    if match is None:
        return None
    word = match.group(1).lower()
    month = _MONTHS.get(word) or _MONTH_ABBREVIATIONS[word[:3]]
    year = (prior.start.year if prior is not None else anchor.year)
    start = date(year, month, 1)
    if start > anchor:
        start = date(year - 1, month, 1)
    return Period(start=start, end=_add_months(start, 1))


def _minimal_patch(extractor, text: str, slots: dict[str, Any]) -> dict[str, Any]:
    """Only the slots the extractor would not read back from ``text`` by itself.

    Patching a slot the text already carries would bypass the grounder's own
    checks (a sibling-metric swap, a dimension clarification), so the
    rewritten text does the work and the patch only pins what it cannot say.
    """
    entities = extractor.extract(text).entities
    patch: dict[str, Any] = {}
    if entities.metric_id != slots["metric_id"]:
        patch["metric_id"] = slots["metric_id"]
    if {(f.dimension, f.values) for f in entities.filters} != {(f.dimension, f.values) for f in slots["filters"]}:
        patch["filters"] = [item.model_dump(mode="json") for item in slots["filters"]]
    if set(entities.dimensions) != set(slots["dimensions"]):
        patch["dimensions"] = list(slots["dimensions"])
    if slots["period"] is not None and entities.period != slots["period"]:
        patch["period"] = slots["period"].model_dump(mode="json")
    if entities.comparison_period != slots["comparison_period"]:
        comparison = slots["comparison_period"]
        patch["comparison_period"] = comparison.model_dump(mode="json") if comparison is not None else None
    if slots["grain"] not in (None, "month") and entities.grain != slots["grain"]:
        patch["grain"] = slots["grain"]
    return patch


def rewrite(message: str, context: ContextState | None, *, extractor, registry=None, anchor: str = DEFAULT_ANCHOR) -> Rewrite:
    """Rewrite ``message`` against the session context. Falls back to ``cold`` whenever it is unsure."""

    is_reset, rest = detect_reset(message)
    if is_reset:
        return Rewrite(kind="reset", text=rest)
    if context is None:
        return Rewrite(kind="cold", text=message)
    found = _prior(context)
    if found is None:
        return Rewrite(kind="cold", text=message)
    turn, prior = found
    if turn.intent in _COLD_INTENTS or prior.metric_id is None:
        return Rewrite(kind="cold", text=message)

    extraction = extractor.extract(message)
    entities = extraction.entities
    names = [item.intent for item in extraction.intents]
    lowered = message.lower()
    marker = bool(_MARKER.search(message))
    special = set(extraction.special)
    if _BREAKDOWN.search(message):
        special.discard("vague")  # "break it down" is vague only without a prior turn (V10)
    if extraction.absent or {"vague", "risk", "spike_scan"} & special or _COLD_INTENTS & set(names):
        return Rewrite(kind="cold", text=message)
    rank_match = _RANK.search(message) if (prior.dimensions or entities.dimensions) else None
    has_slot = bool(rank_match or entities.filters or entities.period or entities.dimensions or entities.grain or entities.comparison_period
                    or _BARE_MONTH.search(message) or _LAST_YEAR.search(message) or _BREAKDOWN.search(message))
    escalation = bool({"diagnostic", "forecast", "impact"} & set(names)) or bool(_FORECAST.search(message))
    if entities.metric_id is not None and not marker:
        return Rewrite(kind="cold", text=message)  # self-contained: it names its own metric and leans on nothing
    if entities.metric_id is None and not (has_slot or escalation or marker):
        return Rewrite(kind="cold", text=message)

    anchor_date = date(int(anchor[:4]), int(anchor[5:7]), 1)
    inherited: list[str] = []
    shape: str | None = None
    prior_intent: IntentName = turn.intent if turn.intent in ("descriptive", "diagnostic", "forecast", "impact") else "descriptive"

    # metric
    metric_id = prior.metric_id
    if entities.metric_id is not None and entities.metric_id != prior.metric_id:
        metric_id, shape = entities.metric_id, "metric_swap"
    else:
        inherited.append("metric_id")

    # filters: a new value on the same dimension replaces the old one
    filters = list(prior.filters)
    if entities.filters:
        swapped = {item.dimension for item in entities.filters}
        kept = [item for item in filters if item.dimension not in swapped]
        filters = [*kept, *entities.filters]
        shape = shape or "filter_swap"
        if kept:
            inherited.append("filters")
    elif filters:
        inherited.append("filters")

    # breakdown
    dimensions = list(prior.dimensions)
    if entities.dimensions:
        dimensions = list(dict.fromkeys([*dimensions, *entities.dimensions]))
        shape = shape or "drill_down"
        # Breaking down by a dimension replaces a filter on that same dimension ("SP" -> "by state").
        filters = [item for item in filters if item.dimension not in entities.dimensions]
        if "filters" in inherited and not any(item in prior.filters for item in filters):
            inherited.remove("filters")
        if prior.dimensions:
            inherited.append("dimensions")
    elif dimensions:
        inherited.append("dimensions")

    # windows
    period, comparison = prior.period, prior.comparison_period
    new_period = None
    if not _LAST_YEAR.search(message):
        new_period = entities.period or _bare_month(message, prior.period, anchor_date)
    compare = bool(_COMPARE.search(message))
    if compare and prior.period is not None:
        if _LAST_YEAR.search(message):
            comparison = _shift(prior.period, -12)
        elif _PREVIOUS_PERIOD.search(message):
            comparison = _shift(prior.period, -_months(prior.period))
        elif entities.comparison_period is not None:
            period, comparison = entities.period or period, entities.comparison_period
        elif new_period is not None:
            comparison = new_period
        else:
            comparison = _shift(prior.period, -12)
        shape = shape or "compare_period"
        if period == prior.period:
            inherited.append("period")
    elif _LAST_YEAR.search(message) and prior.period is not None:
        period, comparison = _shift(prior.period, -12), None
        shape = shape or "window_shift"
    elif new_period is not None:
        period = new_period
        comparison = entities.comparison_period
        shape = shape or "window_shift"
    else:
        if period is not None:
            inherited.append("period")
        if comparison is not None:
            inherited.append("comparison_period")

    # grain
    grain = prior.grain
    if entities.grain is not None and entities.grain != prior.grain:
        grain = entities.grain
        shape = shape or "grain_change"
    elif grain is not None:
        inherited.append("grain")

    # intent
    intent: IntentName = prior_intent
    if "forecast" in names or _FORECAST.search(message):
        intent, shape = "forecast", "escalate_forecast"
    elif "impact" in names:
        intent, shape = "impact", "escalate_impact"
    elif "diagnostic" in names:
        intent, shape = "diagnostic", "escalate_diagnostic"
    elif compare:
        intent = "descriptive"
    elif shape == "drill_down" and prior_intent == "forecast":
        intent = "descriptive"

    metric_label = _metric_label(registry, metric_id)
    slots: dict[str, Any] = {"metric_id": metric_id, "filters": tuple(filters), "dimensions": tuple(dimensions),
                             "period": period, "comparison_period": comparison, "grain": grain}
    scope = turn.scope_summary.rsplit(" · ", 2)[0] if turn.scope_summary else describe_period(prior.period)
    common = dict(prior_turn_id=turn.turn_id, prior_scope=scope)

    def _option(text: str, option_slots: dict[str, Any]) -> dict[str, Any]:
        return {"effective_text": text, **_minimal_patch(extractor, text, option_slots)}

    if intent == "forecast":
        # A forecast projects forward from the last complete period: the window is not inherited.
        slots["period"], slots["comparison_period"] = None, None
        inherited = [name for name in inherited if name not in ("period", "comparison_period")]
        if dimensions and not entities.dimensions:
            # U4: a breakdown would be one forecast per value; ask, default to the aggregate (F10).
            total = {**slots, "dimensions": ()}
            split_word = ", ".join(_DIMENSION_WORDS.get(name, name) for name in dimensions)
            total_text = render(intent="forecast", metric=metric_label, filters=slots["filters"], dimensions=(), period=None,
                                comparison=None, grain=grain, anchor=anchor)
            split_text = render(intent="forecast", metric=metric_label, filters=slots["filters"], dimensions=tuple(dimensions),
                                period=None, comparison=None, grain=grain, anchor=anchor)
            request = clarify.build(
                slot="dimension",
                understood=f"You want a forecast of {metric_label} from your previous question ({scope}), which was split by {split_word}.",
                needs=f"Forecast the total, or one series per {split_word}?",
                question=f"Should I forecast total {metric_label}, or each {split_word} separately",
                choices=[clarify.Choice(f"Forecast total {metric_label}", _option(total_text, total)),
                         clarify.Choice(f"Forecast each {split_word} (largest series only)", _option(split_text, slots))],
                rationale="One aggregate series has the most history and the tightest interval.",
            )
            return Rewrite(kind="clarify", text=message, shape="escalate_forecast", clarification=request, intent="forecast", **common)

    if intent == "diagnostic" and shape == "escalate_diagnostic" and not has_slot and entities.metric_id is None \
            and prior_intent == "descriptive" and period is not None and comparison is None and _months(period) > 1:
        # U2: "why?" after a multi-month total has no change to explain yet.
        prior_year = _shift(period, -12)
        if _JUDGEMENT.search(message):
            # A reference with a judgement ("so low") is answered against the like-for-like window a year earlier,
            # and the comparison is part of the restated question (V2-ANS-1, 6.3 rule 2).
            slots["comparison_period"] = prior_year
            effective = render(intent="diagnostic", metric=metric_label, filters=slots["filters"], dimensions=slots["dimensions"],
                               period=period, comparison=prior_year, grain=grain, anchor=anchor)
            ordered = tuple(name for name in SLOTS if name in inherited and _present(slots[name]))
            return Rewrite(kind="followup", text=effective, shape="reference", effective_text=effective,
                           patch=_minimal_patch(extractor, effective, slots), inherited_fields=ordered, intent="diagnostic", **common)
        last_month = Period(start=_add_months(period.end, -1), end=period.end)
        year_slots = {**slots, "comparison_period": prior_year}
        month_slots = {**slots, "period": last_month}
        year_text = render(intent="diagnostic", metric=metric_label, filters=slots["filters"], dimensions=slots["dimensions"],
                           period=period, comparison=prior_year, grain=grain, anchor=anchor)
        month_text = render(intent="diagnostic", metric=metric_label, filters=slots["filters"], dimensions=slots["dimensions"],
                            period=last_month, comparison=None, grain=grain, anchor=anchor)
        request = clarify.build(
            slot="comparison_period",
            understood=f"You asked why, about {metric_label} over {describe_period(period)} ({scope}). That was a single total, so there is no change to explain yet.",
            needs="Why compared to what?",
            question=f"Why compared to what: {period_text(prior_year, anchor=anchor)}, or the latest month of {period_text(period, anchor=anchor)}",
            choices=[clarify.Choice(f"Versus {period_text(prior_year, anchor=anchor)}", _option(year_text, year_slots),
                                    f"{describe_period(period)} against {describe_period(prior_year)}"),
                     clarify.Choice(f"The change in {period_text(last_month, anchor=anchor)}", _option(month_text, month_slots),
                                    f"{describe_period(last_month)} against the month before")],
            rationale="The same window a year earlier is the like-for-like comparison and removes seasonality.",
        )
        return Rewrite(kind="clarify", text=message, shape="escalate_diagnostic", clarification=request, intent="diagnostic", **common)

    if _BREAKDOWN.search(message) and not entities.dimensions:
        # V10 with context: "break it down" names no dimension.
        metric = registry.get(metric_id) if registry is not None else None
        allowed = [d.name for d in metric.allowed_dimensions if d.name not in ("month", "year")] if metric is not None else []
        allowed = [name for name in ("product_category", "customer_state", "payment_type", "order_status", "customer_city", "seller_state")
                   if name in allowed] or allowed
        if len(allowed) >= 2:
            choices = []
            for name in allowed[:4]:
                option_slots = {**slots, "dimensions": tuple(dict.fromkeys([*dimensions, name]))}
                text = render(intent="descriptive", metric=metric_label, filters=slots["filters"], dimensions=option_slots["dimensions"],
                              period=slots["period"], comparison=slots["comparison_period"], grain=grain, anchor=anchor)
                choices.append(clarify.Choice(f"By {_DIMENSION_WORDS.get(name, name)}", _option(text, option_slots)))
            request = clarify.build(slot="dimension", understood=f"You want {metric_label} from your previous question ({scope}) broken down.",
                                    needs="Break it down by what?", question=f"How should I break down {metric_label}",
                                    choices=choices, rationale=f"{allowed[0]} is the first governed breakdown of this metric.")
            return Rewrite(kind="clarify", text=message, shape="drill_down", clarification=request, intent="descriptive", **common)

    rank = None
    if rank_match is not None and intent == "descriptive":
        # U7 "just the top 5": the same breakdown, ranked.
        rank = " ".join(part for part in (rank_match.group(1).lower(), rank_match.group(2)) if part)
        shape = shape or "rank"
    ordered = tuple(name for name in SLOTS if name in inherited and _present(slots[name]))
    if not ordered:
        return Rewrite(kind="cold", text=message)
    effective = render(intent=intent, metric=metric_label, filters=slots["filters"], dimensions=slots["dimensions"],
                       period=slots["period"], comparison=slots["comparison_period"], grain=slots["grain"], anchor=anchor, rank=rank)
    return Rewrite(kind="followup", text=effective, shape=shape or "restate", effective_text=effective,
                   patch=_minimal_patch(extractor, effective, slots),
                   inherited_fields=ordered, intent=intent, **common)


def _present(value: Any) -> bool:
    return value is not None and value != () and value != []


def apply_to_resolved(resolved: ResolvedQuestion, rewrite_result: Rewrite, *, raw_text: str) -> ResolvedQuestion:
    """Mark a grounded question as context-resolved, with what was inherited shown (RQ-2)."""
    note = rewrite_result.note
    assumptions = (*resolved.assumptions, *([note] if note else ()))
    data = resolved.model_dump()
    data.update(text=raw_text, effective_text=rewrite_result.effective_text, inherited_fields=rewrite_result.inherited_fields,
                resolution_source="context", assumptions=tuple(dict.fromkeys(assumptions)))
    return ResolvedQuestion.model_validate(data)


__all__ = ["SLOTS", "Rewrite", "apply_to_resolved", "detect_reset", "period_text", "promote_bare_metric", "render", "rewrite"]
