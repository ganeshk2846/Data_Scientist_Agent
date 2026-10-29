"""Table trust metadata and stale-copy graph (GRD-1/3)."""
import sqlite3
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.onboarding import pipeline
from src.onboarding.pipeline import build_catalog
from src.knowledge.catalog_api import CatalogAPI
from src.knowledge.retrieval import SchemaRetriever


def test_freshness_duplicate_uncertainty_and_stale_copy_link(tmp_path):
    db = tmp_path / "trust.sqlite"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE orders (order_id INTEGER PRIMARY KEY, updated_at TEXT, amount REAL);
        CREATE TABLE orders_archive (order_id INTEGER, updated_at TEXT, amount REAL);
        INSERT INTO orders VALUES (1, '2025-01-01T00:00:00+00:00', 10.0);
        INSERT INTO orders_archive VALUES (1, '2021-01-01T00:00:00+00:00', 10.0);
        INSERT INTO orders_archive VALUES (1, '2021-01-01T00:00:00+00:00', 10.0);
    """)
    con.commit()
    con.close()
    report = build_catalog(db, tmp_path / "catalog")
    catalog = CatalogAPI(tmp_path / "catalog" / "catalog.json")
    assert catalog.data["trust"]["orders"]["freshness"] == "known"
    assert catalog.data["trust"]["orders"]["freshness_days"] is not None
    assert catalog.data["trust"]["orders_archive"]["likely_stale_copy"]
    assert catalog.data["trust"]["orders_archive"]["likely_stale_copy_of"] == "orders"
    assert catalog.data["trust"]["orders_archive"]["duplicate_rate"] is None
    assert any(edge["type"] == "stale_copy_of" and edge["target"] == "table:orders"
               for edge in catalog.data["graph"]["edges"])
    assert "orders_archive" in report["stale_copy_tables"]


def test_failed_stage_is_reported_and_resumes_without_catalog_corruption(monkeypatch, tmp_path):
    db = tmp_path / "recovery.sqlite"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE accounts (account_id INTEGER PRIMARY KEY, label TEXT)")
    connection.execute("INSERT INTO accounts VALUES (1, 'active')")
    connection.commit()
    connection.close()
    output = tmp_path / "catalog"
    inspect = pipeline._introspect

    def fail_once(path):
        raise RuntimeError("temporary introspection failure")

    monkeypatch.setattr(pipeline, "_introspect", fail_once)
    with pytest.raises(RuntimeError, match="temporary introspection failure"):
        build_catalog(db, output)

    failed_job = json.loads((output / "job.json").read_text(encoding="utf-8"))
    assert failed_job["status"] == "failed"
    assert failed_job["stages"]["introspect"]["status"] == "failed"
    assert "temporary introspection failure" in failed_job["stages"]["introspect"]["error"]
    assert not (output / "catalog.json").exists()

    monkeypatch.setattr(pipeline, "_introspect", inspect)
    result = build_catalog(db, output)
    recovered_job = json.loads((output / "job.json").read_text(encoding="utf-8"))
    assert result["table_count"] == 1
    assert recovered_job["status"] == result["status"]
    assert recovered_job["stages"]["introspect"]["status"] == "complete"


def _single_table_warehouse(path):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE accounts (account_id INTEGER PRIMARY KEY, label TEXT)")
    connection.execute("INSERT INTO accounts VALUES (1, 'active')")
    connection.commit()
    connection.close()


def test_graph_query_layer_exposes_nodes_neighbors_and_paths(tmp_path):
    db = tmp_path / "graph.sqlite"
    connection = sqlite3.connect(db)
    connection.executescript("""
        CREATE TABLE parent (tenant_id INTEGER, item_id INTEGER, PRIMARY KEY (tenant_id, item_id));
        CREATE TABLE child (child_id INTEGER PRIMARY KEY, tenant_id INTEGER, item_id INTEGER,
          FOREIGN KEY (tenant_id, item_id) REFERENCES parent (tenant_id, item_id));
        INSERT INTO parent VALUES (1, 10), (1, 11);
        INSERT INTO child VALUES (1, 1, 10), (2, 1, 11);
    """)
    connection.commit()
    connection.close()
    output = tmp_path / "catalog"
    build_catalog(db, output)
    api = CatalogAPI(output / "catalog.json")

    assert api.graph().node("table:child")["type"] == "table"
    assert "table:parent" in api.graph_nodes("table")
    assert "column:child.tenant_id" in api.graph_nodes("column")
    assert api.graph_neighbors("column:child.tenant_id", edge_type="join") == [
        "column:parent.item_id", "column:parent.tenant_id"
    ]

    path = api.graph_paths("table:child", "table:parent")
    assert "join" in [edge["type"] for edge in path]
    assert api.graph_paths("table:child", "table:missing") == []
    with pytest.raises(ValueError, match="max_depth"):
        api.graph_paths("table:child", "table:parent", max_depth=0)


def test_catalog_and_index_share_publication_version(tmp_path):
    db = tmp_path / "versioned.sqlite"
    _single_table_warehouse(db)
    output = tmp_path / "catalog"

    first = build_catalog(db, output)
    api = CatalogAPI(output / "catalog.json")
    assert first["catalog_version"] == api.data["catalog_version"] == api.index()["catalog_version"]
    manifest = json.loads((output / "published.json").read_text(encoding="utf-8"))
    assert manifest["catalog_version"] == first["catalog_version"]
    assert {"catalog.json", "index_build.json", "profile.json", "knowledge_graph.json"} <= set(manifest["artifacts"])

    second = build_catalog(db, output)
    assert second["catalog_version"] == first["catalog_version"]
    assert CatalogAPI(output / "catalog.json").index()["catalog_version"] == second["catalog_version"]

    index_path = output / "index_build.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["catalog_version"] = "catalog-not-published"
    index_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="publication mismatch"):
        CatalogAPI(output / "catalog.json").index()


@pytest.mark.parametrize(
    "artifact,occurrence,mode,detection",
    [
        ("profile.json", 1, "after", "none"),
        ("index_build.json", 2, "after", "index"),
        ("catalog.json", 1, "after", "init"),
        ("published.json", 1, "before", "init"),
    ],
)
def test_process_crash_matrix_fails_closed_or_resumes(tmp_path, artifact, occurrence, mode, detection):
    db = tmp_path / "crash.sqlite"
    _single_table_warehouse(db)
    output = tmp_path / "catalog"
    first = build_catalog(db, output)

    connection = sqlite3.connect(db)
    connection.execute("INSERT INTO accounts VALUES (2, 'pending')")
    connection.commit()
    connection.close()

    script = """
import os
import sys
from pathlib import Path
from src.onboarding import pipeline
target, mode, occurrence = sys.argv[3], sys.argv[4], int(sys.argv[5])
original = pipeline._write
seen = {}
def crashing_write(path, value):
    name = Path(path).name
    seen[name] = seen.get(name, 0) + 1
    matched = name == target and seen[name] == occurrence
    if matched and mode == "before":
        os._exit(9)
    result = original(path, value)
    if matched and mode == "after":
        os._exit(9)
    return result
pipeline._write = crashing_write
pipeline.build_catalog(sys.argv[1], sys.argv[2])
"""
    crashed = subprocess.run(
        [sys.executable, "-c", script, str(db), str(output), artifact, mode, str(occurrence)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=120,
    )
    assert crashed.returncode == 9, crashed.stderr

    if detection == "init":
        with pytest.raises(ValueError, match="publication mismatch"):
            CatalogAPI(output / "catalog.json")
    else:
        reader = CatalogAPI(output / "catalog.json")
        if detection == "index":
            with pytest.raises(ValueError, match="publication mismatch"):
                reader.index()
            assert SchemaRetriever(reader).retrieve("accounts").needs_clarification
        else:
            assert reader.data["catalog_version"] == first["catalog_version"]
            assert reader.index()["catalog_version"] == first["catalog_version"]
            assert not SchemaRetriever(reader).retrieve("accounts").needs_clarification

    recovered = build_catalog(db, output)
    published = CatalogAPI(output / "catalog.json")
    assert published.index()["catalog_version"] == published.data["catalog_version"]
    assert published.data["catalog_version"] == recovered["catalog_version"]
    assert not SchemaRetriever(published).retrieve("accounts").needs_clarification
