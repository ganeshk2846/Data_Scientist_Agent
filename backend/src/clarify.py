"""Structured clarification (contracts.md section 4, CL-1..7).

One question, 2-4 clickable options, a stated default, at most two rounds.
Every option is a *patch* over ``ResolvedQuestion`` fields, so accepting it is
deterministic - the model never re-interprets the reply (CL-6). When round 2
would still be ambiguous, or the user does not answer, the agent proceeds on
the default and records it as an assumption: a clarification is never a dead
end and never a refusal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from contracts.v2 import (
    ClarifiableSlot,
    ClarificationOption,
    ClarificationRequest,
    DefaultAssumption,
)

MAX_ROUNDS = 2


@dataclass(frozen=True)
class Choice:
    label: str
    patch: Mapping[str, Any]
    detail: str | None = None


def _iso(value: date) -> str:
    return value.isoformat()


def _add_months(start: date, months: int) -> date:
    index = start.year * 12 + start.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def build(
    *,
    slot: ClarifiableSlot,
    understood: str,
    needs: str,
    question: str,
    choices: Sequence[Choice],
    default_index: int = 0,
    rationale: str,
    round_number: int = 1,
    of_run_id: str | None = None,
) -> ClarificationRequest:
    """Build a request; options beyond four are cut, never asked as a second question."""
    choices = list(choices)[:4]
    if len(choices) < 2:
        raise ValueError("a clarification needs at least two options (CL-2)")
    options = tuple(
        ClarificationOption(
            option_id=f"O{index}",
            label=choice.label,
            detail=choice.detail,
            resolves_to=dict(choice.patch),
            recommended=index - 1 == default_index,
        )
        for index, choice in enumerate(choices, start=1)
    )
    return ClarificationRequest(
        what_understood=understood,
        what_needs_clarification=needs,
        question=question if question.endswith("?") else question + "?",
        options=options,
        default_assumption=DefaultAssumption(option_id=f"O{default_index + 1}", rationale=rationale),
        round=2 if round_number >= 2 else 1,
        slot=slot,
        of_run_id=of_run_id if round_number >= 2 else None,
    )


def period_choices(anchor: date, history_start: date) -> list[Choice]:
    end = _add_months(anchor, 1)
    return [
        Choice("Last 12 complete months", {"period": {"start": _iso(_add_months(anchor, -11)), "end": _iso(end)}, "grain": "month"},
               f"{_add_months(anchor, -11):%Y-%m} to {anchor:%Y-%m}"),
        Choice(f"{anchor.year} to date", {"period": {"start": _iso(date(anchor.year, 1, 1)), "end": _iso(end)}, "grain": "month"},
               f"{anchor.year}-01 to {anchor:%Y-%m}"),
        Choice("All history", {"period": {"start": _iso(history_start), "end": _iso(end)}, "grain": "month"},
               f"{history_start:%Y-%m} to {anchor:%Y-%m}, excluding incomplete edge months"),
    ]


def recent_choices(anchor: date) -> list[Choice]:
    end = _add_months(anchor, 1)
    return [
        Choice("Last complete month", {"period": {"start": _iso(anchor), "end": _iso(end)}, "grain": "month"}, f"{anchor:%Y-%m}"),
        Choice("Last 3 complete months", {"period": {"start": _iso(_add_months(anchor, -2)), "end": _iso(end)}, "grain": "month"},
               f"{_add_months(anchor, -2):%Y-%m} to {anchor:%Y-%m}"),
        Choice("Last 12 complete months", {"period": {"start": _iso(_add_months(anchor, -11)), "end": _iso(end)}, "grain": "month"},
               f"{_add_months(anchor, -11):%Y-%m} to {anchor:%Y-%m}"),
    ]


METRIC_CHOICES = [
    Choice("Revenue (payments received)", {"metric_id": "revenue"}, "order_payments, order grain"),
    Choice("GMV (item price plus freight)", {"metric_id": "gmv"}, "order_items, item grain"),
    Choice("Order count", {"metric_id": "order_count"}, "distinct orders"),
    Choice("Average order value", {"metric_id": "aov"}, "revenue per order"),
]
GROSS_NET_CHOICES = [
    Choice("Gross: GMV, item price plus freight before payment adjustments", {"metric_id": "gmv"}, "order_items"),
    Choice("Net: revenue, payments received", {"metric_id": "revenue"}, "order_payments"),
]
GRAIN_CHOICES = [
    Choice("Monthly", {"grain": "month"}),
    Choice("Weekly", {"grain": "week"}),
    Choice("Daily", {"grain": "day"}),
    Choice("Quarterly", {"grain": "quarter"}),
]


def horizon_choices() -> list[Choice]:
    return [
        Choice("Next 3 months", {"effective_text": "forecast for the next 3 months"}),
        Choice("Next 6 months", {"effective_text": "forecast for the next 6 months"}),
        Choice("Next quarter", {"effective_text": "forecast for the next quarter"}),
    ]


def question_choices(questions: Sequence[tuple[str, str]]) -> list[Choice]:
    """Suggestions that each rewrite the question into an answerable one."""
    return [Choice(label, {"effective_text": text}) for label, text in questions]


def next_round(previous: ClarificationRequest | None) -> int:
    return 1 if previous is None else previous.round + 1


def patch_for(request: ClarificationRequest, option_id: str | None) -> tuple[dict[str, Any], str]:
    """The option's patch and an assumption line; unknown or missing ids take the default (CL-3)."""
    chosen = next((option for option in request.options if option.option_id == option_id), None)
    if chosen is None:
        chosen = next(option for option in request.options if option.option_id == request.default_assumption.option_id)
        note = f"No option was chosen, so the default was used: {chosen.label} ({request.default_assumption.rationale})"
    else:
        note = f"You chose: {chosen.label}."
    return dict(chosen.resolves_to), note


def option_by_label(request: ClarificationRequest, reply: str) -> str | None:
    """Map a free-text reply that repeats an option label (or its id) onto that option."""
    text = reply.strip().lower()
    for option in request.options:
        if text in {option.option_id.lower(), option.label.lower()} or option.label.lower().startswith(text) and len(text) >= 4:
            return option.option_id
    return None


__all__ = [
    "GRAIN_CHOICES",
    "GROSS_NET_CHOICES",
    "MAX_ROUNDS",
    "METRIC_CHOICES",
    "Choice",
    "build",
    "horizon_choices",
    "next_round",
    "option_by_label",
    "patch_for",
    "period_choices",
    "question_choices",
    "recent_choices",
]
