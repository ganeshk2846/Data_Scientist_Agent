"""Metric intent and slot resolution (MET-2, MET-4).

Simple governed questions are resolved deterministically and never touch a
model. Ambiguous or complex phrasing can be delegated to a local reasoning
model; the returned slots are validated against the registry before they can
reach the SQL compiler.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date
from typing import Any

from contracts.models import (
    LinkedValue,
    MetricDefinition,
    MetricFilter,
    MetricResolution,
    ModelUsage,
    Period,
    ResolvedDimension,
)
from models.client import ModelResponseError, ModelUnavailableError

from .registry import MetricRegistry

_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_PATTERN = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\s+(20\d{2})\b",
    re.IGNORECASE,
)
_QUARTER_PATTERN = re.compile(
    r"\bq([1-4])(?:\s*(?:of\s*)?(20\d{2}))?\b",
    re.IGNORECASE,
)
_QUARTER_WORD_PATTERN = re.compile(
    r"\b(first|second|third|fourth)\s+quarter(?:\s+(?:of\s+)?(20\d{2}))?\b",
    re.IGNORECASE,
)
_TIME_GRAINS: tuple[tuple[str, str], ...] = (
    ("daily", "day"),
    ("by day", "day"),
    ("weekly", "week"),
    ("by week", "week"),
    ("monthly", "month"),
    ("by month", "month"),
    ("quarterly", "quarter"),
    ("by quarter", "quarter"),
    ("yearly", "year"),
    ("annual", "year"),
    ("by year", "year"),
)
_STATUS_WORDS = {
    "delivered": "delivered",
    "completed": "delivered",
    "shipped": "shipped",
    "canceled": "canceled",
    "cancelled": "canceled",
    "processing": "processing",
    "invoiced": "invoiced",
    "approved": "approved",
    "unavailable": "unavailable",
}
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "each",
        "for",
        "from",
        "get",
        "give",
        "go",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "many",
        "me",
        "most",
        "much",
        "my",
        "number",
        "of",
        "on",
        "or",
        "our",
        "per",
        "please",
        "record",
        "records",
        "row",
        "rows",
        "show",
        "sum",
        "table",
        "tables",
        "tell",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "to",
        "top",
        "total",
        "up",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "placed",
        "purchased",
        "bought",
        "sold",
        "made",
        "generated",
        "received",
        "recorded",
    ]
)
_BRAZIL_STATES = frozenset(
    [
        "ac",
        "al",
        "am",
        "ap",
        "ba",
        "ce",
        "df",
        "es",
        "go",
        "ma",
        "mg",
        "ms",
        "mt",
        "pa",
        "pb",
        "pe",
        "pi",
        "pr",
        "rj",
        "rn",
        "ro",
        "rr",
        "rs",
        "sc",
        "se",
        "sp",
        "to",
    ]
)
_STATE_FILTER_PATTERN = re.compile(
    r"\b(?:in|state(?:\s+of)?|from|for|region)\s+([a-z]{2})\b",
    re.IGNORECASE,
)
_COMPARATIVE_WORDS = frozenset(
    [
        "difference",
        "differences",
        "different",
        "differ",
        "compare",
        "compared",
        "comparing",
        "comparison",
        "versus",
        "vs",
        "growth",
        "change",
        "changed",
        "changing",
        "net",
        "delta",
        "increase",
        "decrease",
        "decline",
        "drop",
        "fell",
        "rose",
    ]
)


def _normalize(text: str) -> str:
    lowered = text.lower().replace("&", " and ")
    lowered = re.sub(r"[_\-/]+", " ", lowered)
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(lowered.split())


def _contains(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _remove_phrase(text: str, phrase: str) -> str:
    if not phrase:
        return text
    return re.sub(
        rf"(?<!\w){re.escape(phrase)}(?!\w)",
        " ",
        text,
    )


def _allowed_dimension(
    metric: MetricDefinition, requested: str
) -> ResolvedDimension | None:
    normalized = _normalize(requested)
    for dimension in metric.allowed_dimensions:
        phrases = (dimension.name, *dimension.synonyms)
        if any(_normalize(phrase) == normalized for phrase in phrases):
            return ResolvedDimension(
                requested=dimension.name,
                allowed=True,
                column=dimension.column,
                table=dimension.table,
            )
    return None


def _detect_time_grain(question: str) -> str | None:
    for phrase, grain in _TIME_GRAINS:
        if _contains(question, phrase):
            return grain
    return None


def _add_months(start: date, months: int) -> date:
    index = start.year * 12 + (start.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _detect_period(question: str) -> Period | None:
    month = _MONTH_PATTERN.search(question)
    if month is not None:
        start = date(int(month.group(2)), _MONTHS[month.group(1).lower()], 1)
        return Period(start=start, end=_add_months(start, 1))

    quarter = _QUARTER_PATTERN.search(question)
    if quarter is not None:
        year = int(quarter.group(2)) if quarter.group(2) else date.today().year
        start = date(year, (int(quarter.group(1)) - 1) * 3 + 1, 1)
        return Period(start=start, end=_add_months(start, 3))

    quarter_word = _QUARTER_WORD_PATTERN.search(question)
    if quarter_word is not None:
        number = ("first", "second", "third", "fourth").index(
            quarter_word.group(1).lower()
        ) + 1
        year = (
            int(quarter_word.group(2)) if quarter_word.group(2) else date.today().year
        )
        start = date(year, (number - 1) * 3 + 1, 1)
        return Period(start=start, end=_add_months(start, 3))

    match = _YEAR_PATTERN.search(question)
    if match is None:
        return None
    year = int(match.group(1))
    return Period(start=date(year, 1, 1), end=date(year + 1, 1, 1))


def _has_orders(metric: MetricDefinition) -> bool:
    return metric.base_table == "orders" or any(
        "orders" in edge.edge_id for edge in metric.join_path
    )


def _filter_allowed(metric: MetricDefinition, table: str, column: str) -> bool:
    pair = (table.lower(), column.lower())
    allowed = {
        (dimension.table.lower(), dimension.column.lower())
        for dimension in metric.allowed_dimensions
    }
    if "." in metric.date_column:
        date_table, date_column = metric.date_column.split(".", 1)
        allowed.add((date_table.lower(), date_column.lower()))
    return pair in allowed


class MetricResolver:
    """Resolves a question to a governed metric and validated slots."""

    def __init__(
        self,
        registry: MetricRegistry | None = None,
        *,
        client: object | None = None,
        use_model: bool = True,
    ) -> None:
        self._registry = registry or MetricRegistry.default()
        self._client = client
        self._use_model = use_model

    @property
    def registry(self) -> MetricRegistry:
        return self._registry

    def resolve(
        self,
        question: str,
        *,
        linked_values: Iterable[LinkedValue] = (),
        use_model: bool | None = None,
    ) -> MetricResolution:
        normalized = _normalize(question)
        if not normalized:
            raise ValueError("question must not be empty")

        should_use_model = self._use_model if use_model is None else use_model
        match = self._registry.match_question(normalized)

        if match is None:
            if should_use_model and self._client is not None:
                return self._resolve_with_model(question)
            return self._ungoverned()

        metric, phrase = match
        time_grain = _detect_time_grain(normalized)
        period = _detect_period(normalized)
        dimensions: list[ResolvedDimension] = []
        requested_dimensions: list[str] = []

        for dimension in metric.allowed_dimensions:
            synonyms = (dimension.name, *dimension.synonyms)
            if any(_contains(normalized, _normalize(item)) for item in synonyms):
                if time_grain is not None and dimension.time_grain == time_grain:
                    requested_dimensions.append(dimension.name)
                    continue
                dimensions.append(
                    ResolvedDimension(
                        requested=dimension.name,
                        allowed=True,
                        column=dimension.column,
                        table=dimension.table,
                    )
                )
                requested_dimensions.append(dimension.name)

        filters = list(self._deterministic_filters(normalized, metric))
        for value in linked_values:
            if _filter_allowed(metric, value.table, value.column):
                filters.append(
                    MetricFilter(
                        table=value.table,
                        column=value.column,
                        operator="=",
                        value=value.literal,
                    )
                )

        leftovers = self._leftovers(
            normalized,
            metric=metric,
            metric_phrase=phrase,
            dimensions=requested_dimensions,
            time_grain=time_grain,
            period=period,
            filters=filters,
        )

        deterministic = self._resolution(
            metric,
            dimensions=dimensions,
            filters=filters,
            period=period,
            time_grain=time_grain,
            coverage="full" if not leftovers else "partial",
            caveats=(
                ()
                if not leftovers
                else (
                    (
                        "Some parts of the question were not mapped to governed "
                        f"slots: {', '.join(leftovers)}."
                    ),
                )
            ),
        )

        if not leftovers or not should_use_model or self._client is None:
            return deterministic
        return self._resolve_with_model(question)

    def _deterministic_filters(
        self, question: str, metric: MetricDefinition
    ) -> tuple[MetricFilter, ...]:
        filters: list[MetricFilter] = []
        if _has_orders(metric):
            for word, status in _STATUS_WORDS.items():
                if _contains(question, word):
                    filters.append(
                        MetricFilter(
                            table="orders",
                            column="order_status",
                            operator="=",
                            value=status,
                        ),
                    )
                    break
        has_state_dim = any(
            d.column == "customer_state" for d in metric.allowed_dimensions
        )
        if has_state_dim:
            for match in _STATE_FILTER_PATTERN.finditer(question):
                candidate = match.group(1).lower()
                if candidate in _BRAZIL_STATES:
                    filters.append(
                        MetricFilter(
                            table="customers",
                            column="customer_state",
                            operator="=",
                            value=candidate.upper(),
                        )
                    )
                    break
        return tuple(filters)

    def _leftovers(
        self,
        question: str,
        *,
        metric: MetricDefinition,
        metric_phrase: str,
        dimensions: Iterable[str],
        time_grain: str | None,
        period: Period | None,
        filters: Iterable[MetricFilter],
    ) -> tuple[str, ...]:
        remaining = question
        phrases = [metric_phrase, metric.name, metric.metric_id, *metric.synonyms]
        for dimension in metric.allowed_dimensions:
            if dimension.name in set(dimensions):
                phrases.extend((dimension.name, *dimension.synonyms))
        for phrase in phrases:
            remaining = _remove_phrase(remaining, _normalize(phrase))
        for phrase, _ in _TIME_GRAINS:
            remaining = _remove_phrase(remaining, phrase)
        if time_grain is not None:
            remaining = _remove_phrase(remaining, time_grain)
        if period is not None:
            remaining = _MONTH_PATTERN.sub(" ", remaining)
            remaining = _QUARTER_PATTERN.sub(" ", remaining)
            remaining = _QUARTER_WORD_PATTERN.sub(" ", remaining)
            remaining = _YEAR_PATTERN.sub(" ", remaining)
        for word in _STATUS_WORDS:
            remaining = _remove_phrase(remaining, word)
        for item in filters:
            val_str = str(item.value).lower() if item.value is not None else ""
            remaining = _remove_phrase(remaining, val_str)
            remaining = _remove_phrase(remaining, item.column.lower())
        return tuple(
            token
            for token in remaining.split()
            if token not in _STOPWORDS
            and token not in _COMPARATIVE_WORDS
            and not token.isdigit()
        )

    def _resolution(
        self,
        metric: MetricDefinition,
        *,
        dimensions: Iterable[ResolvedDimension],
        filters: Iterable[MetricFilter],
        period: Period | None,
        time_grain: str | None,
        coverage: str,
        caveats: Iterable[str] = (),
        reasoning: str | None = None,
        model: ModelUsage | None = None,
    ) -> MetricResolution:
        extras = tuple(caveats)
        if coverage == "none":
            extras = tuple(dict.fromkeys(("ungoverned metric", *extras)))
        return MetricResolution(
            coverage=coverage,  # type: ignore[arg-type]
            metric_id=metric.metric_id,
            definition=metric,
            resolved_dimensions=tuple(dimensions),
            grain=metric.grain[0] if metric.grain else None,
            date_column=metric.date_column,
            required_filters=metric.required_filters,
            caveats=tuple(dict.fromkeys((*metric.caveats, *extras))),
            filters=tuple(filters),
            period=period,
            time_grain=time_grain,  # type: ignore[arg-type]
            reasoning=reasoning,
            model=model,
        )

    def _ungoverned(self, *caveats: str) -> MetricResolution:
        return MetricResolution(
            coverage="none",
            caveats=tuple(dict.fromkeys(("ungoverned metric", *caveats))),
        )

    def _resolve_with_model(self, question: str) -> MetricResolution:
        if self._client is None:
            return self._ungoverned()

        try:
            result = self._client.chat_json(  # type: ignore[attr-defined]
                self._messages(question)
            )
        except ModelUnavailableError as exc:
            return self._ungoverned(
                f"The reasoning model is unavailable; used deterministic "
                f"resolution: {exc}"
            )
        except ModelResponseError as exc:
            return self._ungoverned(
                f"The reasoning model returned an unusable response: {exc}"
            )

        if isinstance(result, tuple) and len(result) == 2:
            payload, usage = result
        else:
            payload, usage = result, None
        if not isinstance(payload, dict):
            return self._ungoverned(
                "The reasoning model did not return a metric resolution object."
            )

        metric_id = payload.get("metric_id")
        if not isinstance(metric_id, str) or not metric_id.strip():
            return self._ungoverned()
        metric = self._registry.get(metric_id)
        if metric is None:
            return self._ungoverned(
                f"The reasoning model selected an unregistered metric: {metric_id}."
            )

        dimensions, dimension_caveats = self._model_dimensions(metric, payload)
        filters, filter_caveats = self._model_filters(metric, payload)
        period = self._model_period(payload)
        time_grain = self._model_time_grain(payload)

        unresolved = (*dimension_caveats, *filter_caveats)
        coverage = "partial" if unresolved else "full"
        reasoning = payload.get("reasoning")
        reasoning = reasoning if isinstance(reasoning, str) else None

        return self._resolution(
            metric,
            dimensions=dimensions,
            filters=filters,
            period=period,
            time_grain=time_grain,
            coverage=coverage,
            caveats=unresolved,
            reasoning=reasoning,
            model=usage if isinstance(usage, ModelUsage) else None,
        )

    def _model_dimensions(
        self, metric: MetricDefinition, payload: dict[str, Any]
    ) -> tuple[list[ResolvedDimension], tuple[str, ...]]:
        raw = payload.get("dimensions")
        if raw is None:
            return [], ()
        if not isinstance(raw, list):
            return [], ("The model's dimensions field was not a list.",)

        resolved: list[ResolvedDimension] = []
        caveats: list[str] = []
        for item in raw:
            if not isinstance(item, str):
                caveats.append("The model returned a non-text dimension.")
                continue
            match = _allowed_dimension(metric, item)
            if match is None:
                resolved.append(
                    ResolvedDimension(
                        requested=item,
                        allowed=False,
                        reason="The metric registry does not allow this dimension.",
                    )
                )
                caveats.append(f"Unsupported dimension: {item}.")
            else:
                resolved.append(match)
        return resolved, tuple(caveats)

    def _model_filters(
        self, metric: MetricDefinition, payload: dict[str, Any]
    ) -> tuple[list[MetricFilter], tuple[str, ...]]:
        raw = payload.get("filters")
        if raw is None:
            return [], ()
        if not isinstance(raw, list):
            return [], ("The model's filters field was not a list.",)

        filters: list[MetricFilter] = []
        caveats: list[str] = []
        for item in raw:
            if not isinstance(item, dict):
                caveats.append("The model returned a malformed filter.")
                continue
            table = item.get("table")
            column = item.get("column")
            operator = item.get("operator", "=")
            value = item.get("value")
            if not isinstance(table, str) or not isinstance(column, str):
                caveats.append("The model returned a filter without table/column.")
                continue
            if not _filter_allowed(metric, table, column):
                caveats.append(f"Unsupported filter column: {table}.{column}.")
                continue
            if isinstance(value, list):
                value = tuple(str(entry) for entry in value)
            elif value is not None:
                value = str(value)
            else:
                caveats.append("The model returned a filter without a value.")
                continue
            try:
                filters.append(
                    MetricFilter(
                        table=table,
                        column=column,
                        operator=operator,
                        value=value,
                    )
                )
            except ValueError:
                caveats.append(
                    f"The model returned an invalid filter on {table}.{column}."
                )
        return filters, tuple(caveats)

    @staticmethod
    def _model_period(payload: dict[str, Any]) -> Period | None:
        raw = payload.get("period")
        if not isinstance(raw, dict):
            return None
        start = raw.get("start")
        end = raw.get("end")
        if not isinstance(start, str) or not isinstance(end, str):
            return None
        try:
            return Period(start=date.fromisoformat(start), end=date.fromisoformat(end))
        except ValueError:
            return None

    @staticmethod
    def _model_time_grain(payload: dict[str, Any]) -> str | None:
        value = payload.get("time_grain")
        if value in {"day", "week", "month", "quarter", "year"}:
            return value
        return None

    def _messages(self, question: str) -> list[dict[str, str]]:
        metrics = [
            {
                "metric_id": metric.metric_id,
                "name": metric.name,
                "synonyms": list(metric.synonyms),
                "grain": list(metric.grain),
                "date_column": metric.date_column,
                "dimensions": [
                    {
                        "name": dimension.name,
                        "column": dimension.column,
                        "table": dimension.table,
                        "synonyms": list(dimension.synonyms),
                    }
                    for dimension in metric.allowed_dimensions
                ],
            }
            for metric in self._registry.metrics
        ]
        system = (
            "You map a business question to exactly one governed metric. "
            "Return a JSON object only, with keys metric_id, dimensions, "
            "time_grain, period, filters, and reasoning. Use only metric_id and "
            "dimension names from the governed registry. Use ISO dates for period "
            "(start inclusive, end exclusive). Filters must use a governed table, "
            "column and operator. Never invent a metric or a value. If no governed "
            "metric fits, return metric_id as null."
        )
        user = json.dumps(
            {
                "question": question,
                "governed_metrics": metrics,
            },
            ensure_ascii=False,
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]


__all__ = ["MetricResolver"]
