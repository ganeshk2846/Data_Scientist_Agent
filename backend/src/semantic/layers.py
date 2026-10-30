"""``data_layer`` from the tables a step actually read (SY-1, SY-2).

The layer is derived from executed SQL or an explicit list of tables, never
declared by a model. An unregistered table fails closed: a figure whose
source table is unknown cannot be labelled, so it cannot be served.
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlglot
from sqlglot import exp

from contracts.v2 import DataLayer
from semantic.tables import TableRegistry


def tables_in_sql(sql: str, dialect: str = "sqlite") -> tuple[str, ...]:
    """Physical tables referenced by ``sql``, CTE names excluded, sorted."""
    tree = sqlglot.parse_one(sql, read=dialect)
    ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    names = {
        table.name.lower()
        for table in tree.find_all(exp.Table)
        if table.name and table.name.lower() not in ctes
    }
    return tuple(sorted(names))


def data_layer_for(
    tables: Iterable[str],
    registry: TableRegistry | None = None,
) -> tuple[DataLayer, tuple[str, ...]]:
    """Return ``(data_layer, synthetic_tables)`` for the tables read."""
    registry = registry or TableRegistry.default()
    read = sorted({name.lower() for name in tables})
    unknown = [name for name in read if name not in registry]
    if unknown:
        raise KeyError(f"unregistered tables cannot be labelled: {', '.join(unknown)}")
    synthetic = tuple(name for name in read if registry.require(name).is_synthetic)
    if not synthetic:
        return "real", ()
    if len(synthetic) == len(read):
        return "synthetic", synthetic
    return "mixed", synthetic


def data_layer_for_sql(
    sql: str,
    registry: TableRegistry | None = None,
) -> tuple[DataLayer, tuple[str, ...]]:
    return data_layer_for(tables_in_sql(sql), registry)


def synthetic_caveat(synthetic_tables: Iterable[str]) -> str | None:
    """The caveat SY-1 requires whenever a synthetic table was read."""
    names = sorted(set(synthetic_tables))
    if not names:
        return None
    return (
        "Based on synthetic data: "
        + ", ".join(names)
        + (" is" if len(names) == 1 else " are")
        + " generated for demonstration and are not measurements of the real "
        "business."
    )


__all__ = ["data_layer_for", "data_layer_for_sql", "synthetic_caveat", "tables_in_sql"]
