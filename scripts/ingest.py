"""Load a folder of CSVs as new tables and register them (build plan Track 1, item 6).

    python scripts/ingest.py <folder> [--db data/brazil_ecommerce_v2.sqlite]
                             [--registry semantics/ingested_tables.json]
                             [--semantics semantics/]

For each ``*.csv`` in the folder:

1. **Profile** every column: SQLite type, null rate, distinct count. No cell
   values are copied into the registry or the docs.
2. **Infer the grain**: the smallest set of one or two columns that is unique
   and non-null. Infer a date column by name and parseability.
3. **Propose join edges** to registered tables where a column's name matches
   a known key and its values overlap the warehouse's. Every edge is
   ``status: proposed`` - a person approves it (GRD-2); nothing is
   auto-approved.
4. **Load** the table into the V2 database (never the real snapshot) and
   **register** it: description, synonyms, grain, keys, columns, edges, and
   a ``semantics/<table>.md`` page. ``catalog_version`` is recomputed.

A ``<name>.md`` or ``<name>.txt`` next to a CSV supplies its description.
Re-running on the same folder is idempotent.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from semantic.tables import TableRegistry, ingested_tables  # noqa: E402
from semantic.versioning import catalog_version  # noqa: E402

DEFAULT_DB = REPO_ROOT / "data" / "brazil_ecommerce_v2.sqlite"
DEFAULT_REGISTRY = REPO_ROOT / "semantics" / "ingested_tables.json"
DEFAULT_SEMANTICS = REPO_ROOT / "semantics"
REAL_SNAPSHOT = REPO_ROOT / "brazil_ecommerce.sqlite"

#: Column names that, when their values overlap, suggest a join edge.
KNOWN_KEYS: dict[str, str] = {
    "order_id": "orders.order_id",
    "customer_id": "customers.customer_id",
    "customer_unique_id": "customers.customer_unique_id",
    "product_id": "products.product_id",
    "seller_id": "sellers.seller_id",
    "customer_state": "customers.customer_state",
    "state": "customers.customer_state",
    "seller_state": "sellers.seller_state",
    "product_category_name": "products.product_category_name",
    "category": "products.product_category_name",
    "zip_code_prefix": "geolocation.geolocation_zip_code_prefix",
}
MIN_OVERLAP = 0.5
_DATE_NAME = re.compile(r"(date|time|timestamp|_at$|^day$|^month$)", re.IGNORECASE)


@dataclass(frozen=True)
class IngestedTable:
    entry: dict
    frame: pd.DataFrame


def table_name(stem: str) -> str:
    name = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_") or "table"
    return f"u_{name}" if name[0].isdigit() else name


def _sqlite_type(series: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(series) or pd.api.types.is_integer_dtype(series):
        return "INTEGER"
    if pd.api.types.is_float_dtype(series):
        return "REAL"
    return "TEXT"


def _is_date(name: str, series: pd.Series) -> bool:
    if not _DATE_NAME.search(name) or series.dropna().empty:
        return False
    parsed = pd.to_datetime(series.dropna().astype(str), errors="coerce", format="mixed")
    return parsed.notna().mean() >= 0.9


def _grain(frame: pd.DataFrame) -> tuple[str, tuple[str, ...]]:
    columns = list(frame.columns)
    for size in (1, 2):
        for keys in combinations(columns, size):
            subset = frame[list(keys)]
            if subset.notna().all(axis=None) and not subset.duplicated().any():
                return " x ".join(keys), tuple(keys)
    return "row (no unique key of one or two columns)", (columns[0],)


def _synonyms(name: str) -> list[str]:
    words = name.removeprefix("u_").replace("_", " ")
    out = {words}
    out.add(words[:-1] if words.endswith("s") else words + "s")
    return sorted(out)


def _proposed_edges(conn: sqlite3.Connection, frame: pd.DataFrame) -> list[dict]:
    edges = []
    for column in frame.columns:
        reference = KNOWN_KEYS.get(column.lower())
        if reference is None:
            continue
        table, key = reference.split(".")
        try:
            known = {row[0] for row in conn.execute(f'SELECT DISTINCT "{key}" FROM "{table}"')}
        except sqlite3.OperationalError:
            continue
        values = set(frame[column].dropna().astype(str))
        if not values:
            continue
        overlap = len(values & {str(v) for v in known}) / len(values)
        if overlap >= MIN_OVERLAP:
            edges.append({
                "column": column,
                "references": reference,
                "overlap": round(overlap, 4),
                "status": "proposed",
            })
    return edges


def profile(path: Path, conn: sqlite3.Connection, taken: set[str]) -> IngestedTable:
    frame = pd.read_csv(path)
    if frame.empty or not len(frame.columns):
        raise ValueError(f"{path.name} has no rows")
    frame.columns = [table_name(str(column)) for column in frame.columns]
    name = table_name(path.stem)
    if name in taken:
        raise ValueError(f"{path.name}: {name!r} is already a registered warehouse table")
    grain, keys = _grain(frame)
    dates = [column for column in frame.columns if _is_date(column, frame[column])]
    description = None
    for suffix in (".md", ".txt"):
        sidecar = path.with_suffix(suffix)
        if sidecar.is_file():
            description = " ".join(sidecar.read_text(encoding="utf-8").split())
            break
    entry = {
        "name": name,
        "source": "user_supplied",
        "file": path.name,
        "description": description or f"User-supplied table loaded from {path.name}.",
        "synonyms": _synonyms(name),
        "grain": grain,
        "key_columns": list(keys),
        "date_column": dates[0] if dates else None,
        "row_count": int(len(frame)),
        "columns": [
            {
                "name": column,
                "type": _sqlite_type(frame[column]),
                "null_rate": round(float(frame[column].isna().mean()), 4),
                "distinct": int(frame[column].nunique(dropna=True)),
            }
            for column in frame.columns
        ],
        "join_edges": _proposed_edges(conn, frame),
    }
    return IngestedTable(entry, frame)


def _load(conn: sqlite3.Connection, table: IngestedTable) -> None:
    entry, frame = table.entry, table.frame
    conn.execute(f'DROP TABLE IF EXISTS "{entry["name"]}"')
    columns = ", ".join(f'"{c["name"]}" {c["type"]}' for c in entry["columns"])
    conn.execute(f'CREATE TABLE "{entry["name"]}" ({columns})')
    rows = frame.astype(object).where(frame.notna(), None).itertuples(index=False, name=None)
    conn.executemany(f'INSERT INTO "{entry["name"]}" VALUES ({", ".join("?" * len(entry["columns"]))})', rows)


def _semantics_page(entry: dict) -> str:
    lines = [
        f"# `{entry['name']}`",
        "",
        "**Source:** user-supplied (`scripts/ingest.py`), loaded from "
        f"`{entry['file']}`. Not part of the Olist snapshot and not synthetic.",
        "",
        entry["description"],
        "",
        f"- **Grain:** {entry['grain']}",
        f"- **Key columns:** {', '.join(f'`{k}`' for k in entry['key_columns'])}",
        f"- **Date column:** {'`' + entry['date_column'] + '`' if entry['date_column'] else 'none detected'}",
        f"- **Synonyms:** {', '.join(entry['synonyms'])}",
        "",
        "## Columns",
        "",
        "| Column | Type | Null rate | Distinct |",
        "| --- | --- | --- | --- |",
        *(f"| `{c['name']}` | {c['type']} | {c['null_rate']:.1%} | {c['distinct']:,} |" for c in entry["columns"]),
        "",
        "## Proposed join edges (need approval, GRD-2)",
        "",
    ]
    if entry["join_edges"]:
        lines += [f"- `{entry['name']}.{e['column']}` -> `{e['references']}` ({e['overlap']:.0%} of values match)" for e in entry["join_edges"]]
    else:
        lines.append("- none found")
    return "\n".join(lines) + "\n"


def ingest(
    folder: Path,
    *,
    db: Path = DEFAULT_DB,
    registry_path: Path = DEFAULT_REGISTRY,
    semantics_dir: Path | None = DEFAULT_SEMANTICS,
) -> dict:
    folder, db = Path(folder), Path(db).resolve()
    if db == REAL_SNAPSHOT.resolve():
        raise ValueError("ingestion never writes into the real snapshot (V2-SYN-1, SAFE-2)")
    if not db.is_file():
        raise FileNotFoundError(f"{db} not found; build the V2 database first")
    files = sorted(folder.glob("*.csv"))
    if not files:
        raise ValueError(f"no CSV files in {folder}")

    registry_path = Path(registry_path)
    existing = json.loads(registry_path.read_text()) if registry_path.is_file() else {"tables": []}
    taken = {table.name for table in TableRegistry.default().tables}

    with sqlite3.connect(db) as conn:
        tables = [profile(path, conn, taken) for path in files]
        for table in tables:
            _load(conn, table)

    merged = {entry["name"]: entry for entry in existing["tables"]}
    merged.update({table.entry["name"]: table.entry for table in tables})
    payload = {"tables": [merged[name] for name in sorted(merged)]}
    payload["catalog_version"] = catalog_version(TableRegistry.default().with_tables(ingested_tables(payload)))
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if semantics_dir is not None:
        semantics_dir = Path(semantics_dir)
        semantics_dir.mkdir(parents=True, exist_ok=True)
        for table in tables:
            (semantics_dir / f"{table.entry['name']}.md").write_text(_semantics_page(table.entry), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load a folder of CSVs into the V2 database and register them.")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--semantics", type=Path, default=DEFAULT_SEMANTICS)
    args = parser.parse_args(argv)
    payload = ingest(args.folder, db=args.db, registry_path=args.registry, semantics_dir=args.semantics)
    for entry in payload["tables"]:
        edges = ", ".join(f"{e['column']}->{e['references']}" for e in entry["join_edges"]) or "none"
        print(f"{entry['name']:<28} {entry['row_count']:>8,} rows  grain: {entry['grain']}  proposed edges: {edges}")
    print(f"catalog_version {payload['catalog_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
