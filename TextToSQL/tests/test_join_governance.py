import json
import sqlite3

from src.knowledge.catalog_api import CatalogAPI, JoinGraph
from src.onboarding.pipeline import approve_review, build_catalog


def test_composite_declared_foreign_key_starts_approved_with_audit(tmp_path):
    db = tmp_path / "composite.sqlite"
    out = tmp_path / "catalog"
    connection = sqlite3.connect(db)
    connection.executescript("""
    CREATE TABLE parent (tenant_id INTEGER, item_id INTEGER, PRIMARY KEY (tenant_id, item_id));
    CREATE TABLE child (child_id INTEGER PRIMARY KEY, tenant_id INTEGER, item_id INTEGER,
      FOREIGN KEY (tenant_id, item_id) REFERENCES parent (tenant_id, item_id));
    INSERT INTO parent VALUES (1, 10), (1, 11);
    INSERT INTO child VALUES (1, 1, 10), (2, 1, 10), (3, 1, 11);
    """)
    connection.commit()
    connection.close()
    build_catalog(db, out)
    api = CatalogAPI(out / "catalog.json")
    edges = api.join_edges()
    composite = [edge for edge in edges if edge["evidence"] == "declared_foreign_key"]
    assert len(composite) == 1
    edge = composite[0]
    assert edge["left"]["columns"] == ["tenant_id", "item_id"]
    assert edge["right"]["columns"] == ["tenant_id", "item_id"]
    assert edge["review"]["reviewer"] == "system:declared_foreign_key"
    assert edge["review"]["reviewed_at"]
    assert api.paths("child", "parent") == [edge]


def test_proposed_and_rejected_edges_are_excluded_and_rejection_survives_refresh(tmp_path):
    db = tmp_path / "proposed.sqlite"
    out = tmp_path / "catalog"
    connection = sqlite3.connect(db)
    connection.executescript("CREATE TABLE left_table (order_id INTEGER); CREATE TABLE right_table (order_id INTEGER); INSERT INTO left_table VALUES (1),(1),(2); INSERT INTO right_table VALUES (1),(2),(2);")
    connection.commit()
    connection.close()
    build_catalog(db, out)
    api = CatalogAPI(out / "catalog.json")
    proposed = [edge for edge in api.join_edges(approved_only=False) if edge["status"] == "proposed"]
    assert len(proposed) == 1
    edge = proposed[0]
    assert edge["cardinality"] == "many_to_many"
    assert "many_to_many_fanout_risk" in edge["warnings"]
    assert api.paths("left_table", "right_table") == []
    approve_review(out, reject_joins=[edge["id"]], reviewer="reviewer-test")
    audit1 = json.loads((out / "review.json").read_text())["join_decisions"][edge["id"]]
    approve_review(out, reject_joins=[edge["id"]], reviewer="reviewer-test")
    audit2 = json.loads((out / "review.json").read_text())["join_decisions"][edge["id"]]
    assert audit1 == audit2
    connection = sqlite3.connect(db)
    connection.execute("INSERT INTO left_table VALUES (3)")
    connection.commit()
    connection.close()
    build_catalog(db, out)
    refreshed = CatalogAPI(out / "catalog.json")
    result = next(item for item in refreshed.join_edges(approved_only=False) if item["id"] == edge["id"])
    assert result["status"] == "rejected"
    assert refreshed.paths("left_table", "right_table") == []


def test_approval_is_explicit_and_cycles_do_not_loop():
    graph = JoinGraph([
        {"id": "ab", "left": {"table": "a"}, "right": {"table": "b"}, "status": "proposed"},
        {"id": "bc", "left": {"table": "b"}, "right": {"table": "c"}, "status": "approved"},
        {"id": "ca", "left": {"table": "c"}, "right": {"table": "a"}, "status": "approved"},
        {"id": "cd", "left": {"table": "c"}, "right": {"table": "d"}, "status": "rejected"},
    ])
    assert [edge["id"] for edge in graph.paths("a", "b")] == ["ca", "bc"]
    assert [edge["id"] for edge in graph.paths("a", "c")] == ["ca"]
    assert graph.paths("c", "d") == []
    assert [edge["id"] for edge in graph.paths("a", "b", approved_only=False)] == ["ab"]


def test_approved_inferred_join_is_invalidated_when_refresh_evidence_changes(tmp_path):
    db = tmp_path / "refresh.sqlite"
    out = tmp_path / "catalog"
    connection = sqlite3.connect(db)
    connection.executescript("""
    CREATE TABLE parent (customer_id INTEGER);
    CREATE TABLE child (row_id INTEGER PRIMARY KEY, customer_id INTEGER);
    INSERT INTO parent VALUES (1), (2), (3);
    INSERT INTO child VALUES (1, 1), (2, 2), (3, 3), (4, 3);
    """)
    connection.commit()
    connection.close()
    build_catalog(db, out)
    api = CatalogAPI(out / "catalog.json")
    edge = next(edge for edge in api.join_edges(approved_only=False) if edge["evidence"].get("name_similarity") == 1.0)
    assert edge["status"] == "verified"
    approve_review(out, approve_joins=[edge["id"]], reviewer="reviewer-refresh")
    build_catalog(db, out)
    assert CatalogAPI(out / "catalog.json").paths("parent", "child")

    connection = sqlite3.connect(db)
    connection.execute("UPDATE parent SET customer_id=99 WHERE customer_id=3")
    connection.commit()
    connection.close()
    build_catalog(db, out)
    refreshed = CatalogAPI(out / "catalog.json")
    changed = next(item for item in refreshed.join_edges(approved_only=False) if item["id"] == edge["id"])
    assert changed["status"] == "proposed"
    assert changed["review_invalidated"]["reason"]
    assert refreshed.paths("parent", "child") == []
    history = json.loads((out / "review.json").read_text())["join_decision_history"][edge["id"]]
    assert history[-1]["status"] == "invalidated"
