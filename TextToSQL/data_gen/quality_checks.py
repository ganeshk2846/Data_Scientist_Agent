"""Independent read-only scoring for seeded synthetic warehouse defects."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def audit_generated_warehouse(database: str | Path, manifest_path: str | Path,
                             truth_path: str | Path | None = None) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    planted = manifest.get("planted_features", {})
    database_path = Path(database).resolve()
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    checks: list[dict] = []

    def record(name: str, actual, expected) -> None:
        checks.append({"name": name, "actual": actual, "expected": expected,
                       "passed": actual == expected})

    digest = hashlib.sha256(database_path.read_bytes()).hexdigest()
    record("database_hash_matches_manifest", digest, manifest.get("database_sha256"))

    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        cryptic = sorted(name for name in tables if len(name) == 4 and name.startswith("x"))
        distractors = sorted(name for name in tables if name.startswith("x"))
        record("cryptic_table_count", len(cryptic), planted.get("cryptic_tables"))
        record("distractor_table_count", len(distractors), planted.get("distractor_tables"))

        archive_rows = connection.execute("SELECT COUNT(*) FROM cstmr_archive").fetchone()[0]
        archive_duplicates = connection.execute(
            "SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM cstmr_archive GROUP BY cstmr_id HAVING n>1)"
        ).fetchone()[0]
        record("stale_copy_rows_excluding_duplicate", archive_rows - archive_duplicates,
               planted.get("stale_copy_rows"))
        record("duplicate_archive_rows", archive_duplicates, planted.get("duplicate_archive_rows"))

        regions = {row[0] for row in connection.execute("SELECT DISTINCT region FROM cstmr_dim")}
        expected_regions = set(planted.get("messy_region_values", []))
        record("messy_region_values_present", sorted(regions & expected_regions),
               sorted(expected_regions))
        statuses = {row[0] for row in connection.execute("SELECT DISTINCT status FROM ord_hdr")}
        expected_status = planted.get("messy_status_value")
        record("messy_status_value_present", expected_status in statuses, True)

        missing_keys_actual = (not list(connection.execute("PRAGMA foreign_key_list(ord_hdr)"))
                               and not list(connection.execute("PRAGMA foreign_key_list(ord_line)")))
        record("missing_declared_foreign_keys", missing_keys_actual,
               planted.get("missing_declared_foreign_keys"))
        deleted = connection.execute("SELECT COUNT(*) FROM ord_hdr WHERE deleted_at IS NOT NULL").fetchone()[0]
        record("soft_deleted_orders", deleted, planted.get("soft_deleted_orders"))
        test_orders = connection.execute("SELECT COUNT(*) FROM ord_hdr WHERE is_test=1").fetchone()[0]
        record("test_order_rows", test_orders, planted.get("test_order_rows"))
        merged_cases = connection.execute("SELECT COUNT(*) FROM customer_merge_map").fetchone()[0]
        record("merged_customer_cases", merged_cases, planted.get("merged_customer_cases"))
        late = connection.execute("SELECT COUNT(*) FROM late_events").fetchone()[0]
        record("late_event_rows", late, planted.get("late_event_rows"))
        truncated = connection.execute("SELECT COUNT(*) FROM daily_snapshot WHERE is_complete=0").fetchone()[0]
        record("truncated_snapshot_rows", truncated, planted.get("truncated_snapshot_rows"))

        columns = {row[1].casefold() for table in tables
                   for row in connection.execute(f'PRAGMA table_info("{table}")')}
        asks = planted.get("unanswerable_questions", [])
        forbidden_terms = {"nps", "postal_code"}
        absent_terms = sorted(term for term in forbidden_terms
                              if not any(term in column for column in columns))
        record("unanswerable_ask_fields_absent", absent_terms, sorted(forbidden_terms))

        if truth_path is not None:
            truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
            record("truth_snapshot_matches_manifest", truth.get("snapshot_id"),
                   manifest.get("snapshot_id"))
            record("truth_database_hash_matches_manifest", truth.get("database_sha256"),
                   manifest.get("database_sha256"))
            trap_results = []
            for trap in truth.get("sql_traps", []):
                observed = connection.execute(trap["correct_result_sql"]).fetchone()[0]
                trap_results.append({"trap_id": trap["trap_id"],
                                     "passed": observed == trap.get("correct_value")})
            checks.append({"name": "planted_sql_traps_reconcile", "actual": trap_results,
                           "expected": "all listed trap queries match their truth values",
                           "passed": bool(trap_results) and all(row["passed"] for row in trap_results)})
    finally:
        connection.close()
    return {"snapshot_id": manifest.get("snapshot_id"), "checks": checks,
            "passed": bool(checks) and all(item["passed"] for item in checks),
            "passed_count": sum(item["passed"] for item in checks),
            "check_count": len(checks)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--truth")
    args = parser.parse_args()
    database = Path(args.database)
    manifest = Path(args.manifest) if args.manifest else database.with_suffix(".manifest.json")
    result = audit_generated_warehouse(database, manifest, args.truth)
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
