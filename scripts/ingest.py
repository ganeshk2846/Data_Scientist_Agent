"""Read-only CSV ingestion & semantic onboarding profiler (GRD-2, GRD-12, SAFE-2).

Profiles a directory of CSV files, infers data types, detects primary keys and candidate
foreign key join edges against the warehouse, proposes join edges for human approval,
and generates registration artifacts without mutating the live warehouse.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _infer_type(values: list[str]) -> str:
    non_empty = [v.strip() for v in values if v.strip()]
    if not non_empty:
        return "TEXT"

    is_int = True
    for v in non_empty:
        if not re.match(r"^-?\d+$", v):
            is_int = False
            break
    if is_int:
        return "INTEGER"

    is_float = True
    for v in non_empty:
        if not re.match(r"^-?\d+(\.\d+)?$", v):
            is_float = False
            break
    if is_float:
        return "REAL"

    is_date = True
    for v in non_empty:
        if not re.match(r"^\d{4}-\d{2}-\d{2}", v):
            is_date = False
            break
    if is_date:
        return "DATE"

    return "TEXT"


def profile_csv(file_path: Path) -> dict[str, Any]:
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return {"file": file_path.name, "columns": {}, "row_count": 0}

        columns: dict[str, list[str]] = {col: [] for col in header}
        row_count = 0
        for row in reader:
            row_count += 1
            for col, val in zip(header, row):
                columns[col].append(val)

    col_profiles = {}
    candidate_pks = []
    for col, vals in columns.items():
        distinct_vals = set(vals)
        inferred_type = _infer_type(vals)
        unique_ratio = len(distinct_vals) / row_count if row_count > 0 else 0.0
        col_profiles[col] = {
            "type": inferred_type,
            "distinct_count": len(distinct_vals),
            "null_count": sum(1 for v in vals if not v.strip()),
            "unique_ratio": round(unique_ratio, 4),
        }
        if unique_ratio >= 0.99 and row_count > 0:
            candidate_pks.append(col)

    table_name = file_path.stem.lower()

    # Propose join edges based on known naming conventions
    proposed_edges = []
    for col in header:
        if col.endswith("_id"):
            proposed_edges.append(
                {
                    "source_table": table_name,
                    "source_column": col,
                    "target_column": col,
                    "status": "pending_human_approval",
                }
            )
        elif col in ("customer_state", "state"):
            proposed_edges.append(
                {
                    "source_table": table_name,
                    "source_column": col,
                    "target_table": "customers",
                    "target_column": "customer_state",
                    "status": "pending_human_approval",
                }
            )

    return {
        "table_name": table_name,
        "file_name": file_path.name,
        "row_count": row_count,
        "columns": col_profiles,
        "candidate_primary_keys": candidate_pks,
        "proposed_join_edges": proposed_edges,
        "user_supplied": True,
    }


def ingest_folder(
    csv_folder: str | Path, output_catalog: str | Path | None = None
) -> dict[str, Any]:
    folder = Path(csv_folder).resolve()
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")

    csv_files = list(folder.glob("*.csv"))
    if not csv_files:
        print(f"[*] No CSV files found in {folder}")
        return {"tables": {}, "total_tables": 0}

    print(f"[*] Profiling {len(csv_files)} CSV files in {folder}...")
    manifest: dict[str, Any] = {
        "source_folder": str(folder),
        "catalog_version_bump": "2026.10.2",
        "tables": {},
    }

    for csv_file in csv_files:
        profile = profile_csv(csv_file)
        manifest["tables"][profile["table_name"]] = profile
        print(
            f"  - Table '{profile['table_name']}': {profile['row_count']} rows, {len(profile['columns'])} cols"
        )
        if profile["proposed_join_edges"]:
            for edge in profile["proposed_join_edges"]:
                print(
                    f"    * Proposed Join: {edge['source_table']}.{edge['source_column']} -> target (Requires Approval)"
                )

    if output_catalog:
        out_path = Path(output_catalog)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"[+] Semantic registration profile written to {out_path}")

    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CSV Ingestion Profiler (GRD-2, SAFE-2)"
    )
    parser.add_argument("folder", help="Folder containing CSV files")
    parser.add_argument(
        "--output",
        default="data/ingest_profile.json",
        help="Path to write profile output",
    )
    args = parser.parse_args()

    ingest_folder(args.folder, args.output)


if __name__ == "__main__":
    main()
