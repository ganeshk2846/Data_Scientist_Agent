"""scripts/ingest.py registers CSVs as tables, proposing (never approving) joins (GRD-2, 1.15)."""

from __future__ import annotations

import json
import shutil
import sqlite3

import pytest
from semantic.layers import data_layer_for
from semantic.tables import TableRegistry
from semantic.versioning import catalog_version

from scripts.ingest import ingest


@pytest.fixture()
def workspace(v2_build, tmp_path):
    db = tmp_path / "v2.sqlite"
    shutil.copy(v2_build["db"], db)
    with sqlite3.connect(db) as conn:
        states = [row[0] for row in conn.execute("SELECT DISTINCT customer_state FROM customers ORDER BY 1 LIMIT 5")]
        products = [row[0] for row in conn.execute("SELECT product_id FROM products ORDER BY 1 LIMIT 4")]
    folder = tmp_path / "csvs"
    folder.mkdir()
    lines = ["visit_date,customer_state,store_visits"]
    lines += [f"2018-0{month}-01,{state},{10 * month}" for month in (1, 2, 3) for state in states]
    (folder / "Store Visits.csv").write_text("\n".join(lines) + "\n")
    (folder / "Store Visits.md").write_text("Monthly in-store visits per state,\nfrom the retail team.\n")
    ratings = ["product_id,rating,comment"] + [f"{pid},{i % 5 + 1}," for i, pid in enumerate(products)]
    (folder / "product_ratings.csv").write_text("\n".join(ratings) + "\n")
    return {"db": db, "folder": folder, "registry": tmp_path / "semantics" / "ingested.json", "semantics": tmp_path / "semantics"}


def _run(ws):
    return ingest(ws["folder"], db=ws["db"], registry_path=ws["registry"], semantics_dir=ws["semantics"])


def test_csvs_become_tables_with_their_rows(workspace):
    _run(workspace)
    with sqlite3.connect(workspace["db"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM store_visits").fetchone() == (15,)
        assert conn.execute("SELECT COUNT(*) FROM product_ratings").fetchone() == (4,)
        assert conn.execute("SELECT typeof(store_visits) FROM store_visits LIMIT 1").fetchone() == ("integer",)


def test_registry_entry_has_description_synonyms_grain_and_date(workspace):
    payload = _run(workspace)
    entries = {entry["name"]: entry for entry in payload["tables"]}
    visits = entries["store_visits"]
    assert visits["description"] == "Monthly in-store visits per state, from the retail team."
    assert "store visits" in visits["synonyms"]
    assert visits["key_columns"] == ["visit_date", "customer_state"]
    assert visits["date_column"] == "visit_date"
    assert entries["product_ratings"]["key_columns"] == ["product_id"]
    assert json.loads(workspace["registry"].read_text()) == payload


def test_join_edges_are_proposed_never_approved(workspace):
    payload = _run(workspace)
    edges = {(e["column"], e["references"], e["status"]) for t in payload["tables"] for e in t["join_edges"]}
    assert ("customer_state", "customers.customer_state", "proposed") in edges
    assert ("product_id", "products.product_id", "proposed") in edges
    assert all(status == "proposed" for _, _, status in edges)


def test_registered_tables_join_the_semantic_layer(workspace):
    payload = _run(workspace)
    registry = TableRegistry.default().with_ingested(workspace["registry"])
    assert registry.require("store_visits").source == "user_supplied"
    assert data_layer_for(["store_visits", "orders"], registry) == ("real", ())
    assert payload["catalog_version"] != catalog_version()
    page = (workspace["semantics"] / "store_visits.md").read_text()
    assert "Proposed join edges" in page and "customers.customer_state" in page


def test_rerun_is_idempotent(workspace):
    first = _run(workspace)
    assert _run(workspace) == first


def test_refuses_to_shadow_a_warehouse_table(workspace):
    (workspace["folder"] / "orders.csv").write_text("order_id\nx\n")
    with pytest.raises(ValueError, match="already a registered warehouse table"):
        _run(workspace)


def test_never_writes_into_the_real_snapshot(workspace):
    from scripts.ingest import REAL_SNAPSHOT

    with pytest.raises(ValueError, match="real snapshot"):
        ingest(workspace["folder"], db=REAL_SNAPSHOT, registry_path=workspace["registry"])
