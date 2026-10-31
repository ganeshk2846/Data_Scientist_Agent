"""'Which customer segment should we target?' at real-catalogue scale (P1, must-answer).

At ~96k customers ``cluster_members`` built one pandas Series per row and looked the key column up
once per row, so the answer took ~9 s. The row-dict version must assign every member exactly as
before.
"""

from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import pandas as pd
from engine_helpers import table
from engines.prescriptive import cluster_members


def _reference_records(frame: pd.DataFrame, usable: list[str]) -> list[dict[str, Any]]:
    """The previous per-row loop, kept here as the definition of the rules."""
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
    return records


def _customers(count: int, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    revenue = rng.lognormal(4.5, 0.8, count)
    revenue[::97] = np.nan  # missing measures are skipped, not zero
    return pd.DataFrame({
        "customer_unique_id": [f"c{index:06d}" for index in range(count)],
        "segment": rng.choice(["high_value", "one_time", " loyal ", ""], count),  # padded and empty strings
        "ltv_band": rng.choice(["high", "mid", "low"], count),
        "orders": rng.integers(1, 6, count),
        "revenue": revenue,
    })


def _profiles():
    return {0: {"orders": 1.0, "revenue": 60.0, "segment=one_time": 1.0, "ltv_band=low": 1.0},
            1: {"orders": 3.0, "revenue": 250.0, "segment=high_value": 1.0, "ltv_band=high": 1.0},
            2: {"orders": 2.0, "revenue": 120.0, "segment=loyal": 1.0, "ltv_band=mid": 1.0}}


def test_cluster_members_matches_the_per_row_rules():
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.preprocessing import StandardScaler

    frame = _customers(800)
    ref = table(frame, "Q1", customer_unique_id="key")
    got = cluster_members(ref, _profiles(), "customer_unique_id")

    records = _reference_records(frame, ["segment", "ltv_band", "orders", "revenue"])
    vectorizer = DictVectorizer(sparse=False, sort=True)
    matrix = vectorizer.fit_transform(records)
    scaler = StandardScaler().fit(matrix)
    names = list(vectorizer.get_feature_names_out())
    centroids = scaler.transform(np.asarray([[_profiles()[label].get(name, 0.0) for name in names] for label in sorted(_profiles())]))
    nearest = ((scaler.transform(matrix)[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
    expected = {str(key): sorted(_profiles())[int(choice)] for key, choice in zip(frame["customer_unique_id"], nearest, strict=True)}
    assert got == expected


def test_cluster_members_scales_to_a_real_customer_base():
    frame = _customers(100_000, seed=12)
    started = time.perf_counter()
    members = cluster_members(table(frame, "Q1", customer_unique_id="key"), _profiles(), "customer_unique_id")
    assert time.perf_counter() - started < 8.0  # was ~15 s here with a Series per row
    assert len(members) == 100_000
