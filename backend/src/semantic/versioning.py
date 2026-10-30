"""``catalog_version`` for the V2 semantic layer.

A short content hash of every metric definition, aggregation entry, KPI SQL
spec and registered table. Anything that changes what a figure means changes
the version, which invalidates cached analytical rows (AT-2).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from semantic.aggregation import AggregationRegistry
from semantic.kpis import KPI_SPECS
from semantic.metrics_v2 import all_metrics
from semantic.tables import TableRegistry


def catalog_version(tables: TableRegistry | None = None) -> str:
    tables = tables or TableRegistry.default()
    aggregations = AggregationRegistry()
    payload = {
        "metrics": [metric.model_dump(mode="json") for metric in all_metrics().metrics],
        "aggregations": [aggregations.require(m).model_dump(mode="json") for m in aggregations.metric_ids()],
        "kpis": [asdict(spec) for spec in KPI_SPECS],
        "tables": [table.model_dump(mode="json") for table in tables.tables],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"v2-{digest[:12]}"


__all__ = ["catalog_version"]
