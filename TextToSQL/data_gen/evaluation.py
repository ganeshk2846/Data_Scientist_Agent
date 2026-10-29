"""Final held-out run boundary (DATA-6/DATA-8/DATA-9)."""
from __future__ import annotations

from typing import Callable

from src.knowledge.stores import GoldenStore
from .access import heldout_scoring_scope
from .splits import QuestionSplitStore


def run_final_evaluation(split_store: QuestionSplitStore, golden_store: GoldenStore,
                         score_one: Callable[[dict], dict], *, principal: str | None = None,
                         scoring_policy=None) -> list[dict]:
    """Check Golden Store leakage before exposing held-out cases to the scorer."""
    cases = split_store.get("held-out", principal=principal, scoring_policy=scoring_policy)
    golden_store.assert_final_run_safe([case["question"] for case in cases])
    results = []
    with heldout_scoring_scope():
        for case in cases:
            results.append(score_one(case))
    return results
