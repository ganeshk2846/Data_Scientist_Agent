"""Data layer classification for query provenance (SY-2, V2-SYN-4).

Classifies a query or result provenance as:
- 'real' if only real Olist tables are involved
- 'synthetic' if only synthetic tables are involved
- 'mixed' if both real and synthetic tables are joined
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from .tables import REAL_TABLE_NAMES, SYNTHETIC_TABLE_NAMES

DataLayerType = Literal["real", "synthetic", "mixed"]


def compute_data_layer(tables: Iterable[str]) -> DataLayerType:
    """Compute data layer from the set of tables accessed (SY-2)."""
    table_list = [t.lower().strip() for t in tables if t]
    if not table_list:
        return "real"

    has_real = False
    has_synthetic = False

    for t in table_list:
        if t in SYNTHETIC_TABLE_NAMES:
            has_synthetic = True
        elif t in REAL_TABLE_NAMES:
            has_real = True
        else:
            # Default to real if unknown / system
            has_real = True

    if has_real and has_synthetic:
        return "mixed"
    if has_synthetic:
        return "synthetic"
    return "real"
