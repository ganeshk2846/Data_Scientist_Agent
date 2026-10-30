"""Read-only warehouse introspection for SQLite warehouses."""

import sqlite3
from pathlib import Path


def connect_read_only(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"Database not found: {path}")
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def inspect_warehouse(db_path: str) -> dict:
    """Return table DDL, columns, declared foreign keys and approximate timestamps."""
    connection = connect_read_only(db_path)
    try:
        tables = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        result = {}
        for item in tables:
            name = item["name"]
            quoted = '"' + name.replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            fks = connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
            result[name] = {
                "ddl": item["sql"],
                "columns": [
                    {
                        "name": c["name"],
                        "type": c["type"],
                        "not_null": bool(c["notnull"]),
                        "default": c["dflt_value"],
                        "primary_key": bool(c["pk"]),
                    }
                    for c in columns
                ],
                "foreign_keys": [
                    {
                        "id": f["id"],
                        "sequence": f["seq"],
                        "column": f["from"],
                        "references_table": f["table"],
                        "references_column": f["to"],
                        "on_update": f["on_update"],
                        "on_delete": f["on_delete"],
                    }
                    for f in fks
                ],
            }
        return result
    finally:
        connection.close()


def inspect_database(db_path: str) -> dict:
    """Backward-compatible schema mapping: table name to column metadata list."""
    return {
        table: details["columns"]
        for table, details in inspect_warehouse(db_path).items()
    }
