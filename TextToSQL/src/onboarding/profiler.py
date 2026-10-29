"""Cost-bounded column profiling. Large tables are sampled deterministically."""
import sqlite3
import re
from .inspector import connect_read_only
from .privacy import SENSITIVE_COLUMN, sensitive_value, sensitive_variants


def profile_database(db_path: str, sample_limit: int = 20000, sample_values: int = 5, table_names: set[str] | None = None) -> dict:
    connection = connect_read_only(db_path)
    try:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        report = {}
        for (table_name,) in tables:
            if table_names is not None and table_name not in table_names:
                continue
            qt = '"' + table_name.replace('"', '""') + '"'
            row_count = connection.execute(f"SELECT COUNT(*) FROM {qt}").fetchone()[0]
            columns = connection.execute(f"PRAGMA table_info({qt})").fetchall()
            sampled = row_count > sample_limit
            stats = {}
            sensitive_samples = []
            for col in columns:
                name, declared = col[1], col[2] or ""
                qc = '"' + name.replace('"', '""') + '"'
                if sampled:
                    base = f"SELECT {qc} FROM {qt} WHERE rowid % MAX(1, (SELECT CAST(COUNT(*) / {sample_limit} AS INTEGER) FROM {qt})) = 0 LIMIT {sample_limit}"
                    try:
                        values = [r[0] for r in connection.execute(base)]
                    except sqlite3.OperationalError:
                        values = [r[0] for r in connection.execute(f"SELECT {qc} FROM {qt} LIMIT ?", (sample_limit,))]
                    n = len(values)
                    nulls = sum(v is None for v in values)
                    reported_null_count = round(nulls / n * row_count) if n else 0
                    distinct = len({v for v in values if v is not None})
                    present = [v for v in values if v is not None]
                    low, high = (min(present), max(present)) if present and all(isinstance(v, (int, float)) for v in present) else (None, None)
                    examples = list(dict.fromkeys(present))[:sample_values]
                    detection_values = list(dict.fromkeys(present))
                else:
                    n = row_count
                    nulls = connection.execute(f"SELECT COUNT(*) FROM {qt} WHERE {qc} IS NULL").fetchone()[0]
                    reported_null_count = nulls
                    distinct = connection.execute(f"SELECT COUNT(DISTINCT {qc}) FROM {qt}").fetchone()[0]
                    bounds = connection.execute(f"SELECT MIN({qc}), MAX({qc}) FROM {qt}").fetchone()
                    low, high = bounds[0], bounds[1]
                    examples = [r[0] for r in connection.execute(f"SELECT DISTINCT {qc} FROM {qt} WHERE {qc} IS NOT NULL LIMIT ?", (sample_values,))]
                    detection_values = [r[0] for r in connection.execute(f"SELECT DISTINCT {qc} FROM {qt} WHERE {qc} IS NOT NULL LIMIT ?", (sample_limit,))]
                high_cardinality_name = bool(re.search(r"(^|_)(name|full_name|first_name|last_name|title|label)(_|$)", name, re.I) and distinct > 1000)
                named_sensitive = bool(SENSITIVE_COLUMN.search(name))
                detected_values = [] if named_sensitive else [v for v in detection_values if v is not None and sensitive_value(v)][:100]
                is_sensitive = named_sensitive or bool(detected_values) or high_cardinality_name
                if named_sensitive or high_cardinality_name:
                    sensitive_samples.extend(v for v in detection_values[:100] if v is not None)
                else:
                    sensitive_samples.extend(detected_values)
                stats[name] = {"type": declared, "sampled_rows": n, "null_count": reported_null_count, "null_rate": (nulls / n if n else 0.0), "distinct_count": distinct, "min": None if is_sensitive else low, "max": None if is_sensitive else high, "formats": sorted({type(v).__name__ for v in examples}), "sample_values": [] if is_sensitive else examples, "sensitive": is_sensitive, "high_cardinality_name": high_cardinality_name}
            needles = set().union(*(sensitive_variants(v) for v in sensitive_samples)) if sensitive_samples else set()
            for name, column_stats in stats.items():
                if column_stats["sensitive"]:
                    continue
                values = [*column_stats["sample_values"], column_stats["min"], column_stats["max"]]
                if any(needle.casefold() in str(value).casefold() for value in values if value is not None for needle in needles):
                    column_stats.update({"sensitive": True, "min": None, "max": None, "sample_values": []})
            pk = [c[1] for c in columns if c[5]]
            duplicates = None
            if pk:
                key = ", ".join('"' + c.replace('"', '""') + '"' for c in pk)
                duplicates = connection.execute(f"SELECT COUNT(*) FROM (SELECT {key} FROM {qt} GROUP BY {key} HAVING COUNT(*) > 1)").fetchone()[0]
            report[table_name] = {"row_count": row_count, "sampled": sampled, "has_primary_key": bool(pk), "duplicate_key_groups": duplicates, "sensitive_columns": [name for name, item in stats.items() if item["sensitive"]], "columns": stats}
        return report
    finally:
        connection.close()
